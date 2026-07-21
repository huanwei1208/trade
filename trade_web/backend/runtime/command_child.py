"""Crash-safe supervisor for one Web-owned workflow command."""

from __future__ import annotations

import argparse
import ctypes
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from types import FrameType

_PR_SET_PDEATHSIG = 1
_POLL_INTERVAL_SEC = 0.05


def _arm_parent_death_signal(signum: int, *, owner_pid: int) -> None:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Web command parent-death supervision requires Linux")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_PDEATHSIG, signum, 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    if os.getppid() != owner_pid:
        os.kill(os.getpid(), signum)


def _stop_process_group(
    process: subprocess.Popen[bytes],
    signum: int,
    *,
    shutdown_timeout_sec: float,
) -> None:
    signal.signal(signum, signal.SIG_IGN)
    try:
        os.killpg(os.getpgrp(), signum)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=shutdown_timeout_sec)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgrp(), signal.SIGKILL)


def supervise(
    command: Sequence[str],
    *,
    owner_pid: int,
    shutdown_timeout_sec: float,
) -> int:
    if not command:
        raise ValueError("workflow command is required")
    requested_signal: int | None = None

    def request_shutdown(signum: int, _frame: FrameType | None) -> None:
        nonlocal requested_signal
        if requested_signal is None:
            requested_signal = signum

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, request_shutdown)
    _arm_parent_death_signal(signal.SIGTERM, owner_pid=owner_pid)
    if requested_signal is not None:
        return 128 + requested_signal

    process = subprocess.Popen(list(command), stdin=subprocess.DEVNULL)
    while True:
        return_code = process.poll()
        if return_code is not None:
            return return_code if return_code >= 0 else 128 - return_code
        if requested_signal is not None:
            _stop_process_group(
                process,
                requested_signal,
                shutdown_timeout_sec=shutdown_timeout_sec,
            )
            return 128 + requested_signal
        time.sleep(_POLL_INTERVAL_SEC)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-pid", type=int, required=True)
    parser.add_argument("--shutdown-timeout-sec", type=float, default=5.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if args.shutdown_timeout_sec <= 0:
        parser.error("--shutdown-timeout-sec must be positive")
    if args.owner_pid <= 1:
        parser.error("--owner-pid must identify the Web owner process")
    if not command:
        parser.error("workflow command is required after --")
    return supervise(
        command,
        owner_pid=int(args.owner_pid),
        shutdown_timeout_sec=float(args.shutdown_timeout_sec),
    )


if __name__ == "__main__":
    raise SystemExit(main())
