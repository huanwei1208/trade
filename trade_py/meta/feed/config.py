"""FeedConfig: declarative feed/source configuration model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FeedConfig:
    """Describes a single data feed (RSS, API, etc.)."""
    name: str
    url: str                        # resolved URL (base_url + path)
    source_type: str = "rss"        # rss | cls | gdelt | akshare | ...
    status: str = "active"          # active | trial | disabled
    enabled_default: bool = True
    category: str = ""              # newswire | macro | market | portal
    region: str = ""                # CN | HK | US | global
    languages: list[str] = field(default_factory=list)

    # Static quality hints (used when computed scores are unavailable)
    officialness: float = 0.0
    authority: float = 0.0
    quality: float = 0.0
    coverage: float = 0.0
    value: float = 0.0

    notes: str = ""
    meta: dict = field(default_factory=dict)
