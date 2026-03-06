"""SilverRecord: Bronze + LLM enrichment fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class SilverRecord:
    """LLM-enriched article record (Bronze + sentiment analysis)."""
    content_hash: str
    source: str
    published_at: str               # ISO-8601 string
    title: str
    text: str
    url: str
    date: date

    # Sentiment
    sentiment_score: float = 0.0    # -1.0 to 1.0
    sentiment_label: str = "neutral"
    confidence: float = 0.5
    summary: str = ""

    # Event
    event_type: str = "other"
    event_magnitude: float = 0.0
    affected_sectors: list = field(default_factory=list)
    key_entities: list = field(default_factory=list)

    # Signal enrichment
    policy_signal: bool = False
    market_impact_scope: str = "individual"   # individual|sector|market
    time_sensitivity: str = "short_term"      # immediate|short_term|medium_long
    event_chain: str = ""

    # LLM metadata
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
