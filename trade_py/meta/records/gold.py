"""GoldRecord: daily aggregated sentiment signal per symbol."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class GoldRecord:
    """Daily aggregated sentiment signal for a symbol."""
    date: date
    symbol: str
    article_count: int = 0
    avg_sentiment: float = 0.0
    weighted_sentiment: float = 0.0
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    avg_event_magnitude: float = 0.0
    top_event_types: list = field(default_factory=list)
    top_sectors: list = field(default_factory=list)
    policy_signal_count: int = 0
    sources: list = field(default_factory=list)
