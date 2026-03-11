"""ProgressCallback type alias and standard implementations."""

from __future__ import annotations

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
        with tqdm(items, desc=desc, unit=unit, dynamic_ncols=True) as bar:
            for item in bar:
                if isinstance(item, str):
                    bar.set_postfix_str(item[:30], refresh=False)
                yield item
