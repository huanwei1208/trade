"""In-memory MetaStore (tests / dry-run)."""

from __future__ import annotations

from trade_py.meta.feed.score import FeedScore


class MemoryMetaStore:
    """Non-persistent MetaStore for tests."""

    def __init__(self) -> None:
        self._scores: dict[str, FeedScore] = {}
        self._configs: dict[str, dict] = {}

    def get_feed_score(self, feed_name: str) -> FeedScore | None:
        return self._scores.get(feed_name)

    def upsert_feed_score(self, score: FeedScore) -> None:
        self._scores[score.feed_name] = score

    def list_feed_scores(self) -> list[FeedScore]:
        return list(self._scores.values())

    def get_source_config(self, source_id: str) -> dict | None:
        return self._configs.get(source_id)

    def upsert_source_config(self, source_id: str, config: dict) -> None:
        self._configs[source_id] = dict(config)

    def close(self) -> None:
        pass
