from __future__ import annotations

import signal

import pytest

from trade_py.cli import web


def test_force_exit_safeguard_arms_watchdog_on_first_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: dict[int, object] = {}
    watchdogs: list[float] = []

    monkeypatch.setattr(
        signal,
        "signal",
        lambda sig, handler: installed.__setitem__(sig, handler),
    )
    monkeypatch.setattr(
        web,
        "_schedule_force_exit",
        lambda delay: watchdogs.append(delay),
    )

    web._install_force_exit_safeguard(watchdog_delay=5.0)
    handler = installed[signal.SIGINT]
    assert callable(handler)

    handler(signal.SIGINT, None)

    assert watchdogs == [5.0]
    assert installed[signal.SIGINT] is signal.SIG_DFL


def test_cli_web_does_not_take_private_event_bus_shutdown_authority() -> None:
    assert not hasattr(web, "_shutdown_background_resources")
