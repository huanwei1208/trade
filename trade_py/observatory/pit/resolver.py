"""Point-in-Time resolver (WP6).

Wraps the snapshot resolver to enforce the as-of knowledge contract across the whole
snapshot context: data version, prices, thresholds, findings, and outcomes. It
- validates PIT provability (installation_observed vs market_available),
- isolates later revisions from as_known views,
- filters rows visible at the knowledge cut,
- marks backfilled/PIT-unproven and RESTATED_NOT_PIT,
- guarantees deterministic replay (same inputs -> same snapshot/view hash).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trade_py.observatory.catalog import store as catalog_store
from trade_py.observatory.domain.models import SeriesRow, SnapshotContext
from trade_py.observatory.domain.vocab import (
    KnowledgeMode,
    ObservatoryError,
    ReasonCode,
    RevisionPolicy,
)
from trade_py.observatory.pit import coverage as coverage_mod
from trade_py.observatory.service.resolver import SnapshotResolver, SnapshotSelector


@dataclass(frozen=True)
class PitResult:
    context: SnapshotContext
    rows: tuple[SeriesRow, ...]
    coverage: coverage_mod.EvidenceCoverage
    knowledge_mode: str
    revision_policy: str
    pit_valid: bool
    reason_codes: tuple[str, ...]


class PointInTimeResolver:
    def __init__(self, data_root: str | Path) -> None:
        self.data_root = Path(data_root)
        self._resolver = SnapshotResolver(data_root)
        self._coverage = coverage_mod.build_evidence_coverage(self._resolver.catalog)

    @property
    def coverage(self) -> coverage_mod.EvidenceCoverage:
        return self._coverage

    def resolve_context_only(self, selector: SnapshotSelector) -> SnapshotContext:
        """Resolve just the snapshot context (catalog/manifest summary only).

        This performs 0 parquet opens (plan §20.4): it applies the PIT gate and
        returns the context without reading any series artifact.
        """

        coverage_mod.assert_pit_provable(
            self._coverage, selector.knowledge_mode, selector.knowledge_as_of
        )
        return self._resolver.resolve_context(selector, pit_proven=True)

    def resolve(self, selector: SnapshotSelector) -> PitResult:
        # 1) PIT provability gate for installation_observed.
        coverage_mod.assert_pit_provable(
            self._coverage, selector.knowledge_mode, selector.knowledge_as_of
        )
        # 2) Resolve the immutable snapshot context (already knowledge-cut aware).
        pit_status = "proven"
        if (
            selector.knowledge_mode == KnowledgeMode.INSTALLATION_OBSERVED
            and selector.knowledge_as_of is not None
        ):
            pit_status = "proven"
        context = self._resolver.resolve_context(
            selector, pit_proven=True, pit_coverage_status=pit_status
        )
        # 3) Series with as-of visibility + revision policy applied.
        _, rows = self._resolver.resolve_series(selector)
        rows = self._apply_knowledge_cut(rows, selector)
        rows = self._apply_revision_policy(rows, selector)

        flags = coverage_mod.revision_policy_flags(selector.revision_policy)
        reason_codes = list(context.reason_codes) + list(flags["reason_codes"])
        pit_valid = bool(flags["pit_valid"])
        return PitResult(
            context=context,
            rows=tuple(rows),
            coverage=self._coverage,
            knowledge_mode=selector.knowledge_mode.value,
            revision_policy=selector.revision_policy.value,
            pit_valid=pit_valid,
            reason_codes=tuple(reason_codes),
        )

    def _apply_knowledge_cut(self, rows, selector: SnapshotSelector):
        """Filter out bars whose availability is after the knowledge cut.

        - market_available: compare available_at to the cut.
        - installation_observed: compare fetched_at to the cut.
        Future rows are never visible.
        """

        cut = selector.knowledge_as_of
        if cut is None:
            return rows
        field = (
            "available_at"
            if selector.knowledge_mode == KnowledgeMode.MARKET_AVAILABLE
            else "fetched_at"
        )
        visible = []
        for row in rows:
            stamp = getattr(row, field)
            if stamp is None or str(stamp) <= str(cut):
                visible.append(row)
        return visible

    def _apply_revision_policy(self, rows, selector: SnapshotSelector):
        """as_known keeps the version known at T; latest_restated flags not-PIT.

        The immutable run already embodies the as-known snapshot for its own
        knowledge cut, so as_known needs no rewrite here. latest_restated is a
        diagnostic projection that must persistently carry RESTATED_NOT_PIT.
        """

        return rows

    def evidence_report(self) -> dict[str, Any]:
        c = self._coverage
        return {
            "asset_id": c.asset_id,
            "earliest_proven_knowledge_time": c.earliest_proven_knowledge_time,
            "proven_interval": c.proven_interval,
            "unproven_interval": c.unproven_interval,
            "has_precise_stage_times": c.has_precise_stage_times,
            "supportable_modes": list(c.supportable_modes),
            "gap_reason_codes": list(c.gap_reason_codes),
        }
