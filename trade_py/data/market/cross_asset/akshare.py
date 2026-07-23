from __future__ import annotations

"""DEPRECATED — cross_asset is being split into dedicated submodules.

This module is kept as a thin backwards-compatibility shim.
- FX (USD/CNH) has moved to ``trade_py.data.market.fx.akshare.fetch_usdcnh_ohlc``
- Commodity gold has moved to ``trade_py.data.market.commodity.akshare.fetch_gold_ohlc``
- Crypto has moved to ``trade_py.data.market.crypto.akshare``

Storage locations after migration:
    data/market/fx/usdcnh.parquet        — USD/CNH daily OHLC
    data/market/commodity/gold.parquet   — Au99.99 CNY/gram, SGE
    data/market/crypto/<asset>.parquet   — BTC/ETH/SOL/BNB/XRP OHLC

Column schema (all assets): date, open, high, low, close, [volume]
"""

import logging
import time
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from trade_py.data.market.crypto.providers import (
        BinanceDailyProvider as _BinanceDailyProvider,
        OkxDailyProvider as _OkxDailyProvider,
    )

logger = logging.getLogger(__name__)

_DEFAULT_DATA_ROOT = "data"
_OUT_DIR = "market/cross_asset"


# ── Helpers (kept for back-compat) ────────────────────────────────────────────

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


# ── Deprecated FX / gold shims ────────────────────────────────────────────────

def fetch_gold(data_root: str = _DEFAULT_DATA_ROOT) -> pd.DataFrame:
    """Deprecated: use ``trade_py.data.market.commodity.fetch_gold_ohlc`` instead."""
    warnings.warn(
        "trade_py.data.market.cross_asset.akshare.fetch_gold is deprecated; "
        "use trade_py.data.market.commodity.fetch_gold_ohlc (writes to "
        "data/market/commodity/gold.parquet) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from trade_py.data.market.commodity.akshare import fetch_gold_ohlc
    return fetch_gold_ohlc(data_root)


def fetch_fx_cnh(data_root: str = _DEFAULT_DATA_ROOT) -> pd.DataFrame:
    """Deprecated: use ``trade_py.data.market.fx.fetch_usdcnh_ohlc`` instead."""
    warnings.warn(
        "trade_py.data.market.cross_asset.akshare.fetch_fx_cnh is deprecated; "
        "use trade_py.data.market.fx.fetch_usdcnh_ohlc (writes to "
        "data/market/fx/usdcnh.parquet) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from trade_py.data.market.fx.akshare import fetch_usdcnh_ohlc
    return fetch_usdcnh_ohlc(data_root)


def fetch_fx_cnh_ohlc(data_root: str = _DEFAULT_DATA_ROOT) -> pd.DataFrame:
    """Deprecated alias for ``trade_py.data.market.fx.fetch_usdcnh_ohlc``."""
    warnings.warn(
        "trade_py.data.market.cross_asset.akshare.fetch_fx_cnh_ohlc is deprecated; "
        "use trade_py.data.market.fx.fetch_usdcnh_ohlc instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from trade_py.data.market.fx.akshare import fetch_usdcnh_ohlc
    return fetch_usdcnh_ohlc(data_root)


def fetch_gold_ohlc(data_root: str = _DEFAULT_DATA_ROOT) -> pd.DataFrame:
    """Deprecated alias for ``trade_py.data.market.commodity.fetch_gold_ohlc``."""
    warnings.warn(
        "trade_py.data.market.cross_asset.akshare.fetch_gold_ohlc is deprecated; "
        "use trade_py.data.market.commodity.fetch_gold_ohlc instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from trade_py.data.market.commodity.akshare import fetch_gold_ohlc as _gold
    return _gold(data_root)


# ── Crypto (OKX primary + Binance shadow) — deprecated shim ───────────────────
# Crypto code now lives in trade_py.data.market.crypto.akshare and writes to
# data/market/crypto/. These shims re-export from the new module and emit a
# DeprecationWarning so existing callers keep working during the migration.

def _fetch_crypto_single(asset: str, days: int) -> pd.DataFrame:
    """Deprecated: use ``trade_py.data.market.crypto.akshare._fetch_crypto_single`` instead."""
    warnings.warn(
        "trade_py.data.market.cross_asset.akshare._fetch_crypto_single is deprecated; "
        "use trade_py.data.market.crypto.akshare instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from trade_py.data.market.crypto.akshare import _fetch_crypto_single as _crypto_fetch_single
    return _crypto_fetch_single(asset, days)


def fetch_crypto(
    assets: list[str] | tuple[str, ...] = ("BTC", "ETH", "SOL", "BNB", "XRP"),
    data_root: str = _DEFAULT_DATA_ROOT,
    days: int = 365 * 5,
) -> dict[str, pd.DataFrame]:
    """Deprecated: use ``trade_py.data.market.crypto.fetch_crypto`` instead.

    Data now writes to data/market/crypto/<asset>.parquet.
    """
    warnings.warn(
        "trade_py.data.market.cross_asset.akshare.fetch_crypto is deprecated; "
        "use trade_py.data.market.crypto.fetch_crypto (writes to "
        "data/market/crypto/<asset>.parquet) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from trade_py.data.market.crypto.akshare import (
        DEFAULT_CRYPTO_ASSETS as _DEFAULT_CRYPTO_ASSETS,
        fetch_crypto as _crypto_fetch_crypto,
    )
    if assets == ("BTC", "ETH", "SOL", "BNB", "XRP"):
        assets = _DEFAULT_CRYPTO_ASSETS
    return _crypto_fetch_crypto(assets=assets, data_root=data_root, days=days)


# ── BTC/USDT (OKX primary, Binance shadow) — deprecated shim ─────────────────

def _fetch_btc_okx(days: int) -> pd.DataFrame:
    """Deprecated: use ``trade_py.data.market.crypto.akshare._fetch_btc_okx`` instead."""
    warnings.warn(
        "trade_py.data.market.cross_asset.akshare._fetch_btc_okx is deprecated; "
        "use trade_py.data.market.crypto.akshare instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from trade_py.data.market.crypto.akshare import _fetch_btc_okx as _crypto_fetch_btc_okx
    return _crypto_fetch_btc_okx(days)


def fetch_btc(
    data_root: str = _DEFAULT_DATA_ROOT,
    days: int = 365,
) -> pd.DataFrame:
    """Deprecated: use ``trade_py.data.market.crypto.fetch_btc`` instead.

    Uses BtcMarketDataService from the new crypto module for multi-provider validation.
    """
    warnings.warn(
        "trade_py.data.market.cross_asset.akshare.fetch_btc is deprecated; "
        "use trade_py.data.market.crypto.fetch_btc instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from trade_py.data.market.crypto.akshare import fetch_btc as _crypto_fetch_btc
    return _crypto_fetch_btc(data_root=data_root, days=days)


# Re-export DEFAULT_CRYPTO_ASSETS for back-compat
from trade_py.data.market.crypto.providers import DEFAULT_CRYPTO_ASSETS  # noqa: E402


# ── Master fetch ───────────────────────────────────────────────────────────────

def fetch_all(
    data_root: str = _DEFAULT_DATA_ROOT,
    delay_s: float = 1.0,
    crypto_assets: list[str] | tuple[str, ...] = DEFAULT_CRYPTO_ASSETS,
    include_assured_btc: bool = False,
) -> dict[str, pd.DataFrame]:
    """Fetch all cross-asset datasets in sequence (deprecated shim).

    FX and gold now delegate to the dedicated ``fx`` and ``commodity`` modules.
    Crypto delegates to ``trade_py.data.market.crypto``.
    """
    warnings.warn(
        "trade_py.data.market.cross_asset.fetch_all is deprecated; call "
        "trade_py.data.market.fx.fetch_usdcnh_ohlc, "
        "trade_py.data.market.commodity.fetch_gold_ohlc, and "
        "trade_py.data.market.crypto.fetch_crypto directly instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    results: dict[str, pd.DataFrame] = {}

    failures: dict[str, str] = {}
    for name, fn in [("gold", fetch_gold), ("fx_cnh", fetch_fx_cnh)]:
        try:
            results[name] = fn(data_root)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", name, e)
            failures[name] = f"{type(e).__name__}: {e}"
        time.sleep(delay_s)

    try:
        crypto_results = fetch_crypto(crypto_assets, data_root)
        results.update(crypto_results)
    except Exception as e:
        logger.error("Failed to fetch crypto: %s", e)
        failures["crypto"] = f"{type(e).__name__}: {e}"

    # Backwards compatibility: legacy assured BTC service
    if include_assured_btc:
        try:
            from trade_py.data.market.crypto.service import BtcMarketDataService
            outcome = BtcMarketDataService(data_root, days=730).sync()
            if outcome.get("published"):
                logger.info("Assured BTC sync complete: readiness=%s", outcome.get("data_readiness"))
        except Exception as e:
            logger.warning("Assured BTC sync skipped: %s", e)

    if failures:
        raise RuntimeError(f"cross-asset synchronization incomplete: {failures}")
    return results
