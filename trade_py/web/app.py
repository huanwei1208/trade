"""FastAPI application — TradeDB Web API + UI host.

Routes:
  GET  /                     → web app shell (React dist or legacy console)
  GET  /api/dag              → pipeline_dag table (stage-grouped)
  GET  /api/dag/runtime      → DAG runtime state + latest runs/errors
  POST /api/dag/{id}/enable  → enable a DAG node
  POST /api/dag/{id}/disable → disable a DAG node
  POST /api/trigger          → publish event to bus
  POST /api/run              → run a high-level workflow target
  GET  /api/events           → event_log recent N entries
  GET  /api/workflows        → recent workflow traces
  GET  /api/workflows/{id}   → workflow detail
  GET  /api/runs             → job_runs recent N entries
  GET  /api/models           → model_registry list
  GET  /api/status           → service health + quality gate + agenda + backups
  GET  /api/calendar         → trading calendar + planned events
  GET  /api/agenda           → recent agenda queue
  GET  /api/data-health      → data freshness / coverage snapshot
  GET  /api/backups          → backup snapshots
  POST /predict              → online inference endpoint
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

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


def _latest_brief_summary(data_root: str) -> dict[str, Any]:
    brief_dir = Path(data_root) / "briefs"
    if not brief_dir.exists():
        return {"path": None, "date": None, "excerpt": []}
    files = sorted(brief_dir.glob("*.md"), reverse=True)
    if not files:
        return {"path": None, "date": None, "excerpt": []}
    latest = files[0]
    excerpt: list[str] = []
    try:
        for line in latest.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            excerpt.append(text)
            if len(excerpt) >= 4:
                break
    except Exception:
        excerpt = []
    return {"path": str(latest), "date": latest.stem, "excerpt": excerpt}


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
    app = FastAPI(title="TradeDB Console", version="1.0")

    # Lazy-init inference service
    from trade_web.inference import InferenceService
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
                    COALESCE((SELECT MAX(updated_at) FROM sync_state), '')
                """
            ).fetchone()
        base = "|".join(str(item or "") for item in (row or ()))
        return f"{kind}:{base}"

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

    def _light_hive_snapshot(db, gate: dict[str, Any]) -> dict[str, Any]:
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
        return {
            "datasets": [],
            "domains": domains,
            "highlights": highlights,
            "summary": summary,
            "as_of": date.today().isoformat(),
            "cached": False,
        }

    def _data_hive_payload() -> dict[str, Any]:
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

    def _overview_payload() -> dict[str, Any]:
        db = _db()
        gate = db.quality_gate_get() or {}
        workflows = db.event_workflow_recent(limit=6)
        runtime = db.pipeline_dag_runtime(recent_limit=200)
        top_signals_model = db.signal_suggest(limit=5, by="model_score")
        top_signals_kg = db.signal_suggest(limit=5, by="event_kg_score")
        hive_signature = _payload_signature("hive")
        hive = _cache_get("hive", signature=hive_signature, ttl_seconds=30.0) or _light_hive_snapshot(db, gate)
        brief = _latest_brief_summary(data_root)
        due_agenda = db.agenda_queue_due(limit=6)
        planned_events = db.planned_events_list(
            start_date=date.today().isoformat(),
            end_date=(date.today() + timedelta(days=7)).isoformat(),
            limit=8,
        )
        recent_events = db.event_log_recent(limit=18)
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
            "brief": brief,
            "top_signals": {
                "model_score": top_signals_model,
                "event_kg_score": top_signals_kg,
            },
            "workflows": workflows,
            "root_causes": root_causes,
            "agenda": due_agenda,
            "planned_events": planned_events,
            "recent_events": recent_events,
            "data_hive": hive,
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
    async def run_target(background_tasks: FastAPIBackgroundTasks, req: dict = Body(...)):
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
        background_tasks.add_task(run_cli.main, argv)
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

    @app.get("/api/overview")
    async def get_overview():
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        signature = _payload_signature("overview")
        cached = _cache_get("overview", signature=signature, ttl_seconds=8.0)
        if cached is not None:
            return cached
        payload = _overview_payload()
        return _cache_set("overview", signature=signature, payload=payload)

    @app.get("/api/hive")
    async def get_hive():
        signature = _payload_signature("hive")
        cached = _cache_get("hive", signature=signature, ttl_seconds=30.0)
        if cached is not None:
            return cached
        payload = _data_hive_payload()
        return _cache_set("hive", signature=signature, payload=payload)

    @app.get("/api/data-health")
    async def get_data_health():
        return await get_hive()

    @app.get("/api/events/stream")
    async def stream_events(after_id: int = 0, limit: int = 50, poll_seconds: float = 2.0):
        async def _gen():
            last_id = max(0, int(after_id))
            while True:
                rows = _db().event_log_since(after_id=last_id, limit=limit)
                if rows:
                    for row in rows:
                        last_id = max(last_id, int(row.get("id") or 0))
                        yield f"data: {json.dumps(row, ensure_ascii=False)}\n\n"
                else:
                    yield ": ping\n\n"
                await asyncio.sleep(max(0.5, float(poll_seconds)))

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

    return app
