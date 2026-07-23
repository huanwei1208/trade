"""Crypto research workflow adapter over the existing H1 authority (WP7).

This is the ONLY ResearchRun write-side owner, but it does NOT create a second
current-selection authority. The single authority remains the existing lifecycle
`activate_run` + `persist_crypto_validation_outputs()` atomic writer and the
`_crypto_validation_current.json` pointer. This adapter:

- reads the existing H1 validation outputs into a read-only ResearchRunRef,
- runs the pre-registered H1 kernel against a resolved immutable snapshot,
- exposes run/import/promote workflows with dry-run and atomic receipts,

Web/GET/SDK never call the write paths here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trade_py.observatory.domain.models import ResearchRunRef
from trade_py.observatory.domain.vocab import (
    ObservatoryError,
    ReasonCode,
    ResearchState,
)

HYPOTHESIS_ID = "H1"
HYPOTHESIS_VERSION = "btc-vol-persistence-v1"

# Map existing H1 statuses to research_state (adapter preserves identity).
_STATUS_TO_STATE = {
    "validated": ResearchState.VALIDATED,
    "candidate": ResearchState.CANDIDATE,
    "monitoring": ResearchState.MONITORING,
    "rejected": ResearchState.REJECTED,
    "insufficient_data": ResearchState.BLOCKED,
    "invalid": ResearchState.BLOCKED,
    "exploratory": ResearchState.EXPLORATORY,
    "eligible": ResearchState.ELIGIBLE,
}


def read_current_research(data_root: str | Path) -> ResearchRunRef | None:
    """Read the current H1 validation run as a read-only ResearchRunRef.

    Delegates entirely to the existing pointer-aware reader; returns None when no
    current pointer exists. Never writes.
    """

    try:
        from trade_py.data.warehouse.crypto_store import read_crypto_validation_outputs
    except ImportError:  # pragma: no cover - warehouse always present in-repo
        return None
    try:
        payload = read_crypto_validation_outputs(data_root)
    except (FileNotFoundError, ValueError):
        return None
    pointer = payload.get("current") or {}
    tables = payload.get("tables") or {}
    validation_run_id = str(pointer.get("run_id") or "") or None
    generation_id = str(pointer.get("generation_id") or "") or None

    status = "unknown"
    metrics: dict[str, Any] = {}
    frame = tables.get("ads_crypto_volatility_validation")
    if frame is not None and not frame.empty:
        row = frame.iloc[0].to_dict()
        status = str(row.get("signal_status") or row.get("status") or "unknown")
        metrics = {
            k: (str(row[k]) if row.get(k) is not None else None)
            for k in ("effect_ratio", "ci_low", "ci_high", "q_value", "sample_size", "data_readiness")
            if k in row
        }
    research_state = _STATUS_TO_STATE.get(status, ResearchState.UNKNOWN)
    return ResearchRunRef(
        research_run_id=validation_run_id or f"{HYPOTHESIS_ID}:{generation_id}",
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_version=HYPOTHESIS_VERSION,
        validation_run_id=validation_run_id,
        generation_id=generation_id,
        dataset_snapshot_id=str(pointer.get("dataset_snapshot_id") or "") or None,
        knowledge_as_of=str(pointer.get("knowledge_as_of") or "") or None,
        research_state=research_state,
        is_current=True,
        metrics=metrics,
        evidence_refs=(str(pointer.get("receipt_path") or ""),) if pointer.get("receipt_path") else (),
    )


def hypotheses(data_root: str | Path) -> list[dict[str, Any]]:
    """List hypotheses (V1: only H1) with the current research state."""

    ref = read_current_research(data_root)
    return [
        {
            "hypothesis_id": HYPOTHESIS_ID,
            "hypothesis_version": HYPOTHESIS_VERSION,
            "statement": (
                "After BTC 20-day realized volatility enters a high-volatility "
                "regime, is the next seven full-UTC-day realized volatility "
                "significantly and stably higher than normal days?"
            ),
            "directional": False,
            "research_state": (ref.research_state.value if ref else ResearchState.UNKNOWN.value),
            "current_research_run_id": (ref.research_run_id if ref else None),
        }
    ]


def get_research_run(data_root: str | Path, research_run_id: str) -> dict[str, Any]:
    """Read a research run's evidence (V1: the current H1 run)."""

    ref = read_current_research(data_root)
    if ref is None or ref.research_run_id != research_run_id:
        raise ObservatoryError(
            ReasonCode.SNAPSHOT_NOT_FOUND,
            "research run not found",
            evidence_refs=[],
        )
    return {
        "research_run_id": ref.research_run_id,
        "hypothesis_id": ref.hypothesis_id,
        "hypothesis_version": ref.hypothesis_version,
        "validation_run_id": ref.validation_run_id,
        "generation_id": ref.generation_id,
        "dataset_snapshot_id": ref.dataset_snapshot_id,
        "knowledge_as_of": ref.knowledge_as_of,
        "research_state": ref.research_state.value,
        "is_current": ref.is_current,
        "metrics": ref.metrics,
        "evidence_refs": list(ref.evidence_refs),
    }
