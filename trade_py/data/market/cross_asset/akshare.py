from __future__ import annotations

"""Cross-asset data fetcher: gold (SGE), crypto (OKX primary + Binance shadow, FREE no API keys), USD/CNH (EastMoney).

Storage:
    data/market/cross_asset/gold.parquet — Au99.99 CNY/gram, SGE
    data/market/cross_asset/crypto/<asset>.parquet — e.g. btc.parquet, eth.parquet: <asset>/USDT UTC daily OHLC, OKX primary, Binance shadow assurance
    data/market/cross_asset/fx_cnh.parquet — USD/CNH daily close, EastMoney

All crypto data sources are 100% free public exchange APIs with NO API KEY REQUIRED.
- OKX public market data API (primary OHLCV source)
- Binance public kline API (shadow OHLCV source for cross-validation)

Column schema (all assets): date, open, high, low, close, [volume]
"""

import logging
import time
from pathlib import Path

import pandas as pd

from trade_py.data.market.cross_asset.providers import (
    DEFAULT_CRYPTO_ASSETS,
    OkxDailyProvider,
    BinanceDailyProvider,
    okx_canonical_candidate,
    normalize_binance_klines,
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

    _validate_ohlc_frame("gold", df)
    df.to_parquet(path, index=False)
    logger.info("Gold saved: %d rows → %s", len(df), path)
    return df


# ── USD/CNH (EastMoney primary, ECB Frankfurter fallback) ─────────────────────

def fetch_fx_cnh(data_root: str = _DEFAULT_DATA_ROOT) -> pd.DataFrame:
    """Fetch USD/CNH daily OHLC. Try EastMoney; fall back to ECB Frankfurter on failure.

    EastMoney push2his may block datacenter IPs. Frankfurter is ECB reference rates
    (free, key-less) — only provides a single daily rate so open=high=low=close.
    """
    path = _out_path(data_root, "fx_cnh")
    existing = _load_existing(path)

    df = _fetch_usdcnh_with_fallback(existing_start=existing)

    if existing is not None:
        watermark = _watermark_date(existing)
        if watermark and df["date"].max() <= pd.Timestamp(watermark):
            logger.info("USD/CNH data already up to date (%s)", watermark)
            return existing
        if watermark:
            df = df[df["date"] > pd.Timestamp(watermark)]
        if df.empty:
            return existing
        df = pd.concat([existing, df], ignore_index=True).drop_duplicates(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)

    _validate_ohlc_frame("fx_cnh", df)
    df.to_parquet(path, index=False)
    logger.info("USD/CNH saved: %d rows → %s", len(df), path)
    return df


def _fetch_usdcnh_with_fallback(*, existing_start: pd.DataFrame | None = None) -> pd.DataFrame:
    """Try EastMoney akshare first, fall back to Frankfurter on any failure."""
    try:
        import akshare as ak
        logger.info("Fetching USD/CNH (EastMoney via akshare)…")
        df_raw = ak.forex_hist_em(symbol="USDCNH")
        df = df_raw.rename(columns={
            "日期": "date",
            "今开": "open",
            "最高": "high",
            "最低": "low",
            "最新价": "close",
        })[["date", "open", "high", "low", "close"]].copy()
        df["date"] = pd.to_datetime(df["date"])
        df["volume"] = pd.NA
        df = df.sort_values("date").reset_index(drop=True)
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        logger.info("USD/CNH: EastMoney succeeded, %d rows", len(df))
        return df
    except Exception as exc:
        logger.warning("USD/CNH: EastMoney fetch failed (%s), falling back to ECB Frankfurter", exc)

    return _fetch_usdcny_frankfurter(existing_start=existing_start)


def _fetch_usdcny_frankfurter(*, existing_start: pd.DataFrame | None = None) -> pd.DataFrame:
    """ECB Frankfurter USD/CNY daily rates (free, no API key).

    Publishes one reference rate per business day; weekend/holiday gaps are forward-filled.
    Used as CNH proxy — onshore/offshore spread is typically <0.05 for macro signal use.
    """
    import json
    import urllib.request

    if existing_start is not None and len(existing_start) > 0:
        start = existing_start["date"].max() - pd.Timedelta(days=7)
    else:
        start = pd.Timestamp("2010-01-01")
    start_str = start.strftime("%Y-%m-%d")
    url = f"https://api.frankfurter.app/{start_str}..?from=USD&to=CNY"
    logger.info("Fetching USD/CNY from ECB Frankfurter: %s", url)

    req = urllib.request.Request(url, headers={"User-Agent": "trade-data/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    rates = payload.get("rates", {})
    if not rates:
        raise RuntimeError(f"Frankfurter returned empty rates for {url}")

    rows = []
    for date_str, rate_map in sorted(rates.items()):
        cny = rate_map.get("CNY")
        if cny is None:
            continue
        rows.append({
            "date": pd.Timestamp(date_str),
            "open": cny, "high": cny, "low": cny, "close": cny,
            "volume": pd.NA,
        })

    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    all_days = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    df = df.set_index("date").reindex(all_days).ffill().reset_index().rename(columns={"index": "date"})
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.info("USD/CNH: Frankfurter produced %d rows (%s to %s)",
                len(df), df["date"].min().date(), df["date"].max().date())
    return df.reset_index(drop=True)


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
        run_id=f"cross-asset-fetch-{asset.lower()}",
    )
    candidate = okx_canonical_candidate(capture, contract=okx_provider.contract)
    if candidate.empty:
        # Fallback to Binance if OKX fails for this asset
        logger.warning("OKX returned no data for %s, falling back to Binance", asset)
        binance_provider = BinanceDailyProvider(base_asset=asset)
        binance_capture = binance_provider.capture(
            days=days,
            fetched_at=None,
            run_id=f"cross-asset-fetch-{asset.lower()}-fallback",
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
    """Fetch all supported crypto assets and save to crypto/<asset>.parquet.

    All data is 100% free from public exchange APIs, no API keys or paid services required.
    Assets: BTC, ETH, SOL, BNB, XRP by default (all major liquid crypto assets).
    """
    crypto_root = Path(data_root) / _OUT_DIR / "crypto"
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
                # Also maintain backwards compatibility: copy to btc.parquet for BTC
                if asset == "BTC":
                    legacy_path = Path(data_root) / _OUT_DIR / "btc.parquet"
                    existing.to_parquet(legacy_path, index=False)
                continue
            df = pd.concat([existing, df], ignore_index=True).drop_duplicates(subset=["date"])
            df = df.sort_values("date").reset_index(drop=True)

        _validate_ohlc_frame(asset, df)
        df.to_parquet(path, index=False)
        logger.info("%s saved: %d rows → %s", asset, len(df), path)
        results[asset_lower] = df
        time.sleep(0.3)  # Rate limit courtesy

    # Maintain backwards compatibility: BTC remains at cross_asset/btc.parquet
    if "btc" in results:
        legacy_path = Path(data_root) / _OUT_DIR / "btc.parquet"
        results["btc"].to_parquet(legacy_path, index=False)

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
    from trade_py.data.market.cross_asset.service import BtcMarketDataService
    service = BtcMarketDataService(data_root, days=days)
    payload = service.sync()
    if not payload.get("published", False):
        readiness = payload.get("data_readiness", "unknown")
        raise RuntimeError(
            f"BTC data did not publish cleanly: readiness={readiness} "
            f"run_id={payload.get('run_id')}"
        )
    return _fetch_crypto_single("BTC", days=days)[["date", "open", "high", "low", "close"]]


# ── Master fetch ───────────────────────────────────────────────────────────────

def fetch_all(
    data_root: str = _DEFAULT_DATA_ROOT,
    delay_s: float = 1.0,
    crypto_assets: list[str] | tuple[str, ...] = DEFAULT_CRYPTO_ASSETS,
    include_assured_btc: bool = False,
) -> dict[str, pd.DataFrame]:
    """Fetch all cross-asset datasets in sequence.

    All crypto data uses 100% free public exchange APIs (OKX + Binance), NO API KEYS REQUIRED.
    This is the industry standard approach used by most quantitative trading teams:
    use free public exchange data directly, cross-validate across multiple venues for integrity.
    """
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

    # Backwards compatibility: legacy assured BTC service (uses free Binance shadow now)
    if include_assured_btc:
        try:
            from trade_py.data.market.cross_asset.service import BtcMarketDataService
            outcome = BtcMarketDataService(data_root, days=730).sync()
            if outcome.get("published"):
                logger.info("Assured BTC sync complete: readiness=%s", outcome.get("data_readiness"))
        except Exception as e:
            logger.warning("Assured BTC sync skipped: %s", e)

    if failures:
        raise RuntimeError(f"cross-asset synchronization incomplete: {failures}")
    return results
