"""Quality gate: combines source/event/model outcomes into a go/no-go decision."""
from __future__ import annotations

import logging
from typing import Any

from trade_py.db.trade_db import TradeDB
from trade_py.infra.settings import default_data_root
from trade_py.evaluation.utils import (
    EvalOutcome,
    RECENT_OPERATIONAL_DAYS,
    _cache_fingerprint,
    _cached_gate_outcome,
    _fingerprint_matches,
    _resolve_matured_window,
    _resolve_window,
    _safe_float,
    _safe_int,
    resolve_eval_date,
)
from trade_py.evaluation.sources import evaluate_sources
from trade_py.evaluation.events import evaluate_events
from trade_py.evaluation.models import evaluate_models, _dataset_snapshot

logger = logging.getLogger(__name__)


def evaluate_gate(data_root: str = str(default_data_root()),
                  eval_date: str | None = None,
                  source_outcome: EvalOutcome | None = None,
                  recent_event_outcome: EvalOutcome | None = None,
                  research_event_outcome: EvalOutcome | None = None,
                  research_model_outcome: EvalOutcome | None = None,
                  cache_fingerprint: dict[str, Any] | None = None,
                  persist: bool = True,
                  use_cache: bool = True) -> EvalOutcome:
    target_date = resolve_eval_date(data_root, eval_date)
    db = TradeDB(data_root)
    recent_start, recent_end = _resolve_window(target_date, RECENT_OPERATIONAL_DAYS)
    research_start, research_end = _resolve_matured_window(target_date)
    current_fingerprint = cache_fingerprint or _cache_fingerprint(
        data_root, target_date, recent_start, recent_end, research_start, research_end
    )
    if use_cache:
        cached = _cached_gate_outcome(db, target_date)
        cached_metrics = cached.payload.get("metrics", {}) if cached is not None else {}
        if cached is not None and _fingerprint_matches(cached_metrics.get("cache_fingerprint"), current_fingerprint):
            return cached
    source_outcome = source_outcome or evaluate_sources(
        data_root,
        eval_date=target_date,
        lookback_days=RECENT_OPERATIONAL_DAYS,
        persist=True,
        use_cache=use_cache,
    )
    recent_event_outcome = recent_event_outcome or evaluate_events(
        data_root,
        eval_date=target_date,
        start_date=recent_start,
        end_date=recent_end,
        persist=True,
        use_cache=use_cache,
    )
    research_event_outcome = research_event_outcome or evaluate_events(
        data_root,
        eval_date=target_date,
        start_date=research_start,
        end_date=research_end,
        persist=True,
        use_cache=use_cache,
    )
    research_model_outcome = research_model_outcome or evaluate_models(
        data_root,
        eval_date=target_date,
        start_date=research_start,
        end_date=research_end,
        persist=False,
        use_cache=False,
    )
    snapshot = _dataset_snapshot(
        data_root,
        target_date,
        start_date=research_start,
        metadata_extra={"cache_fingerprint": current_fingerprint},
    )

    latest_reasons: list[str] = []
    matured_reasons: list[str] = []
    missing: list[str] = []
    latest_metrics: dict[str, Any] = {
        "eval_date": target_date,
        "window_start": recent_start,
        "window_end": recent_end,
        "fund_flow_coverage": snapshot["metadata_json"].get("fund_flow_coverage", 0.0),
        "fundamental_coverage": snapshot["metadata_json"].get("fundamental_coverage", 0.0),
        "source_healthy_ratio": (
            sum(1 for row in source_outcome.payload.get("health_rows", []) if row.get("healthy"))
            / max(1, len(source_outcome.payload.get("health_rows", [])))
            if source_outcome.payload.get("health_rows")
            else None
        ),
        "event_count": recent_event_outcome.payload.get("event_count", 0),
    }
    matured_metrics: dict[str, Any] = {
        "window_start": research_start,
        "window_end": research_end,
        "labeled_propagation_ratio": research_event_outcome.payload.get("labeled_propagation_ratio", 0.0),
    }

    min_fund_flow = _safe_float(db.get("eval.min_fund_flow_coverage", 0.85), 0.85)
    min_fundamental = _safe_float(db.get("eval.min_fundamental_coverage", 0.85), 0.85)
    min_event_count = _safe_int(db.get("eval.min_event_count", 5), 5)
    min_labeled_ratio = _safe_float(db.get("eval.min_labeled_propagation_ratio", 0.05), 0.05)
    min_rank_ic = _safe_float(db.get("eval.min_model_rank_ic_5d", 0.02), 0.02)

    if source_outcome.status == "blocked_by_dependency":
        missing.append("source evaluation missing")
    if recent_event_outcome.status == "blocked_by_dependency":
        missing.append("recent event evaluation missing")
    if research_model_outcome.status == "blocked_by_dependency":
        missing.append("research model evaluation missing")

    if latest_metrics["fund_flow_coverage"] < min_fund_flow:
        latest_reasons.append(f"fund_flow coverage {latest_metrics['fund_flow_coverage']:.1%} < {min_fund_flow:.0%}")
    if latest_metrics["fundamental_coverage"] < min_fundamental:
        latest_reasons.append(f"fundamental coverage {latest_metrics['fundamental_coverage']:.1%} < {min_fundamental:.0%}")
    if _safe_int(recent_event_outcome.payload.get("event_count"), 0) < min_event_count:
        latest_reasons.append(f"event_count {recent_event_outcome.payload.get('event_count', 0)} < {min_event_count}")
    if source_outcome.status in {"partial", "blocked_by_dependency"}:
        latest_reasons.append(f"source status={source_outcome.status}")
    if recent_event_outcome.status in {"partial", "blocked_by_dependency"} and _safe_int(recent_event_outcome.payload.get("event_count"), 0) <= 0:
        latest_reasons.append(f"recent event status={recent_event_outcome.status}")

    model_rows = research_model_outcome.payload.get("rows", [])
    model_5d = next((row for row in model_rows if row.get("model_name") == "kg_return_5d"), None)
    if model_5d:
        matured_metrics["model_rank_ic_5d"] = model_5d.get("rank_ic")
        baseline = model_5d.get("baseline_json") or {}
        matured_metrics["model_baseline_delta"] = baseline.get("baseline_delta")
        rank_ic = model_5d.get("rank_ic")
        if rank_ic is None or _safe_float(rank_ic, -1.0) < min_rank_ic:
            matured_reasons.append(f"model rank_ic_5d {_safe_float(rank_ic, -1.0):.4f} < {min_rank_ic:.4f}")
        delta = baseline.get("baseline_delta")
        if delta is not None and _safe_float(delta) < 0:
            matured_reasons.append(f"model below baseline ({_safe_float(delta):.4f})")
    else:
        matured_reasons.append("kg_return_5d evaluation missing")
    if _safe_float(research_event_outcome.payload.get("labeled_propagation_ratio"), 0.0) < min_labeled_ratio:
        matured_reasons.append(
            f"labeled_propagation_ratio {_safe_float(research_event_outcome.payload.get('labeled_propagation_ratio')):.1%} < {min_labeled_ratio:.0%}"
        )
    if research_event_outcome.status == "blocked_by_dependency":
        matured_reasons.append("research event evaluation missing")

    operational_status = "ok"
    if missing and not latest_reasons:
        operational_status = "blocked_by_dependency"
    elif latest_reasons:
        operational_status = "degraded"

    research_status = "ok"
    if research_event_outcome.status == "blocked_by_dependency" or research_model_outcome.status == "blocked_by_dependency":
        research_status = "blocked_by_dependency"
    elif matured_reasons or research_event_outcome.status == "partial" or research_model_outcome.status == "partial":
        research_status = "partial"

    if operational_status in {"degraded", "blocked_by_dependency"}:
        status = operational_status
    elif research_status in {"partial", "blocked_by_dependency"}:
        status = "partial"
    else:
        status = "ok"

    reasons = [f"latest: {reason}" for reason in latest_reasons] + [f"matured: {reason}" for reason in matured_reasons]
    if missing:
        reasons = missing + reasons
    metrics = {
        "operational_status": operational_status,
        "research_status": research_status,
        "overall_status": status,
        "latest_reasons": latest_reasons,
        "matured_reasons": matured_reasons,
        "latest_metrics": latest_metrics,
        "matured_metrics": matured_metrics,
        "missing": missing,
        "cache_fingerprint": current_fingerprint,
        "fund_flow_coverage": latest_metrics.get("fund_flow_coverage"),
        "fundamental_coverage": latest_metrics.get("fundamental_coverage"),
        "source_healthy_ratio": latest_metrics.get("source_healthy_ratio"),
        "event_count": latest_metrics.get("event_count"),
        "labeled_propagation_ratio": matured_metrics.get("labeled_propagation_ratio"),
        "model_rank_ic_5d": matured_metrics.get("model_rank_ic_5d"),
        "model_baseline_delta": matured_metrics.get("model_baseline_delta"),
    }
    if persist:
        db.quality_gate_upsert(target_date, status, reasons, metrics)
    summary = f"quality gate {target_date}: overall={status} op={operational_status} research={research_status}"
    return EvalOutcome(status=status, summary=summary, payload={"eval_date": target_date, "status": status, "reasons": reasons, "metrics": metrics})
