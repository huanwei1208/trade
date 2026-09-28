"""One monotonic deadline shared by a layout-status invocation."""

from __future__ import annotations

import signal
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import NoReturn

from trade_py.devtools.layout_status.errors import invalid


@dataclass(frozen=True)
class InvocationDeadline:
    seconds: float = 5.0
    monotonic: Callable[[], float] = time.monotonic
    _expires_at: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.seconds <= 0:
            raise invalid(
                "layout.status.deadline",
                "Layout evidence validation requires a positive deadline.",
            )
        object.__setattr__(self, "_expires_at", float(self.monotonic()) + self.seconds)

    def check(self) -> None:
        if self.remaining() <= 0:
            self._raise()

    def remaining(self) -> float:
        return self._expires_at - float(self.monotonic())

    @contextmanager
    def interrupt_blocking_calls(self) -> Iterator[None]:
        """Interrupt blocking local syscalls while retaining one absolute deadline."""

        if (
            threading.current_thread() is not threading.main_thread()
            or not hasattr(signal, "setitimer")
            or not hasattr(signal, "SIGALRM")
        ):
            raise invalid(
                "layout.status.deadline_unavailable",
                "This platform cannot enforce the layout validation deadline.",
            )
        self.check()
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_delay, previous_interval = signal.setitimer(signal.ITIMER_REAL, 0)
        started_at = float(self.monotonic())

        def on_alarm(_signum: int, _frame: object) -> NoReturn:
            self._raise()

        signal.signal(signal.SIGALRM, on_alarm)
        signal.setitimer(signal.ITIMER_REAL, max(self.remaining(), 0.000_001))
        try:
            yield
            self.check()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_delay > 0:
                elapsed = max(0.0, float(self.monotonic()) - started_at)
                signal.setitimer(
                    signal.ITIMER_REAL,
                    max(previous_delay - elapsed, 0.000_001),
                    previous_interval,
                )

    @staticmethod
    def _raise() -> NoReturn:
        raise invalid(
            "layout.status.deadline",
            "Layout evidence validation exceeded five seconds.",
        )


__all__ = ["InvocationDeadline"]
