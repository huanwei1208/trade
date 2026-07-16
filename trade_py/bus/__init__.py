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

import inspect
import json
import logging
import time as _time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)


def _parse_event_time(value: Any) -> datetime:
    """Best-effort parse of a created_at timestamp from event_log rows."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


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

# Channel routing: map topic prefixes to dedicated thread pools to avoid congestion.
# Order matters: more specific patterns are checked first.
#
# Channel map:
#   ingest   (4 workers): gate.*, agenda.*, data.*.fetch     — pure network I/O / fetch triggers
#   nlp      (3 workers): sentiment.*, news.*                — slow LLM/NLP enrichment (I/O+CPU)
#   signal   (3 workers): signal.*, model.*, events.*, data.*.ingested
#                                                           — feature build, model train/infer, event extraction
#   decision (2 workers): belief.*, recommend.*              — latency-sensitive recommendation/belief
#   io       (2 workers): everything else                    — webhooks, backups, reports
_CHANNEL_INGEST_PREFIXES = ("gate.", "agenda.")
_CHANNEL_NLP_PREFIXES = ("sentiment.", "news.")
_CHANNEL_SIGNAL_PREFIXES = ("signal.", "model.", "events.")
_CHANNEL_DECISION_PREFIXES = ("belief.", "recommend.")


def _match_data_suffix(topic: str, suffix: str) -> bool:
    """Match data.<domain>.<suffix> pattern, e.g. data.kline.fetch, data.asset.ingested."""
    parts = topic.split(".")
    return len(parts) >= 3 and parts[0] == "data" and parts[-1] == suffix


def _resolve_channel(topic: str) -> str:
    """Resolve topic to channel name for thread pool isolation."""
    # data.*.fetch → ingest (pure network fetch)
    if _match_data_suffix(topic, "fetch"):
        return "ingest"
    # data.*.ingested → signal (post-ingest feature compute)
    if _match_data_suffix(topic, "ingested"):
        return "signal"
    if topic.startswith(_CHANNEL_INGEST_PREFIXES):
        return "ingest"
    if topic.startswith(_CHANNEL_NLP_PREFIXES):
        return "nlp"
    if topic.startswith(_CHANNEL_SIGNAL_PREFIXES):
        return "signal"
    if topic.startswith(_CHANNEL_DECISION_PREFIXES):
        return "decision"
    return "io"


class EventBus:
    """In-process pub/sub with SQLite persistence and multi-channel thread pool isolation.

    pub path: write event_log row (status=pending) → route to channel-specific pool → submit handlers
    Each channel has its own thread pool to prevent slow tasks from starving latency-sensitive ones.
    Channels:
      - ingest   (4 workers): gate.*, agenda.*, data.*.fetch — pure network I/O / fetch triggers
      - nlp      (3 workers): sentiment.*, news.*            — slow LLM/NLP enrichment (I/O+CPU)
      - signal   (3 workers): signal.*, model.*, events.*, data.*.ingested
                                                             — feature build, model train/infer, event extraction
      - decision (2 workers): belief.*, recommend.*          — latency-sensitive recommendation/belief
      - io       (2 workers): everything else                — webhooks, backups, reports
    """

    def __init__(self, db: "TradeDB",
                 ingest_workers: int = 4,
                 nlp_workers: int = 3,
                 signal_workers: int = 3,
                 decision_workers: int = 2,
                 io_workers: int = 2) -> None:
        self._db = db
        # Isolated thread pools per channel
        self._pools = {
            "ingest": ThreadPoolExecutor(max_workers=ingest_workers, thread_name_prefix="bus-ingest"),
            "nlp": ThreadPoolExecutor(max_workers=nlp_workers, thread_name_prefix="bus-nlp"),
            "signal": ThreadPoolExecutor(max_workers=signal_workers, thread_name_prefix="bus-signal"),
            "decision": ThreadPoolExecutor(max_workers=decision_workers, thread_name_prefix="bus-decision"),
            "io": ThreadPoolExecutor(max_workers=io_workers, thread_name_prefix="bus-io"),
        }
        # Backwards compat: default pool for any legacy direct ._pool access
        self._pool = self._pools["io"]
        self._subs: dict[str, list[Callable[[Event], None]]] = defaultdict(list)
        self._active_lock = threading.RLock()
        self._active_tasks_by_event: dict[int, int] = defaultdict(int)
        # Log channel/worker configuration at construction time (startup)
        logger.info(
            "EventBus started with channels: %s",
            ", ".join(f"{name}({pool._max_workers})" for name, pool in self._pools.items()),
        )

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
        self._dispatch_to_handlers(event)
        return event

    def _dispatch_to_handlers(self, event: Event) -> None:
        """Submit handlers that haven't yet succeeded for this event to the pool.

        Skips handlers already recorded as 'ok' in event_handler_runs (idempotency).
        For each eligible handler, marks started in DB before submitting.
        """
        handlers = self._subs.get(event.topic, [])
        if not handlers:
            self._db.event_log_complete(event.id, "ok", "<no_handler>")
            return
        succeeded = self._db.get_succeeded_handlers(event.id)
        channel = _resolve_channel(event.topic)
        pool = self._pools[channel]
        submitted = 0
        for h in handlers:
            handler_name = getattr(h, "__qualname__", repr(h))
            if handler_name in succeeded:
                logger.debug(
                    "Skipping already-succeeded handler %s for event_id=%s topic=%s",
                    handler_name, event.id, event.topic,
                )
                continue
            # Mark started in DB *before* submitting so a crash mid-dispatch still
            # records an in-progress row that will be re-run on replay (it's not 'ok').
            self._db.mark_handler_started(event.id, handler_name)
            self._mark_handler_started(event.id)
            try:
                pool.submit(self._run_handler, h, event, handler_name)
                submitted += 1
            except Exception:
                self._mark_handler_finished(event.id)
                raise
        # If every handler was skipped due to prior success, mark event ok
        if submitted == 0 and len(handlers) > 0 and len(succeeded) >= len(handlers):
            self._db.finalize_event_if_complete(event.id)

    def _handler_accepts_kwarg(self, handler: Callable[..., Any], kwarg_name: str) -> bool:
        """Check if handler's signature accepts the given keyword argument."""
        try:
            sig = inspect.signature(handler)
        except (TypeError, ValueError):
            return False
        if kwarg_name in sig.parameters:
            return True
        # Also accept **kwargs
        for p in sig.parameters.values():
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                return True
        return False

    def _run_handler(self, handler: Callable[..., None], event: Event,
                     handler_name: str | None = None) -> None:
        if handler_name is None:
            handler_name = getattr(handler, "__qualname__", repr(handler))
        t0 = _time.time()
        try:
            # Optionally pass event_id kwarg if the handler accepts it
            kwargs: dict[str, Any] = {}
            if self._handler_accepts_kwarg(handler, "event_id"):
                kwargs["event_id"] = event.id
            if kwargs:
                handler(event, **kwargs)
            else:
                handler(event)
            elapsed = int((_time.time() - t0) * 1000)
            self._db.mark_handler_ok(event.id, handler_name, elapsed)
            logger.debug(
                "handler %s ok | event_id=%s topic=%s elapsed=%dms",
                handler_name, event.id, event.topic, elapsed,
            )
        except Exception as exc:
            elapsed = int((_time.time() - t0) * 1000)
            logger.error(
                "handler %s | event_id=%s topic=%s failed: %s",
                handler_name, event.id, event.topic, exc, exc_info=True,
            )
            self._db.mark_handler_error(event.id, handler_name, str(exc), elapsed)
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
        """On daemon startup: re-dispatch events stuck in 'pending' state (crash recovery).

        For each pending event, re-dispatches to subscribed handlers; the dispatch
        loop skips handlers already recorded as 'ok' in event_handler_runs, so
        partially-completed events only re-run the handlers that haven't finished.
        Does NOT insert new event_log rows — reuses the existing event id.
        """
        pending = self._db.event_log_pending()
        if pending:
            logger.info("Replaying %d pending bus events", len(pending))
        for row in pending:
            try:
                payload_obj = json.loads(row["payload"] or "{}")
            except Exception:
                payload_obj = {}
            event = Event(
                id=int(row["id"]),
                topic=row["topic"],
                payload=payload_obj,
                parent_event_id=row.get("parent_event_id"),
                created_at=_parse_event_time(row.get("created_at")),
                bus=self,
            )
            logger.info(
                "Replaying event id=%s topic=%s", event.id, event.topic,
            )
            self._dispatch_to_handlers(event)

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
    dag_id: int,
    job_name: str,
    emits: str | None,
    stage: str,
    data_root: str,
    config: dict[str, Any],
) -> Callable[[Event], None]:
    """Create a handler closure that runs a job, writes job_runs, and optionally emits."""
    from trade_py.jobs import run_job

    def handler(event: Event) -> None:
        logger.info("dag: job=%s stage=%s topic=%s", job_name, stage, event.topic)
        t0 = _time.time()
        run_id = db.job_run_start(job_name, stage=stage, trigger_event_id=event.id)
        try:
            config_error = str(config.get("__dag_config_error__") or "").strip()
            if config_error:
                raise RuntimeError(f"DAG row {dag_id} has invalid config_json: {config_error}")
            payload_dict = dict(event.payload or {})
            df = str(payload_dict.get("date_from") or "").strip() or None
            dt = str(payload_dict.get("date_to") or "").strip() or None
            result = run_job(
                job_name,
                data_root,
                config=dict(config),
                date_from=df,
                date_to=dt,
            )
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
    handler.__qualname__ = f"dag.{stage}.{job_name}.row_{dag_id}"
    return handler


def _dag_row_config(row: dict[str, Any]) -> dict[str, Any]:
    """Parse one DAG row's config without falling back to another row."""
    raw = row.get("config_json")
    if raw in (None, ""):
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        return {"__dag_config_error__": str(exc)}
    if not isinstance(parsed, dict):
        return {"__dag_config_error__": "expected a JSON object"}
    return parsed


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
            dag_id=int(row["id"]),
            job_name=row["job_name"],
            emits=row["emits"],
            stage=row["stage"],
            data_root=data_root,
            config=_dag_row_config(row),
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
        dag_id=int(row["id"]),
        job_name=str(row.get("job_name") or ""),
        emits=str(row.get("emits") or "") or None,
        stage=str(row.get("stage") or "compute"),
        data_root=data_root,
        config=_dag_row_config(row),
    )
    handler_name = getattr(handler, "__qualname__", repr(handler))
    db.mark_handler_started(event.id, handler_name)
    bus._mark_handler_started(event.id)
    try:
        channel = _resolve_channel(event.topic)
        pool = bus._pools.get(channel, bus._pool)
        pool.submit(bus._run_handler, handler, event, handler_name)
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
