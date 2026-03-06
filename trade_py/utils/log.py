"""Unified logging configuration.

Call setup() once at CLI entry point. All submodules use getLogger(__name__).
"""

from __future__ import annotations

import logging
import sys


def setup(
    level: str = "INFO",
    fmt: str = "%(asctime)s %(levelname)s %(name)s: %(message)s",
) -> None:
    """Configure root logger for CLI entrypoint."""
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        force=True,
    )


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
