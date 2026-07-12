"""EventBus — in-process pub/sub with SQLite persistence.

Architecture:
- EventBus.publish(topic, payload)    → writes event_log row + dispatches handlers async
- EventBus.subscribe(topic, fn)       → registers a handler callable
- EventBus.replay_pending()           → on startup, re-dispatch stuck 'pending' rows
- bootstrap_from_dag(db, data_root)   → read pipeline_dag table, create subscriptions

Topic constants are in the Topic class. Query event_log directly:
  SELECT id, topic, status, handler, created_at FROM event_log ORDER BY id DESC LIMIT 20;
"""
from __future__ import annotations

import json
import logging
import time as _time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)


# ── Topic constants ────────────────────────────────────────────────────────────

class Topic:
    # Schedule gates (time-triggered, one-to-many)
    GATE_MORNING          = "gate.morning"           # 07:00
    GATE_CRYPTO_DAILY     = "gate.crypto_daily"      # 09:00
    GATE_INTRADAY         = "gate.intraday"          # every 1min during market session
    GATE_PRE_MARKET       = "gate.pre_market"         # 07:05
    GATE_SIGNAL_AM        = "gate.signal_am"          # 07:35
    GATE_MARKET_CLOSE     = "gate.market_close"       # 15:15
    GATE_EVENING          = "gate.evening"            # 22:00
    GATE_EVENT_EXTRACT    = "gate.event_extract"      # 22:30
    GATE_EVALUATE_DAILY   = "gate.evaluate_daily"     # 22:45
    GATE_SECTOR_WEEKLY    = "gate.sector_weekly"      # Sat 07:30
    GATE_FUND_WEEKLY      = "gate.fundamental_weekly" # Sat 08:00
    GATE_MACRO_WEEKLY     = "gate.macro_weekly"       # Sun 08:00
    GATE_MODEL_WEEKLY     = "gate.model_weekly"       # Sun 09:00

    # Agenda-driven dispatch
    AGENDA_DUE            = "agenda.due"

    # Downstream data events (result notifications for cascade triggers)
    KLINE_SYNCED          = "data.kline.synced"
    REALTIME_SYNCED       = "data.realtime.synced"
    INDEX_SYNCED          = "data.index.synced"
    SENTIMENT_SYNCED      = "data.sentiment.synced"
    CRYPTO_SYNCED         = "data.crypto.synced"
    ASSET_INGESTED        = "data.asset.ingested"
    BATCH_INGEST_COMPLETED = "data.batch.completed"
    WINDOW_SCORE_UPDATED  = "signal.window.updated"
    FEATURES_BUILT        = "model.features.built"
    LABELS_BUILT          = "model.labels.built"
    MODEL_TRAINED         = "model.trained"

    # Sentiment chain topics (split from data.sentiment.synced)
    SENTIMENT_FETCHED          = "sentiment.fetched"
    SENTIMENT_SILVER_DONE      = "sentiment.silver_done"
    SENTIMENT_GOLD_DONE        = "sentiment.gold_done"
    EVENTS_EXTRACTED           = "events.extracted"
    SIGNALS_EVENTS_UPDATED     = "signals.events_updated"

    # Crypto news/sentiment chain
    NEWS_FETCHED               = "news.fetched"
    NEWS_ANALYZED              = "news.analyzed"
    NEWS_URGENT                = "news.urgent"
    CRYPTO_SENTIMENT_UPDATED   = "data.crypto.sentiment"
    FEAR_GREED_UPDATED         = "data.crypto.fear_greed"

    # EBRT topics
    BELIEF_UPDATED             = "belief.updated"
    RECOMMEND_PRODUCED         = "recommend.produced"

    # Legacy aliases (kept for backward compat)
    SILVER_CREATED        = "data.sentiment.synced"
    MODEL_INFERRED        = "signal.model"

    # All gate topics (for dry-run iteration)
    ALL_GATES = [
        GATE_MORNING, GATE_CRYPTO_DAILY, GATE_INTRADAY, GATE_PRE_MARKET, GATE_SIGNAL_AM,
        GATE_MARKET_CLOSE, GATE_EVENING, GATE_EVENT_EXTRACT, GATE_EVALUATE_DAILY,
        GATE_SECTOR_WEEKLY, GATE_FUND_WEEKLY, GATE_MACRO_WEEKLY,
        GATE_MODEL_WEEKLY,
    ]


# ── Event dataclass ────────────────────────────────────────────────────────────

@dataclass
class Event:
    id: int
    topic: str
    payload: dict
    parent_event_id: int | None
    created_at: datetime
    bus: "EventBus"  # back-reference so handlers can publish downstream events


# ── EventBus ───────────────────────────────────────────────────────────────────

# Channel routing: map topic prefixes to dedicated thread pools to avoid congestion
_CHANNEL_INGEST_PREFIXES = ("gate.", "data.", "agenda.")  # Data ingest/fetch tasks
_CHANNEL_COMPUTE_PREFIXES = ("signal.", "model.", "sentiment.", "events.", "belief.", "recommend.", "news.")  # Compute/ML/signal/news tasks
_CHANNEL_IO_PREFIXES = ()  # All others default to IO pool (webhooks, backup, reports)


def _resolve_channel(topic: str) -> str:
    """Resolve topic to channel name for thread pool isolation."""
    if topic.startswith(_CHANNEL_INGEST_PREFIXES):
        return "ingest"
    if topic.startswith(_CHANNEL_COMPUTE_PREFIXES):
        return "compute"
    return "io"


class EventBus:
    """In-process pub/sub with SQLite persistence and multi-channel thread pool isolation.

    pub path: write event_log row (status=pending) → route to channel-specific pool → submit handlers
    Each channel has its own thread pool to prevent ingest traffic from blocking compute tasks.
    Channels:
      - ingest (4 workers): data fetch/ingest/sync (gate.*, data.*, agenda.*)
      - compute (4 workers): features/signals/models/sentiment/events
      - io (2 workers): webhooks/backups/reports and all other tasks
    """

    def __init__(self, db: "TradeDB",
                 ingest_workers: int = 4,
                 compute_workers: int = 4,
                 io_workers: int = 2) -> None:
        self._db = db
        # Isolated thread pools per channel
        self._pools = {
            "ingest": ThreadPoolExecutor(max_workers=ingest_workers, thread_name_prefix="bus-ingest"),
            "compute": ThreadPoolExecutor(max_workers=compute_workers, thread_name_prefix="bus-compute"),
            "io": ThreadPoolExecutor(max_workers=io_workers, thread_name_prefix="bus-io"),
        }
        # Backwards compat: default pool for any legacy direct ._pool access
        self._pool = self._pools["io"]
        self._subs: dict[str, list[Callable[[Event], None]]] = defaultdict(list)
        self._active_lock = threading.RLock()
        self._active_tasks_by_event: dict[int, int] = defaultdict(int)

    def subscribe(self, topic: str, handler: Callable[[Event], None]) -> None:
        """Register a handler for a topic. Handlers run asynchronously."""
        new_name = getattr(handler, "__qualname__", repr(handler))
        for existing in self._subs[topic]:
            if getattr(existing, "__qualname__", repr(existing)) == new_name:
                return
        self._subs[topic].append(handler)

    def publish(self, topic: str, payload: dict | None = None,
                parent_event_id: int | None = None) -> Event:
        """Persist event to event_log and dispatch to all subscribed handlers async."""
        payload = payload or {}
        eid = self._db.event_log_insert(topic, json.dumps(payload), parent_event_id)
        event = Event(
            id=eid,
            topic=topic,
            payload=payload,
            parent_event_id=parent_event_id,
            created_at=datetime.now(timezone.utc),
            bus=self,
        )
        handlers = self._subs.get(topic, [])
        if not handlers:
            self._db.event_log_complete(eid, "ok", "<no_handler>")
        else:
            channel = _resolve_channel(topic)
            pool = self._pools[channel]
            for h in handlers:
                self._mark_handler_started(event.id)
                try:
                    pool.submit(self._run_handler, h, event)
                except Exception:
                    self._mark_handler_finished(event.id)
                    raise
        return event

    def _run_handler(self, handler: Callable[[Event], None], event: Event) -> None:
        handler_name = getattr(handler, "__qualname__", repr(handler))
        t0 = _time.time()
        try:
            handler(event)
            elapsed = int((_time.time() - t0) * 1000)
            self._db.event_log_complete(event.id, "ok", handler_name, elapsed_ms=elapsed)
        except Exception as exc:
            elapsed = int((_time.time() - t0) * 1000)
            logger.error(
                "handler %s | topic=%s failed: %s",
                handler_name, event.topic, exc, exc_info=True,
            )
            self._db.event_log_complete(
                event.id, "error", handler_name, str(exc)[:500], elapsed_ms=elapsed
            )
        finally:
            self._mark_handler_finished(event.id)

    def _mark_handler_started(self, event_id: int) -> None:
        with self._active_lock:
            self._active_tasks_by_event[event_id] = self._active_tasks_by_event.get(event_id, 0) + 1

    def _mark_handler_finished(self, event_id: int) -> None:
        with self._active_lock:
            current = int(self._active_tasks_by_event.get(event_id, 0))
            if current <= 1:
                self._active_tasks_by_event.pop(event_id, None)
            else:
                self._active_tasks_by_event[event_id] = current - 1

    def _has_active_handlers(self, min_event_id: int | None = None) -> bool:
        with self._active_lock:
            if min_event_id is None:
                return any(count > 0 for count in self._active_tasks_by_event.values())
            return any(event_id >= min_event_id and count > 0 for event_id, count in self._active_tasks_by_event.items())

    def replay_pending(self) -> None:
        """On daemon startup: re-dispatch events stuck in 'pending' state (crash recovery)."""
        pending = self._db.event_log_pending()
        if pending:
            logger.info("Replaying %d pending bus events", len(pending))
        for row in pending:
            self.publish(row["topic"], json.loads(row["payload"] or "{}"))

    def wait_for_idle(self, *, min_event_id: int | None = None, timeout_sec: float = 30.0) -> bool:
        deadline = _time.time() + max(0.1, timeout_sec)
        while _time.time() < deadline:
            pending = self._db.event_log_pending(min_id=min_event_id)
            active = self._has_active_handlers(min_event_id=min_event_id)
            if not pending and not active:
                return True
            _time.sleep(0.1)
        return False

    def shutdown(self, wait: bool = True) -> None:
        for pool in self._pools.values():
            pool.shutdown(wait=wait)


# ── DAG bootstrap ──────────────────────────────────────────────────────────────

def _make_dag_handler(
    db: "TradeDB",
    job_name: str,
    emits: str | None,
    stage: str,
    data_root: str,
) -> Callable[[Event], None]:
    """Create a handler closure that runs a job, writes job_runs, and optionally emits."""
    from trade_py.jobs import run_job

    def handler(event: Event) -> None:
        logger.info("dag: job=%s stage=%s topic=%s", job_name, stage, event.topic)
        t0 = _time.time()
        run_id = db.job_run_start(job_name, stage=stage, trigger_event_id=event.id)
        try:
            payload_dict = dict(event.payload or {})
            df = str(payload_dict.get("date_from") or "").strip() or None
            dt = str(payload_dict.get("date_to") or "").strip() or None
            result = run_job(job_name, data_root, date_from=df, date_to=dt)
            elapsed = int((_time.time() - t0) * 1000)
            db.job_run_finish(run_id, "ok", result_summary=result, elapsed_ms=elapsed)
            logger.info("dag done: job=%s result=%s", job_name, result)
            if emits:
                event.bus.publish(emits, {"result": result}, parent_event_id=event.id)
        except Exception as exc:
            elapsed = int((_time.time() - t0) * 1000)
            db.job_run_finish(run_id, "error",
                              result_summary=str(exc)[:500], elapsed_ms=elapsed)
            raise

    handler.__name__ = job_name
    handler.__qualname__ = f"dag.{stage}.{job_name}"
    return handler


def _make_agenda_handler(db: "TradeDB", data_root: str) -> Callable[[Event], None]:
    """Handle claimed agenda rows by publishing a topic or running a single job."""
    from trade_py.jobs import JOB_REGISTRY, run_job
    from trade_py.event import realize_planned_events

    def handler(event: Event) -> None:
        payload = event.payload or {}
        agenda_id = int(payload.get("agenda_id") or 0)
        trigger_topic = str(payload.get("trigger_topic") or "").strip()
        job_name = str(payload.get("job_name") or "").strip()
        raw_payload = payload.get("payload_json")
        if isinstance(raw_payload, str):
            try:
                action_payload = json.loads(raw_payload)
            except Exception:
                action_payload = {"raw_payload": raw_payload}
        elif isinstance(raw_payload, dict):
            action_payload = raw_payload
        else:
            action_payload = {}

        if agenda_id:
            db.agenda_queue_update_status(agenda_id, "running")

        if trigger_topic:
            event.bus.publish(trigger_topic, action_payload, parent_event_id=event.id)
            if agenda_id:
                db.agenda_queue_update_status(
                    agenda_id, "done", result_summary=f"published {trigger_topic}"
                )
            return

        if job_name:
            effective_job_name = job_name
            if (
                job_name == "event_pipeline"
                and str(payload.get("planned_event_id") or action_payload.get("planned_event_id") or "").strip()
            ):
                effective_job_name = "planned_event_realize"

            stage = JOB_REGISTRY.get(effective_job_name).stage if effective_job_name in JOB_REGISTRY else "compute"
            t0 = _time.time()
            run_id = db.job_run_start(effective_job_name, stage=stage, trigger_event_id=event.id)
            try:
                if effective_job_name == "planned_event_realize":
                    planned_event_id = str(
                        payload.get("planned_event_id")
                        or action_payload.get("planned_event_id")
                        or ""
                    ).strip()
                    result = realize_planned_events(
                        data_root,
                        planned_event_ids=[planned_event_id] if planned_event_id else None,
                    )
                else:
                    result = run_job(effective_job_name, data_root)
                elapsed = int((_time.time() - t0) * 1000)
                db.job_run_finish(run_id, "ok", result_summary=result, elapsed_ms=elapsed)
                if agenda_id:
                    db.agenda_queue_update_status(agenda_id, "done", result_summary=result[:500])
                logger.info(
                    "agenda done: job=%s effective_job=%s agenda_id=%s result=%s",
                    job_name, effective_job_name, agenda_id, result,
                )
                return
            except Exception as exc:
                elapsed = int((_time.time() - t0) * 1000)
                db.job_run_finish(
                    run_id, "error", result_summary=str(exc)[:500], elapsed_ms=elapsed
                )
                if agenda_id:
                    db.agenda_queue_update_status(
                        agenda_id, "error", result_summary=str(exc)[:500]
                    )
                raise

        if agenda_id:
            db.agenda_queue_update_status(
                agenda_id, "skipped", result_summary="no trigger_topic/job_name"
            )

    handler.__name__ = "agenda_due"
    handler.__qualname__ = "agenda.dispatch"
    return handler


def bootstrap_from_dag(db: "TradeDB", data_root: str) -> "EventBus":
    """Read pipeline_dag table, subscribe handlers for each enabled row.

    This replaces the hardcoded handler registration in bus/handlers/*.py.
    Returns the global EventBus singleton.
    """
    bus = get_bus(db)
    rows = db.pipeline_dag_all(enabled_only=True)
    for row in rows:
        handler = _make_dag_handler(
            db,
            job_name=row["job_name"],
            emits=row["emits"],
            stage=row["stage"],
            data_root=data_root,
        )
        bus.subscribe(row["source"], handler)
    bus.subscribe(Topic.AGENDA_DUE, _make_agenda_handler(db, data_root))
    logger.info("bootstrap_from_dag: subscribed %d handlers from pipeline_dag", len(rows))
    return bus


def dispatch_dag_row(
    db: "TradeDB",
    bus: "EventBus",
    data_root: str,
    row: dict,
    payload: dict | None = None,
    *,
    parent_event_id: int | None = None,
) -> Event:
    """Dispatch a single DAG node as if its source topic just arrived.

    This is used by the Web console to replay a failed node and allow downstream
    emits to continue automatically.
    """
    if not row or not row.get("enabled"):
        raise ValueError("DAG row is missing or disabled")
    payload = dict(payload or {})
    event_id = db.event_log_insert(
        str(row.get("source") or ""),
        json.dumps(payload, ensure_ascii=False),
        parent_event_id,
    )
    event = Event(
        id=event_id,
        topic=str(row.get("source") or ""),
        payload=payload,
        parent_event_id=parent_event_id,
        created_at=datetime.now(timezone.utc),
        bus=bus,
    )
    handler = _make_dag_handler(
        db,
        job_name=str(row.get("job_name") or ""),
        emits=str(row.get("emits") or "") or None,
        stage=str(row.get("stage") or "compute"),
        data_root=data_root,
    )
    bus._mark_handler_started(event.id)
    try:
        bus._pool.submit(bus._run_handler, handler, event)
    except Exception:
        bus._mark_handler_finished(event.id)
        raise
    return event


# ── Singleton accessor ─────────────────────────────────────────────────────────

_BUS: EventBus | None = None


def get_bus(db: "TradeDB") -> EventBus:
    """Return the global EventBus instance, creating it if needed."""
    global _BUS
    if _BUS is None:
        _BUS = EventBus(db)
    return _BUS
