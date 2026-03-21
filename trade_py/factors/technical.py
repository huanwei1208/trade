"""Technical indicator computation: RSI, MACD, KDJ, MA gaps, volatility."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from trade_py.factors.definitions import TECHNICAL_DEFAULTS

logger = logging.getLogger(__name__)


def _load_kline_history(data_root: str, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        import duckdb
        from trade_py.utils.data_inspector import _resolve_kline_glob

        kline_glob = _resolve_kline_glob(data_root)
        con = duckdb.connect()
        df = con.execute(
            f"""
            SELECT symbol, date, open, high, low, close, volume
            FROM read_parquet('{kline_glob}', union_by_name=true)
            WHERE date >= '{start_date}' AND date <= '{end_date}'
            ORDER BY symbol, date
            """
        ).df()
        con.close()
        return df
    except Exception as exc:
        logger.debug("failed to load kline history: %s", exc)
        return pd.DataFrame()


def compute_technical_factors(kline_df: pd.DataFrame) -> pd.DataFrame:
    """Compute RSI-14, MACD, KDJ, MA gaps, volatility from OHLCV data.

    Args:
        kline_df: DataFrame with columns [symbol, date, open, high, low, close, volume]

    Returns:
        DataFrame with [date, symbol, tech_*] columns.
    """
    if kline_df.empty:
        return pd.DataFrame(columns=["date", "symbol", *TECHNICAL_DEFAULTS.keys()])
    work = kline_df.copy()
    work["date"] = work["date"].astype(str).str.slice(0, 10)
    for col in ("open", "high", "low", "close", "volume"):
        work[col] = pd.to_numeric(work.get(col), errors="coerce")
    work = work.dropna(subset=["symbol", "date", "close"]).sort_values(["symbol", "date"]).reset_index(drop=True)
    if work.empty:
        return pd.DataFrame(columns=["date", "symbol", *TECHNICAL_DEFAULTS.keys()])

    def _per_symbol(group: pd.DataFrame) -> pd.DataFrame:
        g = group.sort_values("date").copy()
        close = g["close"]
        high = g["high"].fillna(close)
        low = g["low"].fillna(close)
        volume = g["volume"].fillna(0.0)

        ma5 = close.rolling(5, min_periods=5).mean()
        ma20 = close.rolling(20, min_periods=20).mean()
        returns = close.pct_change()
        g["tech_ma_gap_5_20"] = (ma5 / ma20.replace(0, np.nan) - 1.0).replace([np.inf, -np.inf], np.nan)
        g["tech_price_vs_ma20"] = (close / ma20.replace(0, np.nan) - 1.0).replace([np.inf, -np.inf], np.nan)
        g["tech_volatility_20d"] = returns.rolling(20, min_periods=20).std().fillna(0.0)

        vol5 = volume.rolling(5, min_periods=5).mean()
        vol20 = volume.rolling(20, min_periods=20).mean()
        g["tech_volume_ratio_5_20"] = (vol5 / vol20.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta.clip(upper=0.0))
        avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        g["tech_rsi_14"] = (100.0 - 100.0 / (1.0 + rs)).replace([np.inf, -np.inf], np.nan)

        ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
        ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False, min_periods=9).mean()
        hist = dif - dea
        g["tech_macd_hist"] = hist.fillna(0.0)
        g["tech_macd_cross"] = np.where(
            (dif > dea) & (dif.shift(1) <= dea.shift(1)), 1.0,
            np.where((dif < dea) & (dif.shift(1) >= dea.shift(1)), -1.0, 0.0),
        )

        low9 = low.rolling(9, min_periods=9).min()
        high9 = high.rolling(9, min_periods=9).max()
        rsv = ((close - low9) / (high9 - low9).replace(0, np.nan) * 100.0).clip(0.0, 100.0)
        k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
        d = k.ewm(alpha=1 / 3, adjust=False).mean()
        j = 3.0 * k - 2.0 * d
        g["tech_kdj_k"] = k
        g["tech_kdj_d"] = d
        g["tech_kdj_j"] = j
        g["tech_kdj_cross"] = np.where(
            (k > d) & (k.shift(1) <= d.shift(1)), 1.0,
            np.where((k < d) & (k.shift(1) >= d.shift(1)), -1.0, 0.0),
        )
        return g[["date", "symbol", *TECHNICAL_DEFAULTS.keys()]]

    factors = work.groupby("symbol", group_keys=False).apply(_per_symbol)
    for col, default in TECHNICAL_DEFAULTS.items():
        factors[col] = pd.to_numeric(factors.get(col), errors="coerce").fillna(default)
    return factors.reset_index(drop=True)


def merge_technical_factors(data_root: str, df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """Load kline history and merge technical factors into df by (date_col, symbol)."""
    if df.empty or date_col not in df.columns:
        return df
    start = pd.to_datetime(df[date_col], errors="coerce").min()
    end = pd.to_datetime(df[date_col], errors="coerce").max()
    if pd.isna(start) or pd.isna(end):
        return df
    warm_start = (start - pd.Timedelta(days=120)).date().isoformat()
    end_iso = end.date().isoformat()
    tech_df = compute_technical_factors(_load_kline_history(data_root, warm_start, end_iso))
    if tech_df.empty:
        for col, default in TECHNICAL_DEFAULTS.items():
            df[col] = default
        return df
    merged = df.merge(
        tech_df,
        left_on=[date_col, "symbol"],
        right_on=["date", "symbol"],
        how="left",
        suffixes=("", "_tech"),
    )
    if date_col != "date":
        merged = merged.drop(columns=["date"], errors="ignore")
    for col, default in TECHNICAL_DEFAULTS.items():
        merged[col] = pd.to_numeric(merged.get(col), errors="coerce").fillna(default)
    return merged
