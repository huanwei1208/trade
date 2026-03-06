"""Kline/OHLCV market model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class KlineBar:
    symbol: str
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0
    turnover_rate: float = 0.0
    prev_close: float = 0.0
    vwap: float = 0.0
