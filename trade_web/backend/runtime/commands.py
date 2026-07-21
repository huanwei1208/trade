"""Owned subprocess adapter for Web-triggered workflow commands."""

from __future__ import annotations

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
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUN_STAGE = "web_command"
_PERSIST_ATTEMPTS = 3
_PERSIST_RETRY_DELAY_SEC = 0.01
_SHUTDOWN_POLL_INTERVAL_SEC = 0.01


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
        self._persistence_lock = threading.Lock()
        self._lifecycle = "ready"
        self._processes: dict[int, _OwnedProcess] = {}
        self._termination_requested: set[int] = set()
        self._watchers: set[threading.Thread] = set()
        self._pending_completions: dict[int, _PendingCompletion] = {}
        self._owner_lock_path = self._lock_path_for_data_root(data_root)
        self._owner_lock_fd: int | None = None
        self._acquire_owner_lock()
        try:
            self._reconcile_stale_runs()
        except BaseException:
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

        with self._lock:
            if self._lifecycle != "ready":
                return CommandStartResult(
                    outcome=CommandStartOutcome.STOPPING,
                    target=target,
                    detail=f"command runner is {self._lifecycle}",
                )
            if len(self._processes) >= self._max_concurrent:
                return CommandStartResult(
                    outcome=CommandStartOutcome.SATURATED,
                    target=target,
                    detail=f"command capacity={self._max_concurrent}",
                )
            started_monotonic = time.monotonic()
            try:
                run_id = self._db.job_run_start(target, stage=_RUN_STAGE)
            except Exception:
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
                    run_id,
                    "error",
                    detail=f"spawn_error={detail}; exit_code=not_spawned",
                    started_monotonic=started_monotonic,
                    target=target,
                    pid=None,
                )
                return CommandStartResult(
                    outcome=CommandStartOutcome.SPAWN_FAILED,
                    target=target,
                    run_id=run_id,
                    detail=detail,
                )

            process_key = id(process)
            owned_process = _OwnedProcess(
                process=process,
                run_id=run_id,
                target=target,
                started_monotonic=started_monotonic,
            )
            self._processes[process_key] = owned_process
            watcher = threading.Thread(
                target=self._watch_process,
                args=(process_key, owned_process),
                name=f"trade-web-command-{process.pid}",
            )
            self._watchers.add(watcher)
            try:
                watcher.start()
            except Exception as exc:
                self._watchers.discard(watcher)
                cleanup_error: Exception | None = None
                try:
                    self._terminate_after_watcher_failure(
                        process,
                        target=target,
                        run_id=run_id,
                    )
                except Exception as cleanup_exc:
                    cleanup_error = cleanup_exc
                    self._lifecycle = "stopping"
                if process.poll() is not None:
                    self._processes.pop(process_key, None)
                logger.exception(
                    "Web workflow command watcher failed: target=%s run_id=%s pid=%s status=error",
                    target,
                    run_id,
                    process.pid,
                )
                detail = f"watcher {type(exc).__name__}: {exc}"
                if cleanup_error is not None:
                    detail += f"; cleanup {type(cleanup_error).__name__}: {cleanup_error}"
                exit_code = process.poll()
                self._finish_run(
                    run_id,
                    "error",
                    detail=(
                        f"owner_setup_error={detail}; pid={process.pid}; "
                        f"exit_code={exit_code if exit_code is not None else 'unknown'}"
                    ),
                    started_monotonic=started_monotonic,
                    target=target,
                    pid=int(process.pid),
                )
                return CommandStartResult(
                    outcome=CommandStartOutcome.SPAWN_FAILED,
                    target=target,
                    run_id=run_id,
                    detail=detail,
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
        with self._lock:
            if self._lifecycle == "ready":
                self._lifecycle = "stopping"

    def shutdown(self, *, wait: bool = True) -> None:
        self.begin_shutdown()
        shutdown_started = time.monotonic()
        shutdown_deadline = shutdown_started + self._shutdown_timeout_sec
        terminate_deadline = shutdown_started + self._shutdown_timeout_sec * 0.5
        process_deadline = shutdown_started + self._shutdown_timeout_sec * 0.8
        failure: Exception | None = None
        failure = self._signal_owned_processes(signal.SIGTERM, failure=failure)
        if wait:
            self._wait_for_shutdown_state(terminate_deadline)
        failure = self._signal_owned_processes(signal.SIGKILL, failure=failure)
        if wait:
            self._wait_for_shutdown_state(process_deadline)
        self._retry_pending_completions_until(shutdown_deadline)
        with self._lock:
            completed = [
                process_key
                for process_key, owned_process in self._processes.items()
                if owned_process.process.poll() is not None
            ]
            for process_key in completed:
                self._processes.pop(process_key, None)
                self._termination_requested.discard(process_key)
            live_processes = tuple(
                owned_process.process
                for owned_process in self._processes.values()
                if owned_process.process.poll() is None
            )
            live_watchers = tuple(watcher for watcher in self._watchers if watcher.is_alive())
            pending_completions = tuple(self._pending_completions.values())
            self._lifecycle = "stopping"
        if failure is None and not live_processes and not live_watchers and not pending_completions:
            try:
                self._release_owner_lock()
            except Exception as exc:
                failure = exc
                logger.exception("Web workflow command owner lock release failed")
            else:
                with self._lock:
                    self._lifecycle = "stopped"
        if failure is not None:
            raise RuntimeError("workflow command shutdown failed") from failure
        if live_processes or live_watchers or pending_completions:
            raise RuntimeError(
                "workflow command shutdown incomplete: "
                f"processes={len(live_processes)} watchers={len(live_watchers)} "
                f"pending_completions={len(pending_completions)}"
            )

    def _watch_process(
        self,
        process_key: int,
        owned_process: _OwnedProcess,
    ) -> None:
        process = owned_process.process
        return_code: int | None = None
        termination_requested = False
        try:
            try:
                return_code = process.wait()
            except OSError:
                logger.exception(
                    "Web workflow command wait failed: "
                    "target=%s run_id=%s pid=%s status=wait_failed",
                    owned_process.target,
                    owned_process.run_id,
                    process.pid,
                )
                return_code = process.poll()
            with self._lock:
                termination_requested = process_key in self._termination_requested
            if return_code is None:
                return
            if termination_requested or return_code < 0 or return_code >= 128:
                status = "terminated"
            elif return_code == 0:
                status = "ok"
            else:
                status = "error"
            self._finish_run(
                owned_process.run_id,
                status,
                detail=f"pid={process.pid}; exit_code={return_code}",
                started_monotonic=owned_process.started_monotonic,
                target=owned_process.target,
                pid=int(process.pid),
            )
            if status == "error":
                logger.error(
                    "Web workflow command failed: "
                    "target=%s run_id=%s pid=%s status=error return_code=%s",
                    owned_process.target,
                    owned_process.run_id,
                    process.pid,
                    return_code,
                )
        finally:
            with self._lock:
                self._termination_requested.discard(process_key)
                if return_code is not None:
                    self._processes.pop(process_key, None)
                self._watchers.discard(threading.current_thread())

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
            run_id=run_id,
            status=status,
            detail=detail,
            elapsed_ms=elapsed_ms,
            target=target,
            pid=pid,
        )
        with self._lock:
            existing = self._pending_completions.get(run_id)
            if existing is not None and existing != completion:
                raise RuntimeError(f"conflicting completion for run_id={run_id}")
            self._pending_completions[run_id] = completion
        return self._flush_pending_completions(run_ids=(run_id,))

    def _flush_pending_completions(
        self,
        *,
        run_ids: tuple[int, ...] | None = None,
        deadline: float | None = None,
    ) -> bool:
        all_persisted = True
        if deadline is None:
            persistence_lock_acquired = self._persistence_lock.acquire()
        else:
            persistence_lock_acquired = self._persistence_lock.acquire(
                timeout=max(0.0, deadline - time.monotonic())
            )
        if not persistence_lock_acquired:
            return False
        try:
            with self._lock:
                pending_ids = (
                    tuple(self._pending_completions) if run_ids is None else tuple(run_ids)
                )
            for run_id in pending_ids:
                with self._lock:
                    completion = self._pending_completions.get(run_id)
                if completion is None:
                    continue
                persisted = False
                for attempt in range(1, _PERSIST_ATTEMPTS + 1):
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    try:
                        self._db.job_run_finish(
                            completion.run_id,
                            completion.status,
                            result_summary=(
                                f"{completion.detail}; elapsed_ms={completion.elapsed_ms}"
                            ),
                            elapsed_ms=completion.elapsed_ms,
                        )
                    except Exception:
                        logger.exception(
                            "Web workflow command completion persistence failed: "
                            "target=%s run_id=%s pid=%s status=%s attempt=%s",
                            completion.target,
                            completion.run_id,
                            completion.pid if completion.pid is not None else "unknown",
                            completion.status,
                            attempt,
                        )
                        if attempt < _PERSIST_ATTEMPTS:
                            self._sleep_before_persistence_retry(deadline)
                    else:
                        with self._lock:
                            if self._pending_completions.get(run_id) == completion:
                                self._pending_completions.pop(run_id, None)
                        logger.info(
                            "Web workflow command completion persisted: "
                            "target=%s run_id=%s pid=%s status=%s",
                            completion.target,
                            completion.run_id,
                            completion.pid if completion.pid is not None else "unknown",
                            completion.status,
                        )
                        persisted = True
                        break
                if not persisted:
                    all_persisted = False
            return all_persisted
        finally:
            self._persistence_lock.release()

    def _retry_pending_completions_until(self, deadline: float) -> None:
        with self._lock:
            if not self._pending_completions:
                return
        retry_thread = threading.Thread(
            target=self._flush_pending_completions,
            kwargs={"deadline": deadline},
            name="trade-web-command-persistence-retry",
            daemon=True,
        )
        retry_thread.start()
        retry_thread.join(timeout=max(0.0, deadline - time.monotonic()))

    @staticmethod
    def _sleep_before_persistence_retry(deadline: float | None) -> None:
        delay = _PERSIST_RETRY_DELAY_SEC
        if deadline is not None:
            delay = min(delay, max(0.0, deadline - time.monotonic()))
        if delay > 0:
            time.sleep(delay)

    def _signal_owned_processes(
        self,
        requested_signal: int,
        *,
        failure: Exception | None,
    ) -> Exception | None:
        with self._lock:
            owned_processes = tuple(self._processes.items())
            for process_key, owned_process in owned_processes:
                process = owned_process.process
                if process.poll() is not None:
                    continue
                self._termination_requested.add(process_key)
                try:
                    signaled = self._signal_process(process, requested_signal)
                except Exception as exc:
                    self._termination_requested.discard(process_key)
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
                        self._termination_requested.discard(process_key)
        return failure

    def _terminate_after_watcher_failure(
        self,
        process: subprocess.Popen[Any],
        *,
        target: str,
        run_id: int,
    ) -> None:
        if not self._signal_process(process, signal.SIGTERM):
            return
        try:
            process.wait(timeout=self._shutdown_timeout_sec)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Killing Web workflow command without watcher: "
                "target=%s run_id=%s pid=%s status=owner_setup_failed",
                target,
                run_id,
                process.pid,
            )
            self._signal_process(process, signal.SIGKILL)
            process.wait(timeout=self._shutdown_timeout_sec)

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

    def _wait_for_shutdown_state(self, deadline: float) -> None:
        current = threading.current_thread()
        while True:
            with self._lock:
                live_processes = any(
                    owned_process.process.poll() is None
                    for owned_process in self._processes.values()
                )
                live_watchers = tuple(
                    watcher
                    for watcher in self._watchers
                    if watcher is not current and watcher.is_alive()
                )
            if not live_processes and not live_watchers:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if live_watchers:
                live_watchers[0].join(timeout=min(remaining, _SHUTDOWN_POLL_INTERVAL_SEC))
            else:
                time.sleep(min(remaining, _SHUTDOWN_POLL_INTERVAL_SEC))

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
