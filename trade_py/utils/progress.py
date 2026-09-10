"""ProgressCallback type alias and standard implementations."""

from __future__ import annotations

import os
import sys
from typing import Callable, Iterable, Iterator, TypeVar

ProgressCallback = Callable[[str], None]

T = TypeVar("T")


def stderr_progress(msg: str) -> None:
    """Print progress to stderr (default for CLI use)."""
    print(msg, file=sys.stderr, flush=True)


def stdout_progress(msg: str) -> None:
    """Print progress to stdout."""
    print(msg, flush=True)


def noop_progress(msg: str) -> None:  # noqa: ARG001
    """Discard progress messages (for tests / silent mode)."""


def progress_disabled() -> bool:
    """Whether animated progress bars should be suppressed.

    tqdm rewrites one line via carriage returns. Anywhere that cannot happen
    -- a pipe, a log file -- every refresh lands as a new line and drowns the
    log. isatty() alone is not enough: dagu's ssh2 executor allocates a PTY,
    so a scheduled run looks interactive while its output goes to a log file.
    TRADE_NO_PROGRESS=1 is the explicit opt-out for those callers.
    """
    if os.environ.get("TRADE_NO_PROGRESS", "").strip() not in ("", "0", "false"):
        return True
    return not getattr(sys.stderr, "isatty", lambda: False)()


def iter_progress(items: Iterable[T], desc: str = "", unit: str = "item") -> Iterator[T]:
    """Wrap an iterable with a tqdm progress bar.

    Redirects logging through tqdm so log messages don't break the bar.

    Usage:
        for sym in iter_progress(symbols, desc="fund-flow", unit="sym"):
            fetcher.fetch_and_save(sym)
    """
    try:
        from tqdm import tqdm
        from tqdm.contrib.logging import logging_redirect_tqdm
    except ImportError:
        yield from items
        return

    with logging_redirect_tqdm():
        with tqdm(items, desc=desc, unit=unit, dynamic_ncols=True,
                  disable=progress_disabled()) as bar:
            for item in bar:
                if isinstance(item, str):
                    bar.set_postfix_str(item[:30], refresh=False)
                yield item
