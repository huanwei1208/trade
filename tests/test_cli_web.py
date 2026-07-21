from __future__ import annotations

import signal
import sys
import threading
from types import SimpleNamespace

import pytest

from trade_py.cli import web


def test_force_exit_safeguard_arms_watchdog_on_first_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: dict[int, object] = {}
    watchdogs: list[tuple[float, int, str, threading.Event | None]] = []

    monkeypatch.setattr(
        signal,
        "signal",
        lambda sig, handler: installed.__setitem__(sig, handler),
    )
    monkeypatch.setattr(
        web,
        "_schedule_force_exit",
        lambda delay, *, exit_code, reason, cancel_event=None: watchdogs.append(
            (delay, exit_code, reason, cancel_event)
        ),
    )

    web._install_force_exit_safeguard(watchdog_delay=5.0)
    handler = installed[signal.SIGINT]
    assert callable(handler)

    handler(signal.SIGINT, None)

    assert len(watchdogs) == 1
    assert watchdogs[0][0:3] == (5.0, 130, "interrupt shutdown deadline exceeded")
    assert isinstance(watchdogs[0][3], threading.Event)
    assert not watchdogs[0][3].is_set()
    assert installed[signal.SIGINT] is handler


def test_clean_uvicorn_return_does_not_arm_forced_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda *_args, **_kwargs: calls.append("uvicorn")),
    )
    shutdown_complete = threading.Event()
    monkeypatch.setattr(
        web,
        "_install_force_exit_safeguard",
        lambda **_kwargs: shutdown_complete,
    )
    monkeypatch.setattr(
        web,
        "_schedule_force_exit",
        lambda *_args, **_kwargs: calls.append("forced"),
    )
    monkeypatch.setattr(web, "_non_daemon_thread_names", lambda: [])

    assert web.main([]) == 0
    assert calls == ["uvicorn"]
    assert shutdown_complete.is_set()


def test_incomplete_uvicorn_return_arms_nonzero_diagnostic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[tuple[float, int, str]] = []
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        web,
        "_install_force_exit_safeguard",
        lambda **_kwargs: threading.Event(),
    )
    monkeypatch.setattr(web, "_non_daemon_thread_names", lambda: ["stuck-worker"])
    monkeypatch.setattr(
        web,
        "_schedule_force_exit",
        lambda delay, *, exit_code, reason, **_kwargs: scheduled.append((delay, exit_code, reason)),
    )

    assert web.main([]) == 0
    assert scheduled == [
        (
            2.0,
            1,
            "incomplete shutdown; non-daemon threads remain: stuck-worker",
        )
    ]


def test_forced_exit_is_nonzero_and_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_codes: list[int] = []

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs) -> None:
            self._target = target

        def start(self) -> None:
            self._target()

    monkeypatch.setattr(web.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(web.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(web, "_non_daemon_thread_names", lambda: [])
    monkeypatch.setattr(web.os, "_exit", lambda code: exit_codes.append(code))

    web._schedule_force_exit(
        0.1,
        exit_code=130,
        reason="test incomplete shutdown",
    )

    assert exit_codes == [130]
    diagnostic = capsys.readouterr().err
    assert "test incomplete shutdown" in diagnostic
    assert "exit_code=130" in diagnostic


def test_completed_shutdown_cancels_armed_force_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_codes: list[int] = []
    cancellation = threading.Event()
    cancellation.set()

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs) -> None:
            self._target = target

        def start(self) -> None:
            self._target()

    monkeypatch.setattr(web.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(web.os, "_exit", lambda code: exit_codes.append(code))

    web._schedule_force_exit(
        5.0,
        exit_code=130,
        reason="interrupt shutdown deadline exceeded",
        cancel_event=cancellation,
    )

    assert exit_codes == []


def test_cli_web_does_not_take_private_event_bus_shutdown_authority() -> None:
    assert not hasattr(web, "_shutdown_background_resources")
