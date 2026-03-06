"""ProgressCallback type alias and standard implementations."""

from __future__ import annotations

import sys
from typing import Callable

ProgressCallback = Callable[[str], None]


def stderr_progress(msg: str) -> None:
    """Print progress to stderr (default for CLI use)."""
    print(msg, file=sys.stderr, flush=True)


def stdout_progress(msg: str) -> None:
    """Print progress to stdout."""
    print(msg, flush=True)


def noop_progress(msg: str) -> None:  # noqa: ARG001
    """Discard progress messages (for tests / silent mode)."""
