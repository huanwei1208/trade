"""FastAPI application — DAG Web UI + Online Inference Service.

Routes:
  GET  /                     → index.html (DAG three-column view)
  GET  /api/dag              → pipeline_dag table (stage-grouped)
  POST /api/dag/{id}/enable  → enable a DAG node
  POST /api/dag/{id}/disable → disable a DAG node
  POST /api/trigger          → publish event to bus
  GET  /api/events           → event_log recent N entries
  GET  /api/runs             → job_runs recent N entries
  GET  /api/models           → model_registry list
  GET  /api/status           → service health + model info
  POST /predict              → online inference endpoint
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def create_app():
    """FastAPI app factory (used by uvicorn --factory)."""
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from pydantic import BaseModel
    except ImportError:
        raise ImportError("fastapi required: uv add fastapi uvicorn")

    data_root = os.environ.get("TRADE_DATA_ROOT", "data")
    app = FastAPI(title="Trade DAG Monitor", version="1.0")

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

    @app.post("/api/dag/{dag_id}/enable")
    async def enable_dag(dag_id: int):
        _db().pipeline_dag_set_enabled(dag_id, True)
        return {"id": dag_id, "enabled": True}

    @app.post("/api/dag/{dag_id}/disable")
    async def disable_dag(dag_id: int):
        _db().pipeline_dag_set_enabled(dag_id, False)
        return {"id": dag_id, "enabled": False}

    # ── API: trigger event ────────────────────────────────────────────────────

    class TriggerRequest(BaseModel):
        topic: str
        payload: dict = {}

    @app.post("/api/trigger")
    async def trigger_event(req: TriggerRequest):
        from trade_py.bus import get_bus, bootstrap_from_dag
        db = _db()
        bus = get_bus(db)
        bootstrap_from_dag(db, data_root)
        event = bus.publish(req.topic, req.payload)
        return {"event_id": event.id, "topic": req.topic}

    # ── API: event_log ────────────────────────────────────────────────────────

    @app.get("/api/events")
    async def get_events(limit: int = 50, topic: str | None = None):
        return _db().event_log_recent(limit, topic)

    # ── API: job_runs ─────────────────────────────────────────────────────────

    @app.get("/api/runs")
    async def get_runs(limit: int = 50, stage: str | None = None):
        return _db().job_runs_recent(limit, stage=stage)

    # ── API: model_registry ───────────────────────────────────────────────────

    @app.get("/api/models")
    async def get_models():
        return _db().model_registry_list()

    # ── API: status ───────────────────────────────────────────────────────────

    @app.get("/api/status")
    async def get_status():
        return {
            "status": "ok",
            "data_root": data_root,
            "inference_models": _inference.model_names,
            "models_loaded_at": _inference.loaded_at,
        }

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
