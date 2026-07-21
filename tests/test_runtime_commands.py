from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from types import SimpleNamespace
from typing import Any, cast

import pytest

from trade_py.db.trade_db import TradeDB
from trade_web.backend.runtime import command_child
from trade_web.backend.runtime.commands import (
    CommandRunStore,
    CommandStartOutcome,
    CommandStartResult,
    RuntimeCommandRunner,
)


@pytest.fixture(autouse=True)
def _disable_real_process_group_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_group(_pid: int) -> int:
        raise ProcessLookupError

    monkeypatch.setattr(os, "getpgid", missing_group)


class _Process:
    next_pid = 100

    def __init__(self) -> None:
        self.pid = _Process.next_pid
        _Process.next_pid += 1
        self.return_code: int | None = None
        self.wait_started = threading.Event()
        self.release_wait = threading.Event()
        self.terminated = False
        self.killed = False
        self.wait_timeouts: list[float | None] = []

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeouts.append(timeout)
        self.wait_started.set()
        if timeout is not None and not self.release_wait.wait(timeout=0.01):
            raise subprocess.TimeoutExpired("trade", timeout)
        if timeout is None:
            assert self.release_wait.wait(timeout=2)
        self.return_code = -9 if self.killed else -15 if self.terminated else 0
        return self.return_code

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.release_wait.set()


class _JobDB:
    def __init__(self) -> None:
        self.next_run_id = 1
        self.started: list[tuple[int, str, str | None]] = []
        self.finished: list[dict[str, Any]] = []
        self.reconciled: list[tuple[str, str, str]] = []

    def job_runs_finish_running_stage(
        self,
        stage: str,
        *,
        status: str,
        result_summary: str,
    ) -> int:
        self.reconciled.append((stage, status, result_summary))
        return 0

    def job_run_start(
        self,
        job_name: str,
        stage: str | None = None,
        trigger_event_id: int | None = None,
        *,
        run_key: str | None = None,
    ) -> int:
        del trigger_event_id, run_key
        return self._start(job_name, stage)

    def _start(self, job_name: str, stage: str | None) -> int:
        run_id = self.next_run_id
        self.next_run_id += 1
        self.started.append((run_id, job_name, stage))
        return run_id

    def job_run_finish(
        self,
        run_id: int,
        status: str,
        result_summary: str | None = None,
        symbols_processed: int | None = None,
        elapsed_ms: int | None = None,
        message: str | None = None,
    ) -> None:
        del symbols_processed, message
        self.finished.append(
            {
                "run_id": run_id,
                "status": status,
                "result_summary": result_summary,
                "elapsed_ms": elapsed_ms,
            }
        )


def _wait_until(predicate, *, message: str) -> None:
    for _ in range(100):
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError(message)


def test_command_runner_spawns_isolated_cli_with_payload_and_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    process = _Process()
    db = _JobDB()
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def popen(command: list[str], **kwargs):
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    runner = RuntimeCommandRunner(str(tmp_path), db, max_concurrent=1)

    result = runner.start("agenda", payload_json='{"symbol":"BTC"}', limit=7)

    assert result.outcome is CommandStartOutcome.ACCEPTED
    assert result.run_id == 1
    assert result.pid == process.pid
    assert process.wait_started.wait(timeout=1)
    command, kwargs = calls[0]
    assert command[1:7] == [
        "-m",
        "trade_web.backend.runtime.command_child",
        "--owner-pid",
        str(os.getpid()),
        "--shutdown-timeout-sec",
        "5.0",
    ]
    assert command[7:13] == [
        "--",
        command[0],
        "-m",
        "trade_py.cli.main",
        "run",
        "agenda",
    ]
    assert command[-6:] == [
        "--data-root",
        str(tmp_path),
        "--limit",
        "7",
        "--payload",
        '{"symbol":"BTC"}',
    ]
    assert "shell" not in kwargs
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert "stdout" not in kwargs
    assert "stderr" not in kwargs
    assert db.reconciled == [
        (
            "web_command",
            "terminated",
            "owner_restart_reconciliation; pid=unknown; exit_code=unknown; elapsed_ms=unknown",
        )
    ]
    assert db.started == [(1, "agenda", "web_command")]
    assert all("BTC" not in str(item) for item in db.started)

    process.release_wait.set()
    _wait_until(lambda: bool(db.finished), message="command completion was not persisted")
    runner.shutdown(wait=True)
    assert db.finished[0]["status"] == "ok"
    assert f"pid={process.pid}; exit_code=0" in str(db.finished[0]["result_summary"])
    assert db.finished[0]["elapsed_ms"] is not None


def test_command_runner_saturates_and_reopens_capacity_after_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    first_process = _Process()
    second_process = _Process()
    processes = iter([first_process, second_process])
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: next(processes))
    runner = RuntimeCommandRunner(str(tmp_path), _JobDB(), max_concurrent=1)

    first = runner.start("morning")
    assert first_process.wait_started.wait(timeout=1)
    saturated = runner.start("evening")

    assert first.accepted is True
    assert saturated.outcome is CommandStartOutcome.SATURATED
    assert saturated.pid is None

    first_process.release_wait.set()
    for _ in range(100):
        resumed = runner.start("evening")
        if resumed.accepted:
            break
        threading.Event().wait(0.01)
    else:
        raise AssertionError("command capacity was not released")

    second_process.release_wait.set()
    runner.shutdown(wait=True)


def test_command_runner_records_nonzero_exit_as_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class NonzeroProcess(_Process):
        def wait(self, timeout: float | None = None) -> int:
            self.wait_timeouts.append(timeout)
            self.wait_started.set()
            assert self.release_wait.wait(timeout=2)
            self.return_code = 23
            return self.return_code

    process = NonzeroProcess()
    db = _JobDB()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    runner = RuntimeCommandRunner(str(tmp_path), db)

    assert runner.start("morning").accepted
    assert process.wait_started.wait(timeout=1)
    process.release_wait.set()
    for _ in range(100):
        if db.finished:
            break
        threading.Event().wait(0.01)
    else:
        raise AssertionError("command error was not persisted")

    runner.shutdown(wait=True)
    assert db.finished[0]["status"] == "error"
    assert "exit_code=23" in str(db.finished[0]["result_summary"])


def test_command_runner_logs_metadata_without_payload(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    process = _Process()
    db = _JobDB()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    caplog.set_level(logging.INFO, logger="trade_web.backend.runtime.commands")
    runner = RuntimeCommandRunner(str(tmp_path), db)

    result = runner.start("morning", payload_json='{"secret":"never-log"}')
    assert result.run_id == 1
    assert result.pid == process.pid
    assert process.wait_started.wait(timeout=1)
    process.release_wait.set()
    _wait_until(lambda: bool(db.finished), message="command completion was not persisted")
    runner.shutdown(wait=True)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        (f"target=morning run_id=1 pid={process.pid} status=running" in message)
        for message in messages
    )
    assert any(
        (f"target=morning run_id=1 pid={process.pid} status=ok" in message) for message in messages
    )
    assert all("never-log" not in message for message in messages)


def test_command_runner_spawn_failure_and_stopping_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    def fail_spawn(*_args, **_kwargs):
        raise OSError("fork unavailable")

    monkeypatch.setattr(subprocess, "Popen", fail_spawn)
    db = _JobDB()
    runner = RuntimeCommandRunner(str(tmp_path), db)

    failed = runner.start("morning")
    assert failed.outcome is CommandStartOutcome.SPAWN_FAILED
    assert failed.run_id == 1
    assert "fork unavailable" in str(failed.detail)
    _wait_until(lambda: bool(db.finished), message="spawn failure audit was not persisted")
    assert db.finished[0]["status"] == "error"
    assert "spawn_error=OSError: fork unavailable" in str(db.finished[0]["result_summary"])
    assert "exit_code=not_spawned" in str(db.finished[0]["result_summary"])

    runner.begin_shutdown()
    stopping = runner.start("evening")
    assert stopping.outcome is CommandStartOutcome.STOPPING
    runner.shutdown(wait=True)


def test_command_runner_start_persistence_failure_is_distinct_and_safe(
    tmp_path,
) -> None:
    class FailingStartDB(_JobDB):
        def job_run_start(
            self,
            job_name: str,
            stage: str | None = None,
            trigger_event_id: int | None = None,
            *,
            run_key: str | None = None,
        ) -> int:
            del job_name, stage, trigger_event_id, run_key
            raise RuntimeError("credential=never-public")

    runner = RuntimeCommandRunner(str(tmp_path), FailingStartDB())

    failed = runner.start("morning")

    assert failed.outcome is CommandStartOutcome.PERSISTENCE_FAILED
    assert failed.run_id is None
    assert failed.pid is None
    assert failed.detail == "command run persistence unavailable"
    assert "credential" not in failed.detail
    runner.shutdown(wait=True)


def test_command_runner_exclusively_owns_each_data_root_before_reconciliation(
    tmp_path,
) -> None:
    first_db = _JobDB()
    second_db = _JobDB()
    first = RuntimeCommandRunner(str(tmp_path), first_db)

    with pytest.raises(
        RuntimeError,
        match="runtime command owner already active for data root",
    ):
        RuntimeCommandRunner(str(tmp_path), second_db)

    assert len(first_db.reconciled) == 1
    assert second_db.reconciled == []

    first.shutdown(wait=True)
    replacement = RuntimeCommandRunner(str(tmp_path), second_db)
    assert len(second_db.reconciled) == 1
    replacement.shutdown(wait=True)


def test_command_runner_releases_owner_lock_when_reconciliation_fails(
    tmp_path,
) -> None:
    class FailingReconcileDB(_JobDB):
        def job_runs_finish_running_stage(
            self,
            stage: str,
            *,
            status: str,
            result_summary: str,
        ) -> int:
            del stage, status, result_summary
            raise RuntimeError("reconciliation unavailable")

    with pytest.raises(RuntimeError, match="reconciliation unavailable"):
        RuntimeCommandRunner(str(tmp_path), FailingReconcileDB())

    replacement = RuntimeCommandRunner(str(tmp_path), _JobDB())
    replacement.shutdown(wait=True)


def test_command_completion_persistence_retries_exact_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FailOnceFinishDB(_JobDB):
        def __init__(self) -> None:
            super().__init__()
            self.attempts: list[tuple[int, str, str | None, int | None]] = []

        def job_run_finish(
            self,
            run_id: int,
            status: str,
            result_summary: str | None = None,
            symbols_processed: int | None = None,
            elapsed_ms: int | None = None,
            message: str | None = None,
        ) -> None:
            self.attempts.append((run_id, status, result_summary, elapsed_ms))
            if len(self.attempts) == 1:
                raise RuntimeError("temporary persistence failure")
            super().job_run_finish(
                run_id,
                status,
                result_summary,
                symbols_processed,
                elapsed_ms,
                message,
            )

    process = _Process()
    db = FailOnceFinishDB()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    runner = RuntimeCommandRunner(str(tmp_path), db)
    assert runner.start("morning").accepted
    assert process.wait_started.wait(timeout=1)

    process.release_wait.set()
    _wait_until(lambda: bool(db.finished), message="terminal state was not retried")

    assert len(db.attempts) == 2
    assert db.attempts[0] == db.attempts[1]
    assert db.finished[0]["status"] == "ok"
    runner.shutdown(wait=True)


def test_shutdown_retains_terminal_state_and_owner_until_persistence_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class RecoverableFinishDB(_JobDB):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True
            self.attempts: list[tuple[int, str, str | None, int | None]] = []

        def job_run_finish(
            self,
            run_id: int,
            status: str,
            result_summary: str | None = None,
            symbols_processed: int | None = None,
            elapsed_ms: int | None = None,
            message: str | None = None,
        ) -> None:
            self.attempts.append((run_id, status, result_summary, elapsed_ms))
            if self.fail:
                raise RuntimeError("persistent failure")
            super().job_run_finish(
                run_id,
                status,
                result_summary,
                symbols_processed,
                elapsed_ms,
                message,
            )

    process = _Process()
    db = RecoverableFinishDB()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    runner = RuntimeCommandRunner(
        str(tmp_path),
        db,
        max_concurrent=1,
        shutdown_timeout_sec=0.1,
    )
    assert runner.start("morning").accepted
    assert process.wait_started.wait(timeout=1)
    process.release_wait.set()
    _wait_until(
        lambda: len(db.attempts) >= 3,
        message="watcher did not attempt terminal persistence",
    )
    assert runner.start("evening").outcome is CommandStartOutcome.SATURATED

    with pytest.raises(
        RuntimeError,
        match="pending_completions=1",
    ):
        runner.shutdown(wait=True)
    with pytest.raises(
        RuntimeError,
        match="runtime command owner already active for data root",
    ):
        RuntimeCommandRunner(str(tmp_path), _JobDB())

    first_completion = db.attempts[0]
    assert all(attempt == first_completion for attempt in db.attempts)
    db.fail = False
    runner.shutdown(wait=True)

    assert db.finished[0]["run_id"] == first_completion[0]
    assert db.finished[0]["status"] == first_completion[1]
    assert db.finished[0]["result_summary"] == first_completion[2]
    assert db.finished[0]["elapsed_ms"] == first_completion[3]
    replacement = RuntimeCommandRunner(str(tmp_path), _JobDB())
    replacement.shutdown(wait=True)


def test_pending_completion_self_heals_and_reopens_capacity_without_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class RecoveringFinishDB(_JobDB):
        def __init__(self) -> None:
            super().__init__()
            self.allow_finish = threading.Event()
            self.attempts = 0

        def job_run_finish(
            self,
            run_id: int,
            status: str,
            result_summary: str | None = None,
            symbols_processed: int | None = None,
            elapsed_ms: int | None = None,
            message: str | None = None,
        ) -> None:
            self.attempts += 1
            if not self.allow_finish.is_set():
                raise RuntimeError("temporarily unavailable")
            super().job_run_finish(
                run_id,
                status,
                result_summary,
                symbols_processed,
                elapsed_ms,
                message,
            )

    first_process = _Process()
    second_process = _Process()
    processes = iter((first_process, second_process))
    db = RecoveringFinishDB()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: next(processes))
    runner = RuntimeCommandRunner(str(tmp_path), db, max_concurrent=1)

    assert runner.start("morning").accepted
    first_process.release_wait.set()
    _wait_until(lambda: db.attempts >= 2, message="normal-uptime retry worker did not run")
    assert runner.start("evening").outcome is CommandStartOutcome.SATURATED
    assert len(runner._pending_completions) == 1

    db.allow_finish.set()
    _wait_until(lambda: bool(db.finished), message="pending completion did not self-heal")
    resumed = runner.start("evening")
    assert resumed.accepted

    second_process.release_wait.set()
    runner.shutdown(wait=True)


def test_begin_shutdown_closes_admission_while_start_persistence_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    persistence_started = threading.Event()
    release_persistence = threading.Event()

    class BlockingStartDB(_JobDB):
        def job_run_start(
            self,
            job_name: str,
            stage: str | None = None,
            trigger_event_id: int | None = None,
            *,
            run_key: str | None = None,
        ) -> int:
            del trigger_event_id, run_key
            persistence_started.set()
            assert release_persistence.wait(timeout=2)
            return self._start(job_name, stage)

    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("shutdown start must not spawn")
        ),
    )
    db = BlockingStartDB()
    runner = RuntimeCommandRunner(str(tmp_path), db, max_concurrent=1)
    results: list[CommandStartResult] = []
    start_thread = threading.Thread(
        target=lambda: results.append(runner.start("morning")),
        name="blocked-command-start",
    )
    start_thread.start()
    assert persistence_started.wait(timeout=1)

    started = time.monotonic()
    runner.begin_shutdown()
    assert time.monotonic() - started < 0.05
    assert runner.start("evening").outcome is CommandStartOutcome.STOPPING

    release_persistence.set()
    start_thread.join(timeout=2)
    assert results[0].outcome is CommandStartOutcome.STOPPING
    _wait_until(lambda: bool(db.finished), message="cancelled start was not finalized")
    runner.shutdown(wait=True)


def test_inflight_start_consumes_capacity_and_shutdown_honors_deadline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    persistence_started = threading.Event()
    release_persistence = threading.Event()

    class BlockingStartDB(_JobDB):
        def job_run_start(
            self,
            job_name: str,
            stage: str | None = None,
            trigger_event_id: int | None = None,
            *,
            run_key: str | None = None,
        ) -> int:
            del trigger_event_id, run_key
            persistence_started.set()
            assert release_persistence.wait(timeout=2)
            return self._start(job_name, stage)

    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stopping in-flight start must not spawn")
        ),
    )
    db = BlockingStartDB()
    runner = RuntimeCommandRunner(
        str(tmp_path),
        db,
        max_concurrent=1,
        shutdown_timeout_sec=0.05,
    )
    results: list[CommandStartResult] = []
    start_thread = threading.Thread(
        target=lambda: results.append(runner.start("morning")),
        name="deadline-blocked-command-start",
    )
    start_thread.start()
    assert persistence_started.wait(timeout=1)
    assert runner.start("evening").outcome is CommandStartOutcome.SATURATED

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="starts=1"):
        runner.shutdown(wait=True)
    assert time.monotonic() - started < 0.12
    with pytest.raises(
        RuntimeError,
        match="runtime command owner already active for data root",
    ):
        RuntimeCommandRunner(str(tmp_path), _JobDB())

    release_persistence.set()
    start_thread.join(timeout=2)
    assert results[0].outcome is CommandStartOutcome.STOPPING
    _wait_until(lambda: bool(db.finished), message="in-flight stop was not finalized")
    runner.shutdown(wait=True)


def test_transient_wait_failure_keeps_process_owned_until_terminal_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class TransientWaitProcess(_Process):
        def __init__(self) -> None:
            super().__init__()
            self.wait_attempts = 0

        def wait(self, timeout: float | None = None) -> int:
            self.wait_attempts += 1
            if self.wait_attempts == 1:
                self.wait_started.set()
                raise OSError("temporary wait failure")
            return super().wait(timeout=timeout)

    process = TransientWaitProcess()
    db = _JobDB()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    runner = RuntimeCommandRunner(str(tmp_path), db, max_concurrent=1)

    assert runner.start("morning").accepted
    assert process.wait_started.wait(timeout=1)
    assert runner.start("evening").outcome is CommandStartOutcome.SATURATED
    process.release_wait.set()
    _wait_until(lambda: bool(db.finished), message="terminal audit was lost after wait failure")

    assert process.wait_attempts >= 2
    assert db.finished[0]["status"] == "ok"
    runner.shutdown(wait=True)


def test_shutdown_deadline_bounds_blocked_completion_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    persistence_started = threading.Event()
    release_persistence = threading.Event()

    class BlockingFinishDB(_JobDB):
        def job_run_finish(
            self,
            run_id: int,
            status: str,
            result_summary: str | None = None,
            symbols_processed: int | None = None,
            elapsed_ms: int | None = None,
            message: str | None = None,
        ) -> None:
            persistence_started.set()
            assert release_persistence.wait(timeout=2)
            super().job_run_finish(
                run_id,
                status,
                result_summary,
                symbols_processed,
                elapsed_ms,
                message,
            )

    process = _Process()
    db = BlockingFinishDB()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    runner = RuntimeCommandRunner(
        str(tmp_path),
        db,
        shutdown_timeout_sec=0.05,
    )
    assert runner.start("morning").accepted
    assert process.wait_started.wait(timeout=1)
    process.release_wait.set()
    assert persistence_started.wait(timeout=1)

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="pending_completions=1"):
        runner.shutdown(wait=True)
    elapsed = time.monotonic() - started

    assert elapsed < 0.12
    with pytest.raises(
        RuntimeError,
        match="runtime command owner already active for data root",
    ):
        RuntimeCommandRunner(str(tmp_path), _JobDB())

    release_persistence.set()
    _wait_until(lambda: bool(db.finished), message="blocked persistence did not finish")
    runner.shutdown(wait=True)


def test_command_runner_watcher_failure_keeps_unterminated_process_owned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FailingProcess(_Process):
        def terminate(self) -> None:
            raise OSError("terminate denied")

    process = FailingProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    thread_start = threading.Thread.start

    def fail_watcher_start(thread: threading.Thread) -> None:
        if thread.name == "trade-web-command-persistence-retry":
            thread_start(thread)
            return
        raise RuntimeError("thread unavailable")

    monkeypatch.setattr(
        threading.Thread,
        "start",
        fail_watcher_start,
    )
    runner = RuntimeCommandRunner(
        str(tmp_path),
        _JobDB(),
        max_concurrent=1,
        shutdown_timeout_sec=0.01,
    )

    failed = runner.start("morning")

    assert failed.outcome is CommandStartOutcome.SPAWN_FAILED
    assert "thread unavailable" in str(failed.detail)
    assert "terminate denied" in str(failed.detail)
    assert runner.start("evening").outcome is CommandStartOutcome.STOPPING

    process.return_code = 0
    monkeypatch.setattr(threading.Thread, "start", thread_start)
    runner.shutdown(wait=True)


def test_command_runner_shutdown_kills_unresponsive_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    process = _Process()
    signals: list[int] = []

    def kill_group(_group_id: int, requested_signal: int) -> None:
        signals.append(requested_signal)
        if requested_signal == signal.SIGTERM:
            process.terminated = True
        elif requested_signal == signal.SIGKILL:
            process.killed = True
            process.release_wait.set()

    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(os, "killpg", kill_group)
    db = _JobDB()
    runner = RuntimeCommandRunner(
        str(tmp_path),
        db,
        max_concurrent=1,
        shutdown_timeout_sec=0.01,
    )
    assert runner.start("morning").accepted
    assert process.wait_started.wait(timeout=1)

    runner.shutdown(wait=True)

    assert process.terminated is True
    assert process.killed is True
    assert process.poll() == -9
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert db.finished[0]["status"] == "terminated"
    assert "exit_code=-9" in str(db.finished[0]["result_summary"])


def test_command_runner_shutdown_uses_one_deadline_for_all_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class DeadlineProcess(_Process):
        def wait(self, timeout: float | None = None) -> int:
            self.wait_timeouts.append(timeout)
            self.wait_started.set()
            wait_timeout = 2.0 if timeout is None else timeout
            if not self.release_wait.wait(timeout=wait_timeout):
                raise subprocess.TimeoutExpired("trade", wait_timeout)
            self.return_code = -9 if self.killed else -15 if self.terminated else 0
            return self.return_code

    processes = [DeadlineProcess(), DeadlineProcess(), DeadlineProcess()]
    process_iter = iter(processes)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: next(process_iter),
    )
    runner = RuntimeCommandRunner(
        str(tmp_path),
        _JobDB(),
        max_concurrent=len(processes),
        shutdown_timeout_sec=0.08,
    )
    for target in ("morning", "evening", "agenda"):
        assert runner.start(target).accepted
    assert all(process.wait_started.wait(timeout=1) for process in processes)

    started = time.monotonic()
    runner.shutdown(wait=True)
    elapsed = time.monotonic() - started

    assert elapsed < 0.16
    assert all(process.killed for process in processes)


def test_command_runner_shutdown_failure_stays_closed_until_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FailingProcess(_Process):
        def terminate(self) -> None:
            raise OSError("terminate denied")

    process = FailingProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    runner = RuntimeCommandRunner(
        str(tmp_path),
        _JobDB(),
        max_concurrent=1,
        shutdown_timeout_sec=0.01,
    )
    assert runner.start("morning").accepted
    assert process.wait_started.wait(timeout=1)

    with pytest.raises(RuntimeError, match="workflow command shutdown failed"):
        runner.shutdown(wait=True)
    rejected = runner.start("evening")
    assert rejected.outcome is CommandStartOutcome.STOPPING

    process.release_wait.set()
    for _ in range(100):
        if process.poll() is not None:
            break
        threading.Event().wait(0.01)
    else:
        raise AssertionError("command watcher did not observe process exit")
    runner.shutdown(wait=True)


def test_begin_shutdown_does_not_reclassify_natural_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    process = _Process()
    db = _JobDB()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    runner = RuntimeCommandRunner(str(tmp_path), db)

    assert runner.start("morning").accepted
    assert process.wait_started.wait(timeout=1)
    runner.begin_shutdown()
    process.release_wait.set()
    for _ in range(100):
        if db.finished:
            break
        threading.Event().wait(0.01)
    else:
        raise AssertionError("natural completion was not persisted")

    runner.shutdown(wait=True)
    assert db.finished[0]["status"] == "ok"
    assert "exit_code=0" in str(db.finished[0]["result_summary"])


def test_shutdown_waits_for_completion_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    finish_started = threading.Event()
    release_finish = threading.Event()

    class BlockingJobDB(_JobDB):
        def job_run_finish(
            self,
            run_id: int,
            status: str,
            result_summary: str | None = None,
            symbols_processed: int | None = None,
            elapsed_ms: int | None = None,
            message: str | None = None,
        ) -> None:
            finish_started.set()
            assert release_finish.wait(timeout=2)
            super().job_run_finish(
                run_id,
                status,
                result_summary,
                symbols_processed,
                elapsed_ms,
                message,
            )

    process = _Process()
    db = BlockingJobDB()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    runner = RuntimeCommandRunner(str(tmp_path), db, shutdown_timeout_sec=1.0)
    assert runner.start("morning").accepted
    assert process.wait_started.wait(timeout=1)
    process.release_wait.set()
    assert finish_started.wait(timeout=1)

    failures: list[BaseException] = []

    def shutdown() -> None:
        try:
            runner.shutdown(wait=True)
        except BaseException as exc:
            failures.append(exc)

    shutdown_thread = threading.Thread(target=shutdown, name="command-shutdown")
    shutdown_thread.start()
    assert shutdown_thread.is_alive()

    release_finish.set()
    shutdown_thread.join(timeout=2)

    assert not shutdown_thread.is_alive()
    assert not failures
    assert db.finished[0]["status"] == "ok"


def test_command_runner_reconciles_prior_runs_without_consuming_capacity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db = _JobDB()
    process = _Process()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)

    runner = RuntimeCommandRunner(str(tmp_path), db, max_concurrent=1)
    started = runner.start("morning")

    assert started.accepted
    assert db.reconciled[0][0:2] == ("web_command", "terminated")
    assert process.wait_started.wait(timeout=1)
    process.release_wait.set()
    runner.shutdown(wait=True)


def test_parent_death_arm_requests_self_termination_if_parent_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prctl_calls: list[tuple[int, int, int, int, int]] = []
    kill_calls: list[tuple[int, int]] = []
    libc = SimpleNamespace(
        prctl=lambda *args: prctl_calls.append(args) or 0,
    )
    monkeypatch.setattr(command_child.sys, "platform", "linux")
    monkeypatch.setattr(command_child.os, "getppid", lambda: 1)
    monkeypatch.setattr(command_child.os, "getpid", lambda: 9876)
    monkeypatch.setattr(command_child.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))
    monkeypatch.setattr(command_child.ctypes, "CDLL", lambda *_args, **_kwargs: libc)

    command_child._arm_parent_death_signal(signal.SIGTERM, owner_pid=4321)

    assert prctl_calls == [(1, signal.SIGTERM, 0, 0, 0)]
    assert kill_calls == [(9876, signal.SIGTERM)]


def test_command_runner_persists_queryable_run_in_real_temp_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    process = _Process()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        TradeDB,
        "job_runs_finish_running_stage",
        lambda _db, _stage, *, status, result_summary: 0,
        raising=False,
    )
    db = TradeDB(tmp_path)
    runner = RuntimeCommandRunner(str(tmp_path), cast(CommandRunStore, db))

    result = runner.start("morning", payload_json='{"secret":"not-persisted"}')
    running = db.job_runs_recent(stage="web_command")

    assert result.run_id is not None
    assert running[0]["id"] == result.run_id
    assert running[0]["status"] == "running"
    assert "not-persisted" not in str(running[0])

    process.release_wait.set()
    for _ in range(100):
        completed = db.job_runs_recent(stage="web_command")[0]
        if completed["status"] == "ok":
            break
        threading.Event().wait(0.01)
    else:
        raise AssertionError("real job_runs row was not completed")

    runner.shutdown(wait=True)
    db.close()
