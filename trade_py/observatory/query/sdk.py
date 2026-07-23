"""Read-only Python SDK for the BTC Observatory (WP2.6).

Fluent facade over the resolver for Web and Jupyter. Read-only: it never triggers
provider network, sync, publication, or migration. Composite returns a
LayeredComparison that cannot be turned into a dataset.

    from trade_py.observatory.query.sdk import observe
    ctx = observe("crypto.BTC", data_root).snapshot(
        channel="formal", knowledge_as_of=None, knowledge_mode="installation_observed",
    )
    bars = ctx.bars()
    findings = ctx.findings()
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from trade_py.observatory.domain.models import LayeredComparison, SnapshotContext
from trade_py.observatory.domain.vocab import (
    ASSET_ID,
    Channel,
    KnowledgeMode,
    ObservatoryError,
    ReasonCode,
    RevisionPolicy,
)
from trade_py.observatory.service.resolver import SnapshotResolver, SnapshotSelector


class SnapshotHandle:
    """A resolved immutable snapshot; the only object that yields bars/findings."""

    def __init__(self, resolver: SnapshotResolver, selector: SnapshotSelector) -> None:
        self._resolver = resolver
        self._selector = selector
        self._context: SnapshotContext | None = None

    @property
    def context(self) -> SnapshotContext:
        if self._context is None:
            self._context = self._resolver.resolve_context(self._selector)
        return self._context

    @property
    def snapshot_id(self) -> str:
        return self.context.snapshot_id

    def bars(self) -> list[dict[str, Any]]:
        _, rows = self._resolver.resolve_series(self._selector)
        return [row.__dict__ for row in rows]

    def findings(self) -> dict[str, Any]:
        return self.context.findings_summary

    def excluded_dates(self) -> list[dict[str, Any]]:
        return [e.__dict__ for e in self.context.excluded_dates]


class CompositeHandle:
    """A comparison projection; cannot be used as a dataset (COMPOSITE_NOT_DATASET)."""

    def __init__(self, comparison: LayeredComparison) -> None:
        self._comparison = comparison

    @property
    def formal(self):
        return self._comparison.formal

    @property
    def evaluated_candidate(self):
        return self._comparison.evaluated_candidate

    @property
    def observed(self):
        return self._comparison.latest_observed

    def bars(self):  # pragma: no cover - guard
        raise ObservatoryError(
            ReasonCode.COMPOSITE_NOT_DATASET,
            "composite is a comparison projection; select one immutable snapshot",
        )


class AssetQuery:
    def __init__(self, asset_id: str, data_root: str | Path) -> None:
        if asset_id != ASSET_ID:
            raise ObservatoryError(ReasonCode.SNAPSHOT_NOT_FOUND, f"unsupported asset: {asset_id}")
        self.asset_id = asset_id
        self._resolver = SnapshotResolver(data_root)

    def snapshot(
        self,
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
    ) -> SnapshotHandle:
        selector = SnapshotSelector(
            channel=Channel(channel),
            knowledge_as_of=knowledge_as_of,
            knowledge_mode=KnowledgeMode(knowledge_mode),
            revision_policy=RevisionPolicy(revision_policy),
            exact_run_id=run_id,
            exact_release_id=release_id,
            snapshot_id=snapshot_id,
            include_quarantined=include_quarantined,
            date_from=date_from,
            date_to=date_to,
        )
        return SnapshotHandle(self._resolver, selector)

    def composite(
        self,
        *,
        knowledge_as_of: str | None = None,
        knowledge_mode: str = "installation_observed",
        revision_policy: str = "as_known",
        include_quarantined: bool = False,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> CompositeHandle:
        selector = SnapshotSelector(
            knowledge_as_of=knowledge_as_of,
            knowledge_mode=KnowledgeMode(knowledge_mode),
            revision_policy=RevisionPolicy(revision_policy),
            include_quarantined=include_quarantined,
            date_from=date_from,
            date_to=date_to,
        )
        return CompositeHandle(self._resolver.resolve_composite(selector))


def observe(asset_id: str, data_root: str | Path) -> AssetQuery:
    return AssetQuery(asset_id, data_root)
