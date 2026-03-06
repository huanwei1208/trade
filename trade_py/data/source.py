"""Backward-compatible re-exports — canonical definition is in trade_py.meta.records.raw."""

from trade_py.meta.records.raw import RawRecord
from typing import Literal, Protocol, runtime_checkable
from datetime import datetime


@runtime_checkable
class DataSource(Protocol):
    """Protocol every data source must satisfy."""
    source_id: str
    data_type: Literal["news", "price", "flow", "filing"]

    def fetch(self, since: datetime, until: datetime) -> list[RawRecord]: ...
    def health_check(self) -> dict: ...


__all__ = ["RawRecord", "DataSource"]
