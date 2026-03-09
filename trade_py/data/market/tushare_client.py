"""Central Tushare Pro API client.

Manages token loading, rate limiting (≥600 ms between calls), and retry.

Usage:
    from trade_py.data.market.tushare_client import get_pro_api
    pro = get_pro_api(data_root="data")
    df = pro.daily(ts_code="000001.SZ", start_date="20250101", end_date="20250301", adj="hfq")

Token is stored via:
    ./trade account setting-set tushare_token YOUR_TOKEN
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_RATE_LIMIT_SEC = 0.6   # 600 ms — safe for 2000-point accounts


class TushareProClient:
    """Thin wrapper around tushare.pro_api with rate limiting and retry."""

    def __init__(self, token: str) -> None:
        import tushare as ts
        self._api = ts.pro_api(token)
        self._api._DataApi__token = token
        self._api._DataApi__http_url = 'http://lianghua.nanyangqiankun.top'
        self._last_call: float = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < _RATE_LIMIT_SEC:
            time.sleep(_RATE_LIMIT_SEC - elapsed)

    def call(self, endpoint: str, retries: int = 3, **kwargs: Any) -> pd.DataFrame:
        """Call a Tushare Pro endpoint with rate limiting and exponential back-off."""
        fn = getattr(self._api, endpoint)
        last_exc: Exception | None = None
        for attempt in range(retries):
            self._wait()
            try:
                self._last_call = time.monotonic()
                result = fn(**kwargs)
                if result is None:
                    return pd.DataFrame()
                return result
            except Exception as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning(
                    "tushare call %s attempt %d/%d failed: %s — retrying in %ds",
                    endpoint, attempt + 1, retries, exc, wait,
                )
                time.sleep(wait)
        raise RuntimeError(
            f"tushare endpoint {endpoint!r} failed after {retries} attempts"
        ) from last_exc


_INSTANCE: TushareProClient | None = None


def get_pro_api(data_root: str | Path = "data") -> TushareProClient:
    """Return the singleton TushareProClient, initialising it if needed.

    Reads token from SettingsDB (.metadata/trade.db) at data_root.
    Falls back to TUSHARE_TOKEN environment variable.
    """
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE

    token = _load_token(data_root)
    if not token:
        raise RuntimeError(
            "Tushare token not found. Run:\n"
            "  ./trade account setting-set tushare_token YOUR_TOKEN"
        )
    _INSTANCE = TushareProClient(token)
    return _INSTANCE


def _load_token(data_root: str | Path) -> str | None:
    import os
    # 1. Try SettingsDB
    db_path = Path(data_root) / ".metadata" / "trade.db"
    if db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'tushare_token'"
            ).fetchone()
            conn.close()
            if row and row[0]:
                return str(row[0]).strip()
        except Exception as exc:
            logger.debug("Could not read tushare_token from SettingsDB: %s", exc)
    # 2. Environment variable fallback
    return os.environ.get("TUSHARE_TOKEN") or None
