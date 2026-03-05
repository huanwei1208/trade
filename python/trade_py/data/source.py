"""Core data model: RawRecord dataclass and DataSource protocol.

Every data source (RSS, GDELT, CLS, kline, etc.) must return list[RawRecord]
from its fetch() method, enabling a uniform Bronze-write path.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable


@dataclass
class RawRecord:
    """Universal raw record emitted by any DataSource."""
    source_id: str
    data_type: Literal["news", "price", "flow", "filing"]
    published_at: datetime          # timezone-aware (UTC recommended)
    title: str
    text: str
    url: str
    content_hash: str = ""          # filled by __post_init__ if empty
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content_hash:
            raw = f"{self.title}\n{self.text}"
            self.content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]


@runtime_checkable
class DataSource(Protocol):
    """Protocol every data source must satisfy."""
    source_id: str
    data_type: Literal["news", "price", "flow", "filing"]

    def fetch(self, since: datetime, until: datetime) -> list[RawRecord]: ...
    def health_check(self) -> dict: ...
