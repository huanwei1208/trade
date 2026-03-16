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
_DATE_FALLBACKS = ("ann_date", "month", "year", "quarter")


class MacroFetcher:
    """Fetch and persist macro data from Tushare Pro."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self.data_root = str(data_root)
        self._dir = Path(data_root) / "market" / "macro"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.parquet"

    def load(self, name: str) -> pd.DataFrame:
        p = self._path(name)
        if not p.exists():
            return pd.DataFrame()
        return pd.read_parquet(p)

    @staticmethod
    def _resolve_date_column(raw: pd.DataFrame, preferred: str) -> str | None:
        """Return the actual column name matching *preferred* (case-insensitive), or None."""
        lookup = {str(col).lower(): str(col) for col in raw.columns}
        return lookup.get(preferred.lower())

    @staticmethod
    def _normalise_dates(raw: pd.DataFrame, actual_col: str) -> pd.Series:
        values = raw[actual_col].astype(str).str.strip().str.upper()
        if values.str.fullmatch(r"\d{4}Q[1-4]").all():
            periods = pd.PeriodIndex(values, freq="Q")
            return periods.to_timestamp(how="end").normalize()
        if values.str.len().max() == 4:
            return pd.to_datetime(values + "0101", format="%Y%m%d", errors="coerce")
        return pd.to_datetime(values + "01", format="%Y%m%d", errors="coerce")

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
        # Try configured column first, then common tushare fallbacks
        actual_col = self._resolve_date_column(raw, date_col)
        if actual_col is None:
            for fallback in _DATE_FALLBACKS:
                actual_col = self._resolve_date_column(raw, fallback)
                if actual_col is not None:
                    logger.debug("MacroFetcher: %s date column %r not found, using fallback %r", name, date_col, actual_col)
                    break
        if actual_col is None:
            logger.warning("MacroFetcher: no date column (tried %r + fallbacks) in %s. Columns: %s",
                           date_col, name, list(raw.columns))
            return self.load(name)
        raw["date"] = self._normalise_dates(raw, actual_col)

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
        from trade_py.utils.progress import iter_progress
        for name in iter_progress(_DATASETS, desc="macro", unit="dataset"):
            try:
                self.fetch_and_save(name)
            except Exception as exc:
                logger.error("MacroFetcher: %s failed: %s", name, exc)
