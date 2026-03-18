"""FastAPI application — TradeDB Web API + UI host.

Routes:
  GET  /                         → web app shell (React dist or legacy console)
  GET  /api/dag                  → pipeline_dag table (stage-grouped)
  GET  /api/dag/runtime          → DAG runtime state + latest runs/errors
  POST /api/dag/{id}/enable      → enable a DAG node
  POST /api/dag/{id}/disable     → disable a DAG node
  PATCH /api/dag/{id}/config     → update config_json for a DAG node
  POST /api/dag/{id}/run         → run a DAG node (supports date_from/date_to)
  POST /api/trigger              → publish event to bus
  POST /api/run                  → run a high-level workflow target
  GET  /api/events               → event_log recent N entries
  GET  /api/workflows            → recent workflow traces
  GET  /api/workflows/{id}       → workflow detail
  GET  /api/runs                 → job_runs recent N entries
  GET  /api/models               → model_registry list
  GET  /api/status               → service health + quality gate + agenda + backups
  GET  /api/calendar             → trading calendar + planned events
  GET  /api/agenda               → recent agenda queue
  GET  /api/data-health          → data freshness / coverage snapshot
  GET  /api/backups              → backup snapshots
  GET  /api/today-page           → market snapshot + pipeline health + top 5 picks
  GET  /api/signals-page         → top 50 picks with delta + reasons skeleton
  GET  /api/kline/{symbol}       → OHLCV + indicators + event markers + recommendation
  POST /predict                  → online inference endpoint
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from threading import Thread
from typing import Any

try:  # pragma: no cover - optional at import time
    from fastapi import Request as FastAPIRequest
except Exception:  # pragma: no cover - fastapi missing outside web usage
    FastAPIRequest = Any

try:  # pragma: no cover - optional at import time
    from fastapi import BackgroundTasks as FastAPIBackgroundTasks
except Exception:  # pragma: no cover - fastapi missing outside web usage
    FastAPIBackgroundTasks = Any

logger = logging.getLogger(__name__)


def _parse_iso_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _lag_days(value: str | None) -> int | None:
    d = _parse_iso_date(value)
    if not d:
        return None
    return (date.today() - d).days


def _parse_iso_datetime(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _tree_latest_date(root: Path) -> str | None:
    if not root.exists():
        return None
    latest = None
    for path in root.rglob("*.parquet"):
        stem = path.stem
        if len(stem) == 10 and stem[4] == "-" and stem[7] == "-":
            latest = stem if latest is None else max(latest, stem)
    return latest


def _hive_status(*, lag_days: int | None = None, coverage_pct: float | None = None,
                 count: int | None = None, empty_is_error: bool = False) -> str:
    if count is not None and empty_is_error and count <= 0:
        return "error"
    if coverage_pct is not None:
        if coverage_pct < 0.5:
            return "error"
        if coverage_pct < 0.85:
            return "partial"
    if lag_days is not None:
        if lag_days > 7:
            return "error"
        if lag_days > 2:
            return "partial"
    return "ok"


def create_app():
    """FastAPI app factory (used by uvicorn --factory)."""
    try:
        from fastapi import Body, FastAPI, HTTPException
        from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
        from fastapi.staticfiles import StaticFiles
        from pydantic import BaseModel
    except ImportError:
        raise ImportError("fastapi required: uv add fastapi uvicorn")

    data_root = os.environ.get("TRADE_DATA_ROOT", "data")
    shutdown_event = asyncio.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            shutdown_event.set()

    app = FastAPI(title="TradeDB Console", version="1.0", lifespan=lifespan)

    # Lazy-init inference service
    from trade_web.backend.inference import InferenceService
    _inference = InferenceService(data_root)
    _payload_cache: dict[str, dict[str, Any]] = {}
    _payload_cache_lock = Lock()

    # ── DB helper ─────────────────────────────────────────────────────────────

    def _db():
        from trade_py.db.trade_db import TradeDB
        return TradeDB(data_root)

    def _payload_signature(kind: str) -> str:
        db = _db()
        with db._conn_lock:
            row = db._conn.execute(
                """
                SELECT
                    COALESCE((SELECT MAX(updated_at) FROM daily_quality_gate), ''),
                    COALESCE((SELECT MAX(id) FROM job_runs), 0),
                    COALESCE((SELECT MAX(id) FROM event_log), 0),
                    COALESCE((SELECT MAX(updated_at) FROM agenda_queue), ''),
                    COALESCE((SELECT MAX(updated_at) FROM planned_events), ''),
                    COALESCE((SELECT MAX(trained_at) FROM model_registry), ''),
                    COALESCE((SELECT MAX(updated_at) FROM sync_state), ''),
                    COALESCE((SELECT MAX(updated_at) FROM kg_relations), ''),
                    COALESCE((SELECT MAX(generated_at) FROM kg_edge_candidates), ''),
                    COALESCE((SELECT MAX(created_at) FROM market_events), ''),
                    COALESCE((SELECT MAX(validated_at) FROM event_propagations), ''),
                    COALESCE((SELECT MAX(updated_at) FROM settings), '')
                """
            ).fetchone()
        base = "|".join(str(item or "") for item in (row or ()))
        return f"{kind}:{date.today().isoformat()}:{base}"

    def _cache_get(name: str, *, signature: str, ttl_seconds: float) -> dict[str, Any] | None:
        now = time.monotonic()
        with _payload_cache_lock:
            entry = _payload_cache.get(name)
            if not entry:
                return None
            if entry.get("signature") != signature:
                return None
            if now - float(entry.get("built_at", 0.0)) > ttl_seconds:
                return None
            return entry.get("payload")

    def _cache_set(name: str, *, signature: str, payload: dict[str, Any]) -> dict[str, Any]:
        with _payload_cache_lock:
            _payload_cache[name] = {
                "signature": signature,
                "built_at": time.monotonic(),
                "payload": payload,
            }
        return payload

    def _snapshot_get_or_build(
        name: str,
        *,
        signature: str,
        ttl_seconds: float,
        scope: str = "default",
        builder,
    ) -> dict[str, Any]:
        cached = _cache_get(name, signature=signature, ttl_seconds=ttl_seconds)
        if cached is not None:
            return cached
        db = _db()
        stored = db.ui_snapshot_get(name, scope=scope)
        if stored and str(stored.get("signature") or "") == signature:
            payload = stored.get("payload_json") or {}
            if isinstance(payload, dict):
                payload.setdefault("cached", True)
            return _cache_set(name, signature=signature, payload=payload)
        started = time.monotonic()
        payload = builder()
        build_ms = int((time.monotonic() - started) * 1000)
        db.ui_snapshot_upsert(
            name,
            signature,
            payload,
            scope=scope,
            ttl_seconds=int(max(1, ttl_seconds)),
            status="ok",
            build_ms=build_ms,
            producer="trade_web",
        )
        return _cache_set(name, signature=signature, payload=payload)

    async def _stream_wait(poll_seconds: float) -> bool:
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=max(0.25, float(poll_seconds)))
            return True
        except asyncio.TimeoutError:
            return shutdown_event.is_set()

    def _light_health_snapshot(db, gate: dict[str, Any]) -> dict[str, Any]:
        metrics = gate.get("metrics_json") or {}
        fund_cov = metrics.get("fund_flow_coverage")
        fundamental_cov = metrics.get("fundamental_coverage")
        event_count = metrics.get("event_count")
        items = [
            {"status": _hive_status(coverage_pct=fund_cov), "domain": "market"},
            {"status": _hive_status(coverage_pct=fundamental_cov), "domain": "market"},
            {"status": _hive_status(count=event_count, empty_is_error=True), "domain": "event"},
        ]
        summary = {
            "total": len(items),
            "ok": sum(1 for item in items if item["status"] == "ok"),
            "partial": sum(1 for item in items if item["status"] == "partial"),
            "error": sum(1 for item in items if item["status"] == "error"),
        }
        domains = {
            "market": {
                "count": 2,
                "ok": sum(1 for item in items[:2] if item["status"] == "ok"),
                "partial": sum(1 for item in items[:2] if item["status"] == "partial"),
                "error": sum(1 for item in items[:2] if item["status"] == "error"),
            },
            "event": {
                "count": 1,
                "ok": 1 if items[2]["status"] == "ok" else 0,
                "partial": 1 if items[2]["status"] == "partial" else 0,
                "error": 1 if items[2]["status"] == "error" else 0,
            },
        }
        highlights = [
            {"kind": "coverage", "title": "Fund Flow Coverage", "value": round(float(fund_cov or 0.0) * 100, 1)},
            {"kind": "coverage", "title": "Fundamental Coverage", "value": round(float(fundamental_cov or 0.0) * 100, 1)},
            {"kind": "event", "title": "Recent Event Count", "value": int(event_count or 0)},
        ]
        datasets = [
            {
                "id": "fund_flow",
                "name": "Fund Flow",
                "domain": "market",
                "status": items[0]["status"],
                "coverage_pct": fund_cov,
                "freshness_date": None,
                "lineage": "fund-flow -> factors -> signals",
            },
            {
                "id": "fundamental",
                "name": "Fundamental",
                "domain": "market",
                "status": items[1]["status"],
                "coverage_pct": fundamental_cov,
                "freshness_date": None,
                "lineage": "fundamental -> factors -> signals",
            },
            {
                "id": "events",
                "name": "Events",
                "domain": "event",
                "status": items[2]["status"],
                "coverage_pct": None,
                "freshness_date": None,
                "lineage": "sentiment -> market_events -> propagations",
            },
        ]
        return {
            "datasets": datasets,
            "domains": domains,
            "highlights": highlights,
            "summary": summary,
            "as_of": date.today().isoformat(),
            "cached": False,
        }

    def _data_health_payload() -> dict[str, Any]:
        from trade_py.utils.data_inspector import get_data_status

        db = _db()
        gate = db.quality_gate_get() or {}
        gate_metrics = gate.get("metrics_json") or {}
        status = get_data_status(data_root, sample_limit=8)
        sentiment = status.get("sentiment", {})
        kline = status.get("kline", {})
        kline_cov = status.get("kline_coverage", {})
        kline_fresh = status.get("kline_freshness", {})
        instruments = status.get("instruments", {})
        events = status.get("events", {})
        silver = sentiment.get("silver", {})
        gold = sentiment.get("gold", {})

        fund_flow_latest = _tree_latest_date(Path(data_root) / "market" / "fund_flow")
        fundamental_latest = _tree_latest_date(Path(data_root) / "market" / "fundamental")

        model_rows = db.model_registry_list()
        active_models = [row for row in model_rows if row.get("is_active") or row.get("promotion_state") == "active"]
        due_agenda = db.agenda_queue_due(limit=20)
        planned_events = db.planned_events_list(
            start_date=date.today().isoformat(),
            end_date=(date.today() + timedelta(days=7)).isoformat(),
            limit=50,
        )

        datasets = [
            {
                "id": "kline",
                "name": "Kline",
                "domain": "market",
                "refresh_target": "sync",
                "lineage": "market-index -> kline -> factors -> signals",
                "freshness_date": kline.get("max_date"),
                "lag_days": _lag_days(kline.get("max_date")),
                "coverage_pct": (kline_cov.get("coverage_pct") or 0.0) / 100.0 if kline_cov.get("coverage_pct") is not None else None,
                "rows": kline.get("rows", 0),
                "count": kline.get("symbols", 0),
                "status": _hive_status(
                    lag_days=_lag_days(kline.get("max_date")),
                    coverage_pct=((kline_cov.get("coverage_pct") or 0.0) / 100.0) if kline_cov.get("coverage_pct") is not None else None,
                    count=kline.get("symbols", 0),
                    empty_is_error=True,
                ),
                "notes": [
                    f"missing_symbols={kline_cov.get('missing_symbols', 0)}",
                    f"stale_ge_5={kline_fresh.get('stale_ge_5', 0)}",
                ],
            },
            {
                "id": "fund_flow",
                "name": "Fund Flow",
                "domain": "market",
                "refresh_target": "sync",
                "lineage": "fund-flow -> window/factors -> signals",
                "freshness_date": fund_flow_latest,
                "lag_days": _lag_days(fund_flow_latest),
                "coverage_pct": gate_metrics.get("fund_flow_coverage"),
                "rows": None,
                "count": None,
                "status": _hive_status(
                    lag_days=_lag_days(fund_flow_latest),
                    coverage_pct=gate_metrics.get("fund_flow_coverage"),
                ),
                "notes": [],
            },
            {
                "id": "fundamental",
                "name": "Fundamental",
                "domain": "market",
                "refresh_target": "sync",
                "lineage": "fundamental -> instrument/factors -> signals",
                "freshness_date": fundamental_latest,
                "lag_days": _lag_days(fundamental_latest),
                "coverage_pct": gate_metrics.get("fundamental_coverage"),
                "rows": None,
                "count": None,
                "status": _hive_status(
                    lag_days=_lag_days(fundamental_latest),
                    coverage_pct=gate_metrics.get("fundamental_coverage"),
                ),
                "notes": [],
            },
            {
                "id": "sector_map",
                "name": "Sector Map",
                "domain": "reference",
                "refresh_target": "sync",
                "lineage": "reference -> event targets -> KG / features",
                "freshness_date": None,
                "lag_days": None,
                "coverage_pct": (instruments.get("coverage_pct") or 0.0) / 100.0 if instruments.get("coverage_pct") is not None else None,
                "rows": instruments.get("sector_member_rows", 0),
                "count": instruments.get("total_symbols", 0),
                "status": _hive_status(
                    coverage_pct=((instruments.get("coverage_pct") or 0.0) / 100.0) if instruments.get("coverage_pct") is not None else None,
                    count=instruments.get("total_symbols", 0),
                    empty_is_error=True,
                ),
                "notes": [f"unmapped={instruments.get('unmapped', 0)}"],
            },
            {
                "id": "sentiment_silver",
                "name": "Sentiment Silver",
                "domain": "sentiment",
                "refresh_target": "evening",
                "lineage": "bronze -> silver -> gold -> market_events",
                "freshness_date": silver.get("max_date"),
                "lag_days": _lag_days(silver.get("max_date")),
                "coverage_pct": None,
                "rows": silver.get("rows", 0),
                "count": silver.get("dates", 0),
                "status": _hive_status(
                    lag_days=_lag_days(silver.get("max_date")),
                    count=silver.get("dates", 0),
                    empty_is_error=True,
                ),
                "notes": [],
            },
            {
                "id": "sentiment_gold",
                "name": "Sentiment Gold",
                "domain": "sentiment",
                "refresh_target": "evening",
                "lineage": "silver -> gold -> market_events -> propagation",
                "freshness_date": gold.get("max_date"),
                "lag_days": _lag_days(gold.get("max_date")),
                "coverage_pct": None,
                "rows": gold.get("rows", 0),
                "count": gold.get("dates", 0),
                "status": _hive_status(
                    lag_days=_lag_days(gold.get("max_date")),
                    count=gold.get("dates", 0),
                    empty_is_error=True,
                ),
                "notes": [],
            },
            {
                "id": "events",
                "name": "Market Events",
                "domain": "event",
                "refresh_target": "evening",
                "lineage": "event_pipeline -> propagations -> factors/signals",
                "freshness_date": events.get("max_date"),
                "lag_days": _lag_days(events.get("max_date")),
                "coverage_pct": None,
                "rows": events.get("propagation_count", 0),
                "count": events.get("event_count", 0),
                "status": _hive_status(
                    lag_days=_lag_days(events.get("max_date")),
                    count=events.get("event_count", 0),
                    empty_is_error=True,
                ),
                "notes": [f"propagations={events.get('propagation_count', 0)}"],
            },
            {
                "id": "planned_events",
                "name": "Planned Events",
                "domain": "calendar",
                "refresh_target": "sync",
                "lineage": "planned_events -> agenda -> realized market_events",
                "freshness_date": planned_events[0].get("scheduled_at", "")[:10] if planned_events else None,
                "lag_days": None,
                "coverage_pct": None,
                "rows": len(planned_events),
                "count": len(planned_events),
                "status": _hive_status(count=len(planned_events), empty_is_error=True),
                "notes": [f"due_agenda={len(due_agenda)}"],
            },
            {
                "id": "models",
                "name": "Active Models",
                "domain": "model",
                "refresh_target": "evaluate",
                "lineage": "features -> train/evaluate -> active models -> signals",
                "freshness_date": active_models[0].get("trained_at", "")[:10] if active_models else None,
                "lag_days": _lag_days(active_models[0].get("trained_at", "")[:10] if active_models else None),
                "coverage_pct": None,
                "rows": len(model_rows),
                "count": len(active_models),
                "status": _hive_status(
                    lag_days=_lag_days(active_models[0].get("trained_at", "")[:10] if active_models else None),
                    count=len(active_models),
                    empty_is_error=True,
                ),
                "notes": [],
            },
        ]
        by_domain: dict[str, dict[str, Any]] = {}
        for item in datasets:
            bucket = by_domain.setdefault(item["domain"], {"count": 0, "ok": 0, "partial": 0, "error": 0})
            bucket["count"] += 1
            bucket[item["status"]] = bucket.get(item["status"], 0) + 1
        highlights = [
            {
                "kind": "coverage",
                "title": "Kline missing symbols",
                "value": kline_cov.get("missing_symbols", 0),
            },
            {
                "kind": "freshness",
                "title": "Kline stale >=5d",
                "value": kline_fresh.get("stale_ge_5", 0),
            },
            {
                "kind": "mapping",
                "title": "Unmapped instruments",
                "value": instruments.get("unmapped", 0),
            },
        ]
        summary = {
            "total": len(datasets),
            "ok": sum(1 for item in datasets if item["status"] == "ok"),
            "partial": sum(1 for item in datasets if item["status"] == "partial"),
            "error": sum(1 for item in datasets if item["status"] == "error"),
        }
        return {
            "datasets": datasets,
            "domains": by_domain,
            "highlights": highlights,
            "summary": summary,
            "as_of": date.today().isoformat(),
            "cached": True,
        }

    def _pick_workflow_focus(workflows: list[dict[str, Any]], db) -> dict[str, Any] | None:
        if not workflows:
            return None
        preferred = next(
            (row for row in workflows if str(row.get("status") or "") in {"error", "running", "partial"}),
            workflows[0],
        )
        root_event_id = int(preferred.get("root_event_id") or 0)
        if root_event_id <= 0:
            return None
        return db.event_workflow_detail(root_event_id)

    def _workflow_graph(nodes: list[dict[str, Any]]) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
        by_emits: dict[str, list[int]] = {}
        node_ids: set[int] = set()
        for node in nodes:
            dag_id = int(node.get("dag_id") or 0)
            if dag_id <= 0:
                continue
            node_ids.add(dag_id)
            emits = str(node.get("emits") or "").strip()
            if emits:
                by_emits.setdefault(emits, []).append(dag_id)
        predecessors: dict[int, list[int]] = {}
        successors: dict[int, list[int]] = {dag_id: [] for dag_id in node_ids}
        for node in nodes:
            dag_id = int(node.get("dag_id") or 0)
            if dag_id <= 0:
                continue
            source = str(node.get("source") or "").strip()
            preds = list(by_emits.get(source) or [])
            predecessors[dag_id] = preds
            for pred in preds:
                successors.setdefault(pred, []).append(dag_id)
        return predecessors, successors

    def _collect_ancestors(start_id: int, predecessors: dict[int, list[int]]) -> set[int]:
        seen: set[int] = set()
        stack = list(predecessors.get(start_id) or [])
        while stack:
            current = int(stack.pop())
            if current in seen:
                continue
            seen.add(current)
            stack.extend(predecessors.get(current) or [])
        return seen

    def _pick_upstream_replay_node(nodes: list[dict[str, Any]], dag_id: int) -> int:
        predecessors, _ = _workflow_graph(nodes)
        ancestors = _collect_ancestors(dag_id, predecessors)
        if not ancestors:
            return dag_id
        node_by_id = {int(node.get("dag_id") or 0): node for node in nodes}

        def _depth(node_id: int) -> int:
            depth = 0
            frontier = [node_id]
            seen: set[int] = set()
            while frontier:
                nxt: list[int] = []
                for current in frontier:
                    if current in seen:
                        continue
                    seen.add(current)
                    parents = predecessors.get(current) or []
                    if parents:
                        nxt.extend(parents)
                if nxt:
                    depth += 1
                frontier = nxt
            return depth

        preferred = [
            node_id for node_id in ancestors
            if str((node_by_id.get(node_id) or {}).get("status") or "") in {"error", "pending", "partial"}
        ] or list(ancestors)
        preferred.sort(key=lambda node_id: (_depth(node_id), node_id))
        return int(preferred[0]) if preferred else dag_id

    def _pick_root_replay_node(nodes: list[dict[str, Any]], dag_id: int) -> int:
        predecessors, _ = _workflow_graph(nodes)
        ancestors = _collect_ancestors(dag_id, predecessors)
        if not ancestors:
            return dag_id
        node_ids = set(ancestors)
        node_ids.add(dag_id)

        def _depth(node_id: int) -> int:
            depth = 0
            frontier = [node_id]
            seen: set[int] = set()
            while frontier:
                nxt: list[int] = []
                for current in frontier:
                    if current in seen:
                        continue
                    seen.add(current)
                    parents = predecessors.get(current) or []
                    if parents:
                        nxt.extend(parents)
                if nxt:
                    depth += 1
                frontier = nxt
            return depth

        return min(node_ids, key=lambda node_id: (_depth(node_id), node_id))

    def _report_page_payload() -> dict[str, Any]:
        db = _db()
        gate = db.quality_gate_get() or {}
        workflows = db.event_workflow_recent(limit=6)
        runtime = db.pipeline_dag_runtime(recent_limit=200)
        top_signals_model = db.signal_suggest(limit=5, by="model_score")
        top_signals_kg = db.signal_suggest(limit=5, by="event_kg_score")
        health = _light_health_snapshot(db, gate)
        due_agenda = db.agenda_queue_due(limit=6)
        planned_events = db.planned_events_list(
            start_date=date.today().isoformat(),
            end_date=(date.today() + timedelta(days=7)).isoformat(),
            limit=8,
        )
        recent_events = db.event_log_recent(limit=18)
        today_events = db.get_events(
            from_date=date.today().isoformat(),
            to_date=date.today().isoformat(),
            limit=18,
        )
        reasons = gate.get("reasons_json") or []
        metrics = gate.get("metrics_json") or {}
        operational_status = metrics.get("operational_status")
        research_status = metrics.get("research_status")
        root_causes = [row for row in workflows if row.get("root_cause")][:5]
        conclusion = {
            "headline": (
                "Daily operations ready"
                if operational_status == "ok" and gate.get("status") == "ok"
                else "Operationally ready, research still maturing"
                if operational_status == "ok"
                else "Pipeline needs attention"
            ),
            "gate_status": gate.get("status", "unknown"),
            "operational_status": operational_status,
            "research_status": research_status,
            "reason_summary": gate.get("reason_summary") or "",
            "reasons": reasons,
        }
        progress = {
            "workflow_total": len(workflows),
            "workflow_running": sum(1 for row in workflows if row.get("status") == "running"),
            "workflow_error": sum(1 for row in workflows if row.get("status") == "error"),
            "workflow_ok": sum(1 for row in workflows if row.get("status") == "ok"),
            "dag_stage_summary": runtime.get("stage_summary", {}),
        }
        return {
            "system": {
                "today": date.today().isoformat(),
                "data_root": data_root,
                "models_loaded_at": _inference.loaded_at,
                "inference_models": _inference.model_names,
            },
            "conclusion": conclusion,
            "progress": progress,
            "top_signals": {
                "model_score": top_signals_model,
                "event_kg_score": top_signals_kg,
            },
            "workflows": workflows,
            "root_causes": root_causes,
            "agenda": due_agenda,
            "planned_events": planned_events,
            "today_events": today_events,
            "recent_events": recent_events,
            "data_health": health,
            "dag_stage_summary": runtime.get("stage_summary", {}),
        }

    def _events_page_payload() -> dict[str, Any]:
        db = _db()
        today = date.today().isoformat()
        workflows = db.event_workflow_recent(limit=24)
        focus = _pick_workflow_focus(workflows, db)
        runtime = db.pipeline_dag_runtime(recent_limit=240)
        today_events = db.get_events(from_date=today, to_date=today, limit=200)
        recent_market_events = db.get_events(
            from_date=(date.today() - timedelta(days=7)).isoformat(),
            to_date=today,
            limit=120,
        )
        due_agenda = db.agenda_queue_due(limit=24)
        planned_events = db.planned_events_list(
            start_date=today,
            end_date=(date.today() + timedelta(days=3)).isoformat(),
            limit=40,
        )
        failed_nodes = [
            node for node in runtime.get("nodes", [])
            if str(node.get("status") or "") == "error"
        ][:20]
        return {
            "as_of": today,
            "workflows": workflows,
            "focus": focus,
            "dag": runtime,
            "today_events": today_events,
            "recent_market_events": recent_market_events,
            "due_agenda": due_agenda,
            "planned_events": planned_events,
            "failed_nodes": failed_nodes,
        }

    def _kg_page_payload() -> dict[str, Any]:
        from trade_py.domain.kg import SectorGraph

        db = _db()
        snapshot_path = SectorGraph.snapshot_path(data_root)
        snapshot = {}
        if snapshot_path.exists():
            try:
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except Exception:
                snapshot = {}
        active_relations = db.kg_relations_list(limit=40, active_only=True)
        candidates = db.kg_candidates(limit=40, status="pending")
        nodes = db.kg_nodes_list(limit=24)
        with db._conn_lock:
            top_symbols = [
                dict(row) for row in db._conn.execute(
                    """
                    SELECT ep.symbol,
                           COUNT(*) AS propagation_count,
                           ROUND(AVG(ep.kg_score), 4) AS avg_kg_score,
                           MAX(me.event_date) AS latest_event_date
                    FROM event_propagations ep
                    LEFT JOIN market_events me ON me.event_id = ep.event_id
                    GROUP BY ep.symbol
                    ORDER BY propagation_count DESC, avg_kg_score DESC
                    LIMIT 12
                    """
                ).fetchall()
            ]
            rel_type_summary = [
                dict(row) for row in db._conn.execute(
                    """
                    SELECT rel_type, COUNT(*) AS relation_count
                    FROM kg_relations
                    WHERE status='active' AND (valid_to IS NULL OR valid_to >= date('now'))
                    GROUP BY rel_type
                    ORDER BY relation_count DESC, rel_type
                    """
                ).fetchall()
            ]
        return {
            "snapshot": {
                "path": str(snapshot_path),
                "version": snapshot.get("version"),
                "generated_at": snapshot.get("generated_at"),
                "node_count": len(snapshot.get("nodes", [])),
                "edge_count": len(snapshot.get("edges", [])),
                "event_map_count": len(snapshot.get("event_mappings", {})),
            },
            "active_relations": active_relations,
            "candidates": candidates,
            "nodes": nodes,
            "top_symbols": top_symbols,
            "relation_types": rel_type_summary,
        }

    def _today_page_payload() -> dict[str, Any]:
        db = _db()
        gate = db.quality_gate_get() or {}
        runtime = db.pipeline_dag_runtime(recent_limit=200)

        # Pipeline health summary
        nodes = runtime.get("nodes", [])
        ok_count = sum(1 for n in nodes if str(n.get("status") or "") == "ok")
        error_count = sum(1 for n in nodes if str(n.get("status") or "") == "error")
        running_count = sum(1 for n in nodes if str(n.get("status") or "") == "running")
        total_count = len(nodes)

        pipeline_health = {
            "total": total_count,
            "ok": ok_count,
            "error": error_count,
            "running": running_count,
            "status": "ok" if error_count == 0 else ("partial" if ok_count > 0 else "error"),
        }

        # Top 5 picks with delta
        picks_data = db.signal_recommend(limit=5)
        top_picks = picks_data.get("picks", [])
        dropped = picks_data.get("dropped", [])

        # Recent job runs for pipeline context
        recent_runs = db.job_runs_recent(limit=10)

        # Kline sync state for market context
        try:
            kline_last = db.sync_state_get("tushare_kline", "daily", "")
            kline_last_date = kline_last.isoformat() if kline_last is not None else ""
        except Exception:
            kline_last_date = ""

        return {
            "as_of": date.today().isoformat(),
            "pipeline_health": pipeline_health,
            "top_picks": top_picks,
            "dropped_picks": dropped,
            "kline_last_date": kline_last_date,
            "gate_status": gate.get("status", "unknown"),
            "gate_reason": gate.get("reason_summary", ""),
            "recent_runs": recent_runs[:5],
            "error_nodes": [n for n in nodes if str(n.get("status") or "") == "error"][:5],
        }

    def _signals_page_payload() -> dict[str, Any]:
        db = _db()
        recommend = db.signal_recommend(limit=50)
        picks = recommend.get("picks", [])
        dropped = recommend.get("dropped", [])

        # Enrich each pick with instrument name
        for pick in picks:
            sym = str(pick.get("symbol") or "")
            if sym:
                try:
                    instr = db.instrument_lookup(sym)
                    pick["name"] = str(instr.get("name") or "") if instr else ""
                except Exception:
                    pick["name"] = ""

        return {
            "as_of": date.today().isoformat(),
            "picks": picks,
            "dropped": dropped,
            "total": len(picks),
        }

    # ── Static files ──────────────────────────────────────────────────────────

    repo_root = Path(__file__).resolve().parents[2]
    legacy_static_dir = Path(__file__).parent / "static"
    dist_dir = Path(
        os.environ.get("TRADE_WEB_DIST", str(repo_root / "trade_web" / "frontend" / "dist"))
    )
    static_dir = dist_dir if (dist_dir / "index.html").exists() else legacy_static_dir
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    if legacy_static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(legacy_static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return JSONResponse({"message": "Trade DAG API", "docs": "/docs"})

    # ── API: pipeline_dag ─────────────────────────────────────────────────────

    @app.get("/api/dag")
    async def get_dag(all: bool = False):
        rows = _db().pipeline_dag_all(enabled_only=not all)
        by_stage: dict[str, list] = {"fetch": [], "compute": [], "train": []}
        for r in rows:
            by_stage.setdefault(r["stage"], []).append(r)
        return {"stages": by_stage, "total": len(rows)}

    @app.get("/api/dag/runtime")
    async def get_dag_runtime(limit: int = 200):
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        return db.pipeline_dag_runtime(recent_limit=limit)

    @app.post("/api/dag/{dag_id}/enable")
    async def enable_dag(dag_id: int):
        _db().pipeline_dag_set_enabled(dag_id, True)
        return {"id": dag_id, "enabled": True}

    @app.post("/api/dag/{dag_id}/disable")
    async def disable_dag(dag_id: int):
        _db().pipeline_dag_set_enabled(dag_id, False)
        return {"id": dag_id, "enabled": False}

    @app.patch("/api/dag/{dag_id}/config")
    async def update_dag_config(dag_id: int, req: dict = Body(...)):
        """Update config_json for a pipeline_dag row."""
        import json as _json
        config_data = req.get("config") or {}
        if not isinstance(config_data, dict):
            raise HTTPException(status_code=400, detail="config must be a JSON object")
        config_json = _json.dumps(config_data, ensure_ascii=False)
        db = _db()
        row = db.pipeline_dag_get(dag_id)
        if not row:
            raise HTTPException(status_code=404, detail="dag row not found")
        db.pipeline_dag_update_config(dag_id, config_json)
        return {"id": dag_id, "config": config_data}

    @app.post("/api/dag/{dag_id}/run")
    async def run_dag_node(dag_id: int, req: dict = Body(...)):
        from trade_py.bus import bootstrap_from_dag, dispatch_dag_row, get_bus

        mode = str(req.get("mode") or "self").strip().lower()
        if mode not in {"self", "upstream", "downstream", "full"}:
            raise HTTPException(status_code=400, detail="mode must be one of self, upstream, downstream, full")
        payload = req.get("payload") or {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")
        date_from = str(req.get("date_from") or "").strip() or None
        date_to = str(req.get("date_to") or "").strip() or None
        db = _db()
        dag_row = db.pipeline_dag_get(dag_id)
        if not dag_row:
            raise HTTPException(status_code=404, detail="dag row not found")
        if not bool(dag_row.get("enabled")):
            raise HTTPException(status_code=409, detail="dag row is disabled")
        runtime_nodes = db.pipeline_dag_runtime(recent_limit=240).get("nodes", [])
        target_dag_id = dag_id
        if mode == "upstream":
            target_dag_id = _pick_upstream_replay_node(runtime_nodes, dag_id)
        elif mode == "full":
            target_dag_id = _pick_root_replay_node(runtime_nodes, dag_id)
        target_row = db.pipeline_dag_get(target_dag_id) or dag_row
        payload = dict(payload)
        if date_from:
            payload["date_from"] = date_from
        if date_to:
            payload["date_to"] = date_to
        payload["_dispatch"] = {
            "dag_id": dag_id,
            "target_dag_id": target_dag_id,
            "mode": mode,
        }
        bus = get_bus(db)
        bootstrap_from_dag(db, data_root)
        event = dispatch_dag_row(
            db,
            bus,
            data_root,
            target_row,
            payload,
            parent_event_id=None,
        )
        return {
            "accepted": True,
            "mode": mode,
            "dag_id": dag_id,
            "target_dag_id": int(target_row.get("id") or dag_id),
            "job_name": target_row.get("job_name"),
            "event_id": event.id,
            "topic": target_row.get("source"),
        }

    # ── API: trigger event ────────────────────────────────────────────────────

    @app.post("/api/trigger")
    async def trigger_event(req: dict = Body(...)):
        from trade_py.bus import get_bus, bootstrap_from_dag

        topic = str(req.get("topic") or "").strip()
        if not topic:
            raise HTTPException(status_code=400, detail="topic is required")
        payload = req.get("payload") or {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")
        db = _db()
        bus = get_bus(db)
        bootstrap_from_dag(db, data_root)
        event = bus.publish(topic, payload)
        return {"event_id": event.id, "topic": topic}

    @app.post("/api/run")
    async def run_target(req: dict = Body(...)):
        from trade_py.cli import run as run_cli

        target = str(req.get("target") or "").strip()
        if not target:
            raise HTTPException(status_code=400, detail="target is required")
        payload = req.get("payload") or {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")
        limit = max(1, int(req.get("limit") or 10))

        argv = [target, "--data-root", data_root]
        if target == "agenda":
            argv += ["--limit", str(limit)]
        if payload:
            import json as _json

            argv += ["--payload", _json.dumps(payload, ensure_ascii=False)]

        def _run_workflow() -> None:
            try:
                run_cli.main(argv)
            except Exception:
                logger.exception("web-triggered workflow failed: %s", target)

        Thread(target=_run_workflow, name=f"trade-web-run-{target}", daemon=True).start()
        return {"accepted": True, "target": target, "limit": limit}

    # ── API: event_log ────────────────────────────────────────────────────────

    @app.get("/api/events")
    async def get_events(limit: int = 50, topic: str | None = None):
        db = _db()
        db.event_log_mark_stale()
        return db.event_log_recent(limit, topic)

    @app.get("/api/workflows")
    async def get_workflows(limit: int = 20):
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        return db.event_workflow_recent(limit=limit)

    @app.get("/api/workflows/{root_event_id}")
    async def get_workflow_detail(root_event_id: int):
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        detail = db.event_workflow_detail(root_event_id)
        if not detail:
            raise HTTPException(status_code=404, detail="workflow not found")
        return detail

    @app.post("/api/workflows/{root_event_id}/rerun-node")
    async def rerun_workflow_node(root_event_id: int, req: dict = Body(...)):
        from trade_py.bus import bootstrap_from_dag, dispatch_dag_row, get_bus

        dag_id = int(req.get("dag_id") or req.get("node_id") or 0)
        if dag_id <= 0:
            raise HTTPException(status_code=400, detail="dag_id is required")
        mode = str(req.get("mode") or "self").strip().lower()
        if mode not in {"self", "upstream", "downstream", "full"}:
            raise HTTPException(status_code=400, detail="mode must be one of self, upstream, downstream, full")
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        detail = db.event_workflow_detail(root_event_id)
        if not detail:
            raise HTTPException(status_code=404, detail="workflow not found")
        node = next((row for row in detail.get("nodes", []) if int(row.get("dag_id") or 0) == dag_id), None)
        if not node:
            raise HTTPException(status_code=404, detail="dag node not found in workflow")
        dag_row = db.pipeline_dag_get(dag_id)
        if not dag_row:
            raise HTTPException(status_code=404, detail="dag row not found")
        if not bool(dag_row.get("enabled")):
            raise HTTPException(status_code=409, detail="dag row is disabled")

        payload = {}
        source_event = node.get("source_event") or {}
        source_payload = source_event.get("payload_json")
        if isinstance(source_payload, dict):
            payload = dict(source_payload)
        elif isinstance(detail.get("payload_json"), dict):
            payload = dict(detail.get("payload_json") or {})
        payload["_replay"] = {
            "root_event_id": root_event_id,
            "dag_id": dag_id,
            "job_name": node.get("job_name"),
            "mode": mode,
        }
        bus = get_bus(db)
        bootstrap_from_dag(db, data_root)
        target_row = dag_row
        if mode == "full":
            event = bus.publish(str(detail.get("topic") or ""), payload, parent_event_id=root_event_id)
            return {
                "accepted": True,
                "mode": mode,
                "root_event_id": root_event_id,
                "dag_id": dag_id,
                "job_name": node.get("job_name"),
                "event_id": event.id,
                "topic": detail.get("topic"),
                "target_dag_id": dag_id,
            }
        if mode == "upstream":
            upstream_dag_id = _pick_upstream_replay_node(detail.get("nodes") or [], dag_id)
            target_row = db.pipeline_dag_get(upstream_dag_id) or dag_row
        event = dispatch_dag_row(
            db,
            bus,
            data_root,
            target_row,
            payload,
            parent_event_id=root_event_id,
        )
        return {
            "accepted": True,
            "mode": mode,
            "root_event_id": root_event_id,
            "dag_id": dag_id,
            "target_dag_id": int(target_row.get("id") or dag_id),
            "job_name": target_row.get("job_name"),
            "event_id": event.id,
            "topic": target_row.get("source"),
        }

    # ── API: job_runs ─────────────────────────────────────────────────────────

    @app.get("/api/runs")
    async def get_runs(limit: int = 50, stage: str | None = None):
        db = _db()
        db.job_runs_mark_stale_by_policy()
        return db.job_runs_recent(limit, stage=stage)

    # ── API: model_registry ───────────────────────────────────────────────────

    @app.get("/api/models")
    async def get_models():
        return _db().model_registry_list()

    # ── API: status ───────────────────────────────────────────────────────────

    @app.get("/api/status")
    async def get_status():
        db = _db()
        today = date.today().isoformat()
        gate = db.quality_gate_get()
        try:
            from trade_py.backup import backup_doctor
            backup_health = backup_doctor(data_root)
        except Exception as exc:  # pragma: no cover - defensive web path
            logger.warning("backup doctor failed: %s", exc)
            backup_health = {
                "backend": "local",
                "enabled": False,
                "google_drive_available": False,
                "google_drive_folder_id": "",
                "google_drive_key_file": "",
            }
        return {
            "status": "ok",
            "data_root": data_root,
            "today": today,
            "inference_models": _inference.model_names,
            "models_loaded_at": _inference.loaded_at,
            "quality_gate": gate,
            "due_agenda": db.agenda_queue_due(limit=10),
            "planned_events": db.planned_events_list(
                start_date=today,
                end_date=(date.today() + timedelta(days=7)).isoformat(),
                limit=10,
            ),
            "backups": db.backup_snapshots_recent(limit=5),
            "backup_health": backup_health,
        }

    @app.get("/api/report-page")
    async def get_report_page():
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        return _snapshot_get_or_build(
            "report-page",
            signature=_payload_signature("report-page"),
            ttl_seconds=8.0,
            builder=_report_page_payload,
        )

    @app.get("/api/events-page")
    async def get_events_page():
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        return _snapshot_get_or_build(
            "events-page",
            signature=_payload_signature("events-page"),
            ttl_seconds=5.0,
            builder=_events_page_payload,
        )

    @app.get("/api/kg-page")
    async def get_kg_page():
        db = _db()
        db.job_runs_mark_stale_by_policy()
        return _snapshot_get_or_build(
            "kg-page",
            signature=_payload_signature("kg-page"),
            ttl_seconds=20.0,
            builder=_kg_page_payload,
        )

    @app.get("/api/overview")
    async def get_overview():
        return await get_report_page()

    @app.get("/api/hive")
    async def get_hive():
        return await get_data_health()

    @app.get("/api/data-health")
    async def get_data_health():
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        return _snapshot_get_or_build(
            "data-health",
            signature=_payload_signature("data-health"),
            ttl_seconds=30.0,
            builder=_data_health_payload,
        )

    @app.get("/api/events/stream")
    async def stream_events(request: FastAPIRequest, after_id: int = 0, limit: int = 50, poll_seconds: float = 2.0):
        async def _gen():
            last_id = max(0, int(after_id))
            try:
                while True:
                    if shutdown_event.is_set():
                        break
                    try:
                        if await request.is_disconnected():
                            break
                    except RuntimeError:
                        break
                    rows = _db().event_log_since(after_id=last_id, limit=limit)
                    if rows:
                        for row in rows:
                            last_id = max(last_id, int(row.get("id") or 0))
                            yield f"data: {json.dumps(row, ensure_ascii=False)}\n\n"
                    else:
                        yield ": ping\n\n"
                    if await _stream_wait(poll_seconds):
                        break
            except asyncio.CancelledError:
                return
            except RuntimeError:
                return

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/runtime/stream")
    async def stream_runtime(request: FastAPIRequest, scope: str = "report", poll_seconds: float = 2.0):
        scope_name = "events-page" if str(scope).strip().lower() == "events" else "report-page"

        async def _gen():
            last_signature = ""
            try:
                while True:
                    if shutdown_event.is_set():
                        break
                    try:
                        if await request.is_disconnected():
                            break
                    except RuntimeError:
                        break
                    signature = _payload_signature(scope_name)
                    if signature != last_signature:
                        last_signature = signature
                        payload = {
                            "scope": scope_name,
                            "signature": signature,
                            "ts": datetime.now().isoformat(timespec="seconds"),
                        }
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    else:
                        yield ": ping\n\n"
                    if await _stream_wait(poll_seconds):
                        break
            except asyncio.CancelledError:
                return
            except RuntimeError:
                return

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/calendar")
    async def get_calendar(date_str: str | None = None, days: int = 5):
        db = _db()
        start = date.fromisoformat(date_str) if date_str else date.today()
        calendar_rows: list[dict[str, Any]] = []
        for offset in range(max(0, int(days)) + 1):
            cur = start + timedelta(days=offset)
            row = db.trading_calendar_get(cur.isoformat(), exchange="SSE")
            if row:
                calendar_rows.append(row)
        planned = db.planned_events_list(
            start_date=start.isoformat(),
            end_date=(start + timedelta(days=max(0, int(days)))).isoformat(),
            limit=100,
        )
        return {"calendar": calendar_rows, "planned_events": planned}

    @app.get("/api/agenda")
    async def get_agenda(limit: int = 50, status: str | None = None):
        return _db().agenda_queue_recent(limit=limit, status=status)

    @app.get("/api/backups")
    async def get_backups(limit: int = 20, status: str | None = None):
        return _db().backup_snapshots_recent(limit=limit, status=status)

    # ── POST /predict — online inference ─────────────────────────────────────

    class PredictRequest(BaseModel):
        symbols: list[str]
        date: str | None = None

    @app.post("/predict")
    async def predict(req: PredictRequest):
        if not req.symbols:
            raise HTTPException(status_code=400, detail="symbols list is empty")
        results = _inference.predict(req.symbols, req.date)
        return results

    @app.post("/predict/reload")
    async def reload_models():
        """Hot-reload models from model_registry."""
        _inference.reload()
        return {"reloaded": True, "models": _inference.model_names}

    # ── API: today-page ───────────────────────────────────────────────────────

    @app.get("/api/today-page")
    async def get_today_page():
        sig = _payload_signature("today")
        return _snapshot_get_or_build(
            "today_page",
            signature=sig,
            ttl_seconds=120,
            builder=_today_page_payload,
        )

    # ── API: signals-page ─────────────────────────────────────────────────────

    @app.get("/api/signals-page")
    async def get_signals_page():
        sig = _payload_signature("signals")
        return _snapshot_get_or_build(
            "signals_page",
            signature=sig,
            ttl_seconds=300,
            builder=_signals_page_payload,
        )

    # ── API: kline/{symbol} ───────────────────────────────────────────────────

    @app.get("/api/kline/{symbol}")
    async def get_kline(symbol: str, days: int = 60):
        """Return OHLCV + indicators + event markers + recommendation context."""
        import math
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")

        db = _db()

        # Get instrument name
        try:
            instr = db.instrument_lookup(symbol)
            name = str(instr.get("name") or symbol) if instr else symbol
        except Exception:
            name = symbol

        # Read kline data from parquet
        ohlcv: list[dict] = []
        try:
            import pandas as pd
            from pathlib import Path as _Path
            kline_dir = _Path(data_root) / "market" / "kline"
            # Convert symbol "600643.SH" → "600643_SH" for filename lookup
            fname = symbol.replace(".", "_") + ".parquet"
            sym_files = sorted(kline_dir.rglob(fname)) if kline_dir.exists() else []

            if sym_files:
                dfs = []
                for f in sym_files[-4:]:  # last few month partition files
                    try:
                        df_part = pd.read_parquet(f)
                        if "symbol" in df_part.columns:
                            df_part = df_part[df_part["symbol"] == symbol]
                        dfs.append(df_part)
                    except Exception:
                        pass
                if dfs:
                    df = pd.concat(dfs, ignore_index=True)
                    date_col = "date" if "date" in df.columns else (
                        "trade_date" if "trade_date" in df.columns else df.columns[0]
                    )
                    if date_col == "trade_date":
                        df = df.rename(columns={"trade_date": "date"})
                        date_col = "date"
                    df = df.sort_values(date_col).tail(max(days, 60))
                    for _, row_data in df.iterrows():
                        try:
                            ohlcv.append({
                                "date": str(row_data.get("date") or ""),
                                "open": float(row_data.get("open") or 0),
                                "high": float(row_data.get("high") or 0),
                                "low": float(row_data.get("low") or 0),
                                "close": float(row_data.get("close") or 0),
                                "volume": int(float(row_data.get("vol") or row_data.get("volume") or 0)),
                            })
                        except Exception:
                            pass
        except Exception:
            pass

        # Compute technical indicators from ohlcv
        indicators: dict[str, Any] = {}
        if len(ohlcv) >= 14:
            closes = [float(r["close"]) for r in ohlcv if float(r.get("close") or 0) > 0]
            vols = [float(r["volume"]) for r in ohlcv if float(r.get("volume") or 0) > 0]
            if len(closes) >= 14:
                # RSI-14
                gains, losses = [], []
                for i in range(1, 15):
                    delta = closes[-i] - closes[-i - 1] if i + 1 < len(closes) else 0
                    (gains if delta > 0 else losses).append(abs(delta))
                avg_gain = sum(gains) / 14 if gains else 0.001
                avg_loss = sum(losses) / 14 if losses else 0.001
                rs = avg_gain / avg_loss if avg_loss > 0 else 100
                rsi = round(100 - 100 / (1 + rs), 1)
                indicators["rsi_14"] = rsi
            if len(vols) >= 20 and vols[-1] > 0:
                vol_ma20 = sum(vols[-20:]) / 20
                vol_ratio = round(vols[-1] / vol_ma20, 2) if vol_ma20 > 0 else 1.0
                indicators["vol_ratio"] = vol_ratio
            if len(closes) >= 52:
                high_52w = max(closes[-252:] if len(closes) >= 252 else closes)
                low_52w = min(closes[-252:] if len(closes) >= 252 else closes)
                rng = high_52w - low_52w
                dist = round((closes[-1] - low_52w) / rng, 3) if rng > 0 else 0.5
                indicators["dist_52w_low"] = dist

        # Get event markers for this symbol
        event_markers: list[dict] = []
        try:
            with db._conn_lock:
                ep_rows = db._conn.execute("""
                    SELECT me.event_date, me.event_type, me.magnitude, ep.kg_score
                    FROM event_propagations ep
                    JOIN market_events me ON ep.event_id = me.event_id
                    WHERE ep.symbol = ?
                    ORDER BY me.event_date DESC
                    LIMIT 20
                """, (symbol,)).fetchall()
            for row in ep_rows:
                try:
                    event_markers.append({
                        "date": str(row[0] or ""),
                        "event_type": str(row[1] or ""),
                        "magnitude": float(row[2] or 0),
                        "kg_score": float(row[3] or 0),
                    })
                except Exception:
                    pass
        except Exception:
            pass

        # Get latest signal
        latest_signal: dict = {}
        try:
            with db._conn_lock:
                sig_row = db._conn.execute("""
                    WITH latest AS (SELECT symbol, MAX(date) AS max_date FROM signals WHERE symbol=? GROUP BY symbol)
                    SELECT sc.*
                    FROM signals sc JOIN latest ON sc.symbol=latest.symbol AND sc.date=latest.max_date
                    LIMIT 1
                """, (symbol,)).fetchone()
            if sig_row:
                latest_signal = dict(sig_row)
        except Exception:
            pass

        # Prediction from inference service
        prediction: dict = {}
        try:
            pred = _inference.predict(symbol)
            if pred:
                prediction = pred
        except Exception:
            pass

        # Recommendation context
        recommendation: dict = {}
        try:
            hist_ret_5d: float | None = None
            hist_count = 0
            event_type_str = ""
            if event_markers:
                top_event = event_markers[0]
                event_type_str = top_event.get("event_type", "")
                with db._conn_lock:
                    hist_row = db._conn.execute("""
                        SELECT COUNT(*) AS cnt, AVG(ep.actual_return_5d) AS ret5d
                        FROM event_propagations ep
                        JOIN market_events me ON ep.event_id = me.event_id
                        WHERE ep.symbol = ?
                        AND me.event_type = ?
                        AND ep.actual_return_5d IS NOT NULL
                    """, (symbol, event_type_str)).fetchone()
                if hist_row:
                    hist_count = int(hist_row[0] or 0)
                    hist_ret_5d = float(hist_row[1]) * 100 if hist_row[1] is not None else None

            rsi = float(indicators.get("rsi_14") or 50)
            vol_ratio = float(indicators.get("vol_ratio") or 1.0)
            net_sent = float(latest_signal.get("net_sentiment") or 0)

            reasons: list[str] = []
            if hist_count > 3 and hist_ret_5d is not None and hist_ret_5d > 1.5:
                reasons.append(f"{event_type_str} 事件历史{hist_count}次均5日收益 +{hist_ret_5d:.1f}%")
            if rsi < 45:
                reasons.append(f"RSI {rsi:.0f}，接近超卖低位")
            elif rsi < 55:
                reasons.append(f"RSI {rsi:.0f}，中性偏低")
            if vol_ratio < 0.8:
                reasons.append(f"近期缩量（量比 {vol_ratio:.2f}），低位蓄势")
            if net_sent > 0.2:
                reasons.append(f"情绪偏正（{net_sent:.2f}）")
            elif net_sent < -0.3:
                reasons.append(f"情绪偏负（{net_sent:.2f}）")

            model_score = float(latest_signal.get("model_score") or 0)
            window_score = float(latest_signal.get("window_score") or 0)
            bullish_dims = sum([
                model_score > 0.5, window_score > 70, rsi < 50,
                vol_ratio < 1.0, net_sent > 0,
            ])

            recommendation = {
                "conviction": "高" if bullish_dims >= 3 else ("中" if bullish_dims >= 2 else "低"),
                "bullish_dims": bullish_dims,
                "reasons": reasons[:4],
                "hist_event_stats": {
                    "event_type": event_type_str,
                    "hist_count": hist_count,
                    "hist_ret_5d_avg": round(hist_ret_5d, 1) if hist_ret_5d is not None else None,
                },
            }
        except Exception:
            pass

        return {
            "symbol": symbol,
            "name": name,
            "ohlcv": ohlcv,
            "event_markers": event_markers,
            "indicators": indicators,
            "prediction": prediction,
            "recommendation": recommendation,
            "latest_signal": {
                "model_score": latest_signal.get("model_score"),
                "window_score": latest_signal.get("window_score"),
                "event_kg_score": latest_signal.get("event_kg_score"),
                "net_sentiment": latest_signal.get("net_sentiment"),
                "status": latest_signal.get("status"),
            },
        }

    return app
