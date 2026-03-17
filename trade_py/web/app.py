"""FastAPI application — DAG Web UI + Online Inference Service.

Routes:
  GET  /                     → index.html (console)
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
  GET  /api/backups          → backup snapshots
  POST /predict              → online inference endpoint
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional at import time
    from fastapi import BackgroundTasks as FastAPIBackgroundTasks
except Exception:  # pragma: no cover - fastapi missing outside web usage
    FastAPIBackgroundTasks = Any

logger = logging.getLogger(__name__)


def create_app():
    """FastAPI app factory (used by uvicorn --factory)."""
    try:
        from fastapi import Body, FastAPI, HTTPException
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from pydantic import BaseModel
    except ImportError:
        raise ImportError("fastapi required: uv add fastapi uvicorn")

    data_root = os.environ.get("TRADE_DATA_ROOT", "data")
    app = FastAPI(title="TradeDB Console", version="1.0")

    # Lazy-init inference service
    from trade_py.web.inference import InferenceService
    _inference = InferenceService(data_root)

    # ── DB helper ─────────────────────────────────────────────────────────────

    def _db():
        from trade_py.db.trade_db import TradeDB
        return TradeDB(data_root)

    # ── Static files ──────────────────────────────────────────────────────────

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

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
