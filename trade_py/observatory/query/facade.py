"""Read-only query facade (WP3 backing).

Assembles serializable response payloads from the resolver, PIT resolver, and
research adapter. The FastAPI layer calls only this facade; it never joins paths,
recomputes business metrics, or updates the catalog. All values are already frozen
by the resolver (decimal strings, frozen reason codes).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from trade_py.observatory.domain.models import (
    LayeredComparison,
    SeriesRow,
    SnapshotContext,
)
from trade_py.observatory.domain.vocab import (
    Channel,
    KnowledgeMode,
    ObservatoryError,
    ReasonCode,
    RevisionPolicy,
)
from trade_py.observatory.pit.resolver import PointInTimeResolver
from trade_py.observatory.research import adapter as research_adapter
from trade_py.observatory.service import artifacts, identity
from trade_py.observatory.service.resolver import SnapshotResolver, SnapshotSelector


def _context_payload(ctx: SnapshotContext) -> dict[str, Any]:
    return {
        "snapshot_id": ctx.snapshot_id,
        "resolved_channel": ctx.resolved_channel,
        "run_id": ctx.run_id,
        "release_id": ctx.release_id,
        "contract": {
            "asset_id": ctx.contract.asset_id,
            "display_symbol": ctx.contract.display_symbol,
            "contract_version": ctx.contract.contract_version,
            "primary_provider": ctx.contract.primary_provider,
            "primary_instrument": ctx.contract.primary_instrument,
            "shadow_provider": ctx.contract.shadow_provider,
            "shadow_instrument": ctx.contract.shadow_instrument,
            "quote": ctx.contract.quote,
            "primary_interval": ctx.contract.primary_interval,
            "shadow_interval": ctx.contract.shadow_interval,
        },
        "market_watermark": ctx.market_watermark,
        "input_watermarks": ctx.input_watermarks,
        "output_watermark": ctx.output_watermark,
        "requested_knowledge_as_of": ctx.requested_knowledge_as_of,
        "effective_knowledge_cut": ctx.effective_knowledge_cut,
        "relevant_fact_sequence": ctx.relevant_fact_sequence,
        "knowledge_mode": ctx.knowledge_mode,
        "revision_policy": ctx.revision_policy,
        "pit_coverage_status": ctx.pit_coverage_status,
        "created_at": ctx.created_at,
        "certified_at": ctx.certified_at,
        "published_at": ctx.published_at,
        "rendered_at": ctx.rendered_at,
        "lifecycle_state": ctx.lifecycle_state.value,
        "quality_state": ctx.quality_state.value,
        "freshness_state": ctx.freshness_state.value,
        "compatibility_state": ctx.compatibility_state.value,
        "acquisition_state": ctx.acquisition_state.value,
        "purpose_fitness": [
            {
                "purpose": pf.purpose,
                "allowed": pf.allowed,
                "status": pf.status,
                "reason_codes": list(pf.reason_codes),
                "evidence_refs": list(pf.evidence_refs),
            }
            for pf in ctx.purpose_fitness
        ],
        "artifact_refs": [
            {"name": ref.name, "sha256": ref.sha256, "relative_path": ref.relative_path}
            for ref in ctx.artifact_refs
        ],
        "findings_summary": ctx.findings_summary,
        "excluded_dates": [
            {
                "date": e.date,
                "exclusion_reason": e.exclusion_reason,
                "quality_flags": list(e.quality_flags),
                "evidence_refs": list(e.evidence_refs),
                "marker_position": e.marker_position,
            }
            for e in ctx.excluded_dates
        ],
        "reason_codes": list(ctx.reason_codes),
    }


def _row_payload(row: SeriesRow) -> dict[str, Any]:
    return {
        "date": row.date,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "volume": row.volume,
        "provider": row.provider,
        "instrument": row.instrument,
        "quote": row.quote,
        "available_at": row.available_at,
        "fetched_at": row.fetched_at,
        "source_run_id": row.source_run_id,
        "membership": list(row.membership),
        "availability_state": row.availability_state.value,
        "quality_flags": list(row.quality_flags),
        "revision_state": row.revision_state.value,
        "render_role": row.render_role.value if row.render_role else None,
        "metrics": row.metrics,
    }


class ObservatoryQuery:
    """Facade over the read-only resolvers for the API layer."""

    def __init__(self, data_root: str | Path) -> None:
        self.data_root = Path(data_root)

    # -- selector construction ----------------------------------------------

    @staticmethod
    def _selector(
        *,
        channel: str = "observed",
        knowledge_as_of: str | None = None,
        knowledge_mode: str = "installation_observed",
        revision_policy: str = "as_known",
        run_id: str | None = None,
        release_id: str | None = None,
        snapshot_id: str | None = None,
        include_quarantined: bool = False,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> SnapshotSelector:
        try:
            return SnapshotSelector(
                channel=Channel(channel),
                knowledge_as_of=(None if knowledge_as_of in (None, "latest") else knowledge_as_of),
                knowledge_mode=KnowledgeMode(knowledge_mode),
                revision_policy=RevisionPolicy(revision_policy),
                exact_run_id=run_id,
                exact_release_id=release_id,
                snapshot_id=snapshot_id,
                include_quarantined=include_quarantined,
                date_from=date_from,
                date_to=date_to,
            )
        except ValueError as exc:
            raise ObservatoryError(ReasonCode.INVALID_SNAPSHOT_SELECTOR, str(exc)) from exc

    # -- endpoints -----------------------------------------------------------

    def context(self, **kwargs) -> dict[str, Any]:
        pit = PointInTimeResolver(self.data_root)
        selector = self._selector(**kwargs)
        # context does 0 parquet opens: catalog/manifest summary only (§20.4).
        snapshot_context = pit.resolve_context_only(selector)
        ctx = _context_payload(snapshot_context)
        vf = identity.compute_view_fingerprint(
            snapshot_id=snapshot_context.snapshot_id,
            fact_fingerprints=[snapshot_context.snapshot_id],
            date_from=selector.date_from,
            date_to=selector.date_to,
            metric_versions={"context": "v1"},
            lens="context",
            page_cursor=None,
            sort_key=None,
        )
        ctx["view_fingerprint"] = vf
        ctx["etag"] = identity.etag_for(vf)
        ctx["evidence_coverage"] = pit.evidence_report()
        ctx["semantic_channels"] = self._channel_refs(pit.coverage.asset_id)
        return ctx

    def _channel_refs(self, asset_id: str) -> dict[str, Any]:
        resolver = SnapshotResolver(self.data_root)
        refs: dict[str, Any] = {}
        for ch in (Channel.FORMAL, Channel.EVALUATED_CANDIDATE, Channel.OBSERVED):
            try:
                run, release, _ = resolver.resolve_run(SnapshotSelector(channel=ch))
                refs[ch.value] = {
                    "run_id": run.run_id,
                    "watermark": run.market_watermark,
                    "release_id": release.release_id if release else None,
                }
            except ObservatoryError as exc:
                refs[ch.value] = {"reason_codes": [exc.reason_code.value]}
        return refs

    def series(self, *, view: str = "composite", **kwargs) -> dict[str, Any]:
        if view == "composite":
            selector = self._selector(**kwargs)
            resolver = SnapshotResolver(self.data_root)
            comparison = resolver.resolve_composite(selector)
            payload = self._composite_payload(comparison)
            vf = identity.compute_view_fingerprint(
                snapshot_id=payload["fingerprint_basis"],
                fact_fingerprints=[payload["fingerprint_basis"]],
                date_from=selector.date_from,
                date_to=selector.date_to,
                metric_versions={"series": "v1"},
                lens="composite",
                page_cursor=None,
                sort_key="date",
            )
            payload["view_fingerprint"] = vf
            payload["etag"] = identity.etag_for(vf)
            return payload
        # Single-snapshot series.
        pit = PointInTimeResolver(self.data_root)
        selector = self._selector(channel=view, **kwargs)
        result = pit.resolve(selector)
        rows = [_row_payload(r) for r in result.rows]
        vf = identity.compute_view_fingerprint(
            snapshot_id=result.context.snapshot_id,
            fact_fingerprints=[result.context.snapshot_id],
            date_from=selector.date_from,
            date_to=selector.date_to,
            metric_versions={"series": "v1"},
            lens=view,
            page_cursor=None,
            sort_key="date",
        )
        return {
            "view": view,
            "context": _context_payload(result.context),
            "rows": rows,
            "pit_valid": result.pit_valid,
            "reason_codes": list(result.reason_codes),
            "view_fingerprint": vf,
            "etag": identity.etag_for(vf),
        }

    def _composite_payload(self, comparison: LayeredComparison) -> dict[str, Any]:
        def layer(layer_obj):
            if layer_obj is None:
                return None
            return {
                "channel": layer_obj.channel,
                "context": _context_payload(layer_obj.context),
                "rows": [_row_payload(r) for r in layer_obj.rows],
            }

        basis_parts = [
            l.context.snapshot_id
            for l in (comparison.formal, comparison.evaluated_candidate, comparison.latest_observed)
            if l is not None
        ]
        import hashlib

        basis = hashlib.sha256("|".join(sorted(basis_parts)).encode()).hexdigest()
        return {
            "view": "composite",
            "asset_id": comparison.asset_id,
            "layers": {
                "formal": layer(comparison.formal),
                "evaluated_candidate": layer(comparison.evaluated_candidate),
                "latest_observed": layer(comparison.latest_observed),
            },
            "reason_codes": list(comparison.reason_codes),
            "fingerprint_basis": basis,
        }

    def date_evidence(self, market_date: str, *, snapshot_id: str | None = None, channel: str = "formal") -> dict[str, Any]:
        resolver = SnapshotResolver(self.data_root)
        selector = self._selector(channel=channel, snapshot_id=snapshot_id)
        context, rows = resolver.resolve_series(selector)
        row = next((r for r in rows if r.date == market_date), None)
        run_id = context.run_id
        # Read reconciliation + revisions for the date (evidence, not recompute).
        recon = self._date_from_frame(run_id, "reconciliation", market_date)
        rev = self._date_from_frame(run_id, "revisions", market_date)
        return {
            "date": market_date,
            "snapshot_id": context.snapshot_id,
            "run_id": run_id,
            "ohlcv": _row_payload(row) if row else None,
            "reconciliation": recon,
            "revision": rev,
            "run_lineage": [run_id],
            "research_visibility": "not_visible",  # Observe never shows future outcome
            "reason_codes": [] if row else [ReasonCode.SNAPSHOT_NOT_FOUND.value],
        }

    def _date_from_frame(self, run_id: str | None, name: str, market_date: str) -> dict[str, Any] | None:
        if run_id is None:
            return None
        try:
            frame = artifacts.read_artifact_frame(self.data_root, run_id, name)
        except ObservatoryError:
            return None
        import pandas as pd

        if "date" not in frame.columns:
            return None
        mask = frame["date"].astype(str).str.startswith(market_date)
        sel = frame.loc[mask]
        if sel.empty:
            return None
        record = sel.iloc[0].to_dict()
        return {k: (None if pd.isna(v) else str(v)) for k, v in record.items()}

    def trust(self, *, snapshot_id: str | None = None, channel: str = "formal") -> dict[str, Any]:
        resolver = SnapshotResolver(self.data_root)
        selector = self._selector(channel=channel, snapshot_id=snapshot_id)
        context = resolver.resolve_context(selector)
        run = resolver.catalog.runs[context.run_id]
        return {
            "snapshot_id": context.snapshot_id,
            "run_id": context.run_id,
            "gates": [
                {
                    "gate": g.get("gate"),
                    "status": g.get("status"),
                    "reason_code": g.get("reason_code"),
                    "detail": g.get("detail"),
                    "metrics": g.get("metrics"),
                }
                for g in run.gates
            ],
            "findings": [
                {
                    "finding_id": f.finding_id,
                    "gate": f.gate,
                    "severity": f.severity,
                    "reason_code": f.reason_code,
                    "affected_dates": list(f.affected_dates),
                    "evidence_refs": list(f.evidence_refs),
                }
                for f in run.findings
            ],
            "acquisition_state": run.acquisition_state.value,
            "quality_state": run.quality_state.value,
        }

    def runs(self, *, cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
        resolver = SnapshotResolver(self.data_root)
        # Deterministic order: created_at desc, run_id tie-break.
        ordered = sorted(
            resolver.catalog.runs.values(),
            key=lambda r: (r.created_at or "", r.run_id),
            reverse=True,
        )
        start = 0
        if cursor:
            ids = [r.run_id for r in ordered]
            if cursor in ids:
                start = ids.index(cursor) + 1
        page = ordered[start : start + limit]
        next_cursor = page[-1].run_id if len(page) == limit and (start + limit) < len(ordered) else None
        return {
            "runs": [
                {
                    "run_id": r.run_id,
                    "created_at": r.created_at,
                    "market_watermark": r.market_watermark,
                    "data_readiness": r.data_readiness,
                    "quality_state": r.quality_state.value,
                    "lifecycle_state": r.lifecycle_state.value,
                    "canonical_rows": r.canonical_rows,
                }
                for r in page
            ],
            "next_cursor": next_cursor,
            "catalog_fingerprint": resolver.catalog.source_fingerprint,
        }

    def run_detail(self, run_id: str) -> dict[str, Any]:
        # Strict boundary validation (path traversal).
        artifacts.run_dir(self.data_root, run_id)
        resolver = SnapshotResolver(self.data_root)
        run = resolver.catalog.runs.get(run_id)
        if run is None:
            raise ObservatoryError(ReasonCode.SNAPSHOT_NOT_FOUND, "run not found")
        return {
            "run_id": run.run_id,
            "created_at": run.created_at,
            "market_watermark": run.market_watermark,
            "data_readiness": run.data_readiness,
            "quality_state": run.quality_state.value,
            "lifecycle_state": run.lifecycle_state.value,
            "acquisition_state": run.acquisition_state.value,
            "canonical_rows": run.canonical_rows,
            "code_revision": run.code_revision,
            "artifact_refs": [
                {"name": ref.name, "sha256": ref.sha256} for ref in run.artifact_refs
            ],
            "gates": [dict(g) for g in run.gates],
        }

    def run_diff(self, base: str, compare: str) -> dict[str, Any]:
        from trade_py.observatory.query.diff import diff_runs

        return diff_runs(self.data_root, base, compare)

    def hypotheses(self) -> dict[str, Any]:
        return {"hypotheses": research_adapter.hypotheses(self.data_root)}

    def research_run(self, research_run_id: str) -> dict[str, Any]:
        return research_adapter.get_research_run(self.data_root, research_run_id)
