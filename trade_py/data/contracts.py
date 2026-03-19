"""Data contracts — explicit provenance and freshness metadata.

These dataclasses are the single place where "how old is this data?" and
"what columns are present?" are encoded.  Downstream consumers (the trust layer,
CLI status commands) read from here rather than from ad hoc assumptions.

Design principles:
  - Minimal: only fields that are actually read by real code paths.
  - Practical: built from sync_state + factor store queries, not abstract.
  - Composable: FreshnessReport aggregates DataSnapshot instances.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class DataSnapshot:
    """Freshness and quality metadata for one dataset × symbol slice.

    Attributes
    ----------
    dataset : str
        Logical name: "kline", "signals", "sentiment_gold", "factors",
        "event_propagations", "fund_flow", "market_events", …
    symbol : str | None
        None means market-wide (e.g. index data, macro).
    as_of_date : str
        The date this snapshot was taken (ISO).
    latest_available_date : str | None
        The most recent date with actual data; None = no data at all.
    freshness_days : int | None
        Days between as_of_date and latest_available_date.
        None = data missing entirely.
    row_count : int
        Approximate number of rows available for this snapshot window.
    missing_columns : list[str]
        Columns expected but absent from the source.
    schema_version : str
        Data schema version (e.g. "v1").
    quality_flags : list[str]
        Machine-readable flags: "stale", "low_coverage", "missing_required",
        "schema_mismatch", "no_data".
    """

    dataset: str
    symbol: str | None
    as_of_date: str
    latest_available_date: str | None = None
    freshness_days: int | None = None
    row_count: int = 0
    missing_columns: list[str] = field(default_factory=list)
    schema_version: str = "v1"
    quality_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "symbol": self.symbol,
            "as_of_date": self.as_of_date,
            "latest_available_date": self.latest_available_date,
            "freshness_days": self.freshness_days,
            "row_count": self.row_count,
            "missing_columns": list(self.missing_columns),
            "schema_version": self.schema_version,
            "quality_flags": list(self.quality_flags),
        }


@dataclass
class SourceMetadata:
    """Metadata about a data source (e.g. Tushare, RSS, internal pipeline).

    Distinct from DataSnapshot: this is about the provider, not the data slice.
    """

    source_id: str           # e.g. "tushare_kline", "rss_sina", "gold_pipeline"
    provider: str            # "tushare", "akshare", "internal", "rss"
    last_success: str | None = None   # ISO datetime of last successful fetch
    reliability_score: float = 1.0   # 0–1; from InfluenceSignal / source eval
    is_degraded: bool = False
    degradation_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "provider": self.provider,
            "last_success": self.last_success,
            "reliability_score": round(self.reliability_score, 4),
            "is_degraded": self.is_degraded,
            "degradation_reason": self.degradation_reason,
        }


@dataclass
class FreshnessReport:
    """Aggregate freshness across all datasets needed for inference.

    This is the primary input to ``compute_prediction_trust()``'s
    ``data_lag_days`` parameter — via ``overall_lag_days``.

    Attributes
    ----------
    snapshots : list[DataSnapshot]
        One entry per dataset checked.
    overall_freshness_score : float
        Weighted average freshness ∈ [0, 1].  Weights are dataset criticality.
    overall_lag_days : int | None
        Max lag_days across critical datasets.  None = at least one critical
        dataset has no data.
    stale_datasets : list[str]
        Datasets with freshness_days > stale_threshold (default 3).
    missing_datasets : list[str]
        Datasets with no data at all (freshness_days is None).
    as_of_date : str
        Date this report was generated.
    """

    snapshots: list[DataSnapshot] = field(default_factory=list)
    overall_freshness_score: float = 1.0
    overall_lag_days: int | None = None
    stale_datasets: list[str] = field(default_factory=list)
    missing_datasets: list[str] = field(default_factory=list)
    as_of_date: str = ""

    def to_dict(self) -> dict:
        return {
            "overall_freshness_score": round(self.overall_freshness_score, 4),
            "overall_lag_days": self.overall_lag_days,
            "stale_datasets": list(self.stale_datasets),
            "missing_datasets": list(self.missing_datasets),
            "as_of_date": self.as_of_date,
            "snapshots": [s.to_dict() for s in self.snapshots],
        }


# ── Freshness threshold constants ──────────────────────────────────────────────

STALE_THRESHOLD_DAYS = 3    # lag > this → "stale" flag
CRITICAL_DATASETS = frozenset({"kline", "signals", "factors"})
OPTIONAL_DATASETS = frozenset({"sentiment_gold", "event_propagations", "fund_flow"})

# Dataset weights for weighted freshness average
_DATASET_WEIGHTS: dict[str, float] = {
    "kline":              0.30,
    "signals":            0.25,
    "factors":            0.20,
    "sentiment_gold":     0.10,
    "event_propagations": 0.10,
    "fund_flow":          0.05,
}


def build_freshness_report(
    snapshots: list[DataSnapshot],
    as_of_date: str | None = None,
) -> FreshnessReport:
    """Compute aggregate freshness metrics from a list of DataSnapshots.

    Each snapshot's freshness_score = max(0, 1 − freshness_days × 0.10).
    Missing data (freshness_days is None) → score 0.0.

    The overall_freshness_score is a weighted average using _DATASET_WEIGHTS.
    Datasets not in the weights dict contribute with weight 0.05.
    """
    today = as_of_date or date.today().isoformat()

    stale: list[str] = []
    missing: list[str] = []
    weighted_sum = 0.0
    weight_total = 0.0

    for snap in snapshots:
        w = _DATASET_WEIGHTS.get(snap.dataset, 0.05)

        if snap.freshness_days is None:
            score = 0.0
            missing.append(snap.dataset)
        else:
            score = max(0.0, 1.0 - snap.freshness_days * 0.10)
            if snap.freshness_days > STALE_THRESHOLD_DAYS:
                stale.append(snap.dataset)

        weighted_sum += score * w
        weight_total += w

    overall = round(weighted_sum / weight_total, 4) if weight_total > 0 else 1.0

    # Overall lag = max lag across critical datasets with data
    critical_lags = [
        s.freshness_days for s in snapshots
        if s.dataset in CRITICAL_DATASETS and s.freshness_days is not None
    ]
    overall_lag = max(critical_lags) if critical_lags else None

    return FreshnessReport(
        snapshots=snapshots,
        overall_freshness_score=overall,
        overall_lag_days=overall_lag,
        stale_datasets=stale,
        missing_datasets=missing,
        as_of_date=today,
    )


def snapshot_from_sync_state(
    dataset: str,
    as_of_date: str,
    sync_last_date,   # date | None — from db.sync_state_get(...)
    row_count: int = 0,
) -> DataSnapshot:
    """Create a DataSnapshot from a sync_state lookup result.

    Parameters
    ----------
    sync_last_date:
        Result of ``db.sync_state_get(source, dataset, symbol)``; a date or None.
    """
    if sync_last_date is None:
        return DataSnapshot(
            dataset=dataset,
            symbol=None,
            as_of_date=as_of_date,
            latest_available_date=None,
            freshness_days=None,
            row_count=row_count,
            quality_flags=["no_data"],
        )

    latest_str = (
        sync_last_date.isoformat()
        if hasattr(sync_last_date, "isoformat")
        else str(sync_last_date)
    )
    try:
        as_of_dt = date.fromisoformat(as_of_date)
        latest_dt = date.fromisoformat(latest_str[:10])
        lag = (as_of_dt - latest_dt).days
    except (ValueError, TypeError):
        lag = None

    flags: list[str] = []
    if lag is None:
        flags.append("unknown_lag")
    elif lag > STALE_THRESHOLD_DAYS:
        flags.append("stale")

    return DataSnapshot(
        dataset=dataset,
        symbol=None,
        as_of_date=as_of_date,
        latest_available_date=latest_str,
        freshness_days=lag,
        row_count=row_count,
        quality_flags=flags,
    )
