"""Tushare K-line provider for the ProviderChain.

Fetches daily OHLCV via tushare pro.daily() with back-adjustment.
Output schema matches the project standard (11 columns).
"""
from __future__ import annotations

import logging

import pandas as pd

from trade_py.data.market.kline.providers import _COLUMN_ORDER, _finalize_frame, ensure_symbol

logger = logging.getLogger(__name__)


def _to_ts_code(symbol: str) -> str:
    """'600000.SH' → '600000.SH'  (Tushare uses the same dotted format)."""
    return ensure_symbol(symbol)


class TushareKlineProvider:
    name = "tushare"

    def __init__(self, data_root: str = "data") -> None:
        self._data_root = data_root

    def fetch(self, symbol: str, start: str, end: str, adjust: str = "hfq") -> pd.DataFrame:
        from trade_py.data.market.tushare_client import get_pro_api

        pro = get_pro_api(self._data_root)
        ts_code = _to_ts_code(symbol)
        start_d = start.replace("-", "")
        end_d = end.replace("-", "")

        # Tushare adj values: "hfq" = backward-adjusted, "qfq" = forward, None = unadjusted
        adj_val = {"hfq": "hfq", "qfq": "qfq", "none": None}.get(adjust, "hfq")

        raw = pro.call(
            "daily",
            ts_code=ts_code,
            start_date=start_d,
            end_date=end_d,
            adj=adj_val,
        )
        if raw is None or raw.empty:
            return pd.DataFrame(columns=_COLUMN_ORDER)

        # Tushare columns: ts_code, trade_date, open, high, low, close, pre_close,
        #                   change, pct_chg, vol, amount
        col_map = {
            "trade_date": "date",
            "vol": "volume",        # 手 (lots)
            "amount": "amount",     # 千元 → 元 (×1000 below)
            "pct_chg": "turnover_rate",  # placeholder; real turnover fetched separately
            "pre_close": "prev_close",
        }
        df = raw.rename(columns=col_map)

        # amount: Tushare returns 千元, convert to 元
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0) * 1000.0

        # If turnover_rate not present, set to 0
        if "turnover_rate" not in df.columns:
            df["turnover_rate"] = 0.0

        keep = ["date", "open", "high", "low", "close", "volume", "amount",
                "turnover_rate", "prev_close"]
        keep = [c for c in keep if c in df.columns]
        return _finalize_frame(symbol, df[keep].copy())
