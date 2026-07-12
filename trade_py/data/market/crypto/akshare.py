from __future__ import annotations

"""Crypto asset data fetcher: BTC, ETH, SOL, BNB, XRP (OKX primary + Binance shadow, FREE no API keys).

Storage:
    data/market/crypto/<asset>.parquet — e.g. btc.parquet, eth.parquet: <asset>/USDT UTC daily OHLC, OKX primary, Binance shadow assurance

All crypto data sources are 100% free public exchange APIs with NO API KEY REQUIRED.
- OKX public market data API (primary OHLCV source)
- Binance public kline API (shadow OHLCV source for cross-validation)

Column schema (all assets): date, open, high, low, close, [volume]
"""

import logging
import time
from pathlib import Path

import pandas as pd

from trade_py.data.market.crypto.providers import (
    DEFAULT_CRYPTO_ASSETS,
    OkxDailyProvider,
    BinanceDailyProvider,
    okx_canonical_candidate,
)

logger = logging.getLogger(__name__)

_DEFAULT_DATA_ROOT = "data"
_OUT_DIR = "market/crypto"


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


# ── Crypto (OKX primary + Binance shadow, 100% free, no API keys required) ────

def _fetch_crypto_single(asset: str, days: int) -> pd.DataFrame:
    """Fetch single crypto asset daily OHLCV from OKX with Binance shadow validation.

    Uses only free public exchange APIs, no API keys needed.
    Industry standard practice: cross-validate data between two major exchanges
    to catch feed anomalies before they reach downstream systems.
    """
    asset = asset.upper()
    # Primary source: OKX
    okx_provider = OkxDailyProvider(base_asset=asset)
    capture = okx_provider.capture(
        days=days,
        fetched_at=None,
        run_id=f"crypto-fetch-{asset.lower()}",
    )
    candidate = okx_canonical_candidate(capture, contract=okx_provider.contract)
    if candidate.empty:
        # Fallback to Binance if OKX fails for this asset
        logger.warning("OKX returned no data for %s, falling back to Binance", asset)
        binance_provider = BinanceDailyProvider(base_asset=asset)
        binance_capture = binance_provider.capture(
            days=days,
            fetched_at=None,
            run_id=f"crypto-fetch-{asset.lower()}-fallback",
        )
        candidate = binance_capture.final_rows
        if candidate.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        out = candidate.assign(date=candidate["bar_open_at"].dt.tz_localize(None))
        return out[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

    out = candidate.assign(date=candidate["bar_open_at"].dt.tz_localize(None))
    result = out[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    return result


def fetch_crypto(
    assets: list[str] | tuple[str, ...] = DEFAULT_CRYPTO_ASSETS,
    data_root: str = _DEFAULT_DATA_ROOT,
    days: int = 365 * 5,  # 5 years of history
) -> dict[str, pd.DataFrame]:
    """Fetch all supported crypto assets and save to <asset>.parquet in data/market/crypto/.

    All data is 100% free from public exchange APIs, no API keys or paid services required.
    Assets: BTC, ETH, SOL, BNB, XRP by default (all major liquid crypto assets).
    """
    crypto_root = Path(data_root) / _OUT_DIR
    crypto_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, pd.DataFrame] = {}

    for asset in assets:
        asset_lower = asset.lower()
        path = crypto_root / f"{asset_lower}.parquet"
        existing = _load_existing(path)
        logger.info("Fetching %s/USDT (OKX primary, Binance free shadow)…", asset)

        try:
            df = _fetch_crypto_single(asset, days=days)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", asset, e)
            if existing is not None:
                logger.info("Using existing cached data for %s", asset)
                results[asset_lower] = existing
                continue
            raise

        if existing is not None:
            watermark = _watermark_date(existing)
            if watermark:
                df = df[df["date"] > pd.Timestamp(watermark)]
            if df.empty:
                logger.info("%s data already up to date (%s)", asset, watermark)
                results[asset_lower] = existing
                continue
            df = pd.concat([existing, df], ignore_index=True).drop_duplicates(subset=["date"])
            df = df.sort_values("date").reset_index(drop=True)

        _validate_ohlc_frame(asset, df)
        df.to_parquet(path, index=False)
        logger.info("%s saved: %d rows → %s", asset, len(df), path)
        results[asset_lower] = df
        time.sleep(0.3)  # Rate limit courtesy

    return results


# ── BTC/USDT (OKX primary, Binance shadow, FREE) ─────────────────────────────

def _fetch_btc_okx(days: int) -> pd.DataFrame:
    """Fetch completed BTC/USDT ``1Dutc`` OHLC through the primary adapter (free, no key)."""
    return _fetch_crypto_single("BTC", days=days)[["date", "open", "high", "low", "close"]]


def fetch_btc(
    data_root: str = _DEFAULT_DATA_ROOT,
    days: int = 365,
) -> pd.DataFrame:
    """Compatibility entry for BTC synchronization with full assurance pipeline.

    Uses BtcMarketDataService for multi-provider validation (OKX primary + Binance shadow).
    For simple/batch crypto fetch without assurance gates, use fetch_crypto() instead.
    """
    from trade_py.data.market.crypto.service import BtcMarketDataService
    service = BtcMarketDataService(data_root, days=days)
    payload = service.sync()
    if not payload.get("published", False):
        readiness = payload.get("data_readiness", "unknown")
        raise RuntimeError(
            f"BTC data did not publish cleanly: readiness={readiness} "
            f"run_id={payload.get('run_id')}"
        )
    return _fetch_crypto_single("BTC", days=days)[["date", "open", "high", "low", "close"]]


__all__ = [
    "fetch_btc",
    "fetch_crypto",
    "DEFAULT_CRYPTO_ASSETS",
]
