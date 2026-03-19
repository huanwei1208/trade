"""Daily evaluation orchestrator.

Coordinates source / event / model / gate evaluation passes, then writes the
QualityReport (including 7-component Trust vector).

Public API (re-exported for backward compatibility):
    evaluate_daily, evaluate_sources, evaluate_events, evaluate_models,
    evaluate_gate, resolve_eval_date, EvalOutcome
"""
from __future__ import annotations

import logging

from trade_py.db.trade_db import TradeDB
from trade_py.infra.settings import default_data_root

# Re-export everything callers may have imported directly from this module.
from trade_py.evaluation.utils import (  # noqa: F401
    EvalOutcome,
    RECENT_OPERATIONAL_DAYS,
    MATURED_RESEARCH_DAYS,
    LABEL_SETTLE_DAYS,
    MIN_SOURCE_IC_LOOKBACK_DAYS,
    _cached_source_outcome,
    _cached_event_outcome,
    _cached_model_outcome,
    _cached_gate_outcome,
    resolve_eval_date,
    _resolve_window,
    _resolve_matured_window,
    _cache_fingerprint,
    _fingerprint_matches,
    _safe_float,
    _safe_int,
)
from trade_py.evaluation.sources import evaluate_sources  # noqa: F401
from trade_py.evaluation.events import evaluate_events  # noqa: F401
from trade_py.evaluation.models import evaluate_models, _dataset_snapshot  # noqa: F401
from trade_py.evaluation.gate import evaluate_gate  # noqa: F401
from trade_py.evaluation.trust import write_quality_report  # noqa: F401

logger = logging.getLogger(__name__)


def evaluate_daily(data_root: str = str(default_data_root()),
                   eval_date: str | None = None,
                   lookback_days: int = 30,
                   use_cache: bool = True) -> EvalOutcome:
    target_date = resolve_eval_date(data_root, eval_date)
    recent_start, recent_end = _resolve_window(target_date, RECENT_OPERATIONAL_DAYS)
    research_start, research_end = _resolve_matured_window(target_date)
    cache_fp = _cache_fingerprint(data_root, target_date, recent_start, recent_end, research_start, research_end)
    db = TradeDB(data_root)

    if use_cache:
        snapshot = db.dataset_snapshot_get(target_date, snapshot_name="daily")
        source_outcome = _cached_source_outcome(db, target_date)
        event_outcome = _cached_event_outcome(db, target_date, recent_start, recent_end)
        model_outcome = _cached_model_outcome(db, target_date)
        gate_outcome = _cached_gate_outcome(db, target_date)
        snapshot_meta = snapshot.get("metadata_json") if snapshot else {}
        gate_metrics = gate_outcome.payload.get("metrics", {}) if gate_outcome else {}
        if (
            snapshot and source_outcome and event_outcome and model_outcome and gate_outcome
            and _fingerprint_matches(snapshot_meta.get("cache_fingerprint"), cache_fp)
            and _fingerprint_matches(gate_metrics.get("cache_fingerprint"), cache_fp)
        ):
            payload = {
                "eval_date": target_date,
                "source": source_outcome.payload,
                "event": event_outcome.payload,
                "model": model_outcome.payload,
                "gate": gate_outcome.payload,
                "snapshot": snapshot,
            }
            summary = (
                f"daily eval {target_date}: "
                f"source={source_outcome.status}, event={event_outcome.status}, "
                f"model={model_outcome.status}, gate={gate_outcome.status} [cached]"
            )
            status = gate_outcome.status
            if status == "ok" and any(out.status in {"partial", "blocked_by_dependency"} for out in [source_outcome, event_outcome, model_outcome]):
                status = "partial"
            return EvalOutcome(status=status, summary=summary, payload=payload)

    source_outcome = evaluate_sources(
        data_root, eval_date=target_date, lookback_days=RECENT_OPERATIONAL_DAYS, persist=True, use_cache=use_cache
    )
    event_outcome = evaluate_events(
        data_root, eval_date=target_date, start_date=recent_start, end_date=recent_end, persist=True, use_cache=use_cache
    )
    model_outcome = evaluate_models(
        data_root, eval_date=target_date, start_date=None, persist=True, use_cache=use_cache
    )
    research_event_outcome = evaluate_events(
        data_root, eval_date=target_date, start_date=research_start, end_date=research_end, persist=True, use_cache=use_cache
    )
    research_model_outcome = evaluate_models(
        data_root, eval_date=target_date, start_date=research_start, end_date=research_end, persist=False, use_cache=False
    )

    snapshot = _dataset_snapshot(
        data_root,
        target_date,
        start_date=research_start,
        metadata_extra={"cache_fingerprint": cache_fp},
    )
    db.dataset_snapshot_upsert(snapshot)

    gate_outcome = evaluate_gate(
        data_root,
        eval_date=target_date,
        source_outcome=source_outcome,
        recent_event_outcome=event_outcome,
        research_event_outcome=research_event_outcome,
        research_model_outcome=research_model_outcome,
        cache_fingerprint=cache_fp,
        persist=True,
        use_cache=False,
    )
    payload = {
        "eval_date": target_date,
        "source": source_outcome.payload,
        "event": event_outcome.payload,
        "model": model_outcome.payload,
        "research_event": research_event_outcome.payload,
        "research_model": research_model_outcome.payload,
        "gate": gate_outcome.payload,
        "snapshot": snapshot,
    }
    summary = (
        f"daily eval {target_date}: "
        f"source={source_outcome.status}, event={event_outcome.status}, model={model_outcome.status}, "
        f"research_event={research_event_outcome.status}, research_model={research_model_outcome.status}, gate={gate_outcome.status}"
    )
    status = gate_outcome.status
    if status == "ok" and any(out.status in {"partial", "blocked_by_dependency"} for out in [source_outcome, event_outcome, model_outcome]):
        status = "partial"

    try:
        write_quality_report(db, target_date, status, gate_outcome, model_outcome)
    except Exception as exc:
        logger.warning("QualityReport write failed: %s", exc)

    return EvalOutcome(status=status, summary=summary, payload=payload, gate_ok=(status == "ok"))
