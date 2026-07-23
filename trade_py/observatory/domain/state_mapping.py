"""State axis mapping (WP0 frozen_contracts.md; used by WP1 projection and WP2).

Maps immutable manifest facts to the frozen orthogonal state axes, preserving the
original value and `mapping_policy_version`. These are one-directional read-side
projections: they never write back to `data_readiness` or relax any publish gate.
"""
from __future__ import annotations

from typing import Any

from trade_py.observatory.domain.vocab import (
    MAPPING_POLICY_VERSION,
    AcquisitionState,
    CompatibilityState,
    FreshnessState,
    LifecycleState,
    QualityState,
)

# manifest data_readiness -> quality_state (frozen table)
_READINESS_TO_QUALITY = {
    "ready": QualityState.ASSURED,
    "degraded": QualityState.DEGRADED,
    "insufficient_data": QualityState.INSUFFICIENT,
    "invalid": QualityState.INVALID,
}


def quality_state_for(manifest: dict[str, Any]) -> QualityState:
    readiness = manifest.get("data_readiness")
    if readiness is None:
        # assurance not run yet
        if not manifest.get("gates"):
            return QualityState.NOT_EVALUATED
        return QualityState.UNKNOWN
    mapped = _READINESS_TO_QUALITY.get(str(readiness))
    return mapped if mapped is not None else QualityState.UNKNOWN


def acquisition_state_for(manifest: dict[str, Any]) -> AcquisitionState:
    evidence = manifest.get("acquisition_evidence") or {}
    providers = evidence.get("providers") or {}
    if not providers:
        # No provider evidence recorded at all.
        rows = int(manifest.get("canonical_rows") or 0)
        return AcquisitionState.EMPTY if rows == 0 else AcquisitionState.UNKNOWN
    statuses = {str(p.get("status") or "unknown") for p in providers.values()}
    primary = str((providers.get("okx") or {}).get("status") or "unknown")
    rows = int(manifest.get("canonical_rows") or 0)
    if statuses <= {"succeeded"}:
        return AcquisitionState.SUCCEEDED if rows > 0 else AcquisitionState.EMPTY
    if primary == "succeeded":
        return AcquisitionState.PARTIAL if rows > 0 else AcquisitionState.EMPTY
    if statuses <= {"failed"}:
        return AcquisitionState.FAILED
    if rows == 0:
        return AcquisitionState.EMPTY
    return AcquisitionState.PARTIAL


def lifecycle_state_for(*, is_published: bool, is_rolled_back: bool = False, is_superseded: bool = False) -> LifecycleState:
    if is_rolled_back:
        return LifecycleState.ROLLED_BACK
    if is_published:
        return LifecycleState.PUBLISHED
    if is_superseded:
        return LifecycleState.SUPERSEDED
    return LifecycleState.STAGED


def freshness_for(watermark: str | None, expected_latest: str | None, max_staleness_days: int = 1) -> FreshnessState:
    """Freshness derived from watermark vs expected latest completed bar (dates only)."""

    if not watermark or not expected_latest:
        return FreshnessState.UNKNOWN
    try:
        from datetime import date

        wm = date.fromisoformat(watermark[:10])
        exp = date.fromisoformat(expected_latest[:10])
    except (ValueError, TypeError):
        return FreshnessState.UNKNOWN
    staleness = (exp - wm).days
    return FreshnessState.FRESH if staleness <= max_staleness_days else FreshnessState.STALE


def compatibility_for(
    *,
    manifest_code_revision: str | None,
    current_code_revision: str | None,
    replay_mismatch: bool = False,
) -> CompatibilityState:
    """Compatibility is separate from historical certification (frozen invariant)."""

    if replay_mismatch:
        return CompatibilityState.REPLAY_MISMATCH
    if manifest_code_revision is None or current_code_revision is None:
        return CompatibilityState.UNKNOWN
    if manifest_code_revision == current_code_revision:
        return CompatibilityState.COMPATIBLE
    return CompatibilityState.CONTRACT_STALE


def mapping_metadata() -> dict[str, str]:
    return {"mapping_policy_version": MAPPING_POLICY_VERSION}
