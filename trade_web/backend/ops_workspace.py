from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from threading import Thread
from typing import Any

from trade_web.backend.readiness import build_readiness_grid

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpsNodeMeta:
    id: str
    name: str
    node_type: str
    layer: str
    description: str
    upstream_ids: tuple[str, ...] = ()
    downstream_ids: tuple[str, ...] = ()
    dataset_key: str | None = None
    replay_jobs: tuple[str, ...] = ()
    backfill_jobs: tuple[str, ...] = ()
    can_backfill: bool = False
    can_replay: bool = True
    can_compare: bool = True


OPS_LAYER_LABELS: dict[str, str] = {
    "source": "Raw Source",
    "feature": "Derived Feature",
    "factor": "Factor",
    "model": "Model State",
    "decision": "Decision Output",
    "workflow": "Workflow Job",
}


OPS_NODE_CATALOG: tuple[OpsNodeMeta, ...] = (
    OpsNodeMeta("source:kline", "Kline", "source", "source", "Daily OHLCV source data.", downstream_ids=("feature:rsi_14", "feature:macd_signal", "feature:volume_ratio", "feature:signal_snapshot"), dataset_key="kline", replay_jobs=("kline_update",), backfill_jobs=("kline_update",), can_backfill=True),
    OpsNodeMeta("source:fund_flow", "Fund Flow", "source", "source", "Daily money flow source data.", downstream_ids=("feature:signal_snapshot", "factor:liquidity_factor"), dataset_key="fund_flow", replay_jobs=("fund_flow_update",), backfill_jobs=("fund_flow_update",), can_backfill=True),
    OpsNodeMeta("source:fundamental", "Fundamental", "source", "source", "Fundamental snapshot source data.", downstream_ids=("feature:signal_snapshot",), dataset_key="fundamental", replay_jobs=("fundamental",), backfill_jobs=("fundamental",), can_backfill=True),
    OpsNodeMeta("source:sentiment_gold", "Sentiment Gold", "source", "source", "Curated sentiment dataset.", downstream_ids=("feature:net_sentiment", "factor:event_factor"), dataset_key="sentiment_gold", replay_jobs=("sentiment_gold",), backfill_jobs=("sentiment_gold",), can_backfill=True),
    OpsNodeMeta("source:events", "Market Events", "source", "source", "Structured event extraction output.", downstream_ids=("feature:event_kg_score", "factor:event_factor"), dataset_key="events", replay_jobs=("event_extract", "kg_propagate"), backfill_jobs=("event_extract",), can_backfill=True),
    OpsNodeMeta("source:planned_events", "Planned Events", "source", "source", "Scheduled events and agenda source data.", downstream_ids=("feature:event_kg_score", "workflow:evaluate_daily"), dataset_key="planned_events", replay_jobs=("planned_event_sync",), backfill_jobs=("planned_event_sync",), can_backfill=True),
    OpsNodeMeta("source:sector_map", "Sector Map", "source", "source", "Sector membership mapping.", downstream_ids=("factor:sector_factor", "feature:event_kg_score"), dataset_key="sector_map", replay_jobs=("sector_refresh",), backfill_jobs=("sector_refresh",), can_backfill=True),
    OpsNodeMeta("source:crypto_btc", "Crypto BTC", "source", "source", "BTC UTC daily assurance and research-validation data health.", downstream_ids=("factor:data_quality_factor", "model:trust", "workflow:crypto_research_validation"), dataset_key="crypto_btc", replay_jobs=("crypto_research_validation",), backfill_jobs=("crypto_btc_fetch",), can_backfill=True),
    OpsNodeMeta("feature:signal_snapshot", "Signal Snapshot", "feature", "feature", "Cross-symbol scoring snapshot from derived features.", upstream_ids=("source:kline", "source:fund_flow", "source:fundamental"), downstream_ids=("factor:trend_factor", "model:model_score", "model:model_risk"), dataset_key="signals", replay_jobs=("window_score",)),
    OpsNodeMeta("feature:rsi_14", "RSI 14", "feature", "feature", "Latest RSI metric.", upstream_ids=("source:kline",), downstream_ids=("factor:momentum_factor", "model:technical_state"), replay_jobs=("window_score",)),
    OpsNodeMeta("feature:macd_signal", "MACD Signal", "feature", "feature", "Latest MACD crossover state.", upstream_ids=("source:kline",), downstream_ids=("factor:momentum_factor", "model:technical_state"), replay_jobs=("window_score",)),
    OpsNodeMeta("feature:volume_ratio", "Volume Ratio", "feature", "feature", "5/20 volume ratio feature.", upstream_ids=("source:kline",), downstream_ids=("factor:liquidity_factor", "model:technical_state"), replay_jobs=("window_score",)),
    OpsNodeMeta("feature:net_sentiment", "Net Sentiment", "feature", "feature", "Net sentiment input feature.", upstream_ids=("source:sentiment_gold",), downstream_ids=("factor:event_factor", "model:sentiment_state"), replay_jobs=("belief_update",)),
    OpsNodeMeta("feature:event_kg_score", "Event KG Score", "feature", "feature", "Event propagation score feature.", upstream_ids=("source:events", "source:sector_map"), downstream_ids=("factor:event_factor", "factor:sector_factor", "model:market_state"), replay_jobs=("kg_propagate",)),
    OpsNodeMeta("factor:trend_factor", "Trend Factor", "factor", "factor", "Trend factor used in the causal chain.", upstream_ids=("feature:signal_snapshot",), downstream_ids=("model:market_state", "model:conviction"), replay_jobs=("belief_update",)),
    OpsNodeMeta("factor:momentum_factor", "Momentum Factor", "factor", "factor", "Momentum factor derived from RSI / MACD.", upstream_ids=("feature:rsi_14", "feature:macd_signal"), downstream_ids=("model:technical_state", "model:conviction"), replay_jobs=("belief_update",)),
    OpsNodeMeta("factor:event_factor", "Event Factor", "factor", "factor", "Event and sentiment factor.", upstream_ids=("feature:event_kg_score", "feature:net_sentiment"), downstream_ids=("model:sentiment_state", "model:conviction"), replay_jobs=("belief_update",)),
    OpsNodeMeta("factor:liquidity_factor", "Liquidity Factor", "factor", "factor", "Liquidity support factor.", upstream_ids=("feature:volume_ratio", "source:fund_flow"), downstream_ids=("model:conviction", "model:blockers"), replay_jobs=("belief_update",)),
    OpsNodeMeta("factor:sector_factor", "Sector Factor", "factor", "factor", "Sector / board context factor.", upstream_ids=("source:sector_map", "feature:event_kg_score"), downstream_ids=("model:conviction",), replay_jobs=("kg_propagate", "belief_update")),
    OpsNodeMeta("factor:data_quality_factor", "Data Quality Factor", "factor", "factor", "Freshness and readiness quality factor.", upstream_ids=("source:kline", "source:fund_flow", "source:fundamental", "source:events", "source:crypto_btc"), downstream_ids=("model:trust", "model:blockers"), replay_jobs=(), can_replay=False),
    OpsNodeMeta("model:market_state", "Market State", "model", "model", "Market regime inference.", upstream_ids=("factor:trend_factor", "feature:event_kg_score"), downstream_ids=("model:conviction", "decision:recommendation"), replay_jobs=(), can_replay=False),
    OpsNodeMeta("model:technical_state", "Technical State", "model", "model", "Technical regime inference.", upstream_ids=("factor:momentum_factor", "feature:volume_ratio"), downstream_ids=("model:conviction", "decision:recommendation"), replay_jobs=(), can_replay=False),
    OpsNodeMeta("model:sentiment_state", "Sentiment State", "model", "model", "Sentiment regime inference.", upstream_ids=("factor:event_factor",), downstream_ids=("model:conviction", "decision:recommendation"), replay_jobs=(), can_replay=False),
    OpsNodeMeta("model:model_score", "Model Score", "model", "model", "Latest model score output.", upstream_ids=("feature:signal_snapshot",), downstream_ids=("model:conviction", "decision:recommendation"), replay_jobs=(), can_replay=False),
    OpsNodeMeta("model:model_risk", "Model Risk", "model", "model", "Latest model risk output.", upstream_ids=("feature:signal_snapshot",), downstream_ids=("model:conviction", "decision:recommendation"), replay_jobs=(), can_replay=False),
    OpsNodeMeta("model:model_registry", "Model Registry", "model", "model", "Active model artifact and training metadata.", upstream_ids=(), downstream_ids=("model:model_score", "model:model_risk", "model:trust"), dataset_key="models", replay_jobs=("model_train",)),
    OpsNodeMeta("model:trust", "Trust", "model", "model", "Data/model trust layer.", upstream_ids=("factor:data_quality_factor",), downstream_ids=("model:conviction", "decision:recommendation"), replay_jobs=(), can_replay=False),
    OpsNodeMeta("model:conviction", "Conviction Vector", "model", "model", "Market / symbol / horizon conviction summary.", upstream_ids=("factor:trend_factor", "factor:momentum_factor", "factor:event_factor", "factor:liquidity_factor", "factor:sector_factor", "model:trust"), downstream_ids=("decision:recommendation",), dataset_key="belief_state", replay_jobs=("belief_update",)),
    OpsNodeMeta("model:blockers", "Blockers", "model", "model", "Operational or state blockers that suppress action.", upstream_ids=("factor:data_quality_factor", "factor:liquidity_factor"), downstream_ids=("decision:recommendation",), replay_jobs=(), can_replay=False),
    OpsNodeMeta("decision:recommendation", "Recommendation", "decision", "decision", "Final action output for the current snapshot.", upstream_ids=("model:market_state", "model:technical_state", "model:sentiment_state", "model:model_score", "model:model_risk", "model:conviction", "model:blockers"), downstream_ids=("decision:thesis", "decision:invalidators", "decision:next_triggers"), dataset_key="recommendation", replay_jobs=("recommend", "evaluate_daily")),
    OpsNodeMeta("decision:thesis", "Thesis", "decision", "decision", "Decision thesis and summary.", upstream_ids=("decision:recommendation",), replay_jobs=("recommend",), can_backfill=False),
    OpsNodeMeta("decision:invalidators", "Invalidators", "decision", "decision", "Invalidation set for the current recommendation.", upstream_ids=("decision:recommendation",), replay_jobs=("recommend",), can_backfill=False),
    OpsNodeMeta("decision:next_triggers", "Next Triggers", "decision", "decision", "Transition conditions that could change the current action.", upstream_ids=("decision:recommendation",), replay_jobs=("recommend",), can_backfill=False),
    OpsNodeMeta("workflow:kline_update", "kline_update", "workflow", "workflow", "Source repair/update workflow.", downstream_ids=("source:kline",), replay_jobs=("kline_update",), backfill_jobs=("kline_update",), can_backfill=True),
    OpsNodeMeta("workflow:window_score", "window_score", "workflow", "workflow", "Feature recomputation workflow.", upstream_ids=("source:kline", "source:fund_flow", "source:fundamental"), downstream_ids=("feature:signal_snapshot",), replay_jobs=("window_score",)),
    OpsNodeMeta("workflow:belief_update", "belief_update", "workflow", "workflow", "Belief and conviction recomputation workflow.", upstream_ids=("feature:signal_snapshot", "feature:event_kg_score", "feature:net_sentiment"), downstream_ids=("factor:trend_factor", "factor:event_factor", "model:conviction"), replay_jobs=("belief_update",)),
    OpsNodeMeta("workflow:recommend", "recommend", "workflow", "workflow", "Recommendation generation workflow.", upstream_ids=("model:conviction",), downstream_ids=("decision:recommendation",), replay_jobs=("recommend",)),
    OpsNodeMeta("workflow:evaluate_daily", "evaluate_daily", "workflow", "workflow", "Daily validation and audit workflow.", upstream_ids=("decision:recommendation",), downstream_ids=(), replay_jobs=("evaluate_daily",)),
)


def _catalog_map() -> dict[str, OpsNodeMeta]:
    return {item.id: item for item in OPS_NODE_CATALOG}


def _normalize_ids(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _get_asof_dates(db, requested_date: str | None = None) -> tuple[str, str | None]:
    as_of = requested_date or db.get_latest_market_asof() or date.today().isoformat()
    try:
        prev_boundary = (date.fromisoformat(as_of) - timedelta(days=1)).isoformat()
        previous = db.get_latest_market_asof(on_or_before=prev_boundary)
    except Exception:
        previous = None
    return as_of, previous


def _pick_representative_symbol(db, as_of: str) -> str | None:
    try:
        picks = db.recommendation_list(as_of)
        if picks:
            return str(picks[0].get("symbol") or "") or None
    except Exception:
        pass
    try:
        rows = db.signal_get(as_of)
        if rows:
            return str(rows[0].get("symbol") or "") or None
    except Exception:
        pass
    try:
        with db._conn_lock:
            row = db._conn.execute("SELECT symbol FROM instruments ORDER BY symbol LIMIT 1").fetchone()
        return str(row["symbol"] or "") if row else None
    except Exception:
        return None


def _latest_signal_row(db, symbol: str, as_of: str) -> dict[str, Any]:
    with db._conn_lock:
        row = db._conn.execute(
            """
            SELECT *
            FROM signals
            WHERE symbol = ? AND date <= ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (symbol, as_of),
        ).fetchone()
    return dict(row) if row else {}


def _latest_factor_values(db, symbol: str, as_of: str, factor_names: list[str]) -> dict[str, float | None]:
    if not factor_names:
        return {}
    placeholders = ",".join("?" for _ in factor_names)
    with db._conn_lock:
        rows = db._conn.execute(
            f"""
            SELECT factor_name, value
            FROM factors
            WHERE symbol = ? AND date <= ? AND factor_name IN ({placeholders})
            ORDER BY date DESC
            """,
            (symbol, as_of, *factor_names),
        ).fetchall()
    result: dict[str, float | None] = {}
    for row in rows:
        name = str(row["factor_name"] or "")
        if name in result:
            continue
        result[name] = None if row["value"] is None else float(row["value"])
    return result


def _job_runtime_lookup(db, job_names: list[str]) -> dict[str, dict[str, Any]]:
    if not job_names:
        return {}
    placeholders = ",".join("?" for _ in job_names)
    with db._conn_lock:
        rows = db._conn.execute(
            f"""
            SELECT a.job_name, a.status, a.started_at, a.completed_at, a.elapsed_ms, a.result_summary
            FROM job_runs a
            JOIN (
                SELECT job_name, MAX(id) AS max_id
                FROM job_runs
                WHERE job_name IN ({placeholders})
                GROUP BY job_name
            ) b ON a.job_name = b.job_name AND a.id = b.max_id
            """,
            tuple(job_names),
        ).fetchall()
        previous_rows = db._conn.execute(
            f"""
            SELECT job_name, status, started_at, completed_at, elapsed_ms, result_summary
            FROM job_runs
            WHERE job_name IN ({placeholders})
            ORDER BY id DESC
            """,
            tuple(job_names),
        ).fetchall()
    latest: dict[str, dict[str, Any]] = {str(row["job_name"]): dict(row) for row in rows}
    previous_lookup: dict[str, dict[str, Any]] = {}
    for row in previous_rows:
        job_name = str(row["job_name"] or "")
        if job_name not in latest:
            continue
        current_started = latest[job_name].get("started_at")
        if row["started_at"] == current_started:
            continue
        if job_name not in previous_lookup:
            previous_lookup[job_name] = dict(row)
    for job_name, item in latest.items():
        item["previous"] = previous_lookup.get(job_name)
    return latest


def _job_average_duration_map(db, job_names: list[str]) -> dict[str, int]:
    if not job_names:
        return {}
    placeholders = ",".join("?" for _ in job_names)
    with db._conn_lock:
        rows = db._conn.execute(
            f"""
            SELECT job_name, CAST(AVG(COALESCE(elapsed_ms, 0)) AS INTEGER) AS avg_ms
            FROM job_runs
            WHERE job_name IN ({placeholders})
            GROUP BY job_name
            """,
            tuple(job_names),
        ).fetchall()
    return {str(row["job_name"]): int(row["avg_ms"] or 0) for row in rows}


def _make_summary(primary: str, secondary: str | None = None, metric: float | int | None = None, changed: bool | None = None) -> dict[str, Any]:
    return {
        "primary": primary,
        "secondary": secondary,
        "metric": metric,
        "changed": changed,
    }


def _status_from_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"ok", "healthy", "ready"}:
        return "ok"
    if text in {"running", "queued", "pending"}:
        return "running"
    if text in {"partial", "degraded", "changed"}:
        return "partial"
    if text in {"error", "blocked", "missing"}:
        return "error"
    return "unknown"


def _status_from_readiness(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"READY", "REPLAYED"}:
        return "ok"
    if text in {"REPLAYING"}:
        return "running"
    if text in {"PARTIAL", "CHANGED", "LATE_READY"}:
        return "partial"
    if text in {"MISSING"}:
        return "error"
    return "unknown"


def _build_symbol_context(explain_svc, symbol: str | None, as_of: str | None) -> dict[str, Any]:
    if not symbol or not as_of:
        return {"symbol": symbol, "as_of": as_of, "state": {}, "explain": {}, "causal": {}}
    state = explain_svc._state_svc.build(symbol, as_of_date=as_of).to_dict()
    explain = explain_svc.explain(symbol, as_of_date=as_of).to_dict()
    causal = explain.get("causal_chain") or explain_svc.causal_chain(symbol, as_of_date=as_of, persist=False, include_validation=False)
    return {
        "symbol": symbol,
        "as_of": as_of,
        "state": state,
        "explain": explain,
        "causal": causal,
    }


def _factor_lookup(causal_chain: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("factor_type") or ""): item
        for item in (causal_chain.get("causal_factors") or [])
        if isinstance(item, dict)
    }


def _node_delta_summary(latest_metric: float | int | None, previous_metric: float | int | None, *, percent: bool = False) -> str | None:
    if latest_metric is None or previous_metric is None:
        return None
    try:
        latest_val = float(latest_metric)
        previous_val = float(previous_metric)
    except Exception:
        return None
    delta = latest_val - previous_val
    if abs(delta) < 1e-9:
        return "no change"
    if percent:
        return f"{delta:+.2%}"
    return f"{delta:+.3f}"


def _build_source_node(meta: OpsNodeMeta, readiness_row: dict[str, Any], latest_cell: dict[str, Any], previous_cell: dict[str, Any] | None, *, representative_symbol: str | None) -> dict[str, Any]:
    latest_cov = latest_cell.get("coverage_pct")
    prev_cov = previous_cell.get("coverage_pct") if previous_cell else None
    latest_primary = f"{latest_cell.get('row_count') or 0}/{latest_cell.get('expected_count') or '—'} rows"
    latest_secondary = f"lag {latest_cell.get('lag_days') if latest_cell.get('lag_days') is not None else '—'}d · {latest_cell.get('source_last_date') or '—'}"
    previous_summary = None
    if previous_cell:
        previous_summary = _make_summary(
            f"{previous_cell.get('row_count') or 0}/{previous_cell.get('expected_count') or '—'} rows",
            f"lag {previous_cell.get('lag_days') if previous_cell.get('lag_days') is not None else '—'}d · {previous_cell.get('source_last_date') or '—'}",
            metric=prev_cov,
            changed=prev_cov != latest_cov,
        )
    return {
        "id": meta.id,
        "name": meta.name,
        "type": meta.node_type,
        "layer": meta.layer,
        "description": meta.description,
        "latest_status": _status_from_readiness(latest_cell.get("status")),
        "last_run_at": latest_cell.get("last_backfill_at"),
        "latest_output_summary": _make_summary(latest_primary, latest_secondary, metric=latest_cov, changed=prev_cov != latest_cov if previous_cell else None),
        "previous_output_summary": previous_summary,
        "delta_summary": _node_delta_summary(latest_cov, prev_cov, percent=True),
        "upstream_ids": list(meta.upstream_ids),
        "downstream_ids": list(meta.downstream_ids),
        "can_backfill": meta.can_backfill,
        "can_replay": meta.can_replay,
        "can_compare": meta.can_compare,
        "mapped_dataset": meta.dataset_key,
        "mapped_job_names": list(meta.backfill_jobs or meta.replay_jobs),
        "representative_symbol": representative_symbol,
    }


def _build_feature_node(meta: OpsNodeMeta, latest_ctx: dict[str, Any], previous_ctx: dict[str, Any], signal_latest: dict[str, Any], signal_previous: dict[str, Any]) -> dict[str, Any]:
    state_latest = latest_ctx.get("state") or {}
    state_previous = previous_ctx.get("state") or {}
    latest_value = None
    previous_value = None
    latest_text = "unavailable"
    previous_summary = None

    if meta.id == "feature:rsi_14":
        latest_value = ((state_latest.get("technical_state") or {}).get("rsi_14"))
        previous_value = ((state_previous.get("technical_state") or {}).get("rsi_14"))
        latest_text = f"RSI {latest_value:.2f}" if isinstance(latest_value, (float, int)) else "RSI unavailable"
        previous_summary = _make_summary(f"RSI {previous_value:.2f}" if isinstance(previous_value, (float, int)) else "RSI unavailable", None, metric=previous_value, changed=previous_value != latest_value if previous_value is not None else None)
    elif meta.id == "feature:macd_signal":
        latest_value = ((state_latest.get("technical_state") or {}).get("macd_signal"))
        previous_value = ((state_previous.get("technical_state") or {}).get("macd_signal"))
        latest_text = f"MACD signal {latest_value:+.0f}" if isinstance(latest_value, (float, int)) else "MACD signal unavailable"
        previous_summary = _make_summary(f"MACD signal {previous_value:+.0f}" if isinstance(previous_value, (float, int)) else "MACD signal unavailable", None, metric=previous_value, changed=previous_value != latest_value if previous_value is not None else None)
    elif meta.id == "feature:volume_ratio":
        latest_value = ((state_latest.get("liquidity_state") or {}).get("vol_ratio"))
        previous_value = ((state_previous.get("liquidity_state") or {}).get("vol_ratio"))
        latest_text = f"Vol ratio {latest_value:.2f}" if isinstance(latest_value, (float, int)) else "Vol ratio unavailable"
        previous_summary = _make_summary(f"Vol ratio {previous_value:.2f}" if isinstance(previous_value, (float, int)) else "Vol ratio unavailable", None, metric=previous_value, changed=previous_value != latest_value if previous_value is not None else None)
    elif meta.id == "feature:net_sentiment":
        latest_value = ((state_latest.get("sentiment_state") or {}).get("net_sentiment"))
        previous_value = ((state_previous.get("sentiment_state") or {}).get("net_sentiment"))
        latest_text = f"Net sentiment {latest_value:+.3f}" if isinstance(latest_value, (float, int)) else "Net sentiment unavailable"
        previous_summary = _make_summary(f"Net sentiment {previous_value:+.3f}" if isinstance(previous_value, (float, int)) else "Net sentiment unavailable", None, metric=previous_value, changed=previous_value != latest_value if previous_value is not None else None)
    elif meta.id == "feature:event_kg_score":
        latest_value = ((state_latest.get("event_state") or {}).get("kg_score"))
        previous_value = ((state_previous.get("event_state") or {}).get("kg_score"))
        latest_text = f"Event KG {latest_value:+.3f}" if isinstance(latest_value, (float, int)) else "Event KG unavailable"
        previous_summary = _make_summary(f"Event KG {previous_value:+.3f}" if isinstance(previous_value, (float, int)) else "Event KG unavailable", None, metric=previous_value, changed=previous_value != latest_value if previous_value is not None else None)
    else:
        latest_value = signal_latest.get("window_score")
        previous_value = signal_previous.get("window_score")
        with_count = signal_latest.get("signal_count")
        latest_text = f"{with_count or 0} symbols scored"
        previous_summary = _make_summary(
            f"{signal_previous.get('signal_count') or 0} symbols scored",
            f"sample model {signal_previous.get('model_score') or '—'}",
            metric=signal_previous.get("signal_count"),
            changed=signal_previous.get("signal_count") != with_count,
        )

    return {
        "id": meta.id,
        "name": meta.name,
        "type": meta.node_type,
        "layer": meta.layer,
        "description": meta.description,
        "latest_status": "ok" if latest_value is not None or meta.id == "feature:signal_snapshot" else "partial",
        "last_run_at": signal_latest.get("updated_at"),
        "latest_output_summary": _make_summary(latest_text, f"symbol {latest_ctx.get('symbol') or '—'}", metric=latest_value if latest_value is not None else signal_latest.get("signal_count"), changed=previous_value != latest_value if previous_value is not None else None),
        "previous_output_summary": previous_summary,
        "delta_summary": _node_delta_summary(latest_value if latest_value is not None else signal_latest.get("signal_count"), previous_value if previous_value is not None else signal_previous.get("signal_count")),
        "upstream_ids": list(meta.upstream_ids),
        "downstream_ids": list(meta.downstream_ids),
        "can_backfill": meta.can_backfill,
        "can_replay": meta.can_replay,
        "can_compare": meta.can_compare,
        "mapped_dataset": meta.dataset_key,
        "mapped_job_names": list(meta.replay_jobs),
        "representative_symbol": latest_ctx.get("symbol"),
    }


def _build_factor_node(meta: OpsNodeMeta, latest_ctx: dict[str, Any], previous_ctx: dict[str, Any]) -> dict[str, Any]:
    latest_factor = _factor_lookup(latest_ctx.get("causal") or {}).get(meta.name.lower().replace(" ", "_"))
    previous_factor = _factor_lookup(previous_ctx.get("causal") or {}).get(meta.name.lower().replace(" ", "_"))
    if meta.id == "factor:trend_factor":
        latest_factor = _factor_lookup(latest_ctx.get("causal") or {}).get("trend_factor")
        previous_factor = _factor_lookup(previous_ctx.get("causal") or {}).get("trend_factor")
    elif meta.id == "factor:momentum_factor":
        latest_factor = _factor_lookup(latest_ctx.get("causal") or {}).get("momentum_factor")
        previous_factor = _factor_lookup(previous_ctx.get("causal") or {}).get("momentum_factor")
    elif meta.id == "factor:event_factor":
        latest_factor = _factor_lookup(latest_ctx.get("causal") or {}).get("event_factor")
        previous_factor = _factor_lookup(previous_ctx.get("causal") or {}).get("event_factor")
    elif meta.id == "factor:liquidity_factor":
        latest_factor = _factor_lookup(latest_ctx.get("causal") or {}).get("liquidity_factor")
        previous_factor = _factor_lookup(previous_ctx.get("causal") or {}).get("liquidity_factor")
    elif meta.id == "factor:sector_factor":
        latest_factor = _factor_lookup(latest_ctx.get("causal") or {}).get("sector_factor")
        previous_factor = _factor_lookup(previous_ctx.get("causal") or {}).get("sector_factor")
    elif meta.id == "factor:data_quality_factor":
        latest_factor = _factor_lookup(latest_ctx.get("causal") or {}).get("data_quality_factor")
        previous_factor = _factor_lookup(previous_ctx.get("causal") or {}).get("data_quality_factor")

    latest_strength = latest_factor.get("strength") if latest_factor else None
    previous_strength = previous_factor.get("strength") if previous_factor else None
    latest_primary = "factor unavailable"
    if latest_factor:
        latest_primary = f"{latest_factor.get('direction') or 'unknown'} · strength {latest_strength if latest_strength is not None else '—'}"
    previous_summary = None
    if previous_factor:
        previous_summary = _make_summary(
            f"{previous_factor.get('direction') or 'unknown'} · strength {previous_strength if previous_strength is not None else '—'}",
            previous_factor.get("rationale"),
            metric=previous_strength,
            changed=latest_strength != previous_strength,
        )
    return {
        "id": meta.id,
        "name": meta.name,
        "type": meta.node_type,
        "layer": meta.layer,
        "description": meta.description,
        "latest_status": "ok" if latest_factor else "unknown",
        "last_run_at": latest_ctx.get("as_of"),
        "latest_output_summary": _make_summary(latest_primary, latest_factor.get("rationale") if latest_factor else "No explicit factor output is stored for this layer yet.", metric=latest_strength, changed=latest_strength != previous_strength if previous_strength is not None else None),
        "previous_output_summary": previous_summary,
        "delta_summary": _node_delta_summary(latest_strength, previous_strength),
        "upstream_ids": list(meta.upstream_ids),
        "downstream_ids": list(meta.downstream_ids),
        "can_backfill": meta.can_backfill,
        "can_replay": meta.can_replay,
        "can_compare": meta.can_compare,
        "mapped_dataset": meta.dataset_key,
        "mapped_job_names": list(meta.replay_jobs),
        "representative_symbol": latest_ctx.get("symbol"),
    }


def _build_model_node(meta: OpsNodeMeta, latest_ctx: dict[str, Any], previous_ctx: dict[str, Any], signal_latest: dict[str, Any], signal_previous: dict[str, Any]) -> dict[str, Any]:
    state_latest = latest_ctx.get("state") or {}
    state_previous = previous_ctx.get("state") or {}
    explain_latest = latest_ctx.get("explain") or {}
    explain_previous = previous_ctx.get("explain") or {}
    causal_latest = latest_ctx.get("causal") or {}
    causal_previous = previous_ctx.get("causal") or {}

    latest_value: Any = None
    previous_value: Any = None
    latest_primary = "unavailable"
    latest_secondary = None

    if meta.id == "model:market_state":
        latest_value = state_latest.get("market_regime")
        previous_value = state_previous.get("market_regime")
        latest_primary = str(latest_value or "unavailable")
        latest_secondary = (state_latest.get("market_state") or {}).get("rationale")
    elif meta.id == "model:technical_state":
        latest_value = state_latest.get("technical_regime")
        previous_value = state_previous.get("technical_regime")
        latest_primary = str(latest_value or "unavailable")
        latest_secondary = (state_latest.get("technical_state") or {}).get("rationale")
    elif meta.id == "model:sentiment_state":
        latest_value = state_latest.get("sentiment_regime")
        previous_value = state_previous.get("sentiment_regime")
        latest_primary = str(latest_value or "unavailable")
        latest_secondary = (state_latest.get("sentiment_state") or {}).get("rationale")
    elif meta.id == "model:model_score":
        latest_value = signal_latest.get("model_score")
        previous_value = signal_previous.get("model_score")
        latest_primary = f"{float(latest_value):.3f}" if latest_value is not None else "model score unavailable"
        latest_secondary = f"sample {latest_ctx.get('symbol') or '—'}"
    elif meta.id == "model:model_risk":
        latest_value = signal_latest.get("model_risk")
        previous_value = signal_previous.get("model_risk")
        latest_primary = f"{float(latest_value):.3f}" if latest_value is not None else "model risk unavailable"
        latest_secondary = f"sample {latest_ctx.get('symbol') or '—'}"
    elif meta.id == "model:model_registry":
        latest_value = signal_latest.get("model_version")
        previous_value = signal_previous.get("model_version")
        latest_primary = str(latest_value or "model artifact unavailable")
        latest_secondary = "active artifact that fed the current scoring snapshot"
    elif meta.id == "model:trust":
        latest_value = ((explain_latest.get("trust") or {}).get("trust_score"))
        previous_value = ((explain_previous.get("trust") or {}).get("trust_score"))
        latest_primary = f"trust {float(latest_value):.2f}" if latest_value is not None else "trust unavailable"
        latest_secondary = ", ".join((explain_latest.get("input_warnings") or [])[:2]) or "no input warnings"
    elif meta.id == "model:conviction":
        latest_value = ((causal_latest.get("conviction_vector") or {}).get("final_decision_confidence"))
        previous_value = ((causal_previous.get("conviction_vector") or {}).get("final_decision_confidence"))
        labels = (causal_latest.get("conviction_vector") or {}).get("labels") or {}
        latest_primary = f"decision {labels.get('final_decision_confidence', 'UNKNOWN')}"
        latest_secondary = f"market {labels.get('market_conviction', 'UNKNOWN')} · symbol {labels.get('symbol_conviction', 'UNKNOWN')}"
    else:
        latest_value = len(state_latest.get("blockers") or [])
        previous_value = len(state_previous.get("blockers") or [])
        latest_primary = f"{latest_value} blockers"
        latest_secondary = ", ".join((state_latest.get("blockers") or [])[:2]) or "no active blockers"

    previous_summary = _make_summary(
        str(previous_value if previous_value is not None else "unavailable"),
        None,
        metric=previous_value if isinstance(previous_value, (float, int)) else None,
        changed=latest_value != previous_value if previous_value is not None else None,
    ) if previous_value is not None else None

    return {
        "id": meta.id,
        "name": meta.name,
        "type": meta.node_type,
        "layer": meta.layer,
        "description": meta.description,
        "latest_status": "ok" if latest_value is not None else "partial",
        "last_run_at": latest_ctx.get("as_of"),
        "latest_output_summary": _make_summary(latest_primary, latest_secondary, metric=latest_value if isinstance(latest_value, (float, int)) else None, changed=latest_value != previous_value if previous_value is not None else None),
        "previous_output_summary": previous_summary,
        "delta_summary": _node_delta_summary(latest_value if isinstance(latest_value, (float, int)) else None, previous_value if isinstance(previous_value, (float, int)) else None),
        "upstream_ids": list(meta.upstream_ids),
        "downstream_ids": list(meta.downstream_ids),
        "can_backfill": meta.can_backfill,
        "can_replay": meta.can_replay,
        "can_compare": meta.can_compare,
        "mapped_dataset": meta.dataset_key,
        "mapped_job_names": list(meta.replay_jobs),
        "representative_symbol": latest_ctx.get("symbol"),
    }


def _build_decision_node(meta: OpsNodeMeta, latest_ctx: dict[str, Any], previous_ctx: dict[str, Any]) -> dict[str, Any]:
    explain_latest = latest_ctx.get("explain") or {}
    explain_previous = previous_ctx.get("explain") or {}
    latest_primary = "unavailable"
    latest_secondary = None
    latest_metric = None
    previous_metric = None

    if meta.id == "decision:recommendation":
        latest_primary = str(explain_latest.get("action") or "unavailable")
        latest_secondary = str(explain_latest.get("thesis") or "") or "No thesis returned."
        latest_metric = (explain_latest.get("trust") or {}).get("trust_score")
        previous_metric = (explain_previous.get("trust") or {}).get("trust_score")
    elif meta.id == "decision:thesis":
        latest_primary = str(explain_latest.get("thesis") or "unavailable")
        latest_secondary = str(explain_latest.get("world_state_summary") or "") or None
    elif meta.id == "decision:invalidators":
        latest_items = explain_latest.get("invalidators") or []
        prev_items = explain_previous.get("invalidators") or []
        latest_primary = f"{len(latest_items)} invalidators"
        latest_secondary = ", ".join(latest_items[:2]) or "No invalidators"
        latest_metric = len(latest_items)
        previous_metric = len(prev_items)
    else:
        latest_items = explain_latest.get("next_triggers") or []
        prev_items = explain_previous.get("next_triggers") or []
        latest_primary = f"{len(latest_items)} next triggers"
        latest_secondary = ", ".join(latest_items[:2]) or "No next triggers"
        latest_metric = len(latest_items)
        previous_metric = len(prev_items)

    previous_summary = None
    if explain_previous:
        if meta.id == "decision:recommendation":
            previous_summary = _make_summary(str(explain_previous.get("action") or "unavailable"), str(explain_previous.get("thesis") or "") or None, metric=previous_metric, changed=(explain_previous.get("action") != explain_latest.get("action")))
        elif meta.id == "decision:thesis":
            previous_summary = _make_summary(str(explain_previous.get("thesis") or "unavailable"), str(explain_previous.get("world_state_summary") or "") or None)
        elif meta.id == "decision:invalidators":
            prev_items = explain_previous.get("invalidators") or []
            previous_summary = _make_summary(f"{len(prev_items)} invalidators", ", ".join(prev_items[:2]) or "No invalidators", metric=previous_metric, changed=previous_metric != latest_metric)
        else:
            prev_items = explain_previous.get("next_triggers") or []
            previous_summary = _make_summary(f"{len(prev_items)} next triggers", ", ".join(prev_items[:2]) or "No next triggers", metric=previous_metric, changed=previous_metric != latest_metric)

    return {
        "id": meta.id,
        "name": meta.name,
        "type": meta.node_type,
        "layer": meta.layer,
        "description": meta.description,
        "latest_status": "ok" if explain_latest else "partial",
        "last_run_at": latest_ctx.get("as_of"),
        "latest_output_summary": _make_summary(latest_primary, latest_secondary, metric=latest_metric, changed=previous_metric != latest_metric if previous_metric is not None else None),
        "previous_output_summary": previous_summary,
        "delta_summary": _node_delta_summary(latest_metric, previous_metric),
        "upstream_ids": list(meta.upstream_ids),
        "downstream_ids": list(meta.downstream_ids),
        "can_backfill": meta.can_backfill,
        "can_replay": meta.can_replay,
        "can_compare": meta.can_compare,
        "mapped_dataset": meta.dataset_key,
        "mapped_job_names": list(meta.replay_jobs),
        "representative_symbol": latest_ctx.get("symbol"),
    }


def _build_workflow_node(meta: OpsNodeMeta, runtime_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    runtime = runtime_lookup.get(meta.name) or runtime_lookup.get(meta.id.split(":", 1)[1]) or {}
    previous = runtime.get("previous") or {}
    latest_primary = str(runtime.get("status") or "unknown")
    latest_secondary = str(runtime.get("result_summary") or "") or "No recent workflow run."
    previous_summary = None
    if previous:
        previous_summary = _make_summary(str(previous.get("status") or "unknown"), str(previous.get("result_summary") or "") or None, metric=previous.get("elapsed_ms"), changed=(previous.get("status") != runtime.get("status")))
    return {
        "id": meta.id,
        "name": meta.name,
        "type": meta.node_type,
        "layer": meta.layer,
        "description": meta.description,
        "latest_status": _status_from_value(runtime.get("status")),
        "last_run_at": runtime.get("completed_at") or runtime.get("started_at"),
        "latest_output_summary": _make_summary(latest_primary, latest_secondary, metric=runtime.get("elapsed_ms"), changed=(previous.get("status") != runtime.get("status")) if previous else None),
        "previous_output_summary": previous_summary,
        "delta_summary": _node_delta_summary(runtime.get("elapsed_ms"), previous.get("elapsed_ms")),
        "upstream_ids": list(meta.upstream_ids),
        "downstream_ids": list(meta.downstream_ids),
        "can_backfill": meta.can_backfill,
        "can_replay": meta.can_replay,
        "can_compare": meta.can_compare,
        "mapped_dataset": meta.dataset_key,
        "mapped_job_names": list(meta.replay_jobs or meta.backfill_jobs),
        "representative_symbol": None,
    }


def build_ops_compute_layers(data_root: str, db, state_svc, explain_svc, *, as_of_date: str | None = None) -> dict[str, Any]:
    as_of, previous_as_of = _get_asof_dates(db, as_of_date)
    representative_symbol = _pick_representative_symbol(db, as_of)
    latest_ctx = _build_symbol_context(explain_svc, representative_symbol, as_of)
    previous_ctx = _build_symbol_context(explain_svc, representative_symbol, previous_as_of) if previous_as_of else {"symbol": representative_symbol, "as_of": previous_as_of, "state": {}, "explain": {}, "causal": {}}
    signal_latest = _latest_signal_row(db, representative_symbol, as_of) if representative_symbol else {}
    signal_previous = _latest_signal_row(db, representative_symbol, previous_as_of) if representative_symbol and previous_as_of else {}
    if signal_latest:
        with db._conn_lock:
            row = db._conn.execute("SELECT COUNT(*) AS count FROM signals WHERE date = ?", (as_of,)).fetchone()
        signal_latest["signal_count"] = int(row["count"] or 0) if row else 0
    if signal_previous and previous_as_of:
        with db._conn_lock:
            row = db._conn.execute("SELECT COUNT(*) AS count FROM signals WHERE date = ?", (previous_as_of,)).fetchone()
        signal_previous["signal_count"] = int(row["count"] or 0) if row else 0

    readiness = build_readiness_grid(data_root, db, days=2, end_date=as_of, include_actions=True)
    readiness_rows = {str(item.get("dataset") or ""): item for item in readiness.get("rows") or []}
    job_lookup = _job_runtime_lookup(db, [item.replay_jobs[0] for item in OPS_NODE_CATALOG if item.replay_jobs])

    nodes: list[dict[str, Any]] = []
    for meta in OPS_NODE_CATALOG:
        if meta.node_type == "source":
            row = readiness_rows.get(meta.dataset_key or "")
            cells = row.get("cells") if row else []
            latest_cell = next((cell for cell in cells if cell.get("date") == as_of), None) if cells else None
            previous_cell = next((cell for cell in cells if previous_as_of and cell.get("date") == previous_as_of), None) if cells else None
            if latest_cell is None:
                latest_cell = {"status": "UNKNOWN", "row_count": None, "expected_count": None, "coverage_pct": None, "lag_days": None, "source_last_date": None}
            nodes.append(_build_source_node(meta, row or {}, latest_cell, previous_cell, representative_symbol=representative_symbol))
        elif meta.node_type == "feature":
            nodes.append(_build_feature_node(meta, latest_ctx, previous_ctx, signal_latest, signal_previous))
        elif meta.node_type == "factor":
            nodes.append(_build_factor_node(meta, latest_ctx, previous_ctx))
        elif meta.node_type == "model":
            nodes.append(_build_model_node(meta, latest_ctx, previous_ctx, signal_latest, signal_previous))
        elif meta.node_type == "decision":
            nodes.append(_build_decision_node(meta, latest_ctx, previous_ctx))
        else:
            nodes.append(_build_workflow_node(meta, job_lookup))

    groups: list[dict[str, Any]] = []
    for layer in OPS_LAYER_LABELS:
        layer_nodes = [node for node in nodes if node.get("layer") == layer]
        groups.append({
            "key": layer,
            "label": OPS_LAYER_LABELS[layer],
            "nodes": layer_nodes,
        })
    return {
        "as_of": as_of,
        "previous_as_of": previous_as_of,
        "representative_symbol": representative_symbol,
        "layers": groups,
        "nodes": nodes,
    }


def get_ops_node_result(data_root: str, db, state_svc, explain_svc, *, node_id: str, as_of_date: str | None = None) -> dict[str, Any]:
    payload = build_ops_compute_layers(data_root, db, state_svc, explain_svc, as_of_date=as_of_date)
    node = next((item for item in payload.get("nodes") or [] if item.get("id") == node_id), None)
    if node is None:
        raise ValueError(f"Unknown ops node: {node_id}")
    catalog = _catalog_map()
    meta = catalog[node_id]
    representative_symbol = payload.get("representative_symbol")
    latest_ctx = _build_symbol_context(explain_svc, representative_symbol, payload.get("as_of"))
    previous_ctx = _build_symbol_context(explain_svc, representative_symbol, payload.get("previous_as_of")) if payload.get("previous_as_of") else {"state": {}, "explain": {}, "causal": {}}
    dependency = build_ops_dependency_path([node_id])
    details: dict[str, Any] = {"kind": meta.node_type}

    if meta.node_type == "source":
        readiness = build_readiness_grid(data_root, db, days=7, end_date=payload.get("as_of"), datasets=[meta.dataset_key] if meta.dataset_key else None)
        row = (readiness.get("rows") or [{}])[0]
        details = {
            "kind": "source",
            "readiness_row": row,
            "affected_outputs": row.get("impacts") or [],
            "mapped_job_names": list(meta.backfill_jobs or meta.replay_jobs),
        }
    elif meta.node_type == "feature":
        details = {
            "kind": "feature",
            "symbol": representative_symbol,
            "state": latest_ctx.get("state"),
            "previous_state": previous_ctx.get("state"),
        }
    elif meta.node_type == "factor":
        factor_lookup = _factor_lookup(latest_ctx.get("causal") or {})
        previous_lookup = _factor_lookup(previous_ctx.get("causal") or {})
        factor_type = meta.id.split(":", 1)[1]
        details = {
            "kind": "factor",
            "symbol": representative_symbol,
            "latest_factor": factor_lookup.get(factor_type),
            "previous_factor": previous_lookup.get(factor_type),
        }
    elif meta.node_type == "model":
        details = {
            "kind": "model",
            "symbol": representative_symbol,
            "latest_state": latest_ctx.get("state"),
            "previous_state": previous_ctx.get("state"),
            "latest_explain": latest_ctx.get("explain"),
            "previous_explain": previous_ctx.get("explain"),
            "latest_causal": latest_ctx.get("causal"),
            "previous_causal": previous_ctx.get("causal"),
        }
    elif meta.node_type == "decision":
        details = {
            "kind": "decision",
            "symbol": representative_symbol,
            "latest_explain": latest_ctx.get("explain"),
            "previous_explain": previous_ctx.get("explain"),
        }
    else:
        with db._conn_lock:
            rows = db._conn.execute(
                """
                SELECT id, job_name, stage, status, result_summary, started_at, completed_at, elapsed_ms
                FROM job_runs
                WHERE job_name = ?
                ORDER BY id DESC
                LIMIT 8
                """,
                (meta.name,),
            ).fetchall()
        details = {
            "kind": "workflow",
            "recent_runs": [dict(row) for row in rows],
        }

    return {
        **node,
        "as_of": payload.get("as_of"),
        "previous_as_of": payload.get("previous_as_of"),
        "representative_symbol": representative_symbol,
        "dependency_path": dependency,
        "details": details,
    }


def build_ops_dependency_path(selected_node_ids: list[str], *, include_neighbors: bool = True) -> dict[str, Any]:
    catalog = _catalog_map()
    selected = [catalog[item] for item in _normalize_ids(selected_node_ids) if item in catalog]
    node_ids: set[str] = {item.id for item in selected}
    edges: set[tuple[str, str]] = set()
    if include_neighbors:
        for item in selected:
            node_ids.update(item.upstream_ids)
            node_ids.update(item.downstream_ids)
    for meta in OPS_NODE_CATALOG:
        for child in meta.downstream_ids:
            if meta.id in node_ids and child in node_ids:
                edges.add((meta.id, child))
    return {
        "selected_node_ids": [item.id for item in selected],
        "nodes": [
            {
                "id": meta.id,
                "name": meta.name,
                "type": meta.node_type,
                "layer": meta.layer,
                "description": meta.description,
            }
            for meta in OPS_NODE_CATALOG
            if meta.id in node_ids
        ],
        "edges": [{"from": src, "to": dst} for src, dst in sorted(edges)],
        "upstream_ids": sorted({item for meta in selected for item in meta.upstream_ids}),
        "downstream_ids": sorted({item for meta in selected for item in meta.downstream_ids}),
    }


def _descendants(node_ids: list[str]) -> set[str]:
    catalog = _catalog_map()
    queue = list(node_ids)
    seen = set(node_ids)
    while queue:
        current = queue.pop(0)
        meta = catalog.get(current)
        if meta is None:
            continue
        for child in meta.downstream_ids:
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return seen


def _ancestors(node_ids: list[str]) -> set[str]:
    catalog = _catalog_map()
    upstream_map: dict[str, set[str]] = {}
    for meta in OPS_NODE_CATALOG:
        for child in meta.downstream_ids:
            upstream_map.setdefault(child, set()).add(meta.id)
    queue = list(node_ids)
    seen = set(node_ids)
    while queue:
        current = queue.pop(0)
        for parent in upstream_map.get(current, set()):
            if parent not in seen:
                seen.add(parent)
                queue.append(parent)
    return seen


def _selection_from_cells(selected_cells: list[dict[str, Any]] | None) -> list[str]:
    result: list[str] = []
    for cell in selected_cells or []:
        dataset = str((cell or {}).get("dataset") or "").strip()
        if dataset:
            result.append(f"source:{dataset}")
    return result


def build_ops_replay_preview(
    db,
    *,
    selected_node_ids: list[str] | None = None,
    selected_cells: list[dict[str, Any]] | None = None,
    date_from: str,
    date_to: str,
    mode: str,
    action: str = "recompute",
) -> dict[str, Any]:
    normalized_nodes = _normalize_ids((selected_node_ids or []) + _selection_from_cells(selected_cells))
    catalog = _catalog_map()
    selected = [catalog[item] for item in normalized_nodes if item in catalog]
    if mode not in {"selected_only", "selected_plus_downstream", "full_chain"}:
        raise ValueError("mode must be one of selected_only, selected_plus_downstream, full_chain")
    if action not in {"repair", "recompute"}:
        raise ValueError("action must be one of repair or recompute")

    if mode == "selected_only":
        scoped_ids = set(item.id for item in selected)
    elif mode == "selected_plus_downstream":
        scoped_ids = _descendants([item.id for item in selected])
    else:
        scoped_ids = _descendants([item.id for item in selected]) | _ancestors([item.id for item in selected])

    scoped_nodes = [catalog[item] for item in scoped_ids if item in catalog]
    average_ms = _job_average_duration_map(db, [job for node in scoped_nodes for job in (*node.backfill_jobs, *node.replay_jobs)])
    jobs_to_run: list[dict[str, Any]] = []
    warnings: list[str] = []
    downstream_affected: set[str] = set()

    for node in scoped_nodes:
        downstream_affected.update(node.downstream_ids)
        target_jobs = node.backfill_jobs if action == "repair" and node.can_backfill else node.replay_jobs
        if not target_jobs and node.can_replay and action == "recompute":
            target_jobs = node.replay_jobs
        if action == "repair" and not node.can_backfill:
            warnings.append(f"{node.name} is not a source-repair target; it will be skipped.")
            continue
        if action == "recompute" and not node.can_replay:
            warnings.append(f"{node.name} is view-only in the current graph; no direct recompute job is mapped.")
            continue
        for job_name in target_jobs:
            jobs_to_run.append({
                "job_name": job_name,
                "mapped_from": node.id,
                "layer": node.layer,
                "node_type": node.node_type,
                "avg_duration_ms": average_ms.get(job_name),
            })

    deduped_jobs: list[dict[str, Any]] = []
    seen_jobs: set[str] = set()
    for item in jobs_to_run:
        job_name = str(item.get("job_name") or "")
        if not job_name or job_name in seen_jobs:
            continue
        seen_jobs.add(job_name)
        deduped_jobs.append(item)

    impacted_layers = sorted({catalog[item].layer for item in downstream_affected if item in catalog})
    return {
        "selected_nodes": [
            {
                "id": node.id,
                "name": node.name,
                "type": node.node_type,
                "layer": node.layer,
            }
            for node in selected
        ],
        "selected_cells": selected_cells or [],
        "mode": mode,
        "action": action,
        "date_from": date_from,
        "date_to": date_to,
        "nodes_to_run": deduped_jobs,
        "downstream_affected": [
            {
                "id": catalog[item].id,
                "name": catalog[item].name,
                "type": catalog[item].node_type,
                "layer": catalog[item].layer,
            }
            for item in sorted(downstream_affected)
            if item in catalog
        ],
        "warnings": warnings,
        "estimated_scope": {
            "selected_count": len(selected),
            "node_count": len(scoped_nodes),
            "job_count": len(deduped_jobs),
            "layers": impacted_layers,
            "estimated_duration_ms": sum(int(item.get("avg_duration_ms") or 0) for item in deduped_jobs),
        },
    }


def execute_ops_replay(
    data_root: str,
    db,
    *,
    selected_node_ids: list[str] | None,
    selected_cells: list[dict[str, Any]] | None,
    date_from: str,
    date_to: str,
    mode: str,
    action: str = "recompute",
) -> dict[str, Any]:
    from trade_py.engine import run_node

    preview = build_ops_replay_preview(
        db,
        selected_node_ids=selected_node_ids,
        selected_cells=selected_cells,
        date_from=date_from,
        date_to=date_to,
        mode=mode,
        action=action,
    )
    job_names = [str(item.get("job_name") or "") for item in preview.get("nodes_to_run") or [] if str(item.get("job_name") or "").strip()]
    if not job_names:
        raise ValueError("No runnable jobs resolved from the selected nodes.")

    title = (
        "Repair selected source nodes"
        if action == "repair"
        else "Recompute selected compute layers"
    )
    payload = {
        "title": title,
        "goal": title,
        "workflow_kind": "ops_replay_builder",
        "selected_node_ids": selected_node_ids or [],
        "selected_cells": selected_cells or [],
        "mode": mode,
        "action": action,
        "date_from": date_from,
        "date_to": date_to,
        "job_names": job_names,
        "job_plan": preview.get("nodes_to_run") or [],
        "preview": preview,
    }
    root_event_id = db.event_log_insert(
        "ops.workspace.replay",
        json.dumps(payload, ensure_ascii=False),
        parent_event_id=None,
    )

    def _run() -> None:
        started = datetime.now(UTC)
        try:
            for item in preview.get("nodes_to_run") or []:
                job_name = str(item.get("job_name") or "")
                if not job_name:
                    continue
                step_payload = {
                    "title": f"{title} · {job_name}",
                    "job_name": job_name,
                    "stage": item.get("layer"),
                    "mapped_from": item.get("mapped_from"),
                    "date_from": date_from,
                    "date_to": date_to,
                }
                step_event_id = db.event_log_insert(
                    "ops.workspace.replay.step",
                    json.dumps(step_payload, ensure_ascii=False),
                    parent_event_id=root_event_id,
                )
                run_id = db.job_run_start(job_name, stage=str(item.get("layer") or "") or None, trigger_event_id=step_event_id)
                step_started = datetime.now(UTC)
                try:
                    summary = run_node(job_name, str(data_root), date_from=date_from, date_to=date_to)
                    elapsed_ms = int((datetime.now(UTC) - step_started).total_seconds() * 1000)
                    db.job_run_finish(run_id, "ok", result_summary=summary, elapsed_ms=elapsed_ms)
                    db.event_log_complete(step_event_id, "ok", job_name, elapsed_ms=elapsed_ms)
                except Exception as exc:
                    elapsed_ms = int((datetime.now(UTC) - step_started).total_seconds() * 1000)
                    db.job_run_finish(run_id, "error", result_summary=str(exc)[:500], elapsed_ms=elapsed_ms)
                    db.event_log_complete(step_event_id, "error", job_name, error=str(exc)[:500], elapsed_ms=elapsed_ms)
                    raise
            total_elapsed = int((datetime.now(UTC) - started).total_seconds() * 1000)
            db.event_log_complete(root_event_id, "ok", "ops.workspace.replay", elapsed_ms=total_elapsed)
        except Exception as exc:
            total_elapsed = int((datetime.now(UTC) - started).total_seconds() * 1000)
            logger.exception("ops replay workflow %s failed", root_event_id)
            db.event_log_complete(root_event_id, "error", "ops.workspace.replay", error=str(exc)[:500], elapsed_ms=total_elapsed)

    Thread(target=_run, name=f"ops-replay-{root_event_id}", daemon=True).start()
    return {
        "accepted": True,
        "workflow_event_id": root_event_id,
        "preview": preview,
    }
