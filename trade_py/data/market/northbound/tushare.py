"""Northbound fund flow (沪深港通) fetcher via Tushare Pro.

Uses pro.moneyflow_hsgt() to fetch daily northbound net flows.
Provides the `northbound_5d_net` feature consumed by feature_builder Group D.

Storage: data/northbound/daily.parquet
Columns: date, hgt_net, sgt_net, total_net, net_5d (rolling 5-day total, billion CNY)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _fetch_raw(data_root: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    from trade_py.data.market.tushare_client import get_pro_api
    pro = get_pro_api(data_root)
    end = (end_date or date.today().strftime("%Y%m%d")).replace("-", "")
    start = (start_date or (date.today() - timedelta(days=365)).strftime("%Y%m%d")).replace("-", "")
    df = pro.call("moneyflow_hsgt", start_date=start, end_date=end)
    return df if df is not None else pd.DataFrame()


class NorthboundFetcher:
    """Fetch and persist daily northbound (沪深港通) net flows."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self.data_root = str(data_root)
        self._dir = Path(data_root) / "northbound"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "daily.parquet"

    def load(self) -> pd.DataFrame:
        if not self._path.exists():
            return pd.DataFrame()
        return pd.read_parquet(self._path)

    def fetch_and_save(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = _fetch_raw(self.data_root, start_date=start_date, end_date=end_date)
        if raw is None or raw.empty:
            logger.warning("NorthboundFetcher: no data returned")
            return self.load()

        # Tushare moneyflow_hsgt columns (亿元):
        # trade_date, ggt_ss(港股通沪), ggt_sz(港股通深), hgt(沪股通), sgt(深股通),
        # north_money(北向资金合计), south_money(南向资金合计)
        def _f(col: str) -> pd.Series:
            return pd.to_numeric(raw.get(col, pd.Series([0.0] * len(raw))), errors="coerce").fillna(0.0)

        df = pd.DataFrame({
            "date":      pd.to_datetime(raw["trade_date"].astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d"),
            "hgt_net":   _f("hgt"),          # 沪股通净流入 (亿元)
            "sgt_net":   _f("sgt"),           # 深股通净流入 (亿元)
            "total_net": _f("north_money"),   # 北向资金合计 (亿元)
        })
        df = df.sort_values("date").reset_index(drop=True)
        # Rolling 5-day sum (亿元)
        df["net_5d"] = df["total_net"].rolling(5, min_periods=1).sum()

        existing = self.load()
        if not existing.empty:
            combined = pd.concat([existing, df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date"], keep="last")
            combined = combined.sort_values("date").reset_index(drop=True)
            combined["net_5d"] = combined["total_net"].rolling(5, min_periods=1).sum()
        else:
            combined = df

        combined.to_parquet(self._path, index=False)
        logger.info("NorthboundFetcher: saved %d rows", len(combined))
        return combined

    def get_5d_net(self, as_of: date | None = None) -> float:
        """Return 5-day rolling northbound net flow (亿元) as of date."""
        df = self.load()
        if df.empty or "net_5d" not in df.columns:
            return 0.0
        df["date"] = pd.to_datetime(df["date"])
        if as_of is not None:
            df = df[df["date"] <= pd.Timestamp(as_of)]
        if df.empty:
            return 0.0
        return float(df.sort_values("date").iloc[-1]["net_5d"])
