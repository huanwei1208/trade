"""FeedScore: computed quality metrics for a feed, derived from Bronze/Silver data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class FeedScore:
    """Data-driven quality score for a feed. Computed by feed_scorer.py."""
    feed_name: str
    computed_at: datetime

    # Coverage: fraction of days in last 30d with ≥1 article
    coverage_30d: float = 0.0

    # Uniqueness: fraction of articles not duplicated across other feeds
    uniqueness: float = 0.0

    # Signal density: fraction of articles with |sentiment_score| > 0.3
    signal_density: float = 0.0

    # Reliability: fraction of successful fetches in last 30 runs
    reliability: float = 0.0

    # Timeliness: median publish-to-ingest lag in minutes (lower = better)
    timeliness_minutes: float = 0.0

    # Composite score 0-100
    composite: float = 0.0

    notes: str = ""
