"""Macro economic data fetcher via Tushare Pro.

Datasets:
    gdp  — pro.cn_gdp()    → data/macro/gdp.parquet
    cpi  — pro.cn_cpi()    → data/macro/cpi.parquet
    ppi  — pro.cn_ppi()    → data/macro/ppi.parquet
    pmi  — pro.cn_pmi()    → data/macro/pmi.parquet

All data is monthly/quarterly frequency; stored as single files sorted by date.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DATASETS = {
    "gdp": ("cn_gdp",  "q_gdp",      "year"),   # endpoint, value_col, date_col
    "cpi": ("cn_cpi",  "nt_yoy",     "month"),
    "ppi": ("cn_ppi",  "ppi_yoy",    "month"),
    "pmi": ("cn_pmi",  "mfg_pmi",    "month"),
}


class MacroFetcher:
    """Fetch and persist macro data from Tushare Pro."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self.data_root = str(data_root)
        self._dir = Path(data_root) / "macro"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.parquet"

    def load(self, name: str) -> pd.DataFrame:
        p = self._path(name)
        if not p.exists():
            return pd.DataFrame()
        return pd.read_parquet(p)

    def fetch_and_save(self, name: str) -> pd.DataFrame:
        if name not in _DATASETS:
            raise ValueError(f"Unknown macro dataset: {name!r}. Choose from {list(_DATASETS)}")
        from trade_py.data.market.tushare_client import get_pro_api
        pro = get_pro_api(self.data_root)
        endpoint, value_col, date_col = _DATASETS[name]
        raw = pro.call(endpoint)
        if raw is None or raw.empty:
            logger.warning("MacroFetcher: no data for %s", name)
            return self.load(name)

        # Normalise date column to YYYY-MM-DD
        if date_col in raw.columns:
            s = raw[date_col].astype(str)
            if s.str.len().max() == 4:
                # year only → YYYY-01-01
                raw["date"] = pd.to_datetime(s + "0101", format="%Y%m%d", errors="coerce")
            else:
                raw["date"] = pd.to_datetime(s + "01", format="%Y%m%d", errors="coerce")
        else:
            logger.warning("MacroFetcher: no date column %r in %s", date_col, name)
            return self.load(name)

        raw = raw.sort_values("date").reset_index(drop=True)
        raw["date"] = raw["date"].dt.strftime("%Y-%m-%d")

        combined = raw
        existing = self.load(name)
        if not existing.empty:
            combined = pd.concat([existing, raw], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date"], keep="last")
            combined = combined.sort_values("date").reset_index(drop=True)

        combined.to_parquet(self._path(name), index=False)
        logger.info("MacroFetcher: saved %d rows for %s", len(combined), name)
        return combined

    def fetch_all(self) -> None:
        for name in _DATASETS:
            try:
                self.fetch_and_save(name)
            except Exception as exc:
                logger.error("MacroFetcher: %s failed: %s", name, exc)
