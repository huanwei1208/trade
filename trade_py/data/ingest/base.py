from __future__ import annotations

"""Abstract base class for asset ingestors."""

import abc
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class IngestResult:
    """Result of a single asset ingest run."""
    asset_id: str
    success: bool
    rows: int = 0
    new_rows: int = 0
    watermark_date: str | None = None
    error: str | None = None
    frame: pd.DataFrame | None = None
    metadata: dict[str, Any] | None = None


class AssetIngestor(abc.ABC):
    """Abstract base class for all asset data ingestors."""

    @abc.abstractmethod
    def fetch(
        self,
        asset: dict,
        *,
        days: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch data for the given asset.

        Args:
            asset: Asset registry entry dict
            days: Number of days to fetch back from now
            start_date: Explicit start date (overrides days if provided)
            end_date: Explicit end date (defaults to today)

        Returns:
            DataFrame with standardized columns: date, open, high, low, close, volume
        """
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Ingestor name, matches venue in asset registry."""
        ...

    def validate_frame(self, df: pd.DataFrame, asset_id: str) -> None:
        """Validate OHLC frame integrity."""
        if df is None or df.empty:
            return
        required = {"date", "open", "high", "low", "close"}
        missing = sorted(required - set(df.columns))
        if missing:
            raise ValueError(f"{asset_id} missing columns: {missing}")
        work = df.copy()
        for col in ("open", "high", "low", "close"):
            work[col] = pd.to_numeric(work[col], errors="coerce")
        invalid = work[
            work[["open", "high", "low", "close"]].isna().any(axis=1)
            | work[["open", "high", "low", "close"]].le(0).any(axis=1)
            | (work["high"] < work["low"])
            | (work["high"] < work["open"])
            | (work["high"] < work["close"])
            | (work["low"] > work["open"])
            | (work["low"] > work["close"])
        ]
        if not invalid.empty:
            sample = invalid[["date", "open", "high", "low", "close"]].head(3).to_dict(orient="records")
            raise ValueError(f"{asset_id} has {len(invalid)} invalid OHLC rows: {sample}")
