"""FX market data fetcher — USD/CNH (USDCNH) daily OHLC.

Primary source: EastMoney via akshare (forex_hist_em, "USDCNH").
Fallback source: ECB Frankfurter (USD/CNY reference rates) — used when EastMoney
blocks datacenter IPs or rate-limits. Frankfurter publishes one reference rate per
business day; weekend/holiday gaps are forward-filled to produce a continuous
daily series. CNY is used as a CNH proxy — onshore/offshore spread is typically
<0.05 for macro signal use.

Storage:
    data/market/fx/usdcnh.parquet — USD/CNH daily OHLC (UTC-aligned close)

Column schema: date, open, high, low, close, volume
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from pathlib import Path

import pandas as pd

from trade_py.utils.retry import retry

logger = logging.getLogger(__name__)

_DEFAULT_DATA_ROOT = "data"
_OUT_DIR = "market/fx"

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


# ── EastMoney primary (akshare forex_hist_em) ─────────────────────────────────

@retry(delays=_FETCH_RETRY_DELAYS_SEC, on=(Exception,))
def _fetch_usdcnh_eastmoney() -> pd.DataFrame:
    """Fetch USDCNH daily OHLC via akshare/EastMoney.

    Returns columns: date, open, high, low, close, volume (sorted by date).
    Raises on any network/parse failure — caller decides fallback.
    """
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


# ── ECB Frankfurter fallback ──────────────────────────────────────────────────

@retry(delays=_FETCH_RETRY_DELAYS_SEC, on=(Exception,))
def _fetch_usdcny_frankfurter(*, existing_start: pd.DataFrame | None = None) -> pd.DataFrame:
    """ECB Frankfurter USD/CNY daily rates (free, no API key).

    Publishes one reference rate per business day; weekend/holiday gaps are
    forward-filled to produce a continuous daily series. Used as CNH proxy —
    onshore/offshore spread is typically <0.05 for macro signal use.
    """
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
    # Forward-fill weekend / holiday gaps → continuous daily series
    all_days = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    df = df.set_index("date").reindex(all_days).ffill().reset_index().rename(columns={"index": "date"})
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.info("USD/CNH: Frankfurter produced %d rows (%s to %s)",
                len(df), df["date"].min().date(), df["date"].max().date())
    return df.reset_index(drop=True)


def _fetch_usdcnh_with_fallback(*, existing_start: pd.DataFrame | None = None) -> pd.DataFrame:
    """Try EastMoney akshare first, fall back to Frankfurter on any failure."""
    try:
        return _fetch_usdcnh_eastmoney()
    except Exception as exc:
        logger.warning("USD/CNH: EastMoney fetch failed (%s), falling back to ECB Frankfurter", exc)

    return _fetch_usdcny_frankfurter(existing_start=existing_start)


# ── Public entrypoint ─────────────────────────────────────────────────────────

def fetch_usdcnh_ohlc(data_root: str = _DEFAULT_DATA_ROOT) -> pd.DataFrame:
    """Fetch USD/CNH daily OHLC and save to ``data/market/fx/usdcnh.parquet``.

    Try EastMoney first; fall back to ECB Frankfurter reference rates on failure.
    Frankfurter returns one rate per business day; weekend/holiday gaps are
    forward-filled to produce a continuous daily series (open=high=low=close
    on non-trading ECB days).

    Incremental: existing parquet is loaded and only new dates (past the stored
    watermark) are appended.
    """
    path = _out_path(data_root, "usdcnh")
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

    _validate_ohlc_frame("usdcnh", df)
    df.to_parquet(path, index=False)
    logger.info("USD/CNH saved: %d rows → %s", len(df), path)
    return df
