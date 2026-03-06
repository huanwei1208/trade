"""Generic retry logic.

Example:
    @retry(delays=(1, 5, 15), on=(IOError,))
    def fetch():
        ...
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Sequence, Type

logger = logging.getLogger(__name__)


def retry(
    delays: Sequence[float] = (1, 5, 15),
    on: tuple[Type[Exception], ...] = (Exception,),
    progress_cb: Callable[[str], None] | None = None,
):
    """Decorator: retry on specified exceptions with exponential back-off."""
    def decorator(fn: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            for attempt, delay in enumerate((*delays, None), start=1):
                try:
                    return fn(*args, **kwargs)
                except on as exc:
                    if delay is None:
                        raise
                    exc_name = type(exc).__name__
                    msg = (
                        f"[retry] {fn.__name__} attempt={attempt} "
                        f"error_type={exc_name} error={exc!r} retry_in={delay}s"
                    )
                    logger.warning(msg)
                    if progress_cb:
                        progress_cb(msg)
                    time.sleep(delay)
        return wrapper
    return decorator
