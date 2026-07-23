"""Commodity market data fetcher — gold (SGE Au99.99, CNY/gram).

Primary source: Shanghai Gold Exchange (SGE) via akshare ``spot_hist_sge``
(symbol="Au99.99") — CNY per gram daily OHLC.

Storage:
    data/market/commodity/gold.parquet — Au99.99 CNY/gram daily OHLC

Column schema: date, open, high, low, close
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd

from trade_py.utils.retry import retry

logger = logging.getLogger(__name__)

_DEFAULT_DATA_ROOT = "data"
_OUT_DIR = "market/commodity"

_FETCH_RETRY_DELAYS_SEC = (1.0, 3.0, 8.0)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _out_path(data_root: str, name: str) -> Path:
    d = Path(data_root) / _OUT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}.parquet"


def _load_existing(path: Path) -> pd.DataFrame | None:
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception:
            return None
    return None


def _watermark_date(df: pd.DataFrame | None) -> str | None:
    """Return ISO date string of the last row, or None."""
    if df is None or df.empty:
        return None
    col = "date" if "date" in df.columns else df.columns[0]
    val = pd.to_datetime(df[col]).max()
    return val.strftime("%Y-%m-%d")


def _validate_ohlc_frame(asset: str, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    required = {"date", "open", "high", "low", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{asset} OHLC data missing columns: {missing}")
    work = df.copy()
    for column in ("open", "high", "low", "close"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    invalid = work[
        work[["open", "high", "low", "close"]].isna().any(axis=1)
        | work[["open", "high", "low", "close"]].le(0).any(axis=1)
        | (work["high"] < work["low"])
        | (work["high"] < work["open"])
        | (work["high"] < work["close"])
        | (work["low"] > work["open"])
        | (work["low"] > work["close"])
    ].copy()
    if invalid.empty:
        return
    invalid["date"] = pd.to_datetime(invalid["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    sample = invalid[["date", "open", "high", "low", "close"]].head(5).to_dict(orient="records")
    start = str(invalid["date"].min())[:10]
    end = str(invalid["date"].max())[:10]
    raise ValueError(
        f"{asset} OHLC data failed validation rows={len(invalid)} "
        f"dates={start}..{end} sample={sample}"
    )


# ── SGE Au99.99 (CNY/gram) ────────────────────────────────────────────────────

@retry(delays=_FETCH_RETRY_DELAYS_SEC, on=(Exception,))
def _fetch_gold_sge() -> pd.DataFrame:
    """Fetch full Au99.99 history from SGE via akshare.

    Returns columns: date, open, high, low, close (sorted ascending by date).
    """
    import akshare as ak

    logger.info("Fetching gold (SGE Au99.99)…")
    df_raw = ak.spot_hist_sge(symbol="Au99.99")
    # akshare returns columns: date, open, close, low, high — reorder to canonical
    df = df_raw.rename(columns={
        "date": "date",
        "open": "open",
        "high": "high",
        "low":  "low",
        "close": "close",
    })[["date", "open", "high", "low", "close"]]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    logger.info("Gold (SGE): fetched %d rows", len(df))
    return df


# ── Public entrypoint ─────────────────────────────────────────────────────────

def fetch_gold_ohlc(data_root: str = _DEFAULT_DATA_ROOT) -> pd.DataFrame:
    """Fetch SGE Au99.99 daily OHLC and save to ``data/market/commodity/gold.parquet``.

    Incremental: existing parquet is loaded and only new dates (past the stored
    watermark) are appended.
    """
    path = _out_path(data_root, "gold")
    existing = _load_existing(path)

    df = _fetch_gold_sge()

    if existing is not None:
        watermark = _watermark_date(existing)
        if watermark:
            df = df[df["date"] > pd.Timestamp(watermark)]
        if df.empty:
            logger.info("Gold data already up to date (%s)", watermark)
            return existing
        df = pd.concat([existing, df], ignore_index=True).drop_duplicates(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)

    _validate_ohlc_frame("gold", df)
    df.to_parquet(path, index=False)
    logger.info("Gold saved: %d rows → %s", len(df), path)
    return df
