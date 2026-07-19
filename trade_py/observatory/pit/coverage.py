"""Point-in-Time evidence coverage and resolution (WP6).

Implements the four-clocks / knowledge-mode contract (plan §6). Two knowledge modes:

- market_available: judged by available_at (when the market could theoretically
  know); historical backfill may participate but is flagged backfilled.
- installation_observed: judged by first_seen_at/fetched_at (what THIS installation
  actually captured); before earliest_proven_knowledge_time it returns
  PIT_NOT_PROVEN.

Never uses filesystem mtime, today's manifest, or guessed times to fabricate
history. Deterministic under frozen fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trade_py.observatory.catalog.projection import Catalog
from trade_py.observatory.domain.vocab import (
    KnowledgeMode,
    ObservatoryError,
    ReasonCode,
    RevisionPolicy,
)


@dataclass(frozen=True)
class EvidenceCoverage:
    asset_id: str
    earliest_proven_knowledge_time: str | None
    proven_interval: str
    partial_interval: str
    unproven_interval: str
    has_precise_stage_times: bool
    supportable_modes: tuple[str, ...]
    gap_reason_codes: tuple[str, ...]

    def supports(self, knowledge_mode: KnowledgeMode, knowledge_as_of: str | None) -> bool:
        """Whether installation-observed PIT is provable at the given cut."""

        if knowledge_mode == KnowledgeMode.MARKET_AVAILABLE:
            return True
        # installation_observed: latest is always provable (we know what we have now).
        if knowledge_as_of is None:
            return True
        if self.earliest_proven_knowledge_time is None:
            return False
        return str(knowledge_as_of) >= str(self.earliest_proven_knowledge_time)


def build_evidence_coverage(catalog: Catalog) -> EvidenceCoverage:
    created = sorted(r.created_at for r in catalog.runs.values() if r.created_at)
    earliest = created[0] if created else None
    has_precise = any(
        r.staged_at is not None and not r.staged_at.unproven for r in catalog.runs.values()
    )
    supportable = ["market_available"]
    if earliest:
        supportable.append("installation_observed_from_earliest_proven")
    gaps: list[str] = []
    if not has_precise:
        gaps.append(ReasonCode.LEGACY_TIME_UNPROVEN.value)
    if earliest:
        gaps.append("PIT_NOT_PROVEN_BEFORE_EARLIEST_RECEIPT")
    return EvidenceCoverage(
        asset_id="crypto.BTC",
        earliest_proven_knowledge_time=earliest,
        proven_interval=f">= {earliest}" if earliest else "none",
        partial_interval="none" if has_precise else "none (no precise stage receipts)",
        unproven_interval=f"< {earliest} for installation_observed" if earliest else "all",
        has_precise_stage_times=has_precise,
        supportable_modes=tuple(supportable),
        gap_reason_codes=tuple(gaps),
    )


def assert_pit_provable(
    coverage: EvidenceCoverage,
    knowledge_mode: KnowledgeMode,
    knowledge_as_of: str | None,
) -> None:
    """Raise PIT_NOT_PROVEN if installation-observed history cannot be proven."""

    if coverage.supports(knowledge_mode, knowledge_as_of):
        return
    raise ObservatoryError(
        ReasonCode.PIT_NOT_PROVEN,
        "installation-observed knowledge is not proven before earliest receipt",
        retryable=False,
        extra={
            "coverage_interval": {
                "earliest_proven_knowledge_time": coverage.earliest_proven_knowledge_time,
                "proven": coverage.proven_interval,
                "unproven": coverage.unproven_interval,
            },
            "requested_knowledge_as_of": knowledge_as_of,
        },
    )


def revision_policy_flags(policy: RevisionPolicy) -> dict[str, Any]:
    """Flags that must persist on responses (RESTATED_NOT_PIT for latest_restated)."""

    if policy == RevisionPolicy.LATEST_RESTATED:
        return {
            "revision_policy": policy.value,
            "reason_codes": [ReasonCode.RESTATED_NOT_PIT.value],
            "pit_valid": False,
        }
    return {"revision_policy": policy.value, "reason_codes": [], "pit_valid": True}
