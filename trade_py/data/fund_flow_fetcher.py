"""A-share fund flow fetcher using akshare.

Fetches daily large-order / institutional fund flow data via akshare and
stores it in Parquet for offline feature computation.

The key derived metric is large_order_net_ratio:
    (超大单净流入 + 大单净流入) / 总成交额

A positive ratio means institutional/large-account money is net-buying;
a negative ratio signals net-selling (potential distribution pattern).

Storage:
    data/fund_flow/{symbol}.parquet

Usage:
    fetcher = FundFlowFetcher("data")
    fetcher.fetch_and_save("600111.SH", days=60)
    df = fetcher.load("600111.SH")
    latest = fetcher.latest_ratio("600111.SH")
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _seccode_to_market(symbol: str) -> tuple[str, str]:
    """Extract (seccode, akshare_market) from 'NNNNNN.SH' or 'NNNNNN.SZ'."""
    parts = symbol.split(".")
    seccode = parts[0]
    suffix = parts[1].upper() if len(parts) > 1 else "SH"
    # akshare market: "sh" for Shanghai, "sz" for Shenzhen, "bj" for Beijing
    if suffix == "SH":
        market = "sh"
    elif suffix == "BJ":
        market = "bj"
    else:
        market = "sz"
    return seccode, market


def _fetch_raw(symbol: str, days: int = 60) -> pd.DataFrame:
    """Fetch raw fund flow time-series from akshare.

    Uses ak.stock_individual_fund_flow(stock=code, market="sh"|"sz").
    Returns a DataFrame with standardised column names, or empty on error.

    The API returns data in descending date order; we return ascending.
    Units: values are in 万元 (10,000 CNY) from the akshare API.
    """
    import akshare as ak

    seccode, market = _seccode_to_market(symbol)
    try:
        raw = ak.stock_individual_fund_flow(stock=seccode, market=market)
    except Exception as exc:
        logger.warning("akshare fund flow fetch failed for %s: %s", symbol, exc)
        return pd.DataFrame()

    if raw is None or raw.empty:
        return pd.DataFrame()

    # Rename Chinese columns to internal names (flexible: try multiple patterns)
    col_map: dict[str, str] = {}
    for col in raw.columns:
        col_str = str(col)
        if "日期" in col_str:
            col_map[col] = "_date"
        elif "超大单" in col_str and "净额" in col_str:
            col_map[col] = "_xl_net"
        elif "大单" in col_str and "净额" in col_str and "超大" not in col_str:
            col_map[col] = "_l_net"
        elif "中单" in col_str and "净额" in col_str:
            col_map[col] = "_m_net"
        elif "小单" in col_str and "净额" in col_str:
            col_map[col] = "_s_net"
        elif "主力" in col_str and "净额" in col_str:
            col_map[col] = "_main_net"

    renamed = raw.rename(columns=col_map)

    # Ensure we have at least a date column
    if "_date" not in renamed.columns:
        logger.warning("No date column found in fund flow response for %s", symbol)
        return pd.DataFrame()

    # Sort ascending by date and limit to the requested number of days
    renamed = renamed.sort_values("_date").reset_index(drop=True)
    if days and len(renamed) > days:
        renamed = renamed.tail(days).reset_index(drop=True)
    return renamed


def _parse_rows(symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
    """Parse akshare fund flow DataFrame into the project schema.

    akshare stock_individual_fund_flow returns values in 万元.
    We convert to 元 (× 1e4) for consistency with the original schema.
    """
    if raw is None or raw.empty:
        return pd.DataFrame()

    def _col(name: str) -> pd.Series:
        return pd.to_numeric(raw.get(name, pd.Series([0.0] * len(raw))),
                             errors="coerce").fillna(0.0)

    date_series = raw["_date"].astype(str).str[:10]

    # 万元 → 元
    xl_net = _col("_xl_net") * 1e4
    l_net  = _col("_l_net")  * 1e4
    m_net  = _col("_m_net")  * 1e4
    s_net  = _col("_s_net")  * 1e4

    # If no per-tier columns, fall back to main order net flow (主力净额)
    if xl_net.abs().sum() == 0 and "_main_net" in raw.columns:
        xl_net = _col("_main_net") * 1e4

    # Approximate total turnover from sum of absolute values of all tiers
    # total_turnover = |xl| + |l| + |m| + |s| (in-flow + out-flow ≈ 2 × |net|)
    # This is only an approximation; the API doesn't directly expose total turnover.
    # We use the same denominator logic as before for ratio calculation.
    total_inflow  = xl_net.clip(lower=0) + l_net.clip(lower=0) + m_net.clip(lower=0) + s_net.clip(lower=0)
    total_outflow = (-xl_net).clip(lower=0) + (-l_net).clip(lower=0) + (-m_net).clip(lower=0) + (-s_net).clip(lower=0)
    total_turnover = total_inflow + total_outflow

    large_net = xl_net + l_net
    ratio = (large_net / total_turnover.where(total_turnover > 1e-6, other=float("nan"))
             ).fillna(0.0)
    sbd = ((large_net - s_net) / total_turnover.where(total_turnover > 1e-6, other=float("nan"))
           ).fillna(0.0)

    # --- Retail heat: small-order dominance ratio, 0–100 rolling percentile ---
    # High score = retail is unusually active (potential sentiment peak)
    small_ratio = (s_net.abs() / total_turnover.where(total_turnover > 1e-6, other=float("nan"))
                   ).fillna(0.0)
    # Rolling 60-day percentile rank × 100 (min_periods=5)
    retail_heat = small_ratio.rolling(60, min_periods=5).rank(pct=True) * 100.0
    retail_heat = retail_heat.fillna(50.0).round(1)

    # --- Distribution zone flag: institutions selling while retail buys ---
    # Flag = 1 when all three conditions hold:
    #   1. large_order_net_ratio < -0.05  (net-sell by smart money)
    #   2. small_net > 0                  (retail still net-buying)
    #   3. sentiment_behavior_divergence < -0.05  (visible divergence)
    dist_flag = (
        (ratio < -0.05) & (s_net > 0) & (sbd < -0.05)
    ).astype(int)

    df = pd.DataFrame({
        "symbol":                        symbol,
        "date":                          date_series.values,
        "xl_net":                        xl_net.values,
        "large_net":                     l_net.values,
        "medium_net":                    m_net.values,
        "small_net":                     s_net.values,
        "total_turnover":                total_turnover.values,
        "large_order_net_ratio":         ratio.round(6).values,
        "sentiment_behavior_divergence": sbd.round(6).values,
        "retail_heat_score":             retail_heat.values,
        "distribution_zone_flag":        dist_flag.values,
    })
    df = df.sort_values("date").reset_index(drop=True)
    return df


class FundFlowFetcher:
    """Fetch and persist daily fund flow data via akshare.

    Stores one Parquet file per symbol under data_root/fund_flow/.
    The key output feature is large_order_net_ratio, consumed by FeatureBuilder
    as part of Group D (market environment).
    """

    def __init__(self, data_root: str | Path = "data") -> None:
        self._root = Path(data_root) / "fund_flow"
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        safe = symbol.replace(".", "_")
        return self._root / f"{safe}.parquet"

    def load(self, symbol: str) -> pd.DataFrame:
        """Load cached fund flow data for a symbol."""
        p = self._path(symbol)
        if not p.exists():
            return pd.DataFrame()
        return pd.read_parquet(p)

    def fetch_and_save(self, symbol: str, days: int = 60) -> pd.DataFrame:
        """Fetch the latest N days of fund flow data and merge with cache.

        Args:
            symbol: Stock code e.g. "600111.SH"
            days:   Number of trading days to fetch (max ~120 from API)

        Returns:
            Combined DataFrame (existing + newly fetched, deduped by date)
        """
        raw = _fetch_raw(symbol, days=days)
        new_df = _parse_rows(symbol, raw)
        if new_df.empty:
            logger.warning("FundFlowFetcher: no data fetched for %s", symbol)
            return self.load(symbol)

        existing = self.load(symbol)
        if not existing.empty:
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(
                subset=["symbol", "date"], keep="last")
            combined = combined.sort_values("date").reset_index(drop=True)
        else:
            combined = new_df

        combined.to_parquet(self._path(symbol), index=False)
        logger.info("FundFlowFetcher: saved %d rows for %s", len(combined), symbol)
        return combined

    def fetch_batch(self, symbols: list[str], days: int = 60) -> None:
        """Fetch fund flow for a list of symbols."""
        for sym in symbols:
            self.fetch_and_save(sym, days=days)

    def latest_ratio(self, symbol: str,
                     as_of: date | None = None) -> float:
        """Return the most recent large_order_net_ratio for a symbol.

        Args:
            symbol: Stock code
            as_of:  Reference date (returns latest row on or before this date)

        Returns:
            Ratio in [-1, +1] range; 0.0 if no data available.
        """
        df = self.load(symbol)
        if df.empty:
            return 0.0
        df["date"] = pd.to_datetime(df["date"])
        if as_of is not None:
            df = df[df["date"] <= pd.Timestamp(as_of)]
        if df.empty:
            return 0.0
        val = df.sort_values("date").iloc[-1]["large_order_net_ratio"]
        return float(val) if val is not None else 0.0

    def divergence_signal(self, symbol: str,
                          as_of: date | None = None) -> float:
        """Return the sentiment_behavior_divergence value.

        Positive: institutions net-buying, retail also buying (aligned).
        Negative: institutions net-selling while retail buys (distribution warning).
        """
        df = self.load(symbol)
        if df.empty:
            return 0.0
        df["date"] = pd.to_datetime(df["date"])
        if as_of is not None:
            df = df[df["date"] <= pd.Timestamp(as_of)]
        if df.empty:
            return 0.0
        val = df.sort_values("date").iloc[-1]["sentiment_behavior_divergence"]
        return float(val) if val is not None else 0.0

    def rolling_ratio(self, symbol: str, window: int = 5,
                      end_date: date | None = None) -> float:
        """Return the rolling mean of large_order_net_ratio over window days."""
        df = self.load(symbol)
        if df.empty:
            return 0.0
        df["date"] = pd.to_datetime(df["date"])
        if end_date is not None:
            df = df[df["date"] <= pd.Timestamp(end_date)]
        if df.empty:
            return 0.0
        tail = df.sort_values("date").tail(window)
        return float(tail["large_order_net_ratio"].mean())

    def retail_heat(self, symbol: str, as_of: date | None = None) -> float:
        """Return the latest retail_heat_score (0–100) for a symbol.

        High score (>80) signals retail overheating — potential sentiment peak.
        Returns 50.0 (neutral) when no data is available.
        """
        df = self.load(symbol)
        if df.empty or "retail_heat_score" not in df.columns:
            return 50.0
        df["date"] = pd.to_datetime(df["date"])
        if as_of is not None:
            df = df[df["date"] <= pd.Timestamp(as_of)]
        if df.empty:
            return 50.0
        val = df.sort_values("date").iloc[-1]["retail_heat_score"]
        return float(val) if val is not None else 50.0

    def is_distribution_zone(self, symbol: str,
                              as_of: date | None = None) -> bool:
        """Return True if the latest bar is flagged as a distribution zone.

        Distribution zone = institutions net-selling while retail is buying.
        """
        df = self.load(symbol)
        if df.empty or "distribution_zone_flag" not in df.columns:
            return False
        df["date"] = pd.to_datetime(df["date"])
        if as_of is not None:
            df = df[df["date"] <= pd.Timestamp(as_of)]
        if df.empty:
            return False
        val = df.sort_values("date").iloc[-1]["distribution_zone_flag"]
        return bool(val)
