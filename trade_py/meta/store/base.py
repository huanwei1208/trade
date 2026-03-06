"""AbstractMetaStore protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from trade_py.meta.feed.score import FeedScore


@runtime_checkable
class AbstractMetaStore(Protocol):
    """Persistent store for feed quality scores and source configurations."""

    # --- Feed scores ---

    def get_feed_score(self, feed_name: str) -> FeedScore | None: ...

    def upsert_feed_score(self, score: FeedScore) -> None: ...

    def list_feed_scores(self) -> list[FeedScore]: ...

    # --- Source configs ---

    def get_source_config(self, source_id: str) -> dict | None: ...

    def upsert_source_config(self, source_id: str, config: dict) -> None: ...

    # --- Lifecycle ---

    def close(self) -> None: ...
