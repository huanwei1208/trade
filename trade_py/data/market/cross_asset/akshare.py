from __future__ import annotations

"""Cross-asset data fetcher: gold (SGE), BTC (OKX), USD/CNH (EastMoney).

Storage:
    data/market/cross_asset/gold.parquet — Au99.99 CNY/gram, SGE
    data/market/cross_asset/btc.parquet — BTC/USDT UTC daily OHLC, OKX
    data/market/cross_asset/fx_cnh.parquet — USD/CNH daily close, EastMoney

Column schema (all assets): date, open, high, low, close, [volume]
"""

import logging
import time
from pathlib import Path

import pandas as pd

from trade_py.data.market.cross_asset.btc import (
    OkxBtcDailyProvider,
    okx_canonical_candidate,
)

logger = logging.getLogger(__name__)

_DEFAULT_DATA_ROOT = "data"
_OUT_DIR = "market/cross_asset"


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


# ── Gold (SGE Au99.99, CNY/gram) ───────────────────────────────────────────────

def fetch_gold(data_root: str = _DEFAULT_DATA_ROOT) -> pd.DataFrame:
    """Fetch SGE Au99.99 full history and save to gold.parquet."""
    import akshare as ak

    path = _out_path(data_root, "gold")
    existing = _load_existing(path)
    logger.info("Fetching gold (SGE Au99.99)…")

    df_raw = ak.spot_hist_sge(symbol="Au99.99")
    # Columns: date, open, close, low, high — reorder to standard
    df = df_raw.rename(columns={
        "date": "date",
        "open": "open",
        "high": "high",
        "low":  "low",
        "close": "close",
    })[["date", "open", "high", "low", "close"]]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if existing is not None:
        watermark = _watermark_date(existing)
        if watermark:
            df = df[df["date"] > pd.Timestamp(watermark)]
        if df.empty:
            logger.info("Gold data already up to date (%s)", watermark)
            return existing
        df = pd.concat([existing, df], ignore_index=True).drop_duplicates(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)

    df.to_parquet(path, index=False)
    logger.info("Gold saved: %d rows → %s", len(df), path)
    return df


# ── USD/CNH (EastMoney forex daily) ───────────────────────────────────────────

def fetch_fx_cnh(data_root: str = _DEFAULT_DATA_ROOT) -> pd.DataFrame:
    """Fetch USD/CNH full daily history and save to fx_cnh.parquet."""
    import akshare as ak

    path = _out_path(data_root, "fx_cnh")
    existing = _load_existing(path)
    logger.info("Fetching USD/CNH (EastMoney)…")

    df_raw = ak.forex_hist_em(symbol="USDCNH")
    # Chinese columns: 日期, 代码, 名称, 今开, 最新价, 最高, 最低, 振幅
    df = df_raw.rename(columns={
        "日期": "date",
        "今开": "open",
        "最高": "high",
        "最低": "low",
        "最新价": "close",
    })[["date", "open", "high", "low", "close"]]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if existing is not None:
        watermark = _watermark_date(existing)
        if watermark:
            df = df[df["date"] > pd.Timestamp(watermark)]
        if df.empty:
            logger.info("USD/CNH data already up to date (%s)", watermark)
            return existing
        df = pd.concat([existing, df], ignore_index=True).drop_duplicates(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)

    df.to_parquet(path, index=False)
    logger.info("USD/CNH saved: %d rows → %s", len(df), path)
    return df


# ── BTC/USDT (OKX primary only) ───────────────────────────────────────────────

def _fetch_btc_okx(days: int) -> pd.DataFrame:
    """Fetch completed BTC/USDT ``1Dutc`` OHLC through the primary adapter."""

    capture = OkxBtcDailyProvider().capture(
        days=days,
        fetched_at=None,
        run_id="legacy-cross-asset-fetch",
    )
    candidate = okx_canonical_candidate(capture)
    if candidate.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    out = candidate.assign(date=candidate["bar_open_at"].dt.tz_localize(None))
    return out[["date", "open", "high", "low", "close"]].reset_index(drop=True)


def fetch_btc(
    data_root: str = _DEFAULT_DATA_ROOT,
    days: int = 365,
) -> pd.DataFrame:
    """Compatibility entry for the assured BTC synchronization workflow.

    CoinGecko is intentionally not a fallback: it is a BTC/USD close-only
    shadow source and is acquired separately by the assurance workflow.
    """
    from trade_py.data.market.cross_asset.service import BtcMarketDataService

    path = Path(data_root) / _OUT_DIR / "btc.parquet"
    try:
        outcome = BtcMarketDataService(data_root, days=days).sync()
    except Exception as e:
        logger.error("Assured BTC synchronization failed: %s", e)
        raise RuntimeError(f"assured BTC synchronization failed: {e}") from e
    if not outcome.get("published"):
        raise RuntimeError(
            "assured BTC synchronization did not publish: "
            f"readiness={outcome.get('data_readiness')} run_id={outcome.get('run_id')}"
        )
    logger.info(
        "Assured BTC synchronization complete: readiness=%s published=%s run_id=%s",
        outcome.get("data_readiness"),
        outcome.get("published"),
        outcome.get("run_id"),
    )
    existing = _load_existing(path)
    return existing if existing is not None else pd.DataFrame()


# ── Master fetch ───────────────────────────────────────────────────────────────

def fetch_all(data_root: str = _DEFAULT_DATA_ROOT, delay_s: float = 1.0) -> dict[str, pd.DataFrame]:
    """Fetch all cross-asset datasets in sequence."""
    results: dict[str, pd.DataFrame] = {}

    failures: dict[str, str] = {}
    for name, fn in [("gold", fetch_gold), ("fx_cnh", fetch_fx_cnh), ("btc", fetch_btc)]:
        try:
            results[name] = fn(data_root)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", name, e)
            failures[name] = f"{type(e).__name__}: {e}"
        time.sleep(delay_s)

    if failures:
        raise RuntimeError(f"cross-asset synchronization incomplete: {failures}")
    return results
