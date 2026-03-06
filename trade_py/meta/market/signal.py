"""Signal models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class WindowScore:
    symbol: str
    score_date: date
    score: int
    model_version: str = "v1"


@dataclass(frozen=True)
class SignalRecord:
    symbol: str
    signal_type: str
    signal_value: float
    generated_at: datetime
    source: str = "trade_py"
