"""Linux subreaper supervisor for one bounded validation command."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_PR_SET_CHILD_SUBREAPER = 36
_TERM_GRACE_SECONDS = 0.5
_KILL_GRACE_SECONDS = 0.5
_PIPE_DRAIN_SECONDS = 0.2


def _enable_subreaper() -> None:
    if not sys.platform.startswith("linux") or not Path("/proc/self/task").is_dir():
        raise RuntimeError("linux_subreaper_unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, "cannot enable child subreaper")


def _children(parent: int) -> tuple[int, ...]:
    path = Path(f"/proc/{parent}/task/{parent}/children")
    try:
        content = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return ()
    if not content:
        return ()
    return tuple(int(value) for value in content.split() if value.isdigit())


def _descendants() -> tuple[int, ...]:
    pending = list(_children(os.getpid()))
    discovered: set[int] = set()
    while pending:
        pid = pending.pop()
        if pid in discovered:
            continue
        discovered.add(pid)
        pending.extend(_children(pid))
    return tuple(sorted(discovered))


def _signal_descendants(signum: signal.Signals) -> None:
    for pid in reversed(_descendants()):
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            raise RuntimeError("descendant_signal_denied") from exc


def _reap_adopted(target_pid: int) -> None:
    for pid in _children(os.getpid()):
        if pid == target_pid:
            continue
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            continue


def _terminate_all(process: subprocess.Popen[bytes]) -> int:
    _signal_descendants(signal.SIGTERM)
    deadline = time.monotonic() + _TERM_GRACE_SECONDS
    while _descendants() and time.monotonic() < deadline:
        process.poll()
        _reap_adopted(process.pid)
        time.sleep(0.01)
    if _descendants():
        _signal_descendants(signal.SIGKILL)
    deadline = time.monotonic() + _KILL_GRACE_SECONDS
    while _descendants() and time.monotonic() < deadline:
        process.poll()
        _reap_adopted(process.pid)
        time.sleep(0.01)
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait(timeout=1)
    _reap_adopted(process.pid)
    return len(_descendants())


def _rss_bytes(pid: int) -> int:
    try:
        rows = Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError):
        return 0
    for row in rows:
        if not row.startswith("VmRSS:"):
            continue
        fields = row.split()
        if len(fields) == 3 and fields[1].isdigit() and fields[2] == "kB":
            return int(fields[1]) * 1024
    return 0


def _process_tree_rss_bytes() -> int:
    return sum(_rss_bytes(pid) for pid in _descendants())


def _tree_size(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for parent, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        files.sort()
        for name in files:
            path = Path(parent) / name
            try:
                metadata = path.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(metadata.st_mode):
                total += metadata.st_size
    return total


def _read_config() -> dict[str, Any]:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise TypeError("supervisor config must be an object")
    expected = {
        "argv",
        "cwd",
        "output_limit_bytes",
        "rss_limit_bytes",
        "temp_limit_bytes",
        "temp_root",
        "timeout_seconds",
    }
    if set(payload) != expected:
        raise ValueError("supervisor config fields differ")
    argv = payload["argv"]
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise TypeError("supervisor argv must be a non-empty string array")
    return payload


def _supervise(config: dict[str, Any]) -> dict[str, Any]:
    argv = tuple(config["argv"])
    cwd = Path(config["cwd"])
    timeout_seconds = float(config["timeout_seconds"])
    output_limit_bytes = int(config["output_limit_bytes"])
    rss_limit_bytes = int(config["rss_limit_bytes"])
    temp_limit_bytes = int(config["temp_limit_bytes"])
    temp_root_value = config["temp_root"]
    temp_root = Path(temp_root_value) if isinstance(temp_root_value, str) else None
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=False,
    )
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("target_pipe_unavailable")
    streams = {
        process.stdout.fileno(): ("stdout", bytearray()),
        process.stderr.fileno(): ("stderr", bytearray()),
    }
    selector = selectors.DefaultSelector()
    for descriptor in streams:
        os.set_blocking(descriptor, False)
        selector.register(descriptor, selectors.EVENT_READ)

    failure_code: str | None = None
    timed_out = False
    peak_rss_bytes = 0
    peak_temp_bytes = 0
    next_temp_sample = 0.0
    deadline = started + timeout_seconds
    try:
        while selector.get_map():
            now = time.monotonic()
            peak_rss_bytes = max(peak_rss_bytes, _process_tree_rss_bytes())
            if temp_root is not None and now >= next_temp_sample:
                peak_temp_bytes = max(peak_temp_bytes, _tree_size(temp_root))
                next_temp_sample = now + 0.25
            if rss_limit_bytes and peak_rss_bytes > rss_limit_bytes:
                failure_code = "layout.performance.capacity_rss"
                break
            if temp_limit_bytes and peak_temp_bytes > temp_limit_bytes:
                failure_code = "layout.performance.capacity_temp"
                break
            if now >= deadline:
                timed_out = True
                failure_code = "layout.performance.process_timeout"
                break

            events = selector.select(timeout=min(deadline - now, 0.02))
            returncode = process.poll()
            if returncode is not None:
                _reap_adopted(process.pid)
                if _descendants():
                    failure_code = "layout.performance.process_survivor"
                    break
                if not events:
                    events = tuple(
                        (key, selectors.EVENT_READ) for key in selector.get_map().values()
                    )
            for key, _mask in events:
                descriptor = int(key.fd)
                try:
                    chunk = os.read(descriptor, 64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(descriptor)
                    continue
                name, output = streams[descriptor]
                remaining = max(0, output_limit_bytes - len(output))
                output.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    failure_code = f"layout.performance.process_output_{name}"
                    break
            if failure_code is not None:
                break

        survivors = 0
        if failure_code is not None or process.poll() is None or _descendants():
            survivors = _terminate_all(process)
        elif process.poll() is None:
            process.wait(timeout=1)

        drain_deadline = time.monotonic() + _PIPE_DRAIN_SECONDS
        while selector.get_map() and time.monotonic() < drain_deadline:
            for key, _mask in selector.select(timeout=0.01):
                descriptor = int(key.fd)
                try:
                    chunk = os.read(descriptor, 64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(descriptor)
                    continue
                _name, output = streams[descriptor]
                remaining = max(0, output_limit_bytes - len(output))
                output.extend(chunk[:remaining])
        peak_rss_bytes = max(peak_rss_bytes, _process_tree_rss_bytes())
        if temp_root is not None:
            peak_temp_bytes = max(peak_temp_bytes, _tree_size(temp_root))
        if failure_code is None and rss_limit_bytes and peak_rss_bytes > rss_limit_bytes:
            failure_code = "layout.performance.capacity_rss"
        if failure_code is None and temp_limit_bytes and peak_temp_bytes > temp_limit_bytes:
            failure_code = "layout.performance.capacity_temp"
        if survivors:
            failure_code = "layout.performance.process_cleanup"
        return {
            "cleanup_survivors": survivors,
            "duration_ms": (time.monotonic() - started) * 1000,
            "failure_code": failure_code,
            "peak_process_tree_rss_bytes": peak_rss_bytes,
            "peak_temp_bytes": peak_temp_bytes,
            "returncode": process.returncode if process.returncode is not None else -1,
            "stderr": base64.b64encode(bytes(streams[process.stderr.fileno()][1])).decode("ascii"),
            "stdout": base64.b64encode(bytes(streams[process.stdout.fileno()][1])).decode("ascii"),
            "timed_out": timed_out,
        }
    except BaseException:
        if process.poll() is None or _descendants():
            _terminate_all(process)
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()


def main() -> int:
    try:
        _enable_subreaper()
        payload = _supervise(_read_config())
    except BaseException as exc:
        payload = {
            "failure_code": "layout.performance.supervisor_unavailable",
            "failure_type": type(exc).__name__,
        }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
