from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from trade_py.devtools.openspec_status.errors import WorkflowCollectionError
from trade_py.devtools.openspec_status.executor import BoundedProcessExecutor


def _run(
    executor: BoundedProcessExecutor,
    tmp_path: Path,
    script: str,
    *,
    timeout: float = 2,
    output_limit: int = 4096,
) -> bytes:
    return executor.run(
        (sys.executable, "-c", script),
        cwd=tmp_path,
        deadline=time.monotonic() + timeout,
        timeout_seconds=timeout,
        output_limit_bytes=output_limit,
        source="openspec",
    ).stdout


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for_pid(path: Path) -> int:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return int(path.read_text(encoding="utf-8"))
        time.sleep(0.01)
    raise AssertionError("child pid was not written")


def test_executor_returns_separate_bounded_streams(tmp_path: Path) -> None:
    executor = BoundedProcessExecutor()

    result = executor.run(
        (
            sys.executable,
            "-c",
            "import sys; print('json'); print('progress', file=sys.stderr)",
        ),
        cwd=tmp_path,
        deadline=time.monotonic() + 2,
        timeout_seconds=2,
        output_limit_bytes=1024,
        source="openspec",
    )

    assert result.stdout == b"json\n"
    assert result.stderr == b"progress\n"
    assert result.returncode == 0


def test_executor_kills_process_group_on_timeout(tmp_path: Path) -> None:
    child_pid = tmp_path / "child.pid"
    script = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid));"
        "time.sleep(60)"
    )

    with pytest.raises(WorkflowCollectionError) as raised:
        _run(BoundedProcessExecutor(), tmp_path, script, timeout=0.2)

    pid = _wait_for_pid(child_pid)
    assert raised.value.error.code == "workflow.process.timeout"
    assert not _pid_exists(pid)


def test_executor_kills_process_group_on_combined_output_limit(tmp_path: Path) -> None:
    script = (
        "import sys,time;"
        "sys.stdout.write('a'*700);sys.stdout.flush();"
        "sys.stderr.write('b'*700);sys.stderr.flush();"
        "time.sleep(60)"
    )

    with pytest.raises(WorkflowCollectionError) as raised:
        _run(BoundedProcessExecutor(), tmp_path, script, output_limit=1024)

    assert raised.value.error.code == "workflow.process.output_limit"


def test_executor_rejects_and_reaps_inherited_survivor(tmp_path: Path) -> None:
    child_pid = tmp_path / "survivor.pid"
    script = (
        "import pathlib,subprocess,sys;"
        "child=subprocess.Popen("
        "[sys.executable,'-c','import time; time.sleep(60)'],"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid))"
    )

    with pytest.raises(WorkflowCollectionError) as raised:
        _run(BoundedProcessExecutor(), tmp_path, script)

    pid = _wait_for_pid(child_pid)
    assert raised.value.error.code == "workflow.process.survivor"
    assert not _pid_exists(pid)


def test_cancel_all_terminates_active_process_group(tmp_path: Path) -> None:
    executor = BoundedProcessExecutor()
    child_pid = tmp_path / "cancel.pid"
    script = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid));"
        "time.sleep(60)"
    )
    errors: list[BaseException] = []

    def run() -> None:
        try:
            _run(executor, tmp_path, script, timeout=10)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    pid = _wait_for_pid(child_pid)
    executor.cancel_all()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors
    assert not _pid_exists(pid)


def test_executor_reaps_process_group_on_unexpected_reader_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    child_pid = tmp_path / "unexpected.pid"
    script = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid));"
        "time.sleep(60)"
    )

    def fail_after_child_started(
        _process: object,
        *,
        deadline: float,
        output_limit_bytes: int,
    ) -> tuple[bytes, bytes]:
        del deadline, output_limit_bytes
        _wait_for_pid(child_pid)
        raise RuntimeError("unexpected selector failure")

    monkeypatch.setattr(
        BoundedProcessExecutor,
        "_communicate",
        staticmethod(fail_after_child_started),
    )

    with pytest.raises(RuntimeError, match="unexpected selector failure"):
        _run(BoundedProcessExecutor(), tmp_path, script)

    assert not _pid_exists(_wait_for_pid(child_pid))
