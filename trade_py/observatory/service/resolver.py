"""Snapshot Resolver (WP2) — the single owner of channel resolution.

Resolves the three orthogonal dimensions (lifecycle channel, knowledge cut,
revision policy) into an immutable snapshot context and series, and builds the
layered composite comparison. All reads go through the checked catalog load, verify
artifact hashes, and fail closed. `latest` freezes at request start.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from trade_py.observatory.catalog import store as catalog_store
from trade_py.observatory.catalog.projection import Catalog
from trade_py.observatory.domain import state_mapping
from trade_py.observatory.domain.models import (
    ExcludedDate,
    LayeredComparison,
    ObservationRun,
    Release,
    SeriesRow,
    SnapshotContext,
    SnapshotLayer,
)
from trade_py.observatory.domain.vocab import (
    AvailabilityState,
    Channel,
    CompatibilityState,
    KnowledgeMode,
    LifecycleState,
    ObservatoryError,
    QualityState,
    ReasonCode,
    RenderRole,
    RevisionPolicy,
    RevisionState,
)
from trade_py.observatory.service import artifacts, identity
from trade_py.observatory.service.purpose_fitness import evaluate_purpose_fitness


@dataclass(frozen=True)
class SnapshotSelector:
    """Orthogonal selector (WP0 §6/§7)."""

    channel: Channel = Channel.OBSERVED
    knowledge_as_of: str | None = None  # None == latest
    knowledge_mode: KnowledgeMode = KnowledgeMode.INSTALLATION_OBSERVED
    revision_policy: RevisionPolicy = RevisionPolicy.AS_KNOWN
    exact_run_id: str | None = None
    exact_release_id: str | None = None
    snapshot_id: str | None = None
    include_quarantined: bool = False
    date_from: str | None = None
    date_to: str | None = None

    def validate(self) -> None:
        # snapshot_id fixes all identity; conflicts are illegal.
        if self.snapshot_id and (self.exact_run_id or self.exact_release_id):
            raise ObservatoryError(
                ReasonCode.INVALID_SNAPSHOT_SELECTOR,
                "snapshot_id conflicts with exact run/release",
            )
        if self.exact_run_id and self.exact_release_id:
            raise ObservatoryError(
                ReasonCode.INVALID_SNAPSHOT_SELECTOR,
                "exact run_id conflicts with release_id",
            )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _visible_before(value: str | None, cut: str | None) -> bool:
    """True if a timestamp is at or before the knowledge cut (or cut is latest)."""

    if cut is None or value is None:
        return True
    return str(value) <= str(cut)


class SnapshotResolver:
    """Resolve semantic channels to immutable snapshots (read-only)."""

    def __init__(self, data_root: str | Path, *, catalog: Catalog | None = None) -> None:
        self.data_root = Path(data_root)
        # Loading through the checked path fails closed if the catalog is stale.
        self._catalog = catalog if catalog is not None else catalog_store.load_catalog_checked(data_root)

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    # -- eligibility helpers -------------------------------------------------

    def _runs_visible(self, cut: str | None, mode: KnowledgeMode) -> list[ObservationRun]:
        # installation_observed: a run did not exist before it was created.
        # market_available: the run is a container; bars are filtered by available_at
        # downstream, so backfilled (later-created) runs legitimately reconstruct
        # market-available history and are not gated by created_at.
        if mode == KnowledgeMode.MARKET_AVAILABLE:
            return list(self._catalog.runs.values())
        return [r for r in self._catalog.runs.values() if _visible_before(r.created_at, cut)]

    def _eligible_observed(self, cut: str | None, mode: KnowledgeMode) -> list[ObservationRun]:
        eligible = []
        for run in self._runs_visible(cut, mode):
            if run.has_d0_blocker:
                continue
            if not run.has_primary_canonical or not run.has_final_bar:
                continue
            if run.market_watermark is None:
                continue
            eligible.append(run)
        eligible.sort(key=lambda r: r.order_key_observed(), reverse=True)
        return eligible

    def _eligible_candidates(self, cut: str | None, mode: KnowledgeMode) -> list[ObservationRun]:
        # Any evaluated (has gates) staged run, newest evaluation first.
        evaluated = [r for r in self._runs_visible(cut, mode) if r.gates]
        evaluated.sort(key=lambda r: r.order_key_candidate(), reverse=True)
        return evaluated

    def _active_release(self, cut: str | None, mode: KnowledgeMode = KnowledgeMode.INSTALLATION_OBSERVED) -> Release | None:
        if mode == KnowledgeMode.MARKET_AVAILABLE:
            visible = list(self._catalog.releases)
        else:
            visible = [r for r in self._catalog.releases if _visible_before(r.published_at, cut)]
        if not visible:
            return None
        # Ledger order already applied; last visible publish that is not rolled back.
        active: Release | None = None
        for rel in visible:
            if rel.lifecycle_state == LifecycleState.ROLLED_BACK:
                active = None
                continue
            active = rel
        return active

    # -- channel resolution --------------------------------------------------

    def resolve_run(self, selector: SnapshotSelector) -> tuple[ObservationRun, Release | None, str]:
        """Resolve the selector to a single ObservationRun and its channel label."""

        selector.validate()
        cut = selector.knowledge_as_of  # None == latest (frozen at request start)
        mode = selector.knowledge_mode

        if selector.exact_run_id:
            run = self._catalog.runs.get(selector.exact_run_id)
            if run is None:
                raise ObservatoryError(ReasonCode.SNAPSHOT_NOT_FOUND, "run not found")
            if mode == KnowledgeMode.INSTALLATION_OBSERVED and not _visible_before(run.created_at, cut):
                raise ObservatoryError(ReasonCode.SNAPSHOT_NOT_FOUND, "run not visible at knowledge cut")
            return run, None, Channel.EXACT.value

        if selector.exact_release_id:
            rel = next((r for r in self._catalog.releases if r.release_id == selector.exact_release_id), None)
            if rel is None:
                raise ObservatoryError(ReasonCode.SNAPSHOT_NOT_FOUND, "release not found")
            run = self._catalog.runs.get(rel.run_id)
            if run is None:
                raise ObservatoryError(ReasonCode.MANIFEST_INVALID, "release run missing")
            return run, rel, Channel.EXACT.value

        if selector.channel == Channel.FORMAL:
            rel = self._active_release(cut, mode)
            if rel is None:
                raise ObservatoryError(ReasonCode.CHANNEL_UNAVAILABLE, "no active formal release")
            run = self._catalog.runs.get(rel.run_id)
            if run is None:
                raise ObservatoryError(ReasonCode.MANIFEST_INVALID, "formal release run missing")
            return run, rel, Channel.FORMAL.value

        if selector.channel == Channel.EVALUATED_CANDIDATE:
            candidates = self._eligible_candidates(cut, mode)
            if not candidates:
                raise ObservatoryError(ReasonCode.CHANNEL_UNAVAILABLE, "no evaluated candidate")
            return candidates[0], None, Channel.EVALUATED_CANDIDATE.value

        # OBSERVED (default)
        observed = self._eligible_observed(cut, mode)
        if not observed:
            raise ObservatoryError(ReasonCode.CHANNEL_UNAVAILABLE, "no qualifying observed run")
        return observed[0], None, Channel.OBSERVED.value

    # -- context + series ----------------------------------------------------

    def _expected_latest_open(self, cut: str | None) -> str | None:
        anchor = cut or _now_iso()
        try:
            d = date.fromisoformat(str(anchor)[:10])
        except ValueError:
            return None
        from datetime import timedelta

        return (d - timedelta(days=1)).isoformat()

    def resolve_context(
        self,
        selector: SnapshotSelector,
        *,
        pit_proven: bool = True,
        pit_coverage_status: str = "proven",
    ) -> SnapshotContext:
        run, release, channel = self.resolve_run(selector)
        if selector.channel == Channel.EVALUATED_CANDIDATE and run.quality_state == QualityState.INVALID:
            # Context still returns the candidate + evidence, but rendering is blocked.
            reason_codes = (ReasonCode.QUALITY_BLOCKED.value,)
        else:
            reason_codes = ()

        cut = selector.knowledge_as_of
        expected_latest = self._expected_latest_open(cut)
        freshness = state_mapping.freshness_for(run.market_watermark, expected_latest)
        compatibility = state_mapping.compatibility_for(
            manifest_code_revision=run.code_revision,
            current_code_revision=run.code_revision,
        ) if channel == Channel.FORMAL.value else CompatibilityState.UNKNOWN

        artifact_sha = [ref.sha256 for ref in run.artifact_refs]
        snapshot_id = identity.compute_snapshot_id(
            contract_id=run.contract.asset_id,
            contract_version=run.contract.contract_version,
            run_id=run.run_id,
            release_id=release.release_id if release else None,
            artifact_sha256s=artifact_sha,
            effective_knowledge_cut=cut or self._effective_latest_cut(),
            knowledge_mode=selector.knowledge_mode.value,
            revision_policy=selector.revision_policy.value,
            include_quarantined=selector.include_quarantined,
        )

        fitness = evaluate_purpose_fitness(
            run=run,
            active_release=release if channel == Channel.FORMAL.value else self._active_release(cut, selector.knowledge_mode),
            is_formal=(channel == Channel.FORMAL.value),
            pit_proven=pit_proven,
        )

        excluded = self._excluded_dates(run)
        findings_summary = {
            "count": len(run.findings),
            "blocking_gate": run.blocking_gate,
            "blocking_reason_code": run.blocking_reason_code,
            "gates": [f.gate for f in run.findings],
        }

        return SnapshotContext(
            snapshot_id=snapshot_id,
            resolved_channel=channel,
            run_id=run.run_id,
            release_id=release.release_id if release else None,
            contract=run.contract,
            market_watermark=run.market_watermark,
            input_watermarks=run.input_watermarks,
            output_watermark=run.output_watermark,
            requested_knowledge_as_of=cut,
            effective_knowledge_cut=cut or self._effective_latest_cut(),
            relevant_fact_sequence=len(self._catalog.runs),
            knowledge_mode=selector.knowledge_mode.value,
            revision_policy=selector.revision_policy.value,
            pit_coverage_status=pit_coverage_status,
            created_at=run.created_at,
            certified_at=run.assurance_completed_at.value if run.assurance_completed_at else None,
            published_at=release.published_at if release else None,
            rendered_at=_now_iso(),
            lifecycle_state=run.lifecycle_state,
            quality_state=run.quality_state,
            freshness_state=freshness,
            compatibility_state=compatibility,
            acquisition_state=run.acquisition_state,
            purpose_fitness=fitness,
            artifact_refs=run.artifact_refs,
            findings_summary=findings_summary,
            excluded_dates=excluded,
            reason_codes=reason_codes,
        )

    def _effective_latest_cut(self) -> str | None:
        """Frozen latest cut = newest created_at across runs (asset-scoped)."""

        times = [r.created_at for r in self._catalog.runs.values() if r.created_at]
        return max(times) if times else None

    def _excluded_dates(self, run: ObservationRun) -> tuple[ExcludedDate, ...]:
        excluded: list[ExcludedDate] = []
        for finding in run.findings:
            for d in finding.affected_dates:
                excluded.append(
                    ExcludedDate(
                        date=d,
                        exclusion_reason=finding.reason_code,
                        quality_flags=("quarantined",),
                        evidence_refs=finding.evidence_refs,
                        marker_position="below",
                    )
                )
        return tuple(excluded)

    def resolve_series(self, selector: SnapshotSelector) -> tuple[SnapshotContext, tuple[SeriesRow, ...]]:
        context = self.resolve_context(selector)
        run = self._catalog.runs[context.run_id]
        if run.quality_state == QualityState.INVALID or run.has_d0_blocker:
            # Series is not renderable; context carries the evidence.
            raise ObservatoryError(
                ReasonCode.QUALITY_BLOCKED,
                "snapshot is not renderable as a canonical series",
                evidence_refs=[f"runs/btc/{run.run_id}/manifest.json"],
            )
        frame = artifacts.read_canonical(self.data_root, run.run_id, _canonical_artifact_sha(run))
        rows = _frame_to_rows(frame, run, selector)
        return context, rows

    def resolve_composite(self, selector: SnapshotSelector) -> LayeredComparison:
        """Build the independent-layer composite comparison (never a dataset)."""

        if selector.exact_run_id or selector.exact_release_id or selector.snapshot_id:
            raise ObservatoryError(
                ReasonCode.INVALID_SNAPSHOT_SELECTOR,
                "composite cannot combine with an exact snapshot/run/release",
            )
        layers: dict[str, SnapshotLayer | None] = {}
        reason_codes: list[str] = []
        for channel in (Channel.FORMAL, Channel.EVALUATED_CANDIDATE, Channel.OBSERVED):
            sub = SnapshotSelector(
                channel=channel,
                knowledge_as_of=selector.knowledge_as_of,
                knowledge_mode=selector.knowledge_mode,
                revision_policy=selector.revision_policy,
                include_quarantined=selector.include_quarantined,
                date_from=selector.date_from,
                date_to=selector.date_to,
            )
            try:
                ctx, rows = self.resolve_series(sub)
                layers[channel.value] = SnapshotLayer(channel=channel.value, context=ctx, rows=rows)
            except ObservatoryError as exc:
                # A blocked/unavailable layer keeps its context absent but records why.
                reason_codes.append(f"{channel.value}:{exc.reason_code.value}")
                layers[channel.value] = None
        composite = LayeredComparison(
            asset_id="crypto.BTC",
            formal=layers.get(Channel.FORMAL.value),
            evaluated_candidate=layers.get(Channel.EVALUATED_CANDIDATE.value),
            latest_observed=layers.get(Channel.OBSERVED.value),
            reason_codes=tuple(reason_codes),
        )
        return _assign_render_roles(composite)


def _canonical_artifact_sha(run: ObservationRun) -> str | None:
    """File-bytes SHA-256 of the canonical artifact (from artifact_hashes).

    Note: run.canonical_hash is a *logical* frame hash, not the file-bytes hash, so
    reads must verify against the artifact ref instead.
    """

    for ref in run.artifact_refs:
        if ref.name == "canonical":
            return ref.sha256
    return None


def _dec(value: Any) -> str | None:

    if value is None:
        return None
    try:
        import math

        if isinstance(value, float) and math.isnan(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _frame_to_rows(frame, run: ObservationRun, selector: SnapshotSelector) -> tuple[SeriesRow, ...]:
    import pandas as pd

    rows: list[SeriesRow] = []
    quarantined = {d for f in run.findings for d in f.affected_dates}
    for _, r in frame.iterrows():
        d = str(pd.Timestamp(r["date"]).date())
        if selector.date_from and d < selector.date_from:
            continue
        if selector.date_to and d > selector.date_to:
            continue
        is_quar = d in quarantined
        if is_quar and not selector.include_quarantined:
            # Excluded from values; still surfaced via context.excluded_dates.
            continue
        rows.append(
            SeriesRow(
                date=d,
                open=_dec(r.get("open")),
                high=_dec(r.get("high")),
                low=_dec(r.get("low")),
                close=_dec(r.get("close")),
                volume=_dec(r.get("volume")),
                provider=str(r.get("provider")) if r.get("provider") is not None else None,
                instrument=str(r.get("instrument")) if r.get("instrument") is not None else None,
                quote=str(r.get("quote_asset")) if r.get("quote_asset") is not None else None,
                available_at=_dec(r.get("available_at")),
                fetched_at=_dec(r.get("fetched_at")),
                source_run_id=str(r.get("run_id")) if r.get("run_id") is not None else run.run_id,
                membership=(run.lifecycle_state.value,),
                availability_state=AvailabilityState.PRESENT,
                quality_flags=("quarantined",) if is_quar else (),
                revision_state=RevisionState.UNCHANGED,
            )
        )
    return tuple(rows)


def _assign_render_roles(composite: LayeredComparison) -> LayeredComparison:
    """Assign render_role per row across layers (overlap vs only)."""

    def dates(layer: SnapshotLayer | None) -> set[str]:
        return {row.date for row in layer.rows} if layer else set()

    formal_dates = dates(composite.formal)
    candidate_dates = dates(composite.evaluated_candidate)

    def role_rows(layer: SnapshotLayer | None, only_role: RenderRole, overlap_role: RenderRole, ref: set[str]) -> SnapshotLayer | None:
        if layer is None:
            return None
        new_rows = tuple(
            SeriesRow(**{**row.__dict__, "render_role": overlap_role if row.date in ref else only_role})
            for row in layer.rows
        )
        return SnapshotLayer(channel=layer.channel, context=layer.context, rows=new_rows)

    formal_layer = None
    if composite.formal is not None:
        formal_layer = SnapshotLayer(
            channel=composite.formal.channel,
            context=composite.formal.context,
            rows=tuple(SeriesRow(**{**row.__dict__, "render_role": RenderRole.FORMAL_BASELINE}) for row in composite.formal.rows),
        )
    candidate_layer = role_rows(composite.evaluated_candidate, RenderRole.CANDIDATE_ONLY, RenderRole.CANDIDATE_OVERLAP, formal_dates)
    observed_layer = role_rows(composite.latest_observed, RenderRole.OBSERVED_ONLY, RenderRole.OBSERVED_OVERLAP, candidate_dates | formal_dates)

    return LayeredComparison(
        asset_id=composite.asset_id,
        formal=formal_layer,
        evaluated_candidate=candidate_layer,
        latest_observed=observed_layer,
        reason_codes=composite.reason_codes,
    )
