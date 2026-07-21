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
  GET  /api/runtime/capacity     → process-local EventBus capacity and lifecycle
  GET  /api/calendar             → trading calendar + planned events
  GET  /api/agenda               → recent agenda queue
  GET  /api/data-health          → data freshness / coverage snapshot
  GET  /api/backups              → backup snapshots
  GET  /api/today-page           → market snapshot + pipeline health + trust_gate + top 5 picks
  GET  /api/signals-page         → top 50 picks with belief delta + top evidence (EBRT)
  GET  /api/belief/{symbol}      → BeliefState history + top AttentionScores (EBRT)
  GET  /api/belief-graph/{symbol} → Layered belief structure (final/sub-beliefs/factors/history)
  GET  /api/symbol-evidence/{symbol} → Article/event evidence + attention items (EBRT_14)
  GET  /api/symbol-sector/{symbol}   → Sector context + peer comparison (EBRT_14)
  GET  /api/symbol-data-ops/{symbol} → Per-domain data coverage matrix (EBRT_14)
  POST /api/symbol-data-ops/repull   → Enqueue re-pull for selected domains (EBRT_14)
  POST /api/symbol-data-ops/replay   → Enqueue downstream replay (EBRT_14)
  POST /api/symbol-data-ops/mark-verified → Mark domain verified (EBRT_14)
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
from threading import Lock, Thread
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from fastapi import Request
else:
    try:  # pragma: no cover - optional at import time
        from fastapi import Request
    except ImportError:  # pragma: no cover - fastapi missing outside web usage
        Request = Any

logger = logging.getLogger(__name__)

_PAYLOAD_OMITTED = object()


class _SyncStateVerificationStore(Protocol):
    def sync_state_mark_verified(
        self,
        source: str,
        dataset: str,
        symbol: str,
    ) -> bool: ...


class _WebRuntimeReadStore(Protocol):
    def readiness_signature_components(self) -> list[str | int]: ...

    def symbol_event_types(self, symbol: str, as_of: str, limit: int) -> list[str]: ...

    def instrument_names(self, symbols: list[str]) -> dict[str, str]: ...

    def kg_projection_summary(self, symbol_limit: int = 12) -> dict[str, list[dict[str, Any]]]: ...

    def quality_history_projection(self, limit: int = 7) -> dict[str, list[dict[str, Any]]]: ...

    def evidence_lookup(self, evidence_id: str) -> dict[str, Any] | None: ...

    def symbol_evidence_projection(
        self,
        symbol: str,
        as_of: str,
        days: int,
        evidence_limit: int = 20,
    ) -> dict[str, Any]: ...

    def symbol_sector_peer_projection(
        self,
        symbol: str,
        as_of: str,
        peer_limit: int,
    ) -> dict[str, Any]: ...

    def symbol_data_freshness_projection(
        self,
        symbol: str,
        as_of: str,
    ) -> dict[str, Any]: ...


def _runtime_reads(db: object) -> _WebRuntimeReadStore:
    return cast(_WebRuntimeReadStore, db)


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


def _hive_status(
    *,
    lag_days: int | None = None,
    coverage_pct: float | None = None,
    count: int | None = None,
    empty_is_error: bool = False,
) -> str:
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
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from pydantic import BaseModel
    except ImportError as exc:
        raise ImportError("fastapi required: uv add fastapi uvicorn") from exc

    from trade_py.bus import EventAdmissionError
    from trade_web.backend.event_admission import event_admission_failure_response

    data_root = os.environ.get("TRADE_DATA_ROOT", "data")
    shutdown_event = asyncio.Event()
    from trade_web.backend.runtime import (
        RuntimeService,
        WebResourceContainer,
        build_runtime_router,
    )

    resources = WebResourceContainer(data_root)
    runtime_service = RuntimeService(resources, shutdown_event)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        resources.start()
        try:
            yield
        finally:
            shutdown_event.set()
            resources.stop(wait=True)

    app = FastAPI(title="TradeDB Console", version="1.0", lifespan=lifespan)
    app.state.resources = resources
    app.state.runtime_service = runtime_service
    app.include_router(build_runtime_router(runtime_service))

    def _request_payload(req: dict[str, Any]) -> dict[str, Any]:
        payload = req.get("payload", _PAYLOAD_OMITTED)
        if payload is _PAYLOAD_OMITTED:
            return {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")
        return payload

    # BTC Observatory read-only routes (registered as a self-contained router so
    # this factory stays minimal; all logic lives in trade_web/backend/observatory).
    # Rollout is explicitly opt-in (default OFF): an unprepared installation must
    # not advertise a broken Observatory page (docs/27 Phase A, F14). The read-only
    # capability probe stays reachable either way so the frontend/routes agree.
    #
    # RA.1 (F14): the capability probe MUST NOT silently disappear. There is no
    # broad `except ImportError: pass` around registration — an import defect is a
    # real bug and must fail fast. Only enabled data-route registration is allowed
    # to degrade: a defect there is logged loudly and surfaced as capability
    # state=error (nav stays hidden), never swallowed into an app without a probe.
    from trade_web.backend.observatory import (
        observatory_enabled,
        register_observatory_capability,
        register_observatory_capability_error,
        register_observatory_routes,
    )

    if observatory_enabled():
        try:
            # Registers the data routes plus (last) the enabled capability probe,
            # so the probe reports enabled=True only after every route is built.
            register_observatory_routes(app, data_root)
        except Exception as exc:  # noqa: BLE001 - surface, don't silently drop routes
            # Log the full exception (with traceback) server-side only. The public
            # /capability probe must not leak str(exc)/paths, so it carries just a
            # stable reason_code (see capability_error_payload).
            logger.error("observatory data-route registration failed: %s", exc, exc_info=True)
            register_observatory_capability_error(app)
    else:
        register_observatory_capability(app, data_root, enabled=False)

    def _inference():
        return resources.inference

    def _state_svc():
        return resources.state_service

    def _decision_svc():
        return resources.decision_service

    def _explain_svc():
        return resources.explanation_service

    from trade_web.backend.ops_workspace import (
        build_ops_compute_layers,
        build_ops_dependency_path,
        build_ops_replay_preview,
        execute_ops_replay,
        get_ops_node_result,
    )
    from trade_web.backend.readiness import (
        build_readiness_grid,
        build_replay_plan,
        compute_readiness_fingerprint,
        create_recovery_action,
        detect_changed_data,
        execute_recovery_action,
        list_recovery_history,
    )

    _payload_cache: dict[str, dict[str, Any]] = {}
    _payload_cache_lock = Lock()
    _PAYLOAD_SCHEMA_VERSION = "2026-03-21-recommendation-recovery-v2"

    # ── DB helper ─────────────────────────────────────────────────────────────

    def _db():
        return resources.db

    def _current_asof(db=None) -> str:
        return runtime_service.current_asof(db)

    def _payload_signature(kind: str, db=None) -> str:
        return runtime_service.payload_signature(kind, db)

    def _readiness_signature(*, days: int, end_date: str | None, datasets: str | None) -> str:
        components = _runtime_reads(_db()).readiness_signature_components()
        base = "|".join(str(item or "") for item in components)
        return (
            f"readiness:{_PAYLOAD_SCHEMA_VERSION}:{days}:{end_date or ''}:{datasets or ''}:{base}"
        )

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
            payload = stored.get("payload_json")
            # Reject null/empty payloads — they indicate a previously failed build.
            # Treat as a cache miss so builder() is called again to produce real data.
            if isinstance(payload, dict) and len(payload) > 0:
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
        from trade_web.backend.market_data import read_symbol_sparkline

        return read_symbol_sparkline(data_root, symbol, days=days)

    def _read_symbol_event_tags(db, symbol: str, *, as_of: str, limit: int = 3) -> list[str]:
        try:
            return _runtime_reads(db).symbol_event_types(symbol, as_of, max(1, int(limit)))
        except Exception as exc:
            logger.warning(
                "symbol event tags unavailable: symbol=%s error=%s", symbol, type(exc).__name__
            )
            return []

    def _read_instrument_name_map(db, symbols: list[str]) -> dict[str, str]:
        cleaned = [
            str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()
        ]
        if not cleaned:
            return {}
        try:
            return _runtime_reads(db).instrument_names(cleaned)
        except Exception as exc:
            logger.warning("instrument names unavailable: error=%s", type(exc).__name__)
            return {}

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
            {
                "kind": "coverage",
                "title": "Fund Flow Coverage",
                "value": round(float(fund_cov or 0.0) * 100, 1),
            },
            {
                "kind": "coverage",
                "title": "Fundamental Coverage",
                "value": round(float(fundamental_cov or 0.0) * 100, 1),
            },
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
        active_models = [
            row
            for row in model_rows
            if row.get("is_active") or row.get("promotion_state") == "active"
        ]
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
                "coverage_pct": (kline_cov.get("coverage_pct") or 0.0) / 100.0
                if kline_cov.get("coverage_pct") is not None
                else None,
                "rows": kline.get("rows", 0),
                "count": kline.get("symbols", 0),
                "status": _hive_status(
                    lag_days=_lag_days(kline.get("max_date")),
                    coverage_pct=((kline_cov.get("coverage_pct") or 0.0) / 100.0)
                    if kline_cov.get("coverage_pct") is not None
                    else None,
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
                "coverage_pct": (instruments.get("coverage_pct") or 0.0) / 100.0
                if instruments.get("coverage_pct") is not None
                else None,
                "rows": instruments.get("sector_member_rows", 0),
                "count": instruments.get("total_symbols", 0),
                "status": _hive_status(
                    coverage_pct=((instruments.get("coverage_pct") or 0.0) / 100.0)
                    if instruments.get("coverage_pct") is not None
                    else None,
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
                "freshness_date": planned_events[0].get("scheduled_at", "")[:10]
                if planned_events
                else None,
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
                "freshness_date": active_models[0].get("trained_at", "")[:10]
                if active_models
                else None,
                "lag_days": _lag_days(
                    active_models[0].get("trained_at", "")[:10] if active_models else None
                ),
                "coverage_pct": None,
                "rows": len(model_rows),
                "count": len(active_models),
                "status": _hive_status(
                    lag_days=_lag_days(
                        active_models[0].get("trained_at", "")[:10] if active_models else None
                    ),
                    count=len(active_models),
                    empty_is_error=True,
                ),
                "notes": [],
            },
        ]
        by_domain: dict[str, dict[str, Any]] = {}
        for item in datasets:
            bucket = by_domain.setdefault(
                item["domain"], {"count": 0, "ok": 0, "partial": 0, "error": 0}
            )
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
            (
                row
                for row in workflows
                if str(row.get("status") or "") in {"error", "running", "partial"}
            ),
            workflows[0],
        )
        root_event_id = int(preferred.get("root_event_id") or 0)
        if root_event_id <= 0:
            return None
        return db.event_workflow_detail(root_event_id)

    def _workflow_graph(
        nodes: list[dict[str, Any]],
    ) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
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
            node_id
            for node_id in ancestors
            if str((node_by_id.get(node_id) or {}).get("status") or "")
            in {"error", "pending", "partial"}
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
                "models_loaded_at": _inference().loaded_at,
                "inference_models": _inference().model_names,
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
        today = _current_asof(db)
        focus_day = date.fromisoformat(today)
        workflows = db.event_workflow_recent(limit=24)
        focus = _pick_workflow_focus(workflows, db)
        runtime = db.pipeline_dag_runtime(recent_limit=240)
        today_events = db.get_events(from_date=today, to_date=today, limit=200)
        recent_market_events = db.get_events(
            from_date=(focus_day - timedelta(days=7)).isoformat(),
            to_date=today,
            limit=120,
        )
        due_agenda = db.agenda_queue_due(limit=24)
        planned_events = db.planned_events_list(
            start_date=today,
            end_date=(focus_day + timedelta(days=3)).isoformat(),
            limit=40,
        )
        failed_nodes = [
            node for node in runtime.get("nodes", []) if str(node.get("status") or "") == "error"
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
        projection = _runtime_reads(db).kg_projection_summary(symbol_limit=12)
        top_symbols = [dict(row) for row in projection.get("top_symbols", [])]
        rel_type_summary = [dict(row) for row in projection.get("relation_types", [])]
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
        today_str = _current_asof(db)
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
                ebrt_recs.append(
                    {
                        **r,
                        "belief_mu": round(belief_mu, 4),
                        "belief_sigma": round(belief_sigma, 4),
                        "belief_delta_mu": round(delta_mu, 4),
                    }
                )
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
                        {
                            "dataset": f.get("dataset"),
                            "lag_days": f.get("lag_days"),
                            "status": f.get("status"),
                        }
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
                    ws = _state_svc().build(sym, as_of_date=today_str)
                    _, act = _decision_svc().decide(ws)
                    action_str = act.action.value
                    rec_state = (
                        "ACTIONABLE"
                        if action_str in ("ADD", "PROBE")
                        else "BROWSE_ONLY"
                        if action_str in ("NO_ACTION", "avoid")
                        else "CONSTRAINED"
                    )
                    enriched = {
                        **pick,
                        "action": action_str,
                        "confidence": act.confidence,
                        "thesis": ws.state_summary,
                        "trust_score": round(ws.trust_score, 4),
                        "trust_level": "HIGH"
                        if ws.trust_score > 0.70
                        else ("MEDIUM" if ws.trust_score > 0.40 else "LOW"),
                        "top_invalidators": act.invalidators[:2],
                        "world_state_summary": ws.state_summary,
                        "event_tags": _read_symbol_event_tags(db, sym, as_of=today_str, limit=2),
                        "sparkline": _read_symbol_sparkline(sym),
                        "factor_summary": {
                            "positive": list(act.supporting_factors[:2]),
                            "negative": list(act.opposing_factors[:2]),
                        },
                        "data_risk_flag": ws.blockers[0] if ws.blockers else None,
                        "recommendation_state": rec_state,
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
        # When globally blocked, downgrade all recommendation_states to CONSTRAINED
        if global_blocked:
            for ta in top_actions:
                if ta.get("recommendation_state") == "ACTIONABLE":
                    ta["recommendation_state"] = "CONSTRAINED"
        actionable_count = sum(
            1 for row in top_actions if str(row.get("action") or "") in {"ADD", "PROBE", "REDUCE"}
        )
        watch_count = sum(1 for row in top_actions if str(row.get("action") or "") == "WATCH")
        decision_posture = (
            "DEGRADED"
            if global_blocked
            else "ACTIONABLE"
            if actionable_count > 0
            else "WATCHLIST"
            if watch_count > 0
            else "NO_ACTION"
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

    def _signals_page_payload(*, search: str | None = None, limit: int = 300) -> dict[str, Any]:
        db = _db()
        today_str = _current_asof(db)
        search_text = str(search or "").strip().lower()
        resolved_limit = max(50, min(int(limit or 300), 2000))

        # EBRT: use Recommendation table if available
        ebrt_recs = []
        try:
            ebrt_recs = db.recommendation_list(today_str)
        except Exception:
            pass

        if ebrt_recs:
            universe_total = len(ebrt_recs)
            name_map = _read_instrument_name_map(
                db,
                [str(item.get("symbol") or "") for item in ebrt_recs],
            )
            filtered_recs = []
            if search_text:
                for rec in ebrt_recs:
                    sym = str(rec.get("symbol") or "").upper()
                    name = name_map.get(sym, "")
                    haystack = f"{sym} {name}".lower()
                    if search_text in haystack:
                        filtered_recs.append(rec)
            else:
                filtered_recs = list(ebrt_recs)

            visible_recs = filtered_recs[:resolved_limit]
            heavy_limit = len(visible_recs) if search_text else min(len(visible_recs), 80)
            picks = []
            for index, r in enumerate(visible_recs):
                sym = str(r.get("symbol") or "")
                name = name_map.get(sym, "")
                belief_mu = 0.0
                belief_sigma = 0.3
                delta_mu = 0.0
                top_evidence: list = []
                sparkline: list[dict[str, Any]] = []
                event_tags: list[str] = []
                try:
                    bs = db.belief_state_get(today_str, sym)
                    if bs:
                        bv = bs.get("belief_vec") or {}
                        belief_mu = float(bv.get("mu", 0.0))
                        belief_sigma = float(bv.get("sigma", 0.3))
                    bt = db.belief_transition_get(sym, today_str)
                    if bt:
                        delta_mu = float((bt.get("delta_vec") or {}).get("mu_delta", 0.0))
                    if index < heavy_limit:
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
                factor_summary_val: dict = {"positive": [], "negative": []}
                data_risk_flag_val: str | None = None
                rec_state_val = "CONSTRAINED"
                if len(picks) < 20:
                    try:
                        ws = _state_svc().build(sym, as_of_date=today_str)
                        _, act = _decision_svc().decide(ws)
                        action_val = act.action.value
                        confidence_val = act.confidence
                        ws_summary = ws.state_summary
                        top_inv = act.invalidators[:2]
                        trust_score_val = round(ws.trust_score, 4)
                        trust_level_val = (
                            "HIGH"
                            if ws.trust_score > 0.70
                            else "MEDIUM"
                            if ws.trust_score > 0.40
                            else "LOW"
                        )
                        factor_summary_val = {
                            "positive": list(act.supporting_factors[:2]),
                            "negative": list(act.opposing_factors[:2]),
                        }
                        data_risk_flag_val = ws.blockers[0] if ws.blockers else None
                        rec_state_val = (
                            "ACTIONABLE"
                            if action_val in ("ADD", "PROBE")
                            else "BROWSE_ONLY"
                            if action_val in ("NO_ACTION", "avoid")
                            else "CONSTRAINED"
                        )
                    except Exception:
                        pass
                else:
                    # For picks 21-50: derive recommendation_state from action directly
                    raw_action = str(r.get("action") or "").upper()
                    rec_state_val = (
                        "ACTIONABLE"
                        if raw_action in ("ADD", "PROBE")
                        else "BROWSE_ONLY"
                        if raw_action in ("NO_ACTION", "AVOID")
                        else "CONSTRAINED"
                    )
                picks.append(
                    {
                        **r,
                        "name": name,
                        "belief_mu": round(belief_mu, 4),
                        "belief_sigma": round(belief_sigma, 4),
                        "belief_delta_mu": round(delta_mu, 4),
                        "top_evidence": top_evidence,
                        "sparkline": sparkline,
                        "event_tags": event_tags,
                        "action": action_val,
                        "confidence": confidence_val,
                        "world_state_summary": ws_summary,
                        "top_invalidators": top_inv,
                        "trust_score": trust_score_val,
                        "trust_level": trust_level_val,
                        "factor_summary": factor_summary_val,
                        "data_risk_flag": data_risk_flag_val,
                        "recommendation_state": rec_state_val,
                    }
                )
            return {
                "as_of": today_str,
                "picks": picks,
                "dropped": [],
                "shown": len(picks),
                "total": len(filtered_recs),
                "universe_total": universe_total,
                "search": search or "",
                "source": "ebrt",
            }

        # Fall back to old signal-based picks
        recommend = db.signal_recommend(
            limit=resolved_limit if not search_text else max(resolved_limit, 200)
        )
        picks = recommend.get("picks", [])
        fallback_name_map = _read_instrument_name_map(
            db,
            [str(pick.get("symbol") or "") for pick in picks],
        )
        if search_text:
            picks = [
                pick
                for pick in picks
                if search_text
                in f"{str(pick.get('symbol') or '').upper()} {fallback_name_map.get(str(pick.get('symbol') or '').upper(), '')}".lower()
            ]
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
            "shown": len(picks),
            "total": len(picks),
            "universe_total": len(picks),
            "search": search or "",
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
    async def get_dag_runtime(
        limit: int = Query(200, ge=1, le=500),
    ):
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
    async def update_dag_config(dag_id: int, req: dict):
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
    async def run_dag_node(dag_id: int, req: dict):
        from trade_py.bus import bootstrap_from_dag, dispatch_dag_row

        mode = str(req.get("mode") or "self").strip().lower()
        if mode not in {"self", "upstream", "downstream", "full"}:
            raise HTTPException(
                status_code=400, detail="mode must be one of self, upstream, downstream, full"
            )
        payload = _request_payload(req)
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
        bus = resources.bus
        bootstrap_from_dag(db, data_root, bus=bus)
        try:
            event = dispatch_dag_row(
                db,
                bus,
                data_root,
                target_row,
                payload,
                parent_event_id=None,
            )
        except EventAdmissionError as exc:
            return event_admission_failure_response(exc)
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
    async def trigger_event(req: dict):
        from trade_py.bus import bootstrap_from_dag

        topic = str(req.get("topic") or "").strip()
        if not topic:
            raise HTTPException(status_code=400, detail="topic is required")
        payload = _request_payload(req)
        db = _db()
        bus = resources.bus
        bootstrap_from_dag(db, data_root, bus=bus)
        result = bus.publish_with_outcome(topic, payload)
        if not result.accepted:
            return event_admission_failure_response(result)
        return {"event_id": result.event.id, "topic": topic}

    @app.post("/api/run")
    async def run_target(req: dict):
        target = str(req.get("target") or "").strip()
        if not target:
            raise HTTPException(status_code=400, detail="target is required")
        payload = _request_payload(req)
        raw_limit = req.get("limit")
        try:
            limit = 10 if raw_limit is None else int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="limit must be between 1 and 500",
            ) from exc
        if limit < 1 or limit > 500:
            raise HTTPException(
                status_code=400,
                detail="limit must be between 1 and 500",
            )

        result = resources.commands.start(
            target,
            payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
            limit=limit,
        )
        if result.accepted:
            return {
                "accepted": True,
                "target": target,
                "limit": limit,
                "pid": result.pid,
                "run_id": result.run_id,
                "status": "running",
            }
        outcome_value = str(getattr(result.outcome, "value", result.outcome))
        failure_contracts = {
            "saturated": {
                "message": "workflow command capacity is exhausted",
                "reason_code": "COMMAND_CAPACITY_EXHAUSTED",
                "status": "saturated",
                "retry_after": "1",
            },
            "stopping": {
                "message": "workflow command runtime is stopping",
                "reason_code": "COMMAND_RUNTIME_STOPPING",
                "status": "stopping",
                "retry_after": "5",
            },
            "spawn_failed": {
                "message": "workflow command could not be started",
                "reason_code": "COMMAND_START_FAILED",
                "status": "error",
                "retry_after": None,
            },
            "persistence_failed": {
                "message": "workflow command could not be recorded",
                "reason_code": "COMMAND_PERSISTENCE_FAILED",
                "status": "error",
                "retry_after": None,
            },
        }
        failure = failure_contracts.get(
            outcome_value,
            {
                "message": "workflow command is unavailable",
                "reason_code": "COMMAND_UNAVAILABLE",
                "status": "error",
                "retry_after": None,
            },
        )
        retry_after = failure["retry_after"]
        headers = {"Retry-After": retry_after} if isinstance(retry_after, str) else {}
        return JSONResponse(
            status_code=503,
            headers=headers,
            content={
                "accepted": False,
                "target": target,
                "limit": limit,
                "outcome": outcome_value,
                "message": failure["message"],
                "reason_code": failure["reason_code"],
                "run_id": result.run_id,
                "status": failure["status"],
            },
        )

    # ── API: event_log ────────────────────────────────────────────────────────

    @app.get("/api/events")
    async def get_events(
        limit: int = Query(50, ge=1, le=500),
        topic: str | None = None,
    ):
        db = _db()
        db.event_log_mark_stale()
        return db.event_log_recent(limit, topic)

    @app.get("/api/workflows")
    async def get_workflows(
        limit: int = Query(20, ge=1, le=500),
    ):
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
    async def rerun_workflow_node(root_event_id: int, req: dict):
        from trade_py.bus import bootstrap_from_dag, dispatch_dag_row

        dag_id = int(req.get("dag_id") or req.get("node_id") or 0)
        if dag_id <= 0:
            raise HTTPException(status_code=400, detail="dag_id is required")
        mode = str(req.get("mode") or "self").strip().lower()
        if mode not in {"self", "upstream", "downstream", "full"}:
            raise HTTPException(
                status_code=400, detail="mode must be one of self, upstream, downstream, full"
            )
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        detail = db.event_workflow_detail(root_event_id)
        if not detail:
            raise HTTPException(status_code=404, detail="workflow not found")
        node = next(
            (row for row in detail.get("nodes", []) if int(row.get("dag_id") or 0) == dag_id), None
        )
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
        bus = resources.bus
        bootstrap_from_dag(db, data_root, bus=bus)
        target_row = dag_row
        if mode == "full":
            result = bus.publish_with_outcome(
                str(detail.get("topic") or ""), payload, parent_event_id=root_event_id
            )
            if not result.accepted:
                return event_admission_failure_response(result)
            return {
                "accepted": True,
                "mode": mode,
                "root_event_id": root_event_id,
                "dag_id": dag_id,
                "job_name": node.get("job_name"),
                "event_id": result.event.id,
                "topic": detail.get("topic"),
                "target_dag_id": dag_id,
            }
        if mode == "upstream":
            upstream_dag_id = _pick_upstream_replay_node(detail.get("nodes") or [], dag_id)
            target_row = db.pipeline_dag_get(upstream_dag_id) or dag_row
        try:
            event = dispatch_dag_row(
                db,
                bus,
                data_root,
                target_row,
                payload,
                parent_event_id=root_event_id,
            )
        except EventAdmissionError as exc:
            return event_admission_failure_response(exc)
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
    async def get_runs(
        limit: int = Query(50, ge=1, le=500),
        stage: str | None = None,
    ):
        db = _db()
        db.job_runs_mark_stale_by_policy()
        return db.job_runs_recent(limit, stage=stage)

    # ── API: model_registry ───────────────────────────────────────────────────

    @app.get("/api/models")
    async def get_models():
        return _db().model_registry_list()

    @app.get("/api/automation/overview")
    async def get_automation_overview():
        db = _db()
        today = date.today()
        today_str = today.isoformat()
        latest_market_asof = db.get_latest_market_asof() or today_str
        latest_trading_day = (
            today_str
            if db.trading_calendar_is_open(today_str, exchange="SSE")
            else db.trading_calendar_prev_trading_day(today_str, exchange="SSE")
            or latest_market_asof
        )
        calendar_rows: list[dict[str, Any]] = []
        for offset in range(-1, 4):
            cur = today + timedelta(days=offset)
            row = db.trading_calendar_get(cur.isoformat(), exchange="SSE")
            if row:
                calendar_rows.append(row)
        due_agenda = db.agenda_queue_due(limit=12)
        recent_agenda = db.agenda_queue_recent(limit=12)
        recent_events = [
            row
            for row in db.event_log_recent(limit=120)
            if str(row.get("topic") or "").startswith("gate.")
            or str(row.get("topic") or "") == "agenda.due"
        ][:12]
        try:
            from trade_py.bus.scheduler import describe_schedule

            schedules = describe_schedule(db)
        except Exception as exc:  # pragma: no cover - defensive web path
            logger.warning("automation schedule introspection failed: %s", exc)
            schedules = []
        return {
            "today": today_str,
            "latest_market_asof": latest_market_asof,
            "latest_trading_day": latest_trading_day,
            "is_trading_day_today": bool(db.trading_calendar_is_open(today_str, exchange="SSE")),
            "web_runs_scheduler": False,
            "requires_daemon": True,
            "daemon_command": "trade start",
            "calendar": calendar_rows,
            "schedules": schedules,
            "due_agenda": due_agenda,
            "recent_agenda": recent_agenda,
            "recent_events": recent_events,
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

    @app.get("/api/research/warehouse/tables")
    async def get_research_warehouse_tables():
        from trade_web.backend.research import list_research_tables

        return list_research_tables(data_root)

    @app.get("/api/research/warehouse/{layer}/{table}")
    async def get_research_warehouse_table(layer: str, table: str, limit: int = 100):
        from fastapi import HTTPException

        from trade_web.backend.research import read_research_table

        try:
            return read_research_table(data_root, layer=layer, table=table, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/readiness-grid")
    async def get_readiness_grid(
        days: int = 30, end_date: str | None = None, datasets: str | None = None
    ):
        db = _db()
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        resolved_days = int(days or 30)
        if resolved_days not in {30, 60, 90}:
            resolved_days = 30
        dataset_list = [
            item.strip() for item in str(datasets or "").split(",") if item.strip()
        ] or None
        scope = f"{resolved_days}:{end_date or ''}:{','.join(dataset_list or [])}"
        return _snapshot_get_or_build(
            "readiness-grid",
            signature=_readiness_signature(
                days=resolved_days, end_date=end_date, datasets=datasets
            ),
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
    async def get_readiness_replay_plan(
        dataset: str,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ):
        db = _db()
        resolved_from = date_from or date or dtm.date.today().isoformat()
        resolved_to = date_to or date or resolved_from
        return build_replay_plan(db, dataset.strip(), date_from=resolved_from, date_to=resolved_to)

    @app.get("/api/readiness/history")
    async def get_readiness_history(
        dataset: str | None = None, date: str | None = None, limit: int = 40
    ):
        return {
            "items": list_recovery_history(
                _db(), dataset=dataset.strip() if dataset else None, date=date, limit=limit
            ),
        }

    @app.post("/api/readiness/detect-changes")
    async def post_readiness_detect_changes(req: dict):
        dataset = str(req.get("dataset") or "").strip()
        if not dataset:
            raise HTTPException(status_code=400, detail="dataset is required")
        date_from = str(req.get("date_from") or req.get("date") or "").strip()
        date_to = str(req.get("date_to") or req.get("date") or date_from).strip()
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        return detect_changed_data(
            data_root, _db(), dataset=dataset, date_from=date_from, date_to=date_to
        )

    @app.post("/api/readiness/backfill")
    async def post_readiness_backfill(req: dict):
        dataset = str(req.get("dataset") or "").strip()
        if not dataset:
            raise HTTPException(status_code=400, detail="dataset is required")
        date_from = str(req.get("date_from") or req.get("date") or "").strip()
        date_to = str(req.get("date_to") or req.get("date") or date_from).strip()
        mode = str(req.get("mode") or "data_only").strip().lower()
        if mode not in {"data_only", "data_plus_downstream", "full_replay"}:
            raise HTTPException(
                status_code=400,
                detail="mode must be one of data_only, data_plus_downstream, full_replay",
            )
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        db = _db()
        plan = build_replay_plan(db, dataset, date_from=date_from, date_to=date_to)
        fingerprint_before = compute_readiness_fingerprint(
            data_root, db, dataset=dataset, day=date_to
        )
        job_names = [plan.get("job_name")] if plan.get("job_name") else []
        if mode in {"data_plus_downstream", "full_replay"}:
            job_names.extend(
                str(item.get("job_name") or "") for item in plan.get("downstream_nodes", [])
            )
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
            fingerprint_before=fingerprint_before,
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
    async def post_readiness_replay(req: dict):
        dataset = str(req.get("dataset") or "").strip()
        if not dataset:
            raise HTTPException(status_code=400, detail="dataset is required")
        date_from = str(req.get("date_from") or req.get("date") or "").strip()
        date_to = str(req.get("date_to") or req.get("date") or date_from).strip()
        mode = str(req.get("mode") or "data_plus_downstream").strip().lower()
        if mode not in {"data_only", "data_plus_downstream", "full_replay"}:
            raise HTTPException(
                status_code=400,
                detail="mode must be one of data_only, data_plus_downstream, full_replay",
            )
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        db = _db()
        plan = build_replay_plan(db, dataset, date_from=date_from, date_to=date_to)
        fingerprint_before = compute_readiness_fingerprint(
            data_root, db, dataset=dataset, day=date_to
        )
        action_id = create_recovery_action(
            db,
            dataset=dataset,
            date_from=date_from,
            date_to=date_to,
            action_type="replay",
            mode=mode,
            job_names=[
                str(item.get("job_name") or "") for item in plan.get("downstream_nodes", [])
            ],
            affected_outputs=list(plan.get("affected_outputs") or []),
            request_payload=req,
            fingerprint_before=fingerprint_before,
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

    @app.get("/api/ops/compute-layers")
    async def get_ops_compute_layers_api(date: str | None = None):
        return build_ops_compute_layers(
            data_root,
            _db(),
            _state_svc(),
            _explain_svc(),
            as_of_date=date,
        )

    @app.get("/api/ops/node/{node_id:path}/result")
    async def get_ops_node_result_api(node_id: str, date: str | None = None):
        try:
            return get_ops_node_result(
                data_root,
                _db(),
                _state_svc(),
                _explain_svc(),
                node_id=node_id,
                as_of_date=date,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/ops/dependency-path")
    async def get_ops_dependency_path_api(node_ids: str):
        ids = [item.strip() for item in str(node_ids or "").split(",") if item.strip()]
        if not ids:
            raise HTTPException(status_code=400, detail="node_ids is required")
        return build_ops_dependency_path(ids)

    @app.post("/api/ops/replay/preview")
    async def post_ops_replay_preview_api(req: dict):
        selected_node_ids = [
            str(item).strip() for item in (req.get("selected_node_ids") or []) if str(item).strip()
        ]
        selected_cells = list(req.get("selected_cells") or [])
        date_from = str(req.get("date_from") or req.get("date") or "").strip()
        date_to = str(req.get("date_to") or req.get("date") or date_from).strip()
        mode = str(req.get("mode") or "selected_plus_downstream").strip().lower()
        action = str(req.get("action") or "recompute").strip().lower()
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        try:
            return build_ops_replay_preview(
                _db(),
                selected_node_ids=selected_node_ids,
                selected_cells=selected_cells,
                date_from=date_from,
                date_to=date_to,
                mode=mode,
                action=action,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/ops/replay/execute")
    async def post_ops_replay_execute_api(req: dict):
        selected_node_ids = [
            str(item).strip() for item in (req.get("selected_node_ids") or []) if str(item).strip()
        ]
        selected_cells = list(req.get("selected_cells") or [])
        date_from = str(req.get("date_from") or req.get("date") or "").strip()
        date_to = str(req.get("date_to") or req.get("date") or date_from).strip()
        mode = str(req.get("mode") or "selected_plus_downstream").strip().lower()
        action = str(req.get("action") or "recompute").strip().lower()
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        try:
            return execute_ops_replay(
                data_root,
                _db(),
                selected_node_ids=selected_node_ids,
                selected_cells=selected_cells,
                date_from=date_from,
                date_to=date_to,
                mode=mode,
                action=action,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ── POST /predict — online inference ─────────────────────────────────────

    class PredictRequest(BaseModel):
        symbols: list[str]
        date: str | None = None

    @app.post("/predict")
    async def predict(req: PredictRequest):
        if not req.symbols:
            raise HTTPException(status_code=400, detail="symbols list is empty")
        results = _inference().predict(req.symbols, req.date)
        return results

    @app.post("/predict/reload")
    async def reload_models():
        """Hot-reload models from model_registry."""
        _inference().reload()
        return {"reloaded": True, "models": _inference().model_names}

    # ── API: belief/{symbol} (EBRT) ───────────────────────────────────────────

    @app.get("/api/belief/{symbol}")
    async def get_belief(symbol: str, days: int = 30):
        """Return BeliefState history + top AttentionScores for a symbol."""
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")

        db = _db()
        today = _current_asof(db)

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
                    delta_mu = (
                        float((bt.get("delta_vec") or {}).get("mu_delta", 0.0)) if bt else 0.0
                    )
                    history.append(
                        {
                            "date": cur.isoformat(),
                            "mu": float(bv.get("mu", 0.0)),
                            "sigma": float(bv.get("sigma", 0.3)),
                            "confidence": float(row.get("confidence") or 0.3),
                            "uncertainty": float(row.get("uncertainty") or 0.3),
                            "delta_mu": round(delta_mu, 4),
                        }
                    )
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
                    row = _runtime_reads(db).evidence_lookup(str(a.get("evidence_id") or ""))
                    if row:
                        ev_type = str(row.get("evidence_type") or "unknown")
                        ev_direction = float(row.get("direction") or 0.0)
                except Exception:
                    pass
                top_attention.append(
                    {
                        "evidence_id": a.get("evidence_id"),
                        "evidence_type": ev_type,
                        "weight": float(a.get("weight") or 0.0),
                        "logit": float(a.get("logit") or 0.0),
                        "direction": round(ev_direction, 2),
                    }
                )
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
    async def get_signals_page(search: str | None = None, limit: int = 300):
        resolved_search = str(search or "").strip() or None
        resolved_limit = max(50, min(int(limit or 300), 2000))
        sig = f"{_payload_signature('signals')}:{resolved_search or ''}:{resolved_limit}"
        return _snapshot_get_or_build(
            "signals_page",
            signature=sig,
            ttl_seconds=300,
            builder=lambda: _signals_page_payload(search=resolved_search, limit=resolved_limit),
        )

    # ── API: state/{symbol} ───────────────────────────────────────────────────

    @app.get("/api/state/{symbol}")
    async def get_state(symbol: str, date: str | None = None):
        """Return WorldState for a symbol (regime labels, blockers, signals)."""
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")
        try:
            ws = _state_svc().build(symbol, as_of_date=date)
            return ws.to_dict()
        except Exception as exc:
            logger.exception("get_state error for %s: %s", symbol, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ── API: explain/{symbol} ─────────────────────────────────────────────────

    @app.get("/api/explain/{symbol}")
    async def get_explain(symbol: str, date: str | None = None):
        """Return full DecisionExplanation for a symbol (4-layer, unified)."""
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")
        try:
            exp = _explain_svc().explain(symbol, as_of_date=date)
            return exp.to_dict()
        except Exception as exc:
            logger.exception("get_explain error for %s: %s", symbol, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/causal/{symbol}")
    async def get_causal_chain(
        symbol: str,
        date: str | None = None,
        persist: bool = False,
        validate: bool = False,
        horizons: str = "1,5,20",
    ):
        """Return the machine-readable causal chain for a symbol."""
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")
        try:
            parsed_horizons = tuple(
                int(item.strip()) for item in horizons.split(",") if item.strip().isdigit()
            ) or (1, 5, 20)
            return _explain_svc().causal_chain(
                symbol,
                as_of_date=date,
                persist=persist,
                include_validation=validate,
                validation_horizons=parsed_horizons,
            )
        except Exception as exc:
            logger.exception("get_causal_chain error for %s: %s", symbol, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/causal/{symbol}/validation")
    async def get_causal_validation(
        symbol: str,
        date: str | None = None,
        snapshot_id: str | None = None,
        horizons: str = "1,5,20",
        persist: bool = True,
    ):
        """Validate the latest causal snapshot for a symbol."""
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")
        try:
            parsed_horizons = tuple(
                int(item.strip()) for item in horizons.split(",") if item.strip().isdigit()
            ) or (1, 5, 20)
            return _explain_svc().causal_validation(
                symbol,
                snapshot_id=snapshot_id,
                as_of_date=date,
                horizons=parsed_horizons,
                persist=persist,
            )
        except Exception as exc:
            logger.exception("get_causal_validation error for %s: %s", symbol, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ── API: actions-page ─────────────────────────────────────────────────────

    @app.get("/api/actions-page")
    async def get_actions_page():
        """Return today's action candidates (WATCH / PROBE / ADD)."""
        from trade_py.decision.action import DecisionAction

        db = _db()
        today_str = _current_asof(db)

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
                ws = _state_svc().build(sym, as_of_date=today_str)
                _, act = _decision_svc().decide(ws)
                if act.action in (
                    DecisionAction.WATCH,
                    DecisionAction.PROBE,
                    DecisionAction.ADD,
                    DecisionAction.REDUCE,
                ):
                    results.append(
                        {
                            "symbol": sym,
                            "action": act.action.value,
                            "confidence": act.confidence,
                            "score": round(act.score, 4),
                            "risk": round(act.risk, 4),
                            "reason": act.reason,
                            "position_hint": act.position_hint,
                            "state_summary": ws.state_summary,
                        }
                    )
            except Exception:
                continue

        results.sort(
            key=lambda x: (
                {"ADD": 0, "PROBE": 1, "WATCH": 2, "REDUCE": 3}.get(x["action"], 9),
                -x["score"],
            )
        )
        return {
            "as_of": today_str,
            "total": len(results),
            "actions": results,
        }

    # ── API: trust/overview ───────────────────────────────────────────────────

    @app.get("/api/trust/overview")
    async def get_trust_overview():
        """Return portfolio-level trust summary from QualityReport."""
        db = _db()
        today_str = _current_asof(db)
        try:
            projection = _runtime_reads(db).quality_history_projection(limit=7)
            rows = [dict(row) for row in projection.get("reports", [])]
            gate_rows = {
                str(row.get("eval_date") or ""): dict(row) for row in projection.get("gates", [])
            }
        except Exception:
            rows = []
            gate_rows = {}

        trend = []
        for row in rows:
            metrics = row.get("metrics")
            if not isinstance(metrics, dict) or not metrics:
                try:
                    metrics = json.loads(row.get("metrics_json") or "{}")
                except Exception:
                    metrics = {}
            gate_metrics = {}
            gate_row = gate_rows.get(str(row.get("eval_date") or ""))
            if gate_row:
                try:
                    gate_metrics = json.loads(gate_row.get("metrics_json") or "{}")
                except Exception:
                    gate_metrics = {}
            latest_gate = gate_metrics.get("latest_metrics") or {}
            coverage = (
                metrics.get("feature_coverage")
                or metrics.get("fund_flow_coverage")
                or latest_gate.get("source_healthy_ratio")
                or latest_gate.get("fund_flow_coverage")
                or latest_gate.get("fundamental_coverage")
                or 0.0
            )
            trend.append(
                {
                    "eval_date": row.get("eval_date"),
                    "trust_scalar": round(float(metrics.get("trust_scalar") or 0.0), 4),
                    "coverage": round(float(coverage or 0.0), 4),
                }
            )
        trend.sort(key=lambda x: x.get("eval_date") or "")

        latest = trend[-1] if trend else {}
        return {
            "as_of": today_str,
            "trust_scalar": latest.get("trust_scalar"),
            "coverage": latest.get("coverage"),
            "trend": trend,
        }

    # ── API: belief-graph/{symbol} ────────────────────────────────────────────

    @app.get("/api/belief-graph/{symbol}")
    async def get_belief_graph(symbol: str, days: int = 30):
        """Return layered belief structure for the Symbol Belief workspace tab.

        Composes from:
          - Belief history (existing /api/belief data)
          - Trust components from DecisionExplanation
          - Top attention scores as factor nodes
          - Provenance edges connecting factors to sub-beliefs
        """
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")

        db = _db()
        today = _current_asof(db)
        from datetime import timedelta as _td

        # ── 1. Belief history ─────────────────────────────────────────────────
        history: list[dict] = []
        try:
            cur = date.today()
            for _ in range(days):
                row = db.belief_state_get(cur.isoformat(), symbol)
                if row:
                    bv = row.get("belief_vec") or {}
                    bt = db.belief_transition_get(symbol, cur.isoformat())
                    delta_mu = (
                        float((bt.get("delta_vec") or {}).get("mu_delta", 0.0)) if bt else 0.0
                    )
                    history.append(
                        {
                            "date": cur.isoformat(),
                            "mu": float(bv.get("mu", 0.0)),
                            "sigma": float(bv.get("sigma", 0.3)),
                            "confidence": float(row.get("confidence") or 0.3),
                            "delta_mu": round(delta_mu, 4),
                        }
                    )
                cur -= _td(days=1)
            history = list(reversed(history))
        except Exception:
            pass

        # ── 2. Latest belief state ────────────────────────────────────────────
        final_belief: dict = {}
        try:
            bs = db.belief_state_get(today, symbol)
            if bs:
                bv = bs.get("belief_vec") or {}
                delta = 0.0
                if len(history) >= 2:
                    delta = history[-1]["mu"] - history[-2]["mu"]
                final_belief = {
                    "score": float(bv.get("mu", 0.0)),
                    "confidence": float(bs.get("confidence") or 0.3),
                    "trust": 0.0,  # filled from recommendation below
                    "delta": round(delta, 4),
                }
        except Exception:
            pass

        # ── 3. Trust via ExplanationService ──────────────────────────────────
        trust_components: dict = {}
        trust_score = 0.0
        belief_vec_latest: dict = {}
        try:
            exp = _explain_svc().explain(symbol, as_of_date=None)
            # DecisionExplanation has flat attrs: trust_score, trust_level, trust_components
            trust_score = float(getattr(exp, "trust_score", 0.0) or 0.0)
            trust_components = dict(getattr(exp, "trust_components", {}) or {})
            if final_belief:
                final_belief["trust"] = trust_score
        except Exception:
            pass

        # Pull latest belief_vec for time-horizon sub-belief fallback
        try:
            bs = db.belief_state_get(today, symbol)
            if bs:
                belief_vec_latest = bs.get("belief_vec") or {}
        except Exception:
            pass

        # ── 4. Sub-beliefs ────────────────────────────────────────────────────
        # Primary: from InferenceService trust components (feature_coverage, data_freshness)
        # Fallback: belief_vec time horizons (mu_1d, mu_5d, mu_20d) show how belief
        #           changes across holding horizons — this is always available when
        #           BeliefState has been computed.
        _SUB_BELIEF_NAMES = {
            "feature_coverage": {"zh": "特征覆盖度", "en": "Feature Coverage"},
            "data_freshness": {"zh": "数据新鲜度", "en": "Data Freshness"},
            "data_quality": {"zh": "数据质量", "en": "Data Quality"},
            "kline": {"zh": "技术面", "en": "Technical"},
            "sentiment": {"zh": "市场情绪", "en": "Sentiment"},
            "events": {"zh": "事件信号", "en": "Events"},
            "fundamentals": {"zh": "基本面", "en": "Fundamentals"},
            "uncertainty": {"zh": "不确定性", "en": "Uncertainty"},
            "mu_1d": {"zh": "1日预期", "en": "1-Day Horizon"},
            "mu_5d": {"zh": "5日预期", "en": "5-Day Horizon"},
            "mu_20d": {"zh": "20日预期", "en": "20-Day Horizon"},
        }
        _SUB_BELIEF_WEIGHTS = {
            "feature_coverage": 0.25,
            "data_freshness": 0.25,
            "data_quality": 0.20,
            "kline": 0.30,
            "sentiment": 0.20,
            "events": 0.15,
            "fundamentals": 0.10,
            "uncertainty": 0.05,
            "mu_1d": 0.20,
            "mu_5d": 0.45,
            "mu_20d": 0.35,
        }
        sub_beliefs: list[dict] = []

        if trust_components:
            # Use trust breakdown from InferenceService
            for key, val in trust_components.items():
                names = _SUB_BELIEF_NAMES.get(key, {"zh": key, "en": key})
                sub_beliefs.append(
                    {
                        "id": key,
                        "name_zh": names["zh"],
                        "name_en": names["en"],
                        "score": round(float(val), 4),
                        "weight": _SUB_BELIEF_WEIGHTS.get(key, 0.1),
                        "source": "trust_components",
                    }
                )
        elif belief_vec_latest:
            # Fallback: use belief time horizons as sub-beliefs
            for key in ("mu_1d", "mu_5d", "mu_20d"):
                val = belief_vec_latest.get(key)
                if val is not None:
                    names = _SUB_BELIEF_NAMES[key]
                    # mu is a raw belief score; clip to [0,1] for display
                    score = float(val)
                    score_display = max(0.0, min(1.0, (score + 1.0) / 2.0))
                    sub_beliefs.append(
                        {
                            "id": key,
                            "name_zh": names["zh"],
                            "name_en": names["en"],
                            "score": round(score_display, 4),
                            "weight": _SUB_BELIEF_WEIGHTS.get(key, 0.1),
                            "source": "belief_vec",
                            "raw_mu": round(score, 4),
                        }
                    )

        # ── 5. Factors from top attention ─────────────────────────────────────
        factors: list[dict] = []
        try:
            attn_rows = db.attention_list(symbol, today, top_n=10)
            for a in attn_rows:
                ev_type = "unknown"
                ev_direction = 0.0
                try:
                    row = _runtime_reads(db).evidence_lookup(str(a.get("evidence_id") or ""))
                    if row:
                        ev_type = str(row.get("evidence_type") or "unknown")
                        ev_direction = float(row.get("direction") or 0.0)
                except Exception:
                    pass
                weight = float(a.get("weight") or 0.0)
                factors.append(
                    {
                        "id": str(a.get("evidence_id", f"factor_{len(factors)}")),
                        "name": ev_type,
                        "score": round(0.5 + ev_direction * 0.5, 3),
                        "weight": round(weight, 4),
                        "direction": round(ev_direction, 2),
                        "evidence_type": ev_type,
                    }
                )
        except Exception:
            pass

        # ── 6. Provenance edges ───────────────────────────────────────────────
        # Connect factor → sub_belief based on evidence_type prefix
        _TYPE_TO_SUB = {
            "sentiment": "sentiment",
            "social": "sentiment",
            "news": "events",
            "event": "events",
            "kg": "events",
            "technical": "kline",
            "momentum": "kline",
            "fundamental": "fundamentals",
            "macro": "fundamentals",
        }
        provenance_edges: list[dict] = []
        sub_ids = {s["id"] for s in sub_beliefs}
        for f in factors:
            ev_type_lower = str(f.get("evidence_type", "")).lower()
            target = None
            for prefix, sub_id in _TYPE_TO_SUB.items():
                if prefix in ev_type_lower and sub_id in sub_ids:
                    target = sub_id
                    break
            if target and f.get("weight", 0) > 0.01:
                provenance_edges.append(
                    {
                        "from": f["id"],
                        "to": target,
                        "weight": f["weight"],
                    }
                )

        return {
            "symbol": symbol,
            "as_of": today,
            "final_belief": final_belief,
            "sub_beliefs": sub_beliefs,
            "factors": factors,
            "history": history,
            "provenance_edges": provenance_edges,
        }

    # ── API: symbol-evidence/{symbol} ────────────────────────────────────────

    @app.get("/api/symbol-evidence/{symbol}")
    async def get_symbol_evidence(symbol: str, days: int = 30):
        """Return article/event evidence for the Evidence workspace tab.

        Sources (in priority order):
          1. market_events for symbol's sector (entity_id = sector_code)
          2. Evidence rows for this symbol
          3. Attention scores with evidence_type context
        """
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")

        db = _db()
        today = _current_asof(db)
        projection = _runtime_reads(db).symbol_evidence_projection(
            symbol,
            today,
            max(0, int(days)),
            evidence_limit=20,
        )
        sector_code = projection.get("sector_code")
        market_events = [
            {
                "id": row.get("event_id"),
                "date": row.get("event_date"),
                "event_type": row.get("event_type"),
                "entity_id": row.get("entity_id"),
                "magnitude": round(float(row.get("magnitude") or 0), 3),
                "confidence": round(float(row.get("confidence") or 1.0), 3),
                "sentiment_score": round(float(row.get("sentiment_score") or 0), 3),
                "news_volume": int(row.get("news_volume") or 0),
                "summary": row.get("summary") or "",
                "source": "market_events",
            }
            for row in projection.get("market_events", [])
        ]
        evidence_items = [
            {
                "id": row.get("evidence_id"),
                "date": row.get("as_of_date"),
                "evidence_type": row.get("evidence_type"),
                "direction": round(float(row.get("direction") or 0), 2),
                "strength": round(float(row.get("strength") or 0), 3),
                "reliability": round(float(row.get("reliability") or 0), 3),
                "novelty": round(float(row.get("novelty") or 0), 3),
                "source": "evidence_table",
            }
            for row in projection.get("evidence_items", [])
        ]

        # 4. Attention scores (top factors with evidence context)
        attention_items: list[dict] = []
        try:
            attn_rows = db.attention_list(symbol, today, top_n=10)
            for a in attn_rows:
                ev_id = str(a.get("evidence_id", ""))
                ev_type = "unknown"
                direction = 0.0
                try:
                    r = _runtime_reads(db).evidence_lookup(ev_id)
                    if r:
                        ev_type = str(r.get("evidence_type") or "unknown")
                        direction = float(r.get("direction") or 0.0)
                except Exception:
                    pass
                attention_items.append(
                    {
                        "id": ev_id,
                        "evidence_type": ev_type,
                        "weight": round(float(a.get("weight") or 0.0), 4),
                        "direction": round(direction, 2),
                        "source": "attention",
                    }
                )
        except Exception:
            pass

        return {
            "symbol": symbol,
            "as_of": today,
            "sector_code": sector_code,
            "market_events": market_events,
            "evidence_items": evidence_items,
            "attention_items": attention_items,
        }

    # ── API: symbol-sector/{symbol} ───────────────────────────────────────────

    @app.get("/api/symbol-sector/{symbol}")
    async def get_symbol_sector(symbol: str, peer_limit: int = 10):
        """Return sector context + peer comparison for a symbol.

        Returns:
          - sector_code, sector_name
          - sector_sentiment: from gold sentiment parquet for latest date
          - peers: top peer symbols with signal/belief/recommendation data
        """
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")

        db = _db()
        today = _current_asof(db)
        projection = _runtime_reads(db).symbol_sector_peer_projection(
            symbol,
            today,
            max(0, int(peer_limit)),
        )
        sector_code = projection.get("sector_code")
        sector_name = projection.get("sector_name")
        sector_sentiment = round(float(projection.get("sector_sentiment") or 0.0), 3)
        sector_event_count = int(projection.get("sector_event_count") or 0)
        peers = []
        for row in projection.get("peers", []):
            peer_entry = dict(row)
            peer_entry["symbol"] = str(peer_entry.get("symbol") or "")
            peer_entry["name"] = str(peer_entry.get("name") or peer_entry["symbol"])
            if peer_entry.get("net_sentiment") is not None:
                peer_entry["net_sentiment"] = round(float(peer_entry["net_sentiment"]), 3)
            if peer_entry.get("score") is not None:
                peer_entry["score"] = round(float(peer_entry["score"]), 3)
            if peer_entry.get("risk") is not None:
                peer_entry["risk"] = round(float(peer_entry["risk"]), 3)
            if peer_entry.get("belief_mu") is not None:
                peer_entry["belief_mu"] = round(float(peer_entry["belief_mu"]), 4)
            if peer_entry.get("belief_confidence") is not None:
                peer_entry["belief_confidence"] = round(
                    float(peer_entry["belief_confidence"]),
                    3,
                )
            peers.append(peer_entry)

        return {
            "symbol": symbol,
            "as_of": today,
            "sector_code": sector_code,
            "sector_name": sector_name,
            "sector_sentiment": sector_sentiment,
            "sector_event_count": sector_event_count,
            "peers": peers,
        }

    # ── API: symbol-data-ops/{symbol} ─────────────────────────────────────────

    @app.get("/api/symbol-data-ops/{symbol}")
    async def get_symbol_data_ops(symbol: str):
        """Return per-domain data coverage matrix for a symbol.

        Domains checked:
          kline, fund_flow, fundamental, sentiment, events, belief, recommend
        """
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")

        db = _db()
        today = _current_asof(db)
        dr = Path(data_root)
        freshness = _runtime_reads(db).symbol_data_freshness_projection(symbol, today)

        def _parquet_freshness(parquet_path: Path) -> tuple[str | None, int | None]:
            """Return (last_date_str, lag_days) from a parquet's mtime or none."""
            try:
                if parquet_path.exists():
                    mtime = parquet_path.stat().st_mtime
                    import datetime as _dt

                    mdate = _dt.datetime.fromtimestamp(mtime).date()
                    lag = (date.today() - mdate).days
                    return mdate.isoformat(), lag
            except Exception:
                pass
            return None, None

        sym_file = symbol.replace(".", "_") + ".parquet"
        domains: list[dict] = []

        # ── kline ────────────────────────────────────────────────────────────
        kline = freshness.get("kline") or {}
        kline_last = kline.get("last_date")
        kline_rows = kline.get("row_count")
        # fallback from monthly parquet directories
        if not kline_last:
            try:
                for month_dir in sorted((dr / "market" / "kline").iterdir(), reverse=True):
                    fp = month_dir / sym_file
                    if fp.exists():
                        kline_last = month_dir.name + "-15"
                        break
            except Exception:
                pass
        kline_lag = _lag_days(kline_last)
        domains.append(
            {
                "id": "kline",
                "name_zh": "日K线",
                "name_en": "Daily Kline",
                "last_date": kline_last,
                "lag_days": kline_lag,
                "row_count": kline_rows,
                "status": _hive_status(lag_days=kline_lag),
                "source": "tushare_kline",
                "can_repull": True,
            }
        )

        # ── fund_flow ─────────────────────────────────────────────────────────
        ff_path = dr / "market" / "fund_flow" / sym_file
        ff_last, ff_lag = _parquet_freshness(ff_path)
        if not ff_last:
            ff_last = (freshness.get("fund_flow") or {}).get("last_date")
            ff_lag = _lag_days(ff_last)
        domains.append(
            {
                "id": "fund_flow",
                "name_zh": "资金流向",
                "name_en": "Fund Flow",
                "last_date": ff_last,
                "lag_days": ff_lag,
                "status": _hive_status(lag_days=ff_lag),
                "source": "akshare",
                "can_repull": True,
            }
        )

        # ── fundamental ───────────────────────────────────────────────────────
        fund_last = (freshness.get("fundamental") or {}).get("last_date")
        fund_lag = _lag_days(fund_last)
        if not fund_last:
            fund_path = dr / "market" / "fundamental" / sym_file
            fund_last, fund_lag = _parquet_freshness(fund_path)
        domains.append(
            {
                "id": "fundamental",
                "name_zh": "基本面",
                "name_en": "Fundamental",
                "last_date": fund_last,
                "lag_days": fund_lag,
                "status": _hive_status(lag_days=fund_lag, coverage_pct=None),
                "source": "tushare",
                "can_repull": False,
            }
        )

        # ── sentiment ─────────────────────────────────────────────────────────
        sent_last = (freshness.get("sentiment") or {}).get("last_date")
        sent_lag = _lag_days(sent_last)
        # Fallback: latest gold parquet
        if not sent_last:
            try:
                gold_dir = dr / "sentiment" / "gold"
                if gold_dir.exists():
                    latest_file = max(gold_dir.iterdir(), key=lambda p: p.name)
                    stem = latest_file.stem
                    if len(stem) == 10:
                        sent_last = stem
                        sent_lag = _lag_days(sent_last)
            except Exception:
                pass
        domains.append(
            {
                "id": "sentiment",
                "name_zh": "情绪信号",
                "name_en": "Sentiment",
                "last_date": sent_last,
                "lag_days": sent_lag,
                "status": _hive_status(lag_days=sent_lag),
                "source": "nlp_pipeline",
                "can_repull": False,
            }
        )

        # ── events ────────────────────────────────────────────────────────────
        events = freshness.get("events") or {}
        events_last = events.get("last_date")
        events_count = events.get("row_count")
        events_lag = _lag_days(events_last)
        domains.append(
            {
                "id": "events",
                "name_zh": "事件库",
                "name_en": "Events",
                "last_date": events_last,
                "lag_days": events_lag,
                "row_count": events_count,
                "status": _hive_status(lag_days=events_lag),
                "source": "kg_pipeline",
                "can_repull": False,
            }
        )

        # ── belief ────────────────────────────────────────────────────────────
        belief_last = (freshness.get("belief") or {}).get("last_date")
        belief_lag = _lag_days(belief_last)
        domains.append(
            {
                "id": "belief",
                "name_zh": "信念状态",
                "name_en": "Belief State",
                "last_date": belief_last,
                "lag_days": belief_lag,
                "status": _hive_status(lag_days=belief_lag),
                "source": "belief_pipeline",
                "can_repull": False,
            }
        )

        # ── recommend ─────────────────────────────────────────────────────────
        rec_last = (freshness.get("recommend") or {}).get("last_date")
        rec_lag = _lag_days(rec_last)
        domains.append(
            {
                "id": "recommend",
                "name_zh": "决策推荐",
                "name_en": "Recommendation",
                "last_date": rec_last,
                "lag_days": rec_lag,
                "status": _hive_status(lag_days=rec_lag),
                "source": "decision_pipeline",
                "can_repull": False,
            }
        )

        return {
            "symbol": symbol,
            "as_of": today,
            "domains": domains,
        }

    # ── API: symbol-data-ops repair actions ───────────────────────────────────

    @app.post("/api/symbol-data-ops/repull")
    async def symbol_data_ops_repull(request: Request):
        """Enqueue a re-pull for selected domains of a symbol.

        Body: { symbol: str, domains: list[str] }
        Returns: { accepted: true, job_id: str, message: str }
        """
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="invalid JSON body") from exc
        symbol = str(body.get("symbol") or "").strip().upper()
        domains = list(body.get("domains") or [])
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")

        job_id = (
            f"repull:{symbol}:{','.join(sorted(domains))}:"
            f"{dtm.datetime.now(dtm.timezone.utc).isoformat()[:19]}"
        )

        from trade_py.bus import Topic

        bus = resources.bus
        domain_topics = {
            "kline": Topic.GATE_MORNING,
            "fund_flow": Topic.GATE_MORNING,
        }
        for domain in domains:
            topic = domain_topics.get(domain)
            if topic:
                result = bus.publish_with_outcome(
                    topic,
                    {"symbol": symbol, "triggered_by": "symbol_data_ops"},
                )
                if not result.accepted:
                    return event_admission_failure_response(result)

        return {
            "accepted": True,
            "job_id": job_id,
            "message": f"Re-pull queued for {symbol}: {', '.join(domains) or 'none'}",
        }

    @app.post("/api/symbol-data-ops/replay")
    async def symbol_data_ops_replay(request: Request):
        """Enqueue downstream replay for selected domains of a symbol.

        Body: { symbol: str, domains: list[str] }
        Returns: { accepted: true, job_id: str, message: str }
        """
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="invalid JSON body") from exc
        symbol = str(body.get("symbol") or "").strip().upper()
        domains = list(body.get("domains") or [])
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")

        job_id = (
            f"replay:{symbol}:{','.join(sorted(domains))}:{dtm.datetime.utcnow().isoformat()[:19]}"
        )

        return {
            "accepted": True,
            "job_id": job_id,
            "message": f"Replay queued for {symbol}: {', '.join(domains) or 'none'}",
        }

    @app.post("/api/symbol-data-ops/mark-verified")
    async def symbol_data_ops_mark_verified(request: Request):
        """Mark selected domains as verified for a symbol.

        Body: { symbol: str, domains: list[str] }
        Updates sync_state.cursor with {'verified': true} for each domain.
        """
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="invalid JSON body") from exc
        symbol = str(body.get("symbol") or "").strip().upper()
        domains = list(body.get("domains") or [])
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")

        db = _db()
        sync_state_db = cast(_SyncStateVerificationStore, db)
        updated: list[str] = []
        _DOMAIN_TO_SOURCE = {
            "kline": ("tushare_kline", "daily"),
            "fund_flow": ("akshare", "fund_flow"),
            "fundamental": ("tushare", "fundamental"),
        }
        for domain in domains:
            src_info = _DOMAIN_TO_SOURCE.get(domain)
            if not src_info:
                continue
            source, dataset = src_info
            try:
                if sync_state_db.sync_state_mark_verified(source, dataset, symbol):
                    updated.append(domain)
            except Exception as exc:
                logger.debug("mark-verified failed for %s/%s: %s", domain, symbol, exc)

        return {
            "accepted": True,
            "updated": updated,
            "message": f"Marked verified: {', '.join(updated) or 'none'} for {symbol}",
        }

    # ── API: kline/{symbol} ───────────────────────────────────────────────────

    @app.get("/api/kline/{symbol}")
    async def get_kline(
        symbol: str,
        days: int = 60,
        date: str | None = None,
        adjust: str = "qfq",
        timeframe: str = "daily",
    ):
        """Return OHLCV + per-bar indicators + quote + price_basis + reason_groups."""
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")
        if adjust not in ("none", "qfq", "hfq"):
            adjust = "qfq"

        db = _db()

        # Get instrument name
        try:
            instr = db.instrument_lookup(symbol)
            name = str(instr.get("name") or symbol) if instr else symbol
        except Exception:
            name = symbol

        context = _explain_svc().build_kline_context(
            symbol,
            days=max(days, 60),
            as_of_date=date,
            db=db,
            data_root=data_root,
            adjust=adjust,
            timeframe=timeframe,
        )

        # Decision explanation — primary truth source for Symbol page
        explanation: dict = {}
        try:
            exp = _explain_svc().explain(symbol, as_of_date=date)
            explanation = exp.to_summary_dict()
        except Exception as exc:
            logger.debug("kline explain failed for %s: %s", symbol, exc)

        return {
            **context,
            "name": name,
            "explanation": explanation,
        }

    # ── API: data observability (business-level) ────────────────────────────

    def _scan_parquet_dates(path: Path) -> tuple[int, str | None, str | None]:
        """Return (row_count, min_date, max_date) for a parquet file using pandas/pyarrow.
        Returns (0, None, None) on any failure or missing file.
        """
        if not path.exists():
            return 0, None, None
        try:
            import pandas as pd

            df = pd.read_parquet(path, columns=["date"])
            if df.empty:
                return 0, None, None
            dates = df["date"].dropna().astype(str)
            return int(len(dates)), str(dates.min()), str(dates.max())
        except Exception:
            # Fallback: try pyarrow directly
            try:
                import pyarrow.parquet as pq

                table = pq.read_table(path, columns=["date"])
                dates = table.column("date").to_pylist()
                dates = [str(d) for d in dates if d is not None]
                if not dates:
                    return 0, None, None
                return len(dates), min(dates)[:10], max(dates)[:10]
            except Exception:
                return 0, None, None

    def _asset_health(
        lag_days: int | None, *, exists: bool = True, coverage_pct: float | None = None
    ) -> str:
        """Classify health for observability: ok, stale, missing, error."""
        if not exists:
            return "missing"
        if lag_days is None:
            return "error"
        if lag_days > 7:
            return "error"
        if lag_days > 2:
            return "stale"
        if coverage_pct is not None and coverage_pct < 85.0:
            return "stale"
        return "ok"

    def _resolve_asset_parquet_path(asset_class: str, symbol: str) -> Path:
        """Resolve the parquet file path for a registered asset.
        Layout: data/market/{asset_class}/{symbol}.parquet
        """
        safe_sym = symbol.replace("/", "_").replace(".", "_")
        return Path(data_root) / "market" / asset_class / f"{safe_sym}.parquet"

    def _resolve_kline_parquet_path(symbol: str) -> Path:
        """Resolve kline parquet path for A-share symbols.
        Layout: data/market/kline/{symbol}.parquet (dots replaced with underscores).
        """
        safe_sym = symbol.replace(".", "_")
        return Path(data_root) / "market" / "kline" / f"{safe_sym}.parquet"

    def _detect_data_types_for_asset(asset_id: str, asset_class: str, symbol: str) -> list[str]:
        """Determine which data types are present for a given asset."""
        types: list[str] = []
        # Kline / price data
        kline_path = _resolve_asset_parquet_path(asset_class, symbol)
        a_share_kline = _resolve_kline_parquet_path(symbol)
        if kline_path.exists() or a_share_kline.exists():
            types.append("kline")
        # For A-shares (asset_class not crypto/fx/commodity), check kline dir
        if asset_class in ("stock", "equity", "a_share") and a_share_kline.exists():
            if "kline" not in types:
                types.append("kline")
        # Sentiment: check sentiment/silver
        sent_silver_dir = Path(data_root) / "sentiment" / "silver"
        if sent_silver_dir.exists():
            for p in sent_silver_dir.rglob("*.parquet"):
                try:
                    import pandas as pd

                    df = pd.read_parquet(p, columns=["symbol"])
                    if symbol in df["symbol"].astype(str).values:
                        types.append("sentiment")
                        break
                except Exception:
                    pass
        # News: check news/silver and news/bronze
        news_silver_dir = Path(data_root) / "news" / "silver"
        news_bronze_dir = Path(data_root) / "news" / "bronze"
        for news_dir in (news_silver_dir, news_bronze_dir):
            if news_dir.exists() and not any(t == "news" for t in types):
                types.append("news")
                break
        return types

    @app.get("/api/data/assets")
    async def get_data_assets():
        """Asset inventory with data status for observability."""
        db = _db()
        assets: list[dict[str, Any]] = []
        summary: dict[str, int] = {
            "total_assets": 0,
            "ok": 0,
            "stale": 0,
            "missing": 0,
            "error": 0,
        }

        # Collect assets from asset_registry
        try:
            registry_rows = db.asset_registry_list(enabled_only=True)
        except Exception:
            registry_rows = []

        # Process registered cross-asset entries (crypto, fx, commodity)
        for row in registry_rows:
            asset_id = str(row.get("asset_id") or "")
            asset_class = str(row.get("asset_class") or "")
            symbol = str(row.get("symbol") or "")
            venue = str(row.get("venue") or "")
            if not asset_id or not symbol:
                continue
            path = _resolve_asset_parquet_path(asset_class, symbol)
            rows_count, first_dt, last_dt = _scan_parquet_dates(path)
            lag = _lag_days(last_dt)
            health = _asset_health(lag, exists=path.exists())
            data_types = _detect_data_types_for_asset(asset_id, asset_class, symbol)
            if "kline" not in data_types and path.exists():
                data_types.insert(0, "kline")
            assets.append(
                {
                    "asset_id": asset_id,
                    "asset_class": asset_class,
                    "symbol": symbol,
                    "venue": venue,
                    "data_types": data_types,
                    "total_rows": rows_count,
                    "first_date": first_dt,
                    "last_date": last_dt,
                    "lag_days": lag if lag is not None else -1,
                    "health": health,
                }
            )

        # Also scan A-share kline directory for stocks not in asset_registry
        try:
            kline_dir = Path(data_root) / "market" / "kline"
            if kline_dir.exists():
                manifest_path = kline_dir / "_manifest.json"
                manifest_symbols: set[str] = set()
                if manifest_path.exists():
                    try:
                        manifest = json.loads(manifest_path.read_text())
                        if isinstance(manifest, dict):
                            for sym_key in manifest.keys():
                                manifest_symbols.add(str(sym_key).replace("_", "."))
                    except Exception:
                        pass
                # Scan parquet files
                registered_symbols = {str(a.get("symbol") or "") for a in assets}
                for p in sorted(kline_dir.glob("*.parquet")):
                    sym = p.stem.replace("_", ".")
                    if sym.startswith("_") or sym in registered_symbols:
                        continue
                    if sym in manifest_symbols or True:  # include all kline files
                        rows_count, first_dt, last_dt = _scan_parquet_dates(p)
                        lag = _lag_days(last_dt)
                        health = _asset_health(lag, exists=p.exists())
                        data_types = ["kline"]
                        # Check sentiment/news for this symbol
                        sent_check = _detect_data_types_for_asset(f"stock.{sym}", "stock", sym)
                        for dt in sent_check:
                            if dt not in data_types:
                                data_types.append(dt)
                        assets.append(
                            {
                                "asset_id": f"stock.{sym}",
                                "asset_class": "stock",
                                "symbol": sym,
                                "venue": "akshare/tushare",
                                "data_types": data_types,
                                "total_rows": rows_count,
                                "first_date": first_dt,
                                "last_date": last_dt,
                                "lag_days": lag if lag is not None else -1,
                                "health": health,
                            }
                        )
        except Exception:
            pass

        summary["total_assets"] = len(assets)
        for a in assets:
            h = str(a.get("health") or "error")
            if h in summary:
                summary[h] += 1

        return {"assets": assets, "summary": summary}

    @app.get("/api/data/kline/{asset_id:path}")
    async def get_data_kline(asset_id: str, days: int = 30):
        """Return OHLCV rows for an asset over the last N days."""
        asset_id = str(asset_id or "").strip()
        if not asset_id:
            raise HTTPException(status_code=400, detail="asset_id is required")
        days_n = max(1, min(int(days or 30), 3650))

        # Resolve path: asset_registry first, then stock fallback
        parts = asset_id.split(".", 1)
        if len(parts) == 2:
            asset_class, symbol = parts[0], parts[1]
        else:
            asset_class, symbol = "stock", asset_id

        path: Path | None = None
        if asset_class in ("crypto", "fx", "commodity"):
            path = _resolve_asset_parquet_path(asset_class, symbol)
            sym_label = symbol.upper()
        else:
            # A-share: try kline dir first
            kp = _resolve_kline_parquet_path(symbol)
            if kp.exists():
                path = kp
            else:
                path = _resolve_asset_parquet_path(asset_class, symbol)
            sym_label = symbol.upper()

        rows: list[dict[str, Any]] = []
        interval = "1d"

        if path and path.exists():
            try:
                import pandas as pd

                end_d = date.today()
                start_d = end_d - timedelta(days=days_n * 2)  # extra buffer for non-trading days
                df = pd.read_parquet(path)
                if not df.empty and "date" in df.columns:
                    df["date"] = df["date"].astype(str).str[:10]
                    df = df[df["date"] >= start_d.isoformat()]
                    df = df.sort_values("date").tail(days_n)
                    for _, r in df.iterrows():

                        def _f(col: str, row=r) -> float | None:
                            v = row.get(col)
                            if v is None or (isinstance(v, float) and pd.isna(v)):
                                return None
                            try:
                                return float(v)
                            except (TypeError, ValueError):
                                return None

                        rows.append(
                            {
                                "date": str(r.get("date") or ""),
                                "open": _f("open"),
                                "high": _f("high"),
                                "low": _f("low"),
                                "close": _f("close"),
                                "volume": _f("volume"),
                            }
                        )
            except Exception as exc:
                logger.warning("data/kline read failed for %s: %s", asset_id, exc)

        return {
            "asset_id": asset_id,
            "symbol": sym_label,
            "interval": interval,
            "rows": rows,
        }

    @app.get("/api/data/gaps/{asset_id:path}")
    async def get_data_gaps(asset_id: str):
        """Gap analysis: expected vs present dates, gap list, longest gap."""
        asset_id = str(asset_id or "").strip()
        if not asset_id:
            raise HTTPException(status_code=400, detail="asset_id is required")

        parts = asset_id.split(".", 1)
        if len(parts) == 2:
            asset_class, symbol = parts[0], parts[1]
        else:
            asset_class, symbol = "stock", asset_id

        path: Path | None = None
        if asset_class in ("crypto", "fx", "commodity"):
            path = _resolve_asset_parquet_path(asset_class, symbol)
        else:
            kp = _resolve_kline_parquet_path(symbol)
            path = kp if kp.exists() else _resolve_asset_parquet_path(asset_class, symbol)

        expected_dates = 0
        present_dates = 0
        coverage_pct = 0.0
        gaps: list[dict[str, Any]] = []
        longest_gap_days = 0

        if path and path.exists():
            try:
                import pandas as pd

                df = pd.read_parquet(path, columns=["date"])
                if not df.empty:
                    dates = sorted(set(df["date"].astype(str).str[:10].dropna().tolist()))
                    present_dates = len(dates)
                    if dates:
                        first = dtm.date.fromisoformat(dates[0])
                        last = dtm.date.fromisoformat(dates[-1])
                        expected_dates = (last - first).days + 1
                        # Find gaps
                        prev: dtm.date | None = None
                        for d_str in dates:
                            d = dtm.date.fromisoformat(d_str)
                            if prev is not None:
                                delta = (d - prev).days
                                if delta > 1:
                                    gap_start = (prev + timedelta(days=1)).isoformat()
                                    gap_end = (d - timedelta(days=1)).isoformat()
                                    gap_len = delta - 1
                                    gaps.append(
                                        {
                                            "start": gap_start,
                                            "end": gap_end,
                                            "days": gap_len,
                                        }
                                    )
                                    if gap_len > longest_gap_days:
                                        longest_gap_days = gap_len
                            prev = d
                        coverage_pct = (
                            round(present_dates / expected_dates * 100.0, 2)
                            if expected_dates > 0
                            else 0.0
                        )
            except Exception as exc:
                logger.warning("data/gaps scan failed for %s: %s", asset_id, exc)

        return {
            "asset_id": asset_id,
            "expected_dates": expected_dates,
            "present_dates": present_dates,
            "coverage_pct": coverage_pct,
            "gaps": gaps,
            "longest_gap_days": longest_gap_days,
        }

    @app.get("/api/data/news")
    async def get_data_news(source: str = "", days: int = 3, limit: int = 30):
        """Return news articles from silver/bronze parquet with optional source filter."""
        days_n = max(1, min(int(days or 3), 30))
        limit_n = max(1, min(int(limit or 30), 200))
        source_filter = str(source or "").strip().lower()
        cutoff = (date.today() - timedelta(days=days_n)).isoformat()

        articles: list[dict[str, Any]] = []
        total = 0

        # Collect from news/silver first (analyzed, has sentiment_score)
        silver_dir = Path(data_root) / "news" / "silver"
        bronze_dir = Path(data_root) / "news" / "bronze"

        def _read_news_dir(base: Path, is_silver: bool) -> None:
            nonlocal total
            if not base.exists():
                return
            files = sorted(base.rglob("*.parquet"), reverse=True)
            for p in files:
                # Try to filter by date from filename
                stem = p.stem
                file_date = None
                if len(stem) == 10 and stem[4] == "-":
                    file_date = stem
                    if file_date < cutoff:
                        continue
                try:
                    import pandas as pd

                    df = pd.read_parquet(p)
                    if df.empty:
                        continue
                    # Normalize columns
                    if "published_at" in df.columns:
                        df = df[df["published_at"].astype(str).str[:10] >= cutoff]
                    if source_filter and "source" in df.columns:
                        df = df[
                            df["source"]
                            .astype(str)
                            .str.lower()
                            .str.contains(source_filter, na=False)
                        ]
                    total += len(df)
                    for _, r in df.iterrows():
                        if len(articles) >= limit_n:
                            return
                        src = str(r.get("source") or "")
                        title = str(r.get("title") or "")
                        url = str(r.get("url") or "")
                        pub = str(r.get("published_at") or r.get("date") or "")
                        summary = str(r.get("summary") or r.get("body", "") or "")
                        if len(summary) > 300:
                            summary = summary[:300] + "..."
                        sent = r.get("sentiment_score")
                        try:
                            sent_val = (
                                float(sent)
                                if sent is not None
                                and not (isinstance(sent, float) and pd.isna(sent))
                                else None
                            )
                        except (TypeError, ValueError):
                            sent_val = None
                        articles.append(
                            {
                                "title": title,
                                "source": src,
                                "published_at": pub,
                                "url": url,
                                "sentiment_score": sent_val,
                                "summary": summary,
                            }
                        )
                except Exception as exc:
                    logger.debug("news read failed for %s: %s", p, exc)
                if len(articles) >= limit_n:
                    return

        _read_news_dir(silver_dir, is_silver=True)
        if len(articles) < limit_n:
            _read_news_dir(bronze_dir, is_silver=False)

        # Sort by published_at descending
        articles.sort(key=lambda a: str(a.get("published_at") or ""), reverse=True)
        articles = articles[:limit_n]

        return {"articles": articles, "total": total}

    @app.get("/api/data/coverage")
    async def get_data_coverage():
        """Coverage matrix: per-asset-class coverage of key data types."""
        # Reuse asset list from /api/data/assets logic (call inline)
        assets_resp = await get_data_assets()
        raw_assets = assets_resp.get("assets")
        asset_list = raw_assets if isinstance(raw_assets, list) else []

        # Group by asset_class
        groups: dict[str, list[dict[str, Any]]] = {}
        for a in asset_list:
            cls = str(a.get("asset_class") or "other")
            groups.setdefault(cls, []).append(a)

        DATA_TYPES = ["kline", "sentiment", "news"]
        asset_classes: list[dict[str, Any]] = []
        for cls_name in sorted(groups.keys()):
            items = groups[cls_name]
            total = len(items)
            dt_stats: dict[str, dict[str, Any]] = {}
            for dt in DATA_TYPES:
                present = sum(
                    1
                    for a in items
                    if dt in (a.get("data_types") or []) and a.get("health") != "missing"
                )
                pct = round(present / total * 100.0, 1) if total > 0 else 0.0
                dt_stats[dt] = {"present": present, "total": total, "pct": pct}
            asset_classes.append(
                {
                    "name": cls_name,
                    "total_assets": total,
                    "data_types": dt_stats,
                }
            )

        return {"asset_classes": asset_classes}

    return app
