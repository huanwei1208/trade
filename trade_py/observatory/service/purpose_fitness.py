"""Purpose fitness policy (WP2.2 / frozen_contracts.md).

Derives purpose fitness one-directionally from resolved facts. Returns explicit
`{purpose, allowed, status, reason_codes, evidence_refs}` and never writes back to
data_readiness, release, or research lifecycle.
"""
from __future__ import annotations

from trade_py.observatory.domain.models import ObservationRun, PurposeFitness, Release
from trade_py.observatory.domain.vocab import (
    LifecycleState,
    Purpose,
    QualityState,
)


def evaluate_purpose_fitness(
    *,
    run: ObservationRun | None,
    active_release: Release | None,
    is_formal: bool,
    pit_proven: bool,
    research_validated: bool = False,
    automated_decision_authorized: bool = False,
) -> tuple[PurposeFitness, ...]:
    """Compute the five purpose-fitness verdicts from resolved facts."""

    fitness: list[PurposeFitness] = []

    has_final_bar = bool(run and run.has_final_bar and not run.has_d0_blocker)
    quality = run.quality_state if run else QualityState.UNKNOWN
    evidence: list[str] = []
    if run:
        evidence.append(f"runs/btc/{run.run_id}/manifest.json")
    if active_release:
        evidence.append(active_release.audit_ref or f"release/{active_release.release_id}")

    # manual_observation: at least a normalized final bar; warnings visible.
    if has_final_bar and quality != QualityState.INVALID:
        fitness.append(
            PurposeFitness(
                Purpose.MANUAL_OBSERVATION.value, True, "allowed",
                reason_codes=() if quality == QualityState.ASSURED else ("QUALITY_WARNINGS_VISIBLE",),
                evidence_refs=tuple(evidence),
            )
        )
    else:
        fitness.append(
            PurposeFitness(
                Purpose.MANUAL_OBSERVATION.value, False, "blocked",
                reason_codes=("QUALITY_BLOCKED" if quality == QualityState.INVALID else "CHANNEL_UNAVAILABLE",),
                evidence_refs=tuple(evidence),
            )
        )

    # exploratory_research: fixed immutable run with explicit quality state.
    if run is not None and quality != QualityState.INVALID:
        fitness.append(
            PurposeFitness(
                Purpose.EXPLORATORY_RESEARCH.value, True, "allowed",
                reason_codes=(), evidence_refs=tuple(evidence),
            )
        )
    else:
        fitness.append(
            PurposeFitness(
                Purpose.EXPLORATORY_RESEARCH.value, False, "blocked",
                reason_codes=("QUALITY_BLOCKED",), evidence_refs=tuple(evidence),
            )
        )

    # formal_system_consumption: only Published Current / Formal Baseline.
    formal_ok = bool(
        is_formal
        and active_release is not None
        and active_release.lifecycle_state == LifecycleState.PUBLISHED
        and run is not None
        and quality in {QualityState.ASSURED, QualityState.DEGRADED}
    )
    fitness.append(
        PurposeFitness(
            Purpose.FORMAL_SYSTEM_CONSUMPTION.value, formal_ok,
            "allowed" if formal_ok else "blocked",
            reason_codes=() if formal_ok else ("CHANNEL_UNAVAILABLE",),
            evidence_refs=tuple(evidence),
        )
    )

    # strict_research: fixed formal snapshot + PIT proven + assured.
    strict_ok = bool(formal_ok and pit_proven and quality == QualityState.ASSURED)
    strict_reasons: list[str] = []
    if not formal_ok:
        strict_reasons.append("CHANNEL_UNAVAILABLE")
    if not pit_proven:
        strict_reasons.append("PIT_NOT_PROVEN")
    if quality != QualityState.ASSURED:
        strict_reasons.append("RESEARCH_NOT_ELIGIBLE")
    fitness.append(
        PurposeFitness(
            Purpose.STRICT_RESEARCH.value, strict_ok,
            "allowed" if strict_ok else "blocked",
            reason_codes=tuple(strict_reasons), evidence_refs=tuple(evidence),
        )
    )

    # automated_decision: independent authorization; never auto-enabled.
    auto_ok = bool(automated_decision_authorized)
    fitness.append(
        PurposeFitness(
            Purpose.AUTOMATED_DECISION.value, auto_ok,
            "allowed" if auto_ok else "blocked",
            reason_codes=() if auto_ok else ("RESEARCH_NOT_ELIGIBLE",),
            evidence_refs=tuple(evidence),
        )
    )

    return tuple(fitness)
