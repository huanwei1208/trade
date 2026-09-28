"""Finite process-group execution for layout performance probes."""

from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_SUPERVISOR_GRACE_SECONDS = 5.0
_SAFE_ENVIRONMENT_NAMES = frozenset(
    {
        "CI",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NO_COLOR",
        "NO_UPDATE_NOTIFIER",
        "PATH",
        "PIP_NO_INDEX",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONHASHSEED",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "SOURCE_DATE_EPOCH",
        "TERM",
        "TMP",
        "TEMP",
        "TMPDIR",
        "TRADE_DATA_ROOT",
        "UV_FROZEN",
        "UV_NO_SYNC",
        "UV_OFFLINE",
    }
)
_SAFE_ENVIRONMENT_PREFIXES = ("NPM_CONFIG_",)


@dataclass(frozen=True)
class ProcessOutcome:
    stdout: bytes
    stderr: bytes
    returncode: int
    duration_ms: float
    timed_out: bool
    cleanup_survivors: int
    peak_process_tree_rss_bytes: int = 0
    peak_temp_bytes: int = 0


class PerformanceProcessError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def run_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    timeout_seconds: float,
    output_limit_bytes: int = 1024 * 1024,
    allowed_returncodes: frozenset[int] = frozenset({0}),
    env: dict[str, str] | None = None,
    allow_timeout: bool = False,
    rss_limit_bytes: int = 0,
    temp_limit_bytes: int = 0,
    temp_root: Path | None = None,
) -> ProcessOutcome:
    if (
        not argv
        or timeout_seconds <= 0
        or output_limit_bytes < 1
        or rss_limit_bytes < 0
        or temp_limit_bytes < 0
    ):
        raise ValueError("process argv and timeout must be finite")
    config = json.dumps(
        {
            "argv": list(argv),
            "cwd": str(cwd.resolve()),
            "output_limit_bytes": output_limit_bytes,
            "rss_limit_bytes": rss_limit_bytes,
            "temp_limit_bytes": temp_limit_bytes,
            "temp_root": str(temp_root.resolve()) if temp_root is not None else None,
            "timeout_seconds": timeout_seconds,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    supervisor = Path(__file__).with_name("process_supervisor.py")
    try:
        process = subprocess.Popen(
            (sys.executable, str(supervisor)),
            cwd=cwd,
            env=_sanitized_environment(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise PerformanceProcessError(
            "layout.performance.process_spawn",
            f"cannot start validation supervisor for {Path(argv[0]).name}",
        ) from exc
    try:
        stdout, _stderr = process.communicate(
            config,
            timeout=timeout_seconds + _SUPERVISOR_GRACE_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        _terminate_group(process)
        raise PerformanceProcessError(
            "layout.performance.supervisor_timeout",
            "validation supervisor exceeded its cleanup deadline",
        ) from exc
    if process.returncode != 0 or len(stdout) > output_limit_bytes * 3 + 64 * 1024:
        raise PerformanceProcessError(
            "layout.performance.supervisor_failure",
            "validation supervisor did not return bounded evidence",
        )
    payload = _supervisor_payload(stdout)
    failure_code = payload.get("failure_code")
    if failure_code == "layout.performance.supervisor_unavailable":
        raise PerformanceProcessError(
            "layout.performance.unavailable_prerequisite",
            "complete validation-process containment is unavailable",
        )
    timed_out = _boolean(payload, "timed_out")
    survivors = _integer(payload, "cleanup_survivors")
    returncode = _integer(payload, "returncode", allow_negative=True)
    outcome = ProcessOutcome(
        stdout=_decoded_output(payload, "stdout", output_limit_bytes),
        stderr=_decoded_output(payload, "stderr", output_limit_bytes),
        returncode=returncode,
        duration_ms=_number(payload, "duration_ms"),
        timed_out=timed_out,
        cleanup_survivors=survivors,
        peak_process_tree_rss_bytes=_integer(payload, "peak_process_tree_rss_bytes"),
        peak_temp_bytes=_integer(payload, "peak_temp_bytes"),
    )
    command = Path(argv[0]).name
    if survivors:
        raise PerformanceProcessError(
            "layout.performance.process_cleanup",
            f"{command} left validation descendants after cleanup",
        )
    if timed_out and not allow_timeout:
        raise PerformanceProcessError(
            "layout.performance.process_timeout",
            f"{command} exceeded its bounded deadline",
        )
    if isinstance(failure_code, str) and not timed_out:
        if failure_code.startswith("layout.performance.capacity_"):
            raise PerformanceProcessError(failure_code, "validation resource limit exceeded")
        if failure_code.startswith("layout.performance.process_output_"):
            raise PerformanceProcessError(
                "layout.performance.process_output",
                f"{command} exceeded its bounded output limit",
            )
        raise PerformanceProcessError(failure_code, f"{command} did not complete cleanly")
    if not timed_out and returncode not in allowed_returncodes:
        raise PerformanceProcessError(
            "layout.performance.process_exit",
            f"{command} exited with status {returncode}",
        )
    return outcome


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    deadline = time.monotonic() + 0.5
    while _group_exists(process.pid) and time.monotonic() < deadline:
        process.poll()
        time.sleep(0.01)
    if _group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        raise PerformanceProcessError(
            "layout.performance.process_cleanup",
            f"process group {process.pid} survived TERM-to-KILL cleanup",
        ) from exc
    deadline = time.monotonic() + 0.5
    while _group_exists(process.pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    if _group_exists(process.pid):
        raise PerformanceProcessError(
            "layout.performance.process_cleanup",
            f"process group {process.pid} remains after cleanup",
        )


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _sanitized_environment(environment: dict[str, str] | None) -> dict[str, str]:
    source = os.environ if environment is None else environment
    selected = {
        name: value
        for name, value in source.items()
        if name in _SAFE_ENVIRONMENT_NAMES
        or any(name.startswith(prefix) for prefix in _SAFE_ENVIRONMENT_PREFIXES)
    }
    selected.setdefault("PATH", os.defpath)
    selected["PYTHONDONTWRITEBYTECODE"] = "1"
    return selected


def _supervisor_payload(raw: bytes) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PerformanceProcessError(
            "layout.performance.supervisor_failure",
            "validation supervisor returned invalid evidence",
        ) from exc
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise PerformanceProcessError(
            "layout.performance.supervisor_failure",
            "validation supervisor evidence must be an object",
        )
    return payload


def _decoded_output(payload: dict[str, object], key: str, limit: int) -> bytes:
    value = payload.get(key)
    if not isinstance(value, str):
        raise PerformanceProcessError(
            "layout.performance.supervisor_failure",
            "validation supervisor omitted captured output",
        )
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise PerformanceProcessError(
            "layout.performance.supervisor_failure",
            "validation supervisor output encoding is invalid",
        ) from exc
    if len(decoded) > limit:
        raise PerformanceProcessError(
            "layout.performance.process_output",
            f"{key} exceeded its bounded output limit",
        )
    return decoded


def _integer(
    payload: dict[str, object],
    key: str,
    *,
    allow_negative: bool = False,
) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or (not allow_negative and value < 0):
        raise PerformanceProcessError(
            "layout.performance.supervisor_failure",
            f"validation supervisor field {key} is invalid",
        )
    return value


def _number(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise PerformanceProcessError(
            "layout.performance.supervisor_failure",
            f"validation supervisor field {key} is invalid",
        )
    return float(value)


def _boolean(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise PerformanceProcessError(
            "layout.performance.supervisor_failure",
            f"validation supervisor field {key} is invalid",
        )
    return value


__all__ = [
    "PerformanceProcessError",
    "ProcessOutcome",
    "run_process",
]
