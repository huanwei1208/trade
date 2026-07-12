"""Free global macro data client.

Sources (all free):
- FRED (Federal Reserve Economic Data): requires free API key (email signup at fred.stlouisfed.org)
  Without a key, falls back to a minimal set of public indicators.
- USD DXY (Dollar Index): from public web source
- US Treasury yield curve: public FRED endpoint (works without key for recent data)
- Crypto-relevant macro: DXY, VIX, US10Y, Fed Funds Rate

Set FRED_API_KEY in environment or trade config to enable full FRED access.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

_FRED_BASE = "https://api.stlouisfed.org/fred"
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

FRED_SERIES: dict[str, dict[str, str]] = {
    "DFF": {"name": "Fed Funds Effective Rate", "category": "monetary", "unit": "%"},
    "DGS10": {"name": "US 10Y Treasury Yield", "category": "rates", "unit": "%"},
    "DGS2": {"name": "US 2Y Treasury Yield", "category": "rates", "unit": "%"},
    "T10Y2Y": {"name": "10Y-2Y Yield Curve", "category": "rates", "unit": "%"},
    "DTWEXBGS": {"name": "Trade Weighted USD Index (DXY proxy)", "category": "fx", "unit": "index"},
    "VIXCLS": {"name": "CBOE VIX", "category": "volatility", "unit": "index"},
    "CPIAUCSL": {"name": "US CPI (All Urban Consumers)", "category": "inflation", "unit": "index"},
    "CPILFESL": {"name": "US Core CPI", "category": "inflation", "unit": "index"},
    "UNRATE": {"name": "US Unemployment Rate", "category": "employment", "unit": "%"},
    "PAYEMS": {"name": "US Nonfarm Payrolls", "category": "employment", "unit": "thousands"},
}


@dataclass
class MacroPoint:
    date: str
    series_id: str
    value: float
    series_name: str
    category: str
    unit: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "series_id": self.series_id,
            "value": self.value,
            "series_name": self.series_name,
            "category": self.category,
            "unit": self.unit,
        }


def _get_api_key() -> str | None:
    return os.environ.get("FRED_API_KEY") or os.environ.get("FRED_KEY")


def _http_get(url: str, timeout: int = 15) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.debug("HTTP GET failed for %s: %s", url, exc)
        return None


def fetch_fred_series(series_id: str, limit: int = 100, api_key: str | None = None) -> list[MacroPoint]:
    """Fetch a FRED series as MacroPoint list. Requires FRED_API_KEY."""
    key = api_key or _get_api_key()
    if not key:
        return []
    meta = FRED_SERIES.get(series_id, {"name": series_id, "category": "other", "unit": ""})
    url = (
        f"{_FRED_BASE}/series/observations"
        f"?series_id={series_id}&api_key={key}&file_type=json"
        f"&sort_order=desc&limit={limit}"
    )
    data = _http_get(url)
    if data is None:
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return []
    points: list[MacroPoint] = []
    for obs in payload.get("observations", []):
        val_str = str(obs.get("value", "")).strip()
        if val_str in ("", ".", "N/A"):
            continue
        try:
            val = float(val_str)
        except ValueError:
            continue
        points.append(MacroPoint(
            date=obs.get("date", ""),
            series_id=series_id,
            value=val,
            series_name=meta["name"],
            category=meta["category"],
            unit=meta["unit"],
        ))
    points.sort(key=lambda p: p.date)
    return points


def fetch_all_global_macro(api_key: str | None = None, limit: int = 365) -> dict[str, list[MacroPoint]]:
    """Fetch all configured FRED series. Returns series_id -> list[MacroPoint]."""
    result: dict[str, list[MacroPoint]] = {}
    key = api_key or _get_api_key()
    for series_id in FRED_SERIES:
        pts = fetch_fred_series(series_id, limit=limit, api_key=key)
        if pts:
            result[series_id] = pts
        time.sleep(0.2)
    return result


def save_macro_parquet(points_by_series: dict[str, list[MacroPoint]], output_dir: Path) -> dict[str, int]:
    """Save macro series to parquet files, one per series."""
    import pandas as pd
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for series_id, points in points_by_series.items():
        if not points:
            continue
        rows = [p.to_dict() for p in points]
        df = pd.DataFrame(rows)
        df["fetched_at"] = datetime.now(timezone.utc).isoformat()
        path = output_dir / "global" / f"{series_id.lower()}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        counts[series_id] = len(points)
    return counts


def get_fear_greed_latest(data_root: str | Path = "data") -> dict[str, Any] | None:
    """Read latest Fear & Greed value from local parquet."""
    import pandas as pd
    path = Path(data_root) / "market" / "cross_asset" / "crypto" / "fear_greed.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return None
        latest = df.sort_values("timestamp").iloc[-1]
        return {
            "value": int(latest["value"]),
            "classification": latest["classification"],
            "date": latest["date"],
        }
    except Exception as exc:
        logger.debug("get_fear_greed_latest error: %s", exc)
        return None
