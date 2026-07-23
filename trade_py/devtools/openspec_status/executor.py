"""Bounded process-tree execution for read-only OpenSpec collection."""

from __future__ import annotations

import os
import selectors
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from trade_py.devtools.openspec_status.errors import (
    WorkflowCollectionError,
    WorkflowError,
)


@dataclass(frozen=True)
class ProcessResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    duration_ms: int


class BoundedProcessExecutor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[int, subprocess.Popen[bytes]] = {}

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        deadline: float,
        timeout_seconds: float,
        output_limit_bytes: int,
        source: str,
        change: str | None = None,
        allowed_returncodes: frozenset[int] = frozenset({0}),
    ) -> ProcessResult:
        if not argv:
            raise ValueError("Process argv must not be empty")
        executable = _resolve_executable(argv[0], cwd)
        if executable is None:
            self._raise(
                "workflow.process.missing",
                source,
                change,
                f"Required executable is unavailable: {argv[0]}",
                f"Install {argv[0]} and rerun the workflow status command.",
            )
        assert executable is not None
        started = time.monotonic()
        local_deadline = min(deadline, started + timeout_seconds)
        try:
            process = subprocess.Popen(
                (executable, *argv[1:]),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            self._raise(
                "workflow.process.spawn",
                source,
                change,
                f"Cannot start {argv[0]}: {exc}",
                "Repair the local tool installation and rerun.",
            )
        self._register(process)
        try:
            assert process.stdout is not None
            assert process.stderr is not None
            try:
                stdout, stderr = self._communicate(
                    process,
                    deadline=local_deadline,
                    output_limit_bytes=output_limit_bytes,
                )
            except KeyboardInterrupt:
                _terminate_group(process)
                raise
            except _ProcessBoundError as exc:
                _terminate_group(process)
                self._raise(
                    exc.code,
                    source,
                    change,
                    exc.message,
                    "Fix the named dependency or reduce its output, then rerun.",
                )
            if _group_exists(process.pid):
                _terminate_group(process)
                self._raise(
                    "workflow.process.survivor",
                    source,
                    change,
                    f"{argv[0]} left a child process running after exit.",
                    "Repair the child process lifecycle and rerun.",
                )
            duration_ms = int((time.monotonic() - started) * 1000)
            if process.returncode not in allowed_returncodes:
                diagnostic = _diagnostic(stderr, stdout)
                suffix = f": {diagnostic}" if diagnostic else ""
                self._raise(
                    "workflow.process.exit",
                    source,
                    change,
                    f"{argv[0]} exited with code {process.returncode}{suffix}",
                    "Run the reported command directly, repair the failure, and rerun.",
                )
            return ProcessResult(
                argv=argv,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )
        finally:
            self._unregister(process)

    def cancel_all(self) -> None:
        with self._lock:
            active = tuple(self._active.values())
        for process in active:
            _terminate_group(process)

    def _register(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._active[process.pid] = process

    def _unregister(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._active.pop(process.pid, None)

    @staticmethod
    def _communicate(
        process: subprocess.Popen[bytes],
        *,
        deadline: float,
        output_limit_bytes: int,
    ) -> tuple[bytes, bytes]:
        if process.stdout is None or process.stderr is None:
            raise _ProcessBoundError(
                "workflow.process.pipe",
                "Child process did not expose bounded output pipes.",
            )
        streams = {
            process.stdout.fileno(): ("stdout", process.stdout),
            process.stderr.fileno(): ("stderr", process.stderr),
        }
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        total = 0
        selector = selectors.DefaultSelector()
        for descriptor, (_, stream) in streams.items():
            os.set_blocking(descriptor, False)
            selector.register(stream, selectors.EVENT_READ, descriptor)
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _ProcessBoundError(
                        "workflow.process.timeout",
                        "Child process exceeded its execution deadline.",
                    )
                for key, _ in selector.select(min(remaining, 0.1)):
                    descriptor = key.data
                    label, stream = streams[descriptor]
                    try:
                        chunk = os.read(descriptor, 65_536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        continue
                    total += len(chunk)
                    if total > output_limit_bytes:
                        raise _ProcessBoundError(
                            "workflow.process.output_limit",
                            f"Child output exceeded {output_limit_bytes} bytes.",
                        )
                    buffers[label].extend(chunk)
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise _ProcessBoundError(
                    "workflow.process.timeout",
                    "Child process did not exit before its deadline.",
                ) from exc
        finally:
            selector.close()
            process.stdout.close()
            process.stderr.close()
        return bytes(buffers["stdout"]), bytes(buffers["stderr"])

    @staticmethod
    def _raise(
        code: str,
        source: str,
        change: str | None,
        message: str,
        remediation: str,
    ) -> NoReturn:
        raise WorkflowCollectionError(
            WorkflowError(
                code=code,
                source=source,
                change=change,
                message=message,
                remediation=remediation,
            )
        )


@dataclass(frozen=True)
class _ProcessBoundError(RuntimeError):
    code: str
    message: str


def _resolve_executable(executable: str, cwd: Path) -> str | None:
    if "/" not in executable:
        return shutil.which(executable)
    candidate = Path(executable)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return (
        str(candidate.resolve()) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    )


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    deadline = time.monotonic() + 0.5
    while _group_exists(process.pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    if _group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _diagnostic(stderr: bytes, stdout: bytes) -> str:
    payload = stderr or stdout
    if len(payload) > 4096:
        payload = payload[-4096:]
    return payload.decode("utf-8", "replace").strip()
