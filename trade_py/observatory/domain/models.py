"""Immutable domain objects for the BTC Observatory (WP1).

These are read-only value objects projected from immutable manifests, the current
pointer, and publish/rollback audits. They preserve the four clocks and never carry
Web DTO or notebook helpers (that separation is a WP2 invariant).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from trade_py.observatory.domain.vocab import (
    AcquisitionState,
    AvailabilityState,
    CompatibilityState,
    FreshnessState,
    LifecycleState,
    QualityState,
    RenderRole,
    ResearchState,
    RevisionState,
)


@dataclass(frozen=True)
class AssetContract:
    """Frozen asset/provider identity."""

    asset_id: str
    display_symbol: str
    contract_version: str
    primary_provider: str
    primary_instrument: str
    shadow_provider: str
    shadow_instrument: str
    quote: str
    primary_interval: str
    shadow_interval: str


@dataclass(frozen=True)
class ArtifactRef:
    """A run-relative artifact reference plus its recorded SHA-256.

    Referencing by (run_id, relative name, sha256) keeps a future content-addressed
    storage migration additive.
    """

    run_id: str
    name: str
    sha256: str
    relative_path: str


@dataclass(frozen=True)
class LegacyTimeProvenance:
    """Provenance for a derived ordering time (WP0 §7.7)."""

    value: str | None
    provenance: str  # "receipt" | "manifest.created_at" | "acquisition_evidence.as_of" | "unproven"
    precision: str  # "exact" | "proxy" | "unknown"
    unproven: bool


@dataclass(frozen=True)
class QualityFinding:
    finding_id: str
    run_id: str
    gate: str
    severity: str
    reason_code: str
    detail: str = ""
    affected_dates: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    blocks_purposes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObservationRun:
    """Immutable run projection.

    Ordering times are derived through the legacy adapter; only *_provenance fields
    reveal whether a time is exact or a proxy.
    """

    run_id: str
    contract: AssetContract
    created_at: str | None
    effective_as_of: str | None
    market_watermark: str | None
    input_watermarks: dict[str, Any]
    output_watermark: str | None
    canonical_rows: int
    code_revision: str | None
    config_hash: str | None
    schema_hash: str | None
    canonical_hash: str | None
    primary_hash: str | None
    shadow_hash: str | None
    artifact_refs: tuple[ArtifactRef, ...]
    gates: tuple[dict[str, Any], ...]
    data_readiness: str | None
    acquisition_state: AcquisitionState
    quality_state: QualityState
    lifecycle_state: LifecycleState
    blocking_gate: str | None
    blocking_reason_code: str | None
    findings: tuple[QualityFinding, ...] = ()
    # Derived ordering times with provenance
    staged_at: LegacyTimeProvenance | None = None
    assurance_completed_at: LegacyTimeProvenance | None = None
    capture_completed_at: LegacyTimeProvenance | None = None
    first_proven_present_at: str | None = None
    has_primary_canonical: bool = False
    has_final_bar: bool = False
    has_d0_blocker: bool = False

    def order_key_observed(self) -> tuple:
        return (
            self.market_watermark or "",
            self.effective_as_of or "",
            (self.capture_completed_at.value if self.capture_completed_at else "") or "",
            self.run_id,
        )

    def order_key_candidate(self) -> tuple:
        return (
            (self.assurance_completed_at.value if self.assurance_completed_at else "") or "",
            (self.staged_at.value if self.staged_at else "") or "",
            self.run_id,
        )

    def order_key_staged(self) -> tuple:
        return (
            (self.staged_at.value if self.staged_at else "") or "",
            self.created_at or "",
            self.run_id,
        )


@dataclass(frozen=True)
class Release:
    release_id: str
    channel: str
    run_id: str
    previous_release_id: str | None
    published_at: str | None
    policy_version: str | None
    audit_ref: str | None
    canonical_sha256: str | None
    lifecycle_state: LifecycleState = LifecycleState.PUBLISHED
    rollback_eligible: bool = True


@dataclass(frozen=True)
class ResearchRunRef:
    """Mirror of the existing H1 validation receipt/pointer (never a second authority)."""

    research_run_id: str
    hypothesis_id: str
    hypothesis_version: str
    validation_run_id: str | None
    generation_id: str | None
    dataset_snapshot_id: str | None
    knowledge_as_of: str | None
    research_state: ResearchState
    is_current: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeriesRow:
    """One market date across orthogonal fields."""

    date: str
    open: str | None
    high: str | None
    low: str | None
    close: str | None
    volume: str | None
    provider: str | None
    instrument: str | None
    quote: str | None
    available_at: str | None
    fetched_at: str | None
    source_run_id: str | None
    membership: tuple[str, ...]
    availability_state: AvailabilityState
    quality_flags: tuple[str, ...]
    revision_state: RevisionState
    render_role: RenderRole | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExcludedDate:
    date: str
    exclusion_reason: str
    quality_flags: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    marker_position: str


@dataclass(frozen=True)
class PurposeFitness:
    purpose: str
    allowed: bool
    status: str
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotContext:
    snapshot_id: str
    resolved_channel: str
    run_id: str | None
    release_id: str | None
    contract: AssetContract
    market_watermark: str | None
    input_watermarks: dict[str, Any]
    output_watermark: str | None
    requested_knowledge_as_of: str | None
    effective_knowledge_cut: str | None
    relevant_fact_sequence: int
    knowledge_mode: str
    revision_policy: str
    pit_coverage_status: str
    created_at: str | None
    certified_at: str | None
    published_at: str | None
    rendered_at: str | None
    lifecycle_state: LifecycleState
    quality_state: QualityState
    freshness_state: FreshnessState
    compatibility_state: CompatibilityState
    acquisition_state: AcquisitionState
    purpose_fitness: tuple[PurposeFitness, ...]
    artifact_refs: tuple[ArtifactRef, ...]
    findings_summary: dict[str, Any]
    excluded_dates: tuple[ExcludedDate, ...]
    reason_codes: tuple[str, ...]
    view_fingerprint: str | None = None


@dataclass(frozen=True)
class SnapshotLayer:
    """A single resolved layer inside a LayeredComparison (never a dataset)."""

    channel: str
    context: SnapshotContext
    rows: tuple[SeriesRow, ...]


@dataclass(frozen=True)
class LayeredComparison:
    """Composite comparison projection: independent layers, never merged."""

    asset_id: str
    formal: SnapshotLayer | None
    evaluated_candidate: SnapshotLayer | None
    latest_observed: SnapshotLayer | None
    reason_codes: tuple[str, ...] = ()

    def as_dataset(self):  # pragma: no cover - guard only
        from trade_py.observatory.domain.vocab import ObservatoryError, ReasonCode

        raise ObservatoryError(
            ReasonCode.COMPOSITE_NOT_DATASET,
            "composite comparison is not a dataset; select one immutable snapshot",
        )
