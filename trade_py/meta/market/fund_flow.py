"""Fund flow market model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class FundFlowRecord:
    symbol: str
    trading_date: date
    main_net_inflow: float = 0.0
    main_net_ratio: float = 0.0
    large_order_net_inflow: float = 0.0
    large_order_net_ratio: float = 0.0
