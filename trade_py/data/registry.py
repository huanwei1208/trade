"""Data source registry: maps source_id → DataSource factory function.

Usage:
    from trade_py.data.registry import register, get, list_sources

    # Register a source (done at module level by each provider)
    register("rss", lambda feeds: RssSource(feeds))

    # Retrieve and instantiate
    src = get("rss", feeds=[...])
    records = src.fetch(since, until)
"""

from __future__ import annotations

import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Callable[..., Any]] = {}


def register(source_id: str, factory: Callable[..., Any]) -> None:
    """Register a DataSource factory under source_id."""
    if source_id in _REGISTRY:
        logger.warning("Overwriting existing registry entry for %r", source_id)
    _REGISTRY[source_id] = factory


def get(source_id: str, **kwargs) -> Any:
    """Instantiate a registered DataSource by source_id.

    Raises KeyError if source_id is not registered.
    """
    if source_id not in _REGISTRY:
        available = list(_REGISTRY)
        raise KeyError(
            f"No DataSource registered for {source_id!r}. "
            f"Available: {available}"
        )
    return _REGISTRY[source_id](**kwargs)


def list_sources() -> list[str]:
    """Return all registered source IDs."""
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Built-in registrations
# ---------------------------------------------------------------------------

def _register_defaults() -> None:
    from trade_py.data.news.rss.base import RssSource
    register("rss", lambda feeds=None, **_: RssSource(feeds or []))

    from trade_py.data.news.gdelt.source import GdeltSource
    register("gdelt", lambda **kw: GdeltSource(**kw))

    from trade_py.data.news.cls_source import ClsSource
    register("cls", lambda **kw: ClsSource(**kw))


try:
    _register_defaults()
except Exception as exc:  # pragma: no cover
    logger.debug("Default source registration skipped: %s", exc)
