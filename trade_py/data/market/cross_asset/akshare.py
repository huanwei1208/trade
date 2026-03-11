from __future__ import annotations

"""Cross-asset data fetcher: gold (SGE), BTC (CoinGecko), USD/CNH (EastMoney).

Storage:
    data/cross_asset/gold.parquet    — Au99.99 CNY/gram, SGE
    data/cross_asset/btc.parquet     — BTC/USD daily OHLC, CoinGecko free API
    data/cross_asset/fx_cnh.parquet  — USD/CNH daily close, EastMoney

Column schema (all assets): date, open, high, low, close, [volume]
"""

import logging
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_DATA_ROOT = "data"
_OUT_DIR = "cross_asset"


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


# ── BTC/USD (OKX primary, CoinGecko fallback) ─────────────────────────────────

def _fetch_btc_okx(days: int) -> pd.DataFrame:
    """Fetch BTC/USDT daily OHLC from OKX public API (no key required)."""
    import requests

    # OKX returns at most 100 candles per request; paginate if needed
    bar = "1D"
    limit = 100
    all_rows: list[list] = []
    after: int | None = None  # fetch backwards from this timestamp_ms

    # Calculate earliest timestamp we need
    import time as _time
    earliest_ms = int((_time.time() - days * 86400) * 1000)

    while True:
        params: dict = {"instId": "BTC-USDT", "bar": bar, "limit": limit}
        if after is not None:
            params["after"] = after
        resp = requests.get(
            "https://www.okx.com/api/v5/market/history-candles",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0" or not data.get("data"):
            break
        rows = data["data"]  # [[ts_ms, o, h, l, c, vol, volCcy, volCcyQuote, confirm], ...]
        all_rows.extend(rows)
        oldest_ts = int(rows[-1][0])
        if oldest_ts <= earliest_ms or len(rows) < limit:
            break
        after = oldest_ts  # next page: fetch candles older than this

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close",
                                          "vol", "vol_ccy", "vol_ccy_quote", "confirm"])
    df["date"] = pd.to_datetime(df["ts"].astype(int), unit="ms").dt.normalize()
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["date", "open", "high", "low", "close"]].drop_duplicates(subset=["date"])


def _fetch_btc_coingecko(days: int) -> pd.DataFrame:
    """Fetch BTC/USD daily OHLC from CoinGecko free API (fallback)."""
    import requests

    url = f"https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days={days}"
    resp = requests.get(url, timeout=20, headers={"Accept": "application/json"})
    resp.raise_for_status()
    raw = resp.json()  # [[ts_ms, o, h, l, c], ...]
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
    return df[["date", "open", "high", "low", "close"]].drop_duplicates(subset=["date"])


def fetch_btc(
    data_root: str = _DEFAULT_DATA_ROOT,
    days: int = 365,
) -> pd.DataFrame:
    """Fetch BTC/USDT daily OHLC. Tries OKX first, falls back to CoinGecko."""
    path = _out_path(data_root, "btc")
    existing = _load_existing(path)
    logger.info("Fetching BTC/USD…")

    df: pd.DataFrame | None = None
    for source, fetcher in [("OKX", _fetch_btc_okx), ("CoinGecko", _fetch_btc_coingecko)]:
        try:
            df = fetcher(days)
            if df is not None and not df.empty:
                logger.debug("BTC data fetched from %s", source)
                break
        except Exception as e:
            logger.warning("BTC fetch failed (%s): %s", source, e)

    if df is None or df.empty:
        logger.error("BTC fetch failed from all sources")
        return existing if existing is not None else pd.DataFrame()

    df = df.sort_values("date").reset_index(drop=True)
    if existing is not None:
        df = pd.concat([existing, df], ignore_index=True).drop_duplicates(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)

    df.to_parquet(path, index=False)
    logger.info("BTC saved: %d rows → %s", len(df), path)
    return df


# ── Master fetch ───────────────────────────────────────────────────────────────

def fetch_all(data_root: str = _DEFAULT_DATA_ROOT, delay_s: float = 1.0) -> dict[str, pd.DataFrame]:
    """Fetch all cross-asset datasets in sequence."""
    results: dict[str, pd.DataFrame] = {}

    for name, fn in [("gold", fetch_gold), ("fx_cnh", fetch_fx_cnh), ("btc", fetch_btc)]:
        try:
            results[name] = fn(data_root)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", name, e)
        time.sleep(delay_s)

    return results
