"""Owned subprocess adapter for Web-triggered workflow commands."""

from __future__ import annotations

import asyncio
import errno
import fcntl
import hashlib
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUN_STAGE = "web_command"
_PERSIST_RETRY_DELAY_SEC = 0.01
_PERSIST_RETRY_MAX_DELAY_SEC = 0.25
_SHUTDOWN_POLL_INTERVAL_SEC = 0.01
_WAIT_RETRY_DELAY_SEC = 0.01


class CommandRunStore(Protocol):
    def job_runs_finish_running_stage(
        self,
        stage: str,
        *,
        status: str,
        result_summary: str,
    ) -> int: ...

    def job_run_start(
        self,
        job_name: str,
        stage: str | None = None,
        trigger_event_id: int | None = None,
        *,
        run_key: str | None = None,
    ) -> int: ...

    def job_run_finish(
        self,
        run_id: int,
        status: str,
        result_summary: str | None = None,
        symbols_processed: int | None = None,
        elapsed_ms: int | None = None,
        message: str | None = None,
    ) -> None: ...


class CommandStartOutcome(str, Enum):
    ACCEPTED = "accepted"
    SATURATED = "saturated"
    STOPPING = "stopping"
    PERSISTENCE_FAILED = "persistence_failed"
    SPAWN_FAILED = "spawn_failed"


@dataclass(frozen=True)
class CommandStartResult:
    outcome: CommandStartOutcome
    target: str
    run_id: int | None = None
    pid: int | None = None
    detail: str | None = None

    @property
    def accepted(self) -> bool:
        return self.outcome is CommandStartOutcome.ACCEPTED


@dataclass(frozen=True)
class _OwnedProcess:
    process: subprocess.Popen[Any]
    run_id: int
    target: str
    started_monotonic: float


@dataclass(frozen=True)
class _PendingCompletion:
    slot_id: int
    run_id: int
    status: str
    detail: str
    elapsed_ms: int
    target: str
    pid: int | None


class RuntimeCommandRunner:
    """Own bounded workflow subprocesses launched by the Web API."""

    def __init__(
        self,
        data_root: str,
        db: CommandRunStore,
        *,
        max_concurrent: int = 2,
        shutdown_timeout_sec: float = 5.0,
    ) -> None:
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be positive")
        if shutdown_timeout_sec <= 0:
            raise ValueError("shutdown_timeout_sec must be positive")
        self._data_root = data_root
        self._db = db
        self._max_concurrent = int(max_concurrent)
        self._shutdown_timeout_sec = float(shutdown_timeout_sec)
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._lifecycle = "ready"
        self._next_slot_id = 1
        self._capacity_slots: set[int] = set()
        self._inflight_starts: set[int] = set()
        self._processes: dict[int, _OwnedProcess] = {}
        self._termination_requested: set[int] = set()
        self._watchers: set[threading.Thread] = set()
        self._pending_completions: dict[int, _PendingCompletion] = {}
        self._terminalizing: set[int] = set()
        self._completion_worker: threading.Thread | None = None
        self._completion_stop_requested = False
        self._start_executor = ThreadPoolExecutor(
            max_workers=self._max_concurrent,
            thread_name_prefix="trade-web-command-start",
        )
        self._start_executor_closed = False
        self._owner_lock_path = self._lock_path_for_data_root(data_root)
        self._owner_lock_fd: int | None = None
        self._acquire_owner_lock()
        try:
            self._reconcile_stale_runs()
            with self._condition:
                self._ensure_completion_worker_locked(required=True)
        except BaseException:
            self._close_start_executor()
            try:
                self._release_owner_lock()
            except Exception:
                logger.exception(
                    "Web workflow command owner lock release failed after reconciliation error"
                )
            raise

    def start(
        self,
        target: str,
        *,
        payload_json: str | None = None,
        limit: int = 10,
    ) -> CommandStartResult:
        reservation = self._reserve_start(target)
        if isinstance(reservation, CommandStartResult):
            return reservation
        return self._start_reserved(
            reservation,
            target,
            payload_json=payload_json,
            limit=limit,
        )

    async def start_async(
        self,
        target: str,
        *,
        payload_json: str | None = None,
        limit: int = 10,
    ) -> CommandStartResult:
        reservation = self._reserve_start(target)
        if isinstance(reservation, CommandStartResult):
            return reservation
        loop = asyncio.get_running_loop()
        try:
            start_future = loop.run_in_executor(
                self._start_executor,
                partial(
                    self._start_reserved,
                    reservation,
                    target,
                    payload_json=payload_json,
                    limit=limit,
                ),
            )
        except Exception:
            self._release_unrecorded_start(reservation)
            raise
        return await asyncio.shield(start_future)

    def _reserve_start(self, target: str) -> int | CommandStartResult:
        with self._condition:
            if self._lifecycle != "ready":
                return CommandStartResult(
                    outcome=CommandStartOutcome.STOPPING,
                    target=target,
                    detail=f"command runner is {self._lifecycle}",
                )
            if len(self._capacity_slots) >= self._max_concurrent:
                return CommandStartResult(
                    outcome=CommandStartOutcome.SATURATED,
                    target=target,
                    detail=f"command capacity={self._max_concurrent}",
                )
            slot_id = self._next_slot_id
            self._next_slot_id += 1
            self._capacity_slots.add(slot_id)
            self._inflight_starts.add(slot_id)
            return slot_id

    def _start_reserved(
        self,
        slot_id: int,
        target: str,
        *,
        payload_json: str | None,
        limit: int,
    ) -> CommandStartResult:
        command = [
            sys.executable,
            "-m",
            "trade_py.cli.main",
            "run",
            target,
            "--data-root",
            self._data_root,
        ]
        if target == "agenda":
            command.extend(["--limit", str(max(1, int(limit)))])
        if payload_json:
            command.extend(["--payload", payload_json])

        started_monotonic = time.monotonic()
        try:
            run_id = self._db.job_run_start(target, stage=_RUN_STAGE)
        except Exception:
            self._release_unrecorded_start(slot_id)
            logger.exception(
                "Web workflow command start persistence failed: "
                "target=%s status=persistence_failed",
                target,
            )
            return CommandStartResult(
                outcome=CommandStartOutcome.PERSISTENCE_FAILED,
                target=target,
                detail="command run persistence unavailable",
            )
        with self._condition:
            stopping = self._lifecycle != "ready"
        if stopping:
            self._finish_run(
                slot_id,
                run_id,
                "terminated",
                detail="owner_shutdown_before_spawn; pid=not_spawned; exit_code=not_spawned",
                started_monotonic=started_monotonic,
                target=target,
                pid=None,
            )
            self._complete_start(slot_id)
            return CommandStartResult(
                outcome=CommandStartOutcome.STOPPING,
                target=target,
                run_id=run_id,
                detail="command runner is stopping",
            )
        try:
            supervisor_command = [
                sys.executable,
                "-m",
                "trade_web.backend.runtime.command_child",
                "--owner-pid",
                str(os.getpid()),
                "--shutdown-timeout-sec",
                str(self._shutdown_timeout_sec),
                "--",
                *command,
            ]
            process = subprocess.Popen(
                supervisor_command,
                cwd=_REPO_ROOT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            logger.exception(
                "Web workflow command spawn failed: "
                "target=%s run_id=%s pid=not_spawned status=error",
                target,
                run_id,
            )
            detail = f"{type(exc).__name__}: {exc}"
            self._finish_run(
                slot_id,
                run_id,
                "error",
                detail=f"spawn_error={detail}; exit_code=not_spawned",
                started_monotonic=started_monotonic,
                target=target,
                pid=None,
            )
            self._complete_start(slot_id)
            return CommandStartResult(
                outcome=CommandStartOutcome.SPAWN_FAILED,
                target=target,
                run_id=run_id,
                detail=detail,
            )

        owned_process = _OwnedProcess(
            process=process,
            run_id=run_id,
            target=target,
            started_monotonic=started_monotonic,
        )
        watcher = threading.Thread(
            target=self._watch_process,
            args=(slot_id, owned_process),
            name=f"trade-web-command-{process.pid}",
        )
        with self._condition:
            self._processes[slot_id] = owned_process
            self._watchers.add(watcher)
            stopping_after_spawn = self._lifecycle != "ready"
        try:
            watcher.start()
        except Exception as exc:
            detail = self._handle_watcher_start_failure(
                slot_id,
                owned_process,
                watcher,
                exc,
            )
            return CommandStartResult(
                outcome=CommandStartOutcome.SPAWN_FAILED,
                target=target,
                run_id=run_id,
                detail=detail,
            )
        self._complete_start(slot_id)
        with self._condition:
            stopping_after_spawn = self._lifecycle != "ready"
        if stopping_after_spawn:
            with self._condition:
                self._termination_requested.add(slot_id)
            try:
                self._signal_process(process, signal.SIGTERM)
            except Exception as exc:
                logger.exception(
                    "Web workflow command post-spawn shutdown signal failed: "
                    "target=%s run_id=%s pid=%s",
                    target,
                    run_id,
                    process.pid,
                )
                return CommandStartResult(
                    outcome=CommandStartOutcome.STOPPING,
                    target=target,
                    run_id=run_id,
                    pid=int(process.pid),
                    detail=f"shutdown signal {type(exc).__name__}: {exc}",
                )
            return CommandStartResult(
                outcome=CommandStartOutcome.STOPPING,
                target=target,
                run_id=run_id,
                pid=int(process.pid),
                detail="command runner is stopping",
            )
        logger.info(
            "Web workflow command accepted: target=%s run_id=%s pid=%s status=running",
            target,
            run_id,
            process.pid,
        )
        return CommandStartResult(
            outcome=CommandStartOutcome.ACCEPTED,
            target=target,
            run_id=run_id,
            pid=int(process.pid),
        )

    def begin_shutdown(self) -> None:
        with self._condition:
            if self._lifecycle == "ready":
                self._lifecycle = "stopping"
            self._completion_stop_requested = True
            self._condition.notify_all()

    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout_sec: float | None = None,
    ) -> None:
        self.begin_shutdown()
        shutdown_started = time.monotonic()
        timeout = self._shutdown_timeout_sec
        if timeout_sec is not None:
            timeout = min(timeout, max(0.0, float(timeout_sec)))
        shutdown_deadline = shutdown_started + timeout
        start_deadline = shutdown_started + timeout * 0.2
        terminate_deadline = shutdown_started + timeout * 0.6
        process_deadline = shutdown_started + timeout * 0.8
        with self._condition:
            if self._pending_completions:
                self._ensure_completion_worker_locked()
        if wait:
            self._wait_for_inflight_starts(start_deadline)
        failure: Exception | None = None
        failure = self._signal_owned_processes(signal.SIGTERM, failure=failure)
        if wait:
            self._wait_for_shutdown_state(terminate_deadline)
        failure = self._signal_owned_processes(signal.SIGKILL, failure=failure)
        if wait:
            self._wait_for_shutdown_state(process_deadline)
        self._finalize_exited_processes()
        if wait:
            self._wait_for_shutdown_state(shutdown_deadline, require_complete=True)
        with self._condition:
            self._discard_finished_watchers_locked()
            inflight_starts = len(self._inflight_starts)
            owned_processes = len(self._processes)
            live_watchers = sum(watcher.is_alive() for watcher in self._watchers)
            pending_completions = len(self._pending_completions)
            capacity_slots = len(self._capacity_slots)
            completion_worker_alive = bool(
                self._completion_worker is not None and self._completion_worker.is_alive()
            )
            self._lifecycle = "stopping"
        complete = not any(
            (
                inflight_starts,
                owned_processes,
                live_watchers,
                pending_completions,
                capacity_slots,
                completion_worker_alive,
            )
        )
        if failure is None and complete:
            try:
                self._close_start_executor()
                self._release_owner_lock()
            except Exception as exc:
                failure = exc
                logger.exception("Web workflow command owner lock release failed")
            else:
                with self._lock:
                    self._lifecycle = "stopped"
        if failure is not None:
            raise RuntimeError("workflow command shutdown failed") from failure
        if not complete:
            raise RuntimeError(
                "workflow command shutdown incomplete: "
                f"starts={inflight_starts} processes={owned_processes} "
                f"watchers={live_watchers} pending_completions={pending_completions} "
                f"capacity={capacity_slots} completion_worker={int(completion_worker_alive)}"
            )

    def _close_start_executor(self) -> None:
        with self._condition:
            if self._start_executor_closed:
                return
            self._start_executor_closed = True
        self._start_executor.shutdown(wait=True, cancel_futures=True)

    def _watch_process(
        self,
        slot_id: int,
        owned_process: _OwnedProcess,
    ) -> None:
        try:
            return_code = self._wait_for_process_exit(owned_process)
            self._record_process_exit(slot_id, owned_process, return_code)
        finally:
            with self._condition:
                self._watchers.discard(threading.current_thread())
                self._condition.notify_all()

    def _wait_for_process_exit(self, owned_process: _OwnedProcess) -> int:
        process = owned_process.process
        while True:
            try:
                return process.wait()
            except OSError:
                logger.exception(
                    "Web workflow command wait failed transiently: "
                    "target=%s run_id=%s pid=%s status=wait_retry",
                    owned_process.target,
                    owned_process.run_id,
                    process.pid,
                )
                try:
                    return_code = process.poll()
                except OSError:
                    return_code = None
                if return_code is not None:
                    return return_code
                with self._condition:
                    self._condition.wait(timeout=_WAIT_RETRY_DELAY_SEC)

    def _record_process_exit(
        self,
        slot_id: int,
        owned_process: _OwnedProcess,
        return_code: int,
    ) -> None:
        with self._condition:
            if self._processes.get(slot_id) != owned_process:
                return
            if slot_id in self._terminalizing:
                return
            self._terminalizing.add(slot_id)
            termination_requested = slot_id in self._termination_requested
        if termination_requested or return_code < 0 or return_code >= 128:
            status = "terminated"
        elif return_code == 0:
            status = "ok"
        else:
            status = "error"
        self._finish_run(
            slot_id,
            owned_process.run_id,
            status,
            detail=f"pid={owned_process.process.pid}; exit_code={return_code}",
            started_monotonic=owned_process.started_monotonic,
            target=owned_process.target,
            pid=int(owned_process.process.pid),
        )
        with self._condition:
            if self._processes.get(slot_id) == owned_process:
                self._processes.pop(slot_id, None)
            self._termination_requested.discard(slot_id)
            self._release_capacity_if_done_locked(slot_id)
            self._condition.notify_all()
        if status == "error":
            logger.error(
                "Web workflow command failed: "
                "target=%s run_id=%s pid=%s status=error return_code=%s",
                owned_process.target,
                owned_process.run_id,
                owned_process.process.pid,
                return_code,
            )

    def _reconcile_stale_runs(self) -> None:
        self._db.job_runs_finish_running_stage(
            _RUN_STAGE,
            status="terminated",
            result_summary=(
                "owner_restart_reconciliation; pid=unknown; exit_code=unknown; elapsed_ms=unknown"
            ),
        )

    def _finish_run(
        self,
        slot_id: int,
        run_id: int,
        status: str,
        *,
        detail: str,
        started_monotonic: float,
        target: str,
        pid: int | None,
    ) -> bool:
        elapsed_ms = max(0, int((time.monotonic() - started_monotonic) * 1000))
        completion = _PendingCompletion(
            slot_id=slot_id,
            run_id=run_id,
            status=status,
            detail=detail,
            elapsed_ms=elapsed_ms,
            target=target,
            pid=pid,
        )
        with self._condition:
            self._terminalizing.add(slot_id)
            existing = self._pending_completions.get(slot_id)
            if existing is not None and existing != completion:
                raise RuntimeError(f"conflicting completion for run_id={run_id}")
            self._pending_completions[slot_id] = completion
            self._ensure_completion_worker_locked()
            self._condition.notify_all()
        return False

    def _persist_completion_once(self, completion: _PendingCompletion) -> bool:
        with self._condition:
            if self._pending_completions.get(completion.slot_id) != completion:
                return True
        try:
            self._db.job_run_finish(
                completion.run_id,
                completion.status,
                result_summary=f"{completion.detail}; elapsed_ms={completion.elapsed_ms}",
                elapsed_ms=completion.elapsed_ms,
            )
        except Exception:
            logger.exception(
                "Web workflow command completion persistence failed: "
                "target=%s run_id=%s pid=%s status=%s",
                completion.target,
                completion.run_id,
                completion.pid if completion.pid is not None else "unknown",
                completion.status,
            )
            return False
        with self._condition:
            if self._pending_completions.get(completion.slot_id) == completion:
                self._pending_completions.pop(completion.slot_id, None)
                self._terminalizing.discard(completion.slot_id)
                self._release_capacity_if_done_locked(completion.slot_id)
            self._condition.notify_all()
        logger.info(
            "Web workflow command completion persisted: target=%s run_id=%s pid=%s status=%s",
            completion.target,
            completion.run_id,
            completion.pid if completion.pid is not None else "unknown",
            completion.status,
        )
        return True

    def _ensure_completion_worker_locked(self, *, required: bool = False) -> None:
        worker = self._completion_worker
        if worker is not None and worker.is_alive():
            return
        worker = threading.Thread(
            target=self._completion_retry_loop,
            name="trade-web-command-persistence-retry",
            daemon=True,
        )
        self._completion_worker = worker
        try:
            worker.start()
        except Exception as exc:
            self._completion_worker = None
            logger.exception("Web workflow command completion retry worker failed to start")
            if required:
                raise RuntimeError("workflow command completion retry worker unavailable") from exc

    def _completion_retry_loop(self) -> None:
        retry_delay = _PERSIST_RETRY_DELAY_SEC
        try:
            while True:
                with self._condition:
                    while not self._pending_completions:
                        if self._completion_can_stop_locked():
                            return
                        self._condition.wait()
                    completion = next(iter(self._pending_completions.values()))
                if self._persist_completion_once(completion):
                    retry_delay = _PERSIST_RETRY_DELAY_SEC
                    continue
                with self._condition:
                    if self._pending_completions.get(completion.slot_id) == completion:
                        self._pending_completions.pop(completion.slot_id)
                        self._pending_completions[completion.slot_id] = completion
                        self._condition.wait(timeout=retry_delay)
                retry_delay = min(retry_delay * 2, _PERSIST_RETRY_MAX_DELAY_SEC)
        finally:
            with self._condition:
                if self._completion_worker is threading.current_thread():
                    self._completion_worker = None
                self._condition.notify_all()

    def _completion_can_stop_locked(self) -> bool:
        return (
            self._completion_stop_requested
            and not self._pending_completions
            and not self._inflight_starts
            and not self._processes
            and not self._terminalizing
        )

    def _signal_owned_processes(
        self,
        requested_signal: int,
        *,
        failure: Exception | None,
    ) -> Exception | None:
        with self._condition:
            owned_processes = tuple(self._processes.items())
        for slot_id, owned_process in owned_processes:
            process = owned_process.process
            try:
                if process.poll() is not None:
                    continue
            except OSError:
                pass
            with self._condition:
                if self._processes.get(slot_id) != owned_process:
                    continue
                self._termination_requested.add(slot_id)
            try:
                signaled = self._signal_process(process, requested_signal)
            except Exception as exc:
                with self._condition:
                    self._termination_requested.discard(slot_id)
                if failure is None:
                    failure = exc
                logger.exception(
                    "Failed to signal Web workflow command: "
                    "target=%s run_id=%s pid=%s status=termination_failed signal=%s",
                    owned_process.target,
                    owned_process.run_id,
                    process.pid,
                    requested_signal,
                )
            else:
                if not signaled:
                    with self._condition:
                        self._termination_requested.discard(slot_id)
        return failure

    def _handle_watcher_start_failure(
        self,
        slot_id: int,
        owned_process: _OwnedProcess,
        watcher: threading.Thread,
        failure: Exception,
    ) -> str:
        process = owned_process.process
        with self._condition:
            self._watchers.discard(watcher)
            self._lifecycle = "stopping"
            self._termination_requested.add(slot_id)
        cleanup_error: Exception | None = None
        try:
            if not self._signal_process(process, signal.SIGTERM):
                with self._condition:
                    self._termination_requested.discard(slot_id)
        except Exception as exc:
            cleanup_error = exc
            with self._condition:
                self._termination_requested.discard(slot_id)
        self._complete_start(slot_id)
        logger.exception(
            "Web workflow command watcher failed: target=%s run_id=%s pid=%s status=error",
            owned_process.target,
            owned_process.run_id,
            process.pid,
            exc_info=failure,
        )
        detail = f"watcher {type(failure).__name__}: {failure}"
        if cleanup_error is not None:
            detail += f"; cleanup {type(cleanup_error).__name__}: {cleanup_error}"
        try:
            return_code = process.poll()
        except OSError:
            return_code = None
        if return_code is not None:
            self._record_process_exit(slot_id, owned_process, return_code)
        return detail

    @staticmethod
    def _signal_process(
        process: subprocess.Popen[Any],
        requested_signal: int,
    ) -> bool:
        if process.poll() is not None:
            return False
        try:
            os.killpg(os.getpgid(process.pid), requested_signal)
        except OSError:
            if process.poll() is not None:
                return False
            if requested_signal == signal.SIGKILL:
                process.kill()
            else:
                process.terminate()
        return True

    def _wait_for_inflight_starts(self, deadline: float) -> None:
        with self._condition:
            while self._inflight_starts:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self._condition.wait(timeout=min(remaining, _SHUTDOWN_POLL_INTERVAL_SEC))

    def _wait_for_shutdown_state(
        self,
        deadline: float,
        *,
        require_complete: bool = False,
    ) -> None:
        current = threading.current_thread()
        while True:
            self._finalize_exited_processes()
            with self._condition:
                self._discard_finished_watchers_locked()
                inflight_starts = bool(self._inflight_starts)
                owned_processes = bool(self._processes)
                live_watchers = tuple(
                    watcher
                    for watcher in self._watchers
                    if watcher is not current and watcher.is_alive()
                )
                pending_completions = bool(self._pending_completions)
                capacity_slots = bool(self._capacity_slots)
                completion_worker_alive = bool(
                    self._completion_worker is not None
                    and self._completion_worker is not current
                    and self._completion_worker.is_alive()
                )
            process_state_done = not inflight_starts and not owned_processes and not live_watchers
            complete = (
                process_state_done
                and not pending_completions
                and not capacity_slots
                and not completion_worker_alive
            )
            if complete if require_complete else process_state_done:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if live_watchers:
                live_watchers[0].join(timeout=min(remaining, _SHUTDOWN_POLL_INTERVAL_SEC))
            else:
                time.sleep(min(remaining, _SHUTDOWN_POLL_INTERVAL_SEC))

    def _finalize_exited_processes(self) -> None:
        with self._condition:
            owned_processes = tuple(self._processes.items())
        for slot_id, owned_process in owned_processes:
            try:
                return_code = owned_process.process.poll()
            except OSError:
                continue
            if return_code is not None:
                self._record_process_exit(slot_id, owned_process, return_code)

    def _release_unrecorded_start(self, slot_id: int) -> None:
        with self._condition:
            self._inflight_starts.discard(slot_id)
            self._capacity_slots.discard(slot_id)
            self._condition.notify_all()

    def _complete_start(self, slot_id: int) -> None:
        with self._condition:
            self._inflight_starts.discard(slot_id)
            self._release_capacity_if_done_locked(slot_id)
            self._condition.notify_all()

    def _release_capacity_if_done_locked(self, slot_id: int) -> None:
        if (
            slot_id not in self._inflight_starts
            and slot_id not in self._processes
            and slot_id not in self._pending_completions
            and slot_id not in self._terminalizing
        ):
            self._capacity_slots.discard(slot_id)

    def _discard_finished_watchers_locked(self) -> None:
        current = threading.current_thread()
        self._watchers = {
            watcher for watcher in self._watchers if watcher is current or watcher.is_alive()
        }

    @staticmethod
    def _lock_path_for_data_root(data_root: str) -> Path:
        canonical_root = str(Path(data_root).expanduser().resolve(strict=False))
        root_digest = hashlib.sha256(os.fsencode(canonical_root)).hexdigest()
        lock_directory = Path(tempfile.gettempdir()) / f"trade-runtime-command-locks-{os.getuid()}"
        lock_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return lock_directory / f"{root_digest}.lock"

    def _acquire_owner_lock(self) -> None:
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        lock_fd = os.open(self._owner_lock_path, flags, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(lock_fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise RuntimeError("runtime command owner already active for data root") from exc
            raise RuntimeError("runtime command owner lock unavailable") from exc
        self._owner_lock_fd = lock_fd

    def _release_owner_lock(self) -> None:
        with self._lock:
            lock_fd = self._owner_lock_fd
            if lock_fd is None:
                return
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            self._owner_lock_fd = None
        try:
            os.close(lock_fd)
        except OSError:
            logger.exception("Web workflow command owner lock descriptor close failed")
