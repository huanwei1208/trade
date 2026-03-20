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
  GET  /api/today-page           → market snapshot + pipeline health + trust_gate + top 5 picks
  GET  /api/signals-page         → top 50 picks with belief delta + top evidence (EBRT)
  GET  /api/belief/{symbol}      → BeliefState history + top AttentionScores (EBRT)
  GET  /api/kline/{symbol}       → OHLCV + indicators + event markers + belief_overlay (EBRT)
  GET  /api/state/{symbol}       → WorldState (regime labels, blockers, signals)
  GET  /api/explain/{symbol}     → DecisionExplanation (4-layer, unified)
  GET  /api/actions-page         → today's action candidates (WATCH/PROBE/ADD)
  GET  /api/trust/overview       → portfolio-level trust summary
  POST /predict                  → online inference endpoint
"""
from __future__ import annotations

import asyncio
import datetime as dtm
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

    # Services layer (state-centered decision architecture)
    from trade_py.services.state_service import StateService
    from trade_py.services.decision_service import DecisionService
    from trade_py.services.explanation_service import ExplanationService
    from trade_web.backend.readiness import (
        build_readiness_grid,
        build_replay_plan,
        create_recovery_action,
        execute_recovery_action,
        list_recovery_history,
    )
    _state_svc    = StateService(data_root)
    _decision_svc = DecisionService(inference=_inference)
    _explain_svc  = ExplanationService(_state_svc, _decision_svc, inference=_inference)

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

    def _readiness_signature(*, days: int, end_date: str | None, datasets: str | None) -> str:
        db = _db()
        with db._conn_lock:
            row = db._conn.execute(
                """
                SELECT
                    COALESCE((SELECT MAX(updated_at) FROM daily_quality_gate), ''),
                    COALESCE((SELECT MAX(eval_date) FROM dataset_snapshots), ''),
                    COALESCE((SELECT MAX(eval_date) FROM QualityReport), ''),
                    COALESCE((SELECT MAX(as_of_date) FROM FreshnessStatus), ''),
                    COALESCE((SELECT MAX(updated_at) FROM sync_state), ''),
                    COALESCE((SELECT MAX(id) FROM data_repair_runs), 0),
                    COALESCE((SELECT MAX(updated_at) FROM data_gaps), ''),
                    COALESCE((SELECT MAX(date) FROM signals), ''),
                    COALESCE((SELECT MAX(as_of_date) FROM BeliefState), ''),
                    COALESCE((SELECT MAX(as_of_date) FROM Recommendation), ''),
                    COALESCE((SELECT MAX(substr(updated_at, 1, 10)) FROM sector_members), ''),
                    COALESCE((SELECT MAX(substr(trained_at, 1, 10)) FROM model_registry), '')
                """
            ).fetchone()
        base = "|".join(str(item or "") for item in (row or ()))
        return f"readiness:{days}:{end_date or ''}:{datasets or ''}:{base}"

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

    def _read_symbol_sparkline(symbol: str, *, days: int = 12) -> list[dict[str, Any]]:
        try:
            from trade_py.data.market.kline import read_kline_range

            end_date = date.today()
            start_date = end_date - timedelta(days=max(14, days * 3))
            df = read_kline_range(
                data_root,
                symbol,
                start_date.isoformat(),
                end_date.isoformat(),
            )
            if df.empty:
                return []
            points: list[dict[str, Any]] = []
            for row in df.tail(days).to_dict(orient="records"):
                points.append({
                    "date": str(row.get("date") or row.get("trade_date") or ""),
                    "close": float(row.get("close") or 0.0),
                })
            return points
        except Exception:
            return []

    def _read_symbol_event_tags(db, symbol: str, *, as_of: str, limit: int = 3) -> list[str]:
        try:
            with db._conn_lock:
                rows = db._conn.execute(
                    """
                    SELECT DISTINCT event_type
                    FROM market_events
                    WHERE symbol = ? AND event_date <= ?
                    ORDER BY event_date DESC
                    LIMIT ?
                    """,
                    (symbol, as_of, max(1, int(limit))),
                ).fetchall()
            return [str(row[0]) for row in rows if row and row[0]]
        except Exception:
            return []

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
        from trade_py.analysis.knowledge_graph import SectorGraph

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

        # EBRT: top picks from Recommendation table (with belief delta)
        today_str = date.today().isoformat()
        ebrt_recs: list[dict] = []
        try:
            recs = db.recommendation_list(today_str)
            for r in recs[:5]:
                sym = str(r.get("symbol") or "")
                bv: dict = {}
                belief_mu = 0.0
                belief_sigma = 0.3
                delta_mu = 0.0
                try:
                    bs = db.belief_state_get(today_str, sym)
                    if bs:
                        bv = bs.get("belief_vec") or {}
                        belief_mu = float(bv.get("mu", 0.0))
                        belief_sigma = float(bv.get("sigma", 0.3))
                    bt = db.belief_transition_get(sym, today_str)
                    if bt:
                        delta_mu = float((bt.get("delta_vec") or {}).get("mu_delta", 0.0))
                except Exception:
                    pass
                ebrt_recs.append({
                    **r,
                    "belief_mu": round(belief_mu, 4),
                    "belief_sigma": round(belief_sigma, 4),
                    "belief_delta_mu": round(delta_mu, 4),
                })
        except Exception:
            pass

        # Fall back to old signal_recommend if no EBRT recs
        if not ebrt_recs:
            picks_data = db.signal_recommend(limit=5)
            top_picks = picks_data.get("picks", [])
            dropped = picks_data.get("dropped", [])
        else:
            top_picks = ebrt_recs
            dropped = []

        # EBRT: Trust Gate from QualityReport
        trust_gate: dict = {}
        try:
            qr = db.quality_report_latest()
            if qr:
                freshness = db.freshness_status_list(today_str)
                metrics = qr.get("metrics") or {}
                trust_vec = metrics.get("trust_vector") or {}
                t_star = metrics.get("trust_scalar")
                trust_gate = {
                    "operational_status": qr.get("operational_status", "unknown"),
                    "research_status": qr.get("research_status", "unknown"),
                    "brier_score": qr.get("brier_score"),
                    "drift_mmd": qr.get("drift_mmd"),
                    "eval_date": qr.get("eval_date", ""),
                    "trust_scalar": t_star,
                    "trust_components": trust_vec,
                    "freshness": [
                        {"dataset": f.get("dataset"), "lag_days": f.get("lag_days"),
                         "status": f.get("status")}
                        for f in freshness
                    ],
                }
        except Exception:
            pass

        # Recent job runs for pipeline context
        recent_runs = db.job_runs_recent(limit=10)

        # Kline sync state for market context
        try:
            kline_last = db.sync_state_get("tushare_kline", "daily", "")
            kline_last_date = kline_last.isoformat() if kline_last is not None else ""
        except Exception:
            kline_last_date = ""

        # Decision-layer enrichment: add action/confidence/thesis to top picks
        today_thesis = ""
        blockers: list[str] = []
        top_actions: list[dict] = []
        market_regime = "UNKNOWN"
        try:
            for pick in top_picks[:5]:
                sym = str(pick.get("symbol") or "")
                if not sym:
                    continue
                try:
                    ws = _state_svc.build(sym, as_of_date=today_str)
                    _, act = _decision_svc.decide(ws)
                    enriched = {
                        **pick,
                        "action":        act.action.value,
                        "confidence":    act.confidence,
                        "thesis":        ws.state_summary,
                        "trust_score":   round(ws.trust_score, 4),
                        "trust_level":   "HIGH" if ws.trust_score > 0.70 else (
                                          "MEDIUM" if ws.trust_score > 0.40 else "LOW"),
                        "top_invalidators": act.invalidators[:2],
                        "world_state_summary": ws.state_summary,
                        "event_tags": _read_symbol_event_tags(db, sym, as_of=today_str, limit=2),
                        "sparkline": _read_symbol_sparkline(sym),
                    }
                    top_actions.append(enriched)
                    # First ADD/PROBE becomes today's thesis
                    if not today_thesis and act.action.value in ("ADD", "PROBE"):
                        today_thesis = ws.state_summary
                    # Collect blockers
                    blockers.extend(ws.blockers[:1])
                    if market_regime == "UNKNOWN":
                        market_regime = str(ws.market_regime or "UNKNOWN")
                except Exception:
                    top_actions.append(pick)
            if not today_thesis and top_actions:
                today_thesis = top_actions[0].get("world_state_summary", "")
        except Exception:
            top_actions = list(top_picks[:5])

        freshness_issues = [
            {
                "dataset": item.get("dataset"),
                "lag_days": item.get("lag_days"),
                "status": item.get("status"),
            }
            for item in (trust_gate.get("freshness") or [])
            if str(item.get("status") or "") != "ok"
        ]
        global_blocked = bool(blockers) or any(
            status in {"blocked", "degraded", "partial"}
            for status in (
                str(trust_gate.get("operational_status") or "").lower(),
                str(trust_gate.get("research_status") or "").lower(),
            )
        )
        actionable_count = sum(
            1 for row in top_actions
            if str(row.get("action") or "") in {"ADD", "PROBE", "REDUCE"}
        )
        watch_count = sum(1 for row in top_actions if str(row.get("action") or "") == "WATCH")
        decision_posture = (
            "DEGRADED" if global_blocked else
            "ACTIONABLE" if actionable_count > 0 else
            "WATCHLIST" if watch_count > 0 else
            "NO_ACTION"
        )
        recovery_condition = (
            "Restore missing or stale datasets and recover trust gate before acting."
            if freshness_issues
            else "Wait for stronger confirmation or regime improvement."
        )

        return {
            "as_of": today_str,
            "today_thesis": today_thesis,
            "market_regime": market_regime,
            "blockers": list(dict.fromkeys(blockers))[:4],
            "decision_posture": decision_posture,
            "global_blocked": global_blocked,
            "blocker_details": freshness_issues,
            "safe_to_view": ["historical chart context", "recent events", "state summaries"],
            "recovery_condition": recovery_condition,
            "pipeline_health": pipeline_health,
            "top_picks": top_picks,
            "top_actions": top_actions,
            "dropped_picks": dropped,
            "kline_last_date": kline_last_date,
            "gate_status": gate.get("status", "unknown"),
            "gate_reason": gate.get("reason_summary", ""),
            "trust_gate": trust_gate,
            "recent_runs": recent_runs[:5],
            "error_nodes": [n for n in nodes if str(n.get("status") or "") == "error"][:5],
        }

    def _signals_page_payload() -> dict[str, Any]:
        db = _db()
        today_str = date.today().isoformat()

        # EBRT: use Recommendation table if available
        ebrt_recs = []
        try:
            ebrt_recs = db.recommendation_list(today_str)
        except Exception:
            pass

        if ebrt_recs:
            picks = []
            for r in ebrt_recs[:50]:
                sym = str(r.get("symbol") or "")
                name = ""
                belief_mu = 0.0
                belief_sigma = 0.3
                delta_mu = 0.0
                top_evidence: list = []
                sparkline: list[dict[str, Any]] = []
                event_tags: list[str] = []
                try:
                    instr = db.instrument_lookup(sym)
                    name = str(instr.get("name") or "") if instr else ""
                except Exception:
                    pass
                try:
                    bs = db.belief_state_get(today_str, sym)
                    if bs:
                        bv = bs.get("belief_vec") or {}
                        belief_mu = float(bv.get("mu", 0.0))
                        belief_sigma = float(bv.get("sigma", 0.3))
                    bt = db.belief_transition_get(sym, today_str)
                    if bt:
                        delta_mu = float((bt.get("delta_vec") or {}).get("mu_delta", 0.0))
                    attn = db.attention_list(sym, today_str, top_n=3)
                    top_evidence = [
                        {"weight": a.get("weight"), "evidence_id": a.get("evidence_id")}
                        for a in attn
                    ]
                    sparkline = _read_symbol_sparkline(sym)
                    event_tags = _read_symbol_event_tags(db, sym, as_of=today_str, limit=3)
                except Exception:
                    pass
                # Decision-layer enrichment (top 20 only — speed)
                action_val = str(r.get("action") or "")
                confidence_val = str(r.get("conviction") or "")
                ws_summary = ""
                top_inv: list[str] = []
                trust_score_val = 0.5
                trust_level_val = "MEDIUM"
                if len(picks) < 20:
                    try:
                        ws = _state_svc.build(sym, as_of_date=today_str)
                        _, act = _decision_svc.decide(ws)
                        action_val    = act.action.value
                        confidence_val = act.confidence
                        ws_summary    = ws.state_summary
                        top_inv       = act.invalidators[:2]
                        trust_score_val = round(ws.trust_score, 4)
                        trust_level_val = ("HIGH" if ws.trust_score > 0.70 else
                                           "MEDIUM" if ws.trust_score > 0.40 else "LOW")
                    except Exception:
                        pass
                picks.append({
                    **r,
                    "name": name,
                    "belief_mu": round(belief_mu, 4),
                    "belief_sigma": round(belief_sigma, 4),
                    "belief_delta_mu": round(delta_mu, 4),
                    "top_evidence": top_evidence,
                    "sparkline": sparkline,
                    "event_tags": event_tags,
                    "action":               action_val,
                    "confidence":           confidence_val,
                    "world_state_summary":  ws_summary,
                    "top_invalidators":     top_inv,
                    "trust_score":          trust_score_val,
                    "trust_level":          trust_level_val,
                })
            return {
                "as_of": today_str,
                "picks": picks,
                "dropped": [],
                "total": len(picks),
                "source": "ebrt",
            }

        # Fall back to old signal-based picks
        recommend = db.signal_recommend(limit=50)
        picks = recommend.get("picks", [])
        dropped = recommend.get("dropped", [])
        for pick in picks:
            sym = str(pick.get("symbol") or "")
            if sym:
                try:
                    instr = db.instrument_lookup(sym)
                    pick["name"] = str(instr.get("name") or "") if instr else ""
                    pick["sparkline"] = _read_symbol_sparkline(sym)
                    pick["event_tags"] = _read_symbol_event_tags(db, sym, as_of=today_str, limit=3)
                except Exception:
                    pick["name"] = ""
        return {
            "as_of": today_str,
            "picks": picks,
            "dropped": dropped,
            "total": len(picks),
            "source": "signals",
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
            from scripts.backup import backup_doctor
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

    @app.get("/api/readiness-grid")
    async def get_readiness_grid(days: int = 30, end_date: str | None = None, datasets: str | None = None):
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        resolved_days = int(days or 30)
        if resolved_days not in {30, 60, 90}:
            resolved_days = 30
        dataset_list = [item.strip() for item in str(datasets or "").split(",") if item.strip()] or None
        scope = f"{resolved_days}:{end_date or ''}:{','.join(dataset_list or [])}"
        return _snapshot_get_or_build(
            "readiness-grid",
            signature=_readiness_signature(days=resolved_days, end_date=end_date, datasets=datasets),
            ttl_seconds=20.0,
            scope=scope,
            builder=lambda: build_readiness_grid(
                data_root,
                _db(),
                days=resolved_days,
                end_date=end_date,
                datasets=dataset_list,
            ),
        )

    @app.get("/api/readiness/replay-plan")
    async def get_readiness_replay_plan(dataset: str, date: str | None = None, date_from: str | None = None, date_to: str | None = None):
        db = _db()
        resolved_from = date_from or date or dtm.date.today().isoformat()
        resolved_to = date_to or date or resolved_from
        return build_replay_plan(db, dataset.strip(), date_from=resolved_from, date_to=resolved_to)

    @app.get("/api/readiness/history")
    async def get_readiness_history(dataset: str | None = None, date: str | None = None, limit: int = 40):
        return {
            "items": list_recovery_history(_db(), dataset=dataset.strip() if dataset else None, date=date, limit=limit),
        }

    @app.post("/api/readiness/backfill")
    async def post_readiness_backfill(req: dict = Body(...)):
        dataset = str(req.get("dataset") or "").strip()
        if not dataset:
            raise HTTPException(status_code=400, detail="dataset is required")
        date_from = str(req.get("date_from") or req.get("date") or "").strip()
        date_to = str(req.get("date_to") or req.get("date") or date_from).strip()
        mode = str(req.get("mode") or "data_only").strip().lower()
        if mode not in {"data_only", "data_plus_downstream", "full_replay"}:
            raise HTTPException(status_code=400, detail="mode must be one of data_only, data_plus_downstream, full_replay")
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        db = _db()
        plan = build_replay_plan(db, dataset, date_from=date_from, date_to=date_to)
        job_names = [plan.get("job_name")] if plan.get("job_name") else []
        if mode in {"data_plus_downstream", "full_replay"}:
            job_names.extend(str(item.get("job_name") or "") for item in plan.get("downstream_nodes", []))
        if mode == "full_replay":
            job_names = [str(item.get("job_name") or "") for item in plan.get("full_chain", [])]
        action_id = create_recovery_action(
            db,
            dataset=dataset,
            date_from=date_from,
            date_to=date_to,
            action_type="backfill",
            mode=mode,
            job_names=[job for job in job_names if job],
            affected_outputs=list(plan.get("affected_outputs") or []),
            request_payload=req,
        )

        def _run() -> None:
            execute_recovery_action(
                data_root,
                _db(),
                action_id=action_id,
                dataset=dataset,
                date_from=date_from,
                date_to=date_to,
                mode=mode,
                action_type="backfill",
            )

        Thread(target=_run, name=f"readiness-backfill-{action_id}", daemon=True).start()
        return {"accepted": True, "action_id": action_id, "plan": plan}

    @app.post("/api/readiness/replay")
    async def post_readiness_replay(req: dict = Body(...)):
        dataset = str(req.get("dataset") or "").strip()
        if not dataset:
            raise HTTPException(status_code=400, detail="dataset is required")
        date_from = str(req.get("date_from") or req.get("date") or "").strip()
        date_to = str(req.get("date_to") or req.get("date") or date_from).strip()
        mode = str(req.get("mode") or "data_plus_downstream").strip().lower()
        if mode not in {"data_only", "data_plus_downstream", "full_replay"}:
            raise HTTPException(status_code=400, detail="mode must be one of data_only, data_plus_downstream, full_replay")
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        db = _db()
        plan = build_replay_plan(db, dataset, date_from=date_from, date_to=date_to)
        action_id = create_recovery_action(
            db,
            dataset=dataset,
            date_from=date_from,
            date_to=date_to,
            action_type="replay",
            mode=mode,
            job_names=[str(item.get("job_name") or "") for item in plan.get("downstream_nodes", [])],
            affected_outputs=list(plan.get("affected_outputs") or []),
            request_payload=req,
        )

        def _run() -> None:
            execute_recovery_action(
                data_root,
                _db(),
                action_id=action_id,
                dataset=dataset,
                date_from=date_from,
                date_to=date_to,
                mode=mode,
                action_type="replay",
            )

        Thread(target=_run, name=f"readiness-replay-{action_id}", daemon=True).start()
        return {"accepted": True, "action_id": action_id, "plan": plan}

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

    # ── API: belief/{symbol} (EBRT) ───────────────────────────────────────────

    @app.get("/api/belief/{symbol}")
    async def get_belief(symbol: str, days: int = 30):
        """Return BeliefState history + top AttentionScores for a symbol."""
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")

        db = _db()
        today = date.today().isoformat()

        # Belief history (last N days)
        history: list[dict] = []
        try:
            cur = date.today()
            from datetime import timedelta as _td
            for _ in range(days):
                row = db.belief_state_get(cur.isoformat(), symbol)
                if row:
                    bv = row.get("belief_vec") or {}
                    bt = db.belief_transition_get(symbol, cur.isoformat())
                    delta_mu = float((bt.get("delta_vec") or {}).get("mu_delta", 0.0)) if bt else 0.0
                    history.append({
                        "date": cur.isoformat(),
                        "mu": float(bv.get("mu", 0.0)),
                        "sigma": float(bv.get("sigma", 0.3)),
                        "confidence": float(row.get("confidence") or 0.3),
                        "uncertainty": float(row.get("uncertainty") or 0.3),
                        "delta_mu": round(delta_mu, 4),
                    })
                cur -= _td(days=1)
        except Exception:
            pass

        # Latest attention scores
        top_attention: list[dict] = []
        try:
            attn_rows = db.attention_list(symbol, today, top_n=10)
            for a in attn_rows:
                ev_type = "unknown"
                ev_direction = 0.0
                try:
                    row = db._conn.execute(
                        "SELECT evidence_type, direction FROM Evidence WHERE evidence_id=?",
                        (a.get("evidence_id", ""),),
                    ).fetchone()
                    if row:
                        ev_type = row[0] or "unknown"
                        ev_direction = float(row[1] or 0.0)
                except Exception:
                    pass
                top_attention.append({
                    "evidence_id": a.get("evidence_id"),
                    "evidence_type": ev_type,
                    "weight": float(a.get("weight") or 0.0),
                    "logit": float(a.get("logit") or 0.0),
                    "direction": round(ev_direction, 2),
                })
        except Exception:
            pass

        # Latest recommendation for this symbol
        rec: dict = {}
        try:
            recs = db.recommendation_list(today)
            for r in recs:
                if r.get("symbol") == symbol:
                    rec = r
                    break
        except Exception:
            pass

        # Latest belief state
        latest_belief: dict = {}
        try:
            bs = db.belief_state_get(today, symbol)
            if bs:
                bv = bs.get("belief_vec") or {}
                latest_belief = {
                    "mu": float(bv.get("mu", 0.0)),
                    "sigma": float(bv.get("sigma", 0.3)),
                    "confidence": float(bs.get("confidence") or 0.3),
                    "uncertainty": float(bs.get("uncertainty") or 0.3),
                    "as_of_date": bs.get("as_of_date"),
                }
        except Exception:
            pass

        return {
            "symbol": symbol,
            "as_of": today,
            "latest_belief": latest_belief,
            "history": list(reversed(history)),
            "top_attention": top_attention,
            "recommendation": rec,
        }

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

    # ── API: state/{symbol} ───────────────────────────────────────────────────

    @app.get("/api/state/{symbol}")
    async def get_state(symbol: str, date: str | None = None):
        """Return WorldState for a symbol (regime labels, blockers, signals)."""
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")
        try:
            ws = _state_svc.build(symbol, as_of_date=date)
            return ws.to_dict()
        except Exception as exc:
            logger.exception("get_state error for %s: %s", symbol, exc)
            raise HTTPException(status_code=500, detail=str(exc))

    # ── API: explain/{symbol} ─────────────────────────────────────────────────

    @app.get("/api/explain/{symbol}")
    async def get_explain(symbol: str, date: str | None = None):
        """Return full DecisionExplanation for a symbol (4-layer, unified)."""
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")
        try:
            exp = _explain_svc.explain(symbol, as_of_date=date)
            return exp.to_dict()
        except Exception as exc:
            logger.exception("get_explain error for %s: %s", symbol, exc)
            raise HTTPException(status_code=500, detail=str(exc))

    # ── API: actions-page ─────────────────────────────────────────────────────

    @app.get("/api/actions-page")
    async def get_actions_page():
        """Return today's action candidates (WATCH / PROBE / ADD)."""
        from trade_py.decision.action import DecisionAction

        db = _db()
        today_str = date.today().isoformat()

        # Get the current EBRT picks as the candidate set
        try:
            picks = db.recommendation_list(today_str)
        except Exception:
            picks = []

        results = []
        for rec in picks[:50]:
            sym = rec.get("symbol", "")
            if not sym:
                continue
            try:
                ws     = _state_svc.build(sym, as_of_date=today_str)
                _, act = _decision_svc.decide(ws)
                if act.action in (
                    DecisionAction.WATCH, DecisionAction.PROBE,
                    DecisionAction.ADD,   DecisionAction.REDUCE,
                ):
                    results.append({
                        "symbol":       sym,
                        "action":       act.action.value,
                        "confidence":   act.confidence,
                        "score":        round(act.score, 4),
                        "risk":         round(act.risk, 4),
                        "reason":       act.reason,
                        "position_hint": act.position_hint,
                        "state_summary": ws.state_summary,
                    })
            except Exception:
                continue

        results.sort(key=lambda x: (
            {"ADD": 0, "PROBE": 1, "WATCH": 2, "REDUCE": 3}.get(x["action"], 9),
            -x["score"],
        ))
        return {
            "as_of":   today_str,
            "total":   len(results),
            "actions": results,
        }

    # ── API: trust/overview ───────────────────────────────────────────────────

    @app.get("/api/trust/overview")
    async def get_trust_overview():
        """Return portfolio-level trust summary from QualityReport."""
        db = _db()
        today_str = date.today().isoformat()
        try:
            rows = db.quality_report_list(limit=7)
        except Exception:
            rows = []

        trend = []
        for row in rows:
            metrics = row.get("metrics_json") or {}
            trend.append({
                "eval_date":    row.get("eval_date"),
                "trust_scalar": round(float(metrics.get("trust_scalar") or 0.0), 4),
                "coverage":     round(float(metrics.get("feature_coverage") or 0.0), 4),
            })
        trend.sort(key=lambda x: (x.get("eval_date") or ""))

        latest = trend[-1] if trend else {}
        return {
            "as_of":         today_str,
            "trust_scalar":  latest.get("trust_scalar"),
            "coverage":      latest.get("coverage"),
            "trend":         trend,
        }

    # ── API: kline/{symbol} ───────────────────────────────────────────────────

    @app.get("/api/kline/{symbol}")
    async def get_kline(symbol: str, days: int = 60):
        """Return OHLCV + indicators + event markers + recommendation context."""
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

        context = _explain_svc.build_kline_context(
            symbol,
            days=max(days, 60),
            db=db,
            data_root=data_root,
        )

        # Decision explanation — primary truth source for Symbol page
        explanation: dict = {}
        try:
            exp = _explain_svc.explain(symbol)
            explanation = exp.to_summary_dict()
        except Exception as exc:
            logger.debug("kline explain failed for %s: %s", symbol, exc)

        return {
            **context,
            "name": name,
            "explanation": explanation,
        }

    return app
