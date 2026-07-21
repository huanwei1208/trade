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
import os
import threading
import time as _time
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, cast

from trade_py.bus.admission import AdmissionPermit, ChannelAdmission, validate_channel_config
from trade_py.bus.models import (
    AdmissionOutcome,
    BusLifecycle,
    HandlerAdmissionResult,
    PublishResult,
    RuntimeCapacitySnapshot,
    RuntimeCapacityStatus,
)

if TYPE_CHECKING:
    from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

_CLAIM_RENEW_INTERVAL_SECONDS = 30.0
_CLAIM_RENEW_INITIAL_BACKOFF_SECONDS = 1.0
_CLAIM_RENEW_MAX_BACKOFF_SECONDS = 15.0
_DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 5.0
_HEARTBEAT_JOIN_TIMEOUT_SECONDS = 0.1
_PAYLOAD_OMITTED = object()


class _EventLogOnceStore(Protocol):
    def event_log_get_or_insert_once(
        self,
        topic: str,
        payload_json: str,
        idempotency_key: str,
        parent_event_id: int | None = None,
    ) -> tuple[dict[str, Any], bool]: ...


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _reject_non_finite_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _canonical_payload(payload: object) -> tuple[str, Mapping[str, Any]]:
    if payload is _PAYLOAD_OMITTED:
        payload = {}
    elif not isinstance(payload, dict):
        raise TypeError(f"event payload must be a dict, got {type(payload).__name__}")
    payload_json = json.dumps(payload, allow_nan=False)
    decoded = json.loads(payload_json, parse_constant=_reject_non_finite_json_constant)
    if not isinstance(decoded, dict):
        raise TypeError(f"event payload must encode a JSON object, got {type(decoded).__name__}")
    return payload_json, cast("Mapping[str, Any]", _freeze_json(decoded))


def _decode_durable_payload(payload_json: object) -> Mapping[str, Any]:
    decoded = json.loads(
        "null" if payload_json is None else str(payload_json),
        parse_constant=_reject_non_finite_json_constant,
    )
    if not isinstance(decoded, dict):
        raise TypeError(f"expected JSON object, got {type(decoded).__name__}")
    return cast("Mapping[str, Any]", _freeze_json(decoded))


def _linux_process_start_ticks(pid: int) -> str:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = stat.rsplit(")", 1)[1].split()
        return fields[19]
    except (IndexError, OSError):
        return "unknown"


def _claim_token() -> str:
    pid = os.getpid()
    return f"process:{pid}:{_linux_process_start_ticks(pid)}:{uuid.uuid4()}"


def _parse_event_time(value: Any) -> datetime:
    """Best-effort parse of a created_at timestamp from event_log rows."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
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
    GATE_MORNING = "gate.morning"  # 07:00
    GATE_CRYPTO_DAILY = "gate.crypto_daily"  # 09:00
    GATE_INTRADAY = "gate.intraday"  # every 1min during market session
    GATE_PRE_MARKET = "gate.pre_market"  # 07:05
    GATE_SIGNAL_AM = "gate.signal_am"  # 07:35
    GATE_MARKET_CLOSE = "gate.market_close"  # 15:15
    GATE_EVENING = "gate.evening"  # 22:00
    GATE_EVENT_EXTRACT = "gate.event_extract"  # 22:30
    GATE_EVALUATE_DAILY = "gate.evaluate_daily"  # 22:45
    GATE_SECTOR_WEEKLY = "gate.sector_weekly"  # Sat 07:30
    GATE_FUND_WEEKLY = "gate.fundamental_weekly"  # Sat 08:00
    GATE_MACRO_WEEKLY = "gate.macro_weekly"  # Sun 08:00
    GATE_MODEL_WEEKLY = "gate.model_weekly"  # Sun 09:00

    # Agenda-driven dispatch
    AGENDA_DUE = "agenda.due"

    # Downstream data events (result notifications for cascade triggers)
    KLINE_SYNCED = "data.kline.synced"
    REALTIME_SYNCED = "data.realtime.synced"
    INDEX_SYNCED = "data.index.synced"
    SENTIMENT_SYNCED = "data.sentiment.synced"
    CRYPTO_SYNCED = "data.crypto.synced"
    ASSET_INGESTED = "data.asset.ingested"
    BATCH_INGEST_COMPLETED = "data.batch.completed"
    WINDOW_SCORE_UPDATED = "signal.window.updated"
    FEATURES_BUILT = "model.features.built"
    LABELS_BUILT = "model.labels.built"
    MODEL_TRAINED = "model.trained"

    # Sentiment chain topics (split from data.sentiment.synced)
    SENTIMENT_FETCHED = "sentiment.fetched"
    SENTIMENT_SILVER_DONE = "sentiment.silver_done"
    SENTIMENT_GOLD_DONE = "sentiment.gold_done"
    EVENTS_EXTRACTED = "events.extracted"
    SIGNALS_EVENTS_UPDATED = "signals.events_updated"

    # Crypto news/sentiment chain
    NEWS_FETCHED = "news.fetched"
    NEWS_ANALYZED = "news.analyzed"
    NEWS_URGENT = "news.urgent"
    CRYPTO_SENTIMENT_UPDATED = "data.crypto.sentiment"
    FEAR_GREED_UPDATED = "data.crypto.fear_greed"

    # EBRT topics
    BELIEF_UPDATED = "belief.updated"
    RECOMMEND_PRODUCED = "recommend.produced"

    # Legacy aliases (kept for backward compat)
    SILVER_CREATED = "data.sentiment.synced"
    MODEL_INFERRED = "signal.model"

    # All gate topics (for dry-run iteration)
    ALL_GATES = [
        GATE_MORNING,
        GATE_CRYPTO_DAILY,
        GATE_INTRADAY,
        GATE_PRE_MARKET,
        GATE_SIGNAL_AM,
        GATE_MARKET_CLOSE,
        GATE_EVENING,
        GATE_EVENT_EXTRACT,
        GATE_EVALUATE_DAILY,
        GATE_SECTOR_WEEKLY,
        GATE_FUND_WEEKLY,
        GATE_MACRO_WEEKLY,
        GATE_MODEL_WEEKLY,
    ]


# ── Event dataclass ────────────────────────────────────────────────────────────


@dataclass
class Event:
    id: int
    topic: str
    payload: Mapping[str, Any]
    parent_event_id: int | None
    created_at: datetime
    bus: EventBus  # back-reference so handlers can publish downstream events


class EventAdmissionError(RuntimeError):
    def __init__(self, result: PublishResult[Event]) -> None:
        self.result = result
        super().__init__(
            f"event {result.event.id} admission {result.outcome.value} "
            f"for topic {result.event.topic}"
        )


class _RuntimeAdmissionFailure(RuntimeError):
    def __init__(self, category: str, detail: str) -> None:
        self.category = category
        super().__init__(detail)


@dataclass
class _OwnedHandlerExecution:
    event_id: int
    handler_name: str
    claim_token: str
    permit: AdmissionPermit
    heartbeat_stop: threading.Event
    heartbeat: threading.Thread
    future: Future[None] | None = None
    cleanup_lock: threading.Lock = field(default_factory=threading.Lock)
    cleaned: bool = False
    cancellation_recorded: bool = False


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
_CHANNEL_NAMES = ("ingest", "nlp", "signal", "decision", "io")


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

    def __init__(
        self,
        db: TradeDB,
        ingest_workers: int = 4,
        nlp_workers: int = 3,
        signal_workers: int = 3,
        decision_workers: int = 2,
        io_workers: int = 2,
        *,
        channel_capacities: Mapping[str, int] | None = None,
    ) -> None:
        self._db = db
        worker_counts = {
            "ingest": ingest_workers,
            "nlp": nlp_workers,
            "signal": signal_workers,
            "decision": decision_workers,
            "io": io_workers,
        }
        supplied_capacities = dict(channel_capacities or {})
        unknown_channels = sorted(set(supplied_capacities) - set(_CHANNEL_NAMES))
        if unknown_channels:
            raise ValueError(f"unknown EventBus channels: {', '.join(unknown_channels)}")
        configs = {
            name: validate_channel_config(
                name,
                workers=workers,
                capacity=supplied_capacities.get(name, workers * 2),
            )
            for name, workers in worker_counts.items()
        }
        # Isolated thread pools per channel. The owning runtime must shut them
        # down explicitly; mutating a started worker's daemon flag is invalid.
        self._pools: dict[str, ThreadPoolExecutor] = {}
        try:
            for name, config in configs.items():
                self._pools[name] = ThreadPoolExecutor(
                    max_workers=config.workers,
                    thread_name_prefix=f"bus-{name}",
                )
        except Exception:
            for pool in self._pools.values():
                pool.shutdown(wait=False)
            raise
        self._admission = {name: ChannelAdmission(name, config) for name, config in configs.items()}
        # Backwards compat: default pool for any legacy direct ._pool access
        self._pool = self._pools["io"]
        self._subs: dict[str, list[Callable[[Event], None]]] = defaultdict(list)
        self._subs_lock = threading.RLock()
        self._active_lock = threading.RLock()
        self._active_tasks_by_event: dict[int, int] = defaultdict(int)
        self._owned_lock = threading.RLock()
        self._owned_executions: dict[tuple[int, str], _OwnedHandlerExecution] = {}
        self._lifecycle_lock = threading.RLock()
        self._shutdown_lock = threading.Lock()
        self._replay_lock = threading.Lock()
        self._replay_after_id = 0
        self._lifecycle = BusLifecycle.READY
        self._generation = str(uuid.uuid4())
        self._started_at = datetime.now(timezone.utc)
        # Log channel/worker configuration at construction time (startup)
        logger.info(
            "EventBus started with channels: %s",
            ", ".join(
                f"{name}(workers={config.workers},capacity={config.capacity})"
                for name, config in configs.items()
            ),
        )

    def subscribe(self, topic: str, handler: Callable[[Event], None]) -> None:
        """Register a handler for a topic. Handlers run asynchronously."""
        new_name = getattr(handler, "__qualname__", repr(handler))
        with self._subs_lock:
            for existing in self._subs[topic]:
                if getattr(existing, "__qualname__", repr(existing)) == new_name:
                    return
            self._subs[topic].append(handler)

    def is_bound_to(self, db: TradeDB) -> bool:
        """Return whether this bus uses the exact supplied database facade."""
        return self._db is db

    def publish(
        self,
        topic: str,
        payload: dict[str, Any] | object = _PAYLOAD_OMITTED,
        parent_event_id: int | None = None,
    ) -> Event:
        """Persist and dispatch an event, raising when admission is not fully accepted."""
        result = self.publish_with_outcome(topic, payload, parent_event_id)
        if not result.accepted:
            error = EventAdmissionError(result)
            cause = next((item.cause for item in result.handlers if item.cause is not None), None)
            if cause is not None:
                raise error from cause
            raise error
        return result.event

    def publish_with_outcome(
        self,
        topic: str,
        payload: dict[str, Any] | object = _PAYLOAD_OMITTED,
        parent_event_id: int | None = None,
    ) -> PublishResult[Event]:
        """Persist an event and return an explicit aggregate admission outcome."""
        payload_json, payload_snapshot = _canonical_payload(payload)
        eid = self._db.event_log_insert(topic, payload_json, parent_event_id)
        event = Event(
            id=eid,
            topic=topic,
            payload=payload_snapshot,
            parent_event_id=parent_event_id,
            created_at=datetime.now(timezone.utc),
            bus=self,
        )
        handlers = self._dispatch_to_handlers(event)
        return PublishResult(
            event=event,
            outcome=self._aggregate_outcome(handlers),
            handlers=handlers,
        )

    def publish_child_once(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        parent_event_id: int,
        handoff_key: str,
    ) -> PublishResult[Event]:
        """Persist and dispatch one deterministic child handoff."""
        payload_json, _payload_snapshot = _canonical_payload(payload)
        row, _created = self._db.event_log_get_or_insert_child(
            topic,
            payload_json,
            parent_event_id,
            handoff_key,
        )
        try:
            payload_obj = _decode_durable_payload(row["payload"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._db.mark_replay_payload_invalid(
                int(row["id"]),
                f"{type(exc).__name__}: {exc}",
            )
            raise TypeError(f"child event payload must be an object: event_id={row['id']}") from exc
        event = Event(
            id=int(row["id"]),
            topic=str(row["topic"]),
            payload=payload_obj,
            parent_event_id=row.get("parent_event_id"),
            created_at=_parse_event_time(row.get("created_at")),
            bus=self,
        )
        handlers = self._dispatch_to_handlers(event)
        return PublishResult(
            event=event,
            outcome=self._aggregate_outcome(handlers),
            handlers=handlers,
        )

    def publish_once(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        parent_event_id: int | None = None,
    ) -> PublishResult[Event]:
        """Persist and dispatch one event for a stable producer idempotency key."""
        payload_json, _payload_snapshot = _canonical_payload(payload)
        row, _created = cast("_EventLogOnceStore", self._db).event_log_get_or_insert_once(
            topic,
            payload_json,
            idempotency_key,
            parent_event_id,
        )
        try:
            payload_obj = _decode_durable_payload(row["payload"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._db.mark_replay_payload_invalid(
                int(row["id"]),
                f"{type(exc).__name__}: {exc}",
            )
            raise TypeError(f"event payload must be an object: event_id={row['id']}") from exc
        event = Event(
            id=int(row["id"]),
            topic=str(row["topic"]),
            payload=payload_obj,
            parent_event_id=row.get("parent_event_id"),
            created_at=_parse_event_time(row.get("created_at")),
            bus=self,
        )
        handlers = self._dispatch_to_handlers(event)
        return PublishResult(
            event=event,
            outcome=self._aggregate_outcome(handlers),
            handlers=handlers,
        )

    def _dispatch_to_handlers(
        self,
        event: Event,
        handlers: Sequence[Callable[[Event], None]] | None = None,
        *,
        preserve_no_handler_error: bool = False,
    ) -> tuple[HandlerAdmissionResult, ...]:
        """Submit handlers that haven't yet succeeded for this event to the pool.

        Every eligible durable handler identity is prepared before the first
        executor admission. Succeeded handlers and already-claimed in-process
        handlers are not submitted again.
        """
        if handlers is None:
            with self._subs_lock:
                handlers = tuple(self._subs.get(event.topic, ()))
        else:
            handlers = tuple(handlers)
        if not handlers:
            if preserve_no_handler_error:
                logger.warning(
                    "replay retained event error without registered handlers | "
                    "event_id=%s topic=%s",
                    event.id,
                    event.topic,
                )
                return ()
            with self._lifecycle_lock:
                lifecycle = self._lifecycle
            if lifecycle is not BusLifecycle.READY:
                channel = _resolve_channel(event.topic)
                detail = self._admission_failure_detail(
                    AdmissionOutcome.SHUTTING_DOWN,
                    channel,
                )
                self._log_admission(
                    logging.WARNING,
                    event=event,
                    handler_name="<no_handler>",
                    channel=channel,
                    outcome=AdmissionOutcome.SHUTTING_DOWN,
                )
                return (
                    HandlerAdmissionResult(
                        event_id=event.id,
                        handler_name="<no_handler>",
                        channel=channel,
                        outcome=AdmissionOutcome.SHUTTING_DOWN,
                        detail=detail,
                    ),
                )
            self._db.event_log_complete(event.id, "ok", "<no_handler>")
            return ()
        succeeded = self._db.get_succeeded_handlers(event.id)
        channel = _resolve_channel(event.topic)
        eligible: list[tuple[Callable[[Event], None], str]] = []
        for handler in handlers:
            handler_name = getattr(handler, "__qualname__", repr(handler))
            if handler_name in succeeded:
                logger.debug(
                    "Skipping already-succeeded handler %s for event_id=%s topic=%s",
                    handler_name,
                    event.id,
                    event.topic,
                )
                continue
            eligible.append((handler, handler_name))

        if not eligible:
            self._db.finalize_event_if_complete(event.id)
            return ()

        self._db.prepare_handler_runs(
            event.id,
            [handler_name for _, handler_name in eligible],
        )
        results = tuple(
            self._admit_handler(event, handler, handler_name, channel)
            for handler, handler_name in eligible
        )
        return results

    def _admit_handler(
        self,
        event: Event,
        handler: Callable[[Event], None],
        handler_name: str,
        channel: str,
    ) -> HandlerAdmissionResult:
        claim_token = _claim_token()
        if not self._db.claim_handler_run(
            event.id,
            handler_name,
            claim_token,
        ):
            return HandlerAdmissionResult(
                event_id=event.id,
                handler_name=handler_name,
                channel=channel,
                outcome=AdmissionOutcome.ACCEPTED,
                detail="already_claimed",
            )

        admission = self._admission[channel]
        with self._lifecycle_lock:
            outcome, permit = admission.acquire()
        if permit is None:
            detail = self._admission_failure_detail(outcome, channel)
            self._db.mark_handler_admission_failed(
                event.id,
                handler_name,
                detail,
                claim_token=claim_token,
            )
            if outcome is not AdmissionOutcome.SATURATED or admission.should_log_saturation():
                self._log_admission(
                    logging.WARNING,
                    event=event,
                    handler_name=handler_name,
                    channel=channel,
                    outcome=outcome,
                )
            return HandlerAdmissionResult(
                event_id=event.id,
                handler_name=handler_name,
                channel=channel,
                outcome=outcome,
                detail=detail,
            )

        heartbeat_stop = threading.Event()
        claim_lost = threading.Event()
        heartbeat = threading.Thread(
            target=self._renew_claim_until_stopped,
            args=(event.id, handler_name, claim_token, heartbeat_stop, claim_lost),
            name=f"bus-claim-{event.id}",
            daemon=True,
        )
        execution = _OwnedHandlerExecution(
            event_id=event.id,
            handler_name=handler_name,
            claim_token=claim_token,
            permit=permit,
            heartbeat_stop=heartbeat_stop,
            heartbeat=heartbeat,
        )
        try:
            heartbeat.start()
        except Exception as exc:
            admission.record_submission_failure()
            permit.release()
            detail = (
                f"runtime_admission:submission_failed: claim heartbeat: {type(exc).__name__}: {exc}"
            )
            self._db.mark_handler_admission_failed(
                event.id,
                handler_name,
                detail,
                claim_token=claim_token,
            )
            self._log_admission(
                logging.ERROR,
                event=event,
                handler_name=handler_name,
                channel=channel,
                outcome=AdmissionOutcome.SUBMISSION_FAILED,
                exc_info=True,
            )
            return HandlerAdmissionResult(
                event_id=event.id,
                handler_name=handler_name,
                channel=channel,
                outcome=AdmissionOutcome.SUBMISSION_FAILED,
                detail=detail,
                cause=exc,
            )

        with self._owned_lock:
            self._owned_executions[(event.id, handler_name)] = execution
        self._mark_handler_started(event.id)
        try:
            future = self._pools[channel].submit(
                self._run_handler,
                handler,
                event,
                handler_name,
                execution,
                claim_lost,
            )
            execution.future = future
        except Exception as exc:
            admission.record_submission_failure()
            heartbeat_stopped = self._stop_claim_heartbeat(heartbeat_stop, heartbeat)
            if not heartbeat_stopped:
                raise RuntimeError(
                    "EventBus claim heartbeat did not stop after executor submission failure"
                ) from exc
            self._release_execution(execution)
            detail = f"runtime_admission:submission_failed: {type(exc).__name__}: {exc}"
            try:
                self._db.mark_handler_admission_failed(
                    event.id,
                    handler_name,
                    detail,
                    claim_token=claim_token,
                )
            except Exception as persistence_error:
                raise RuntimeError(
                    "failed to persist EventBus submission failure "
                    f"for event_id={event.id} handler={handler_name}"
                ) from persistence_error
            self._log_admission(
                logging.ERROR,
                event=event,
                handler_name=handler_name,
                channel=channel,
                outcome=AdmissionOutcome.SUBMISSION_FAILED,
                exc_info=True,
            )
            return HandlerAdmissionResult(
                event_id=event.id,
                handler_name=handler_name,
                channel=channel,
                outcome=AdmissionOutcome.SUBMISSION_FAILED,
                detail=detail,
                cause=exc,
            )
        admission.record_submission_success()
        self._log_admission(
            logging.DEBUG,
            event=event,
            handler_name=handler_name,
            channel=channel,
            outcome=AdmissionOutcome.ACCEPTED,
        )
        return HandlerAdmissionResult(
            event_id=event.id,
            handler_name=handler_name,
            channel=channel,
            outcome=AdmissionOutcome.ACCEPTED,
        )

    @staticmethod
    def _aggregate_outcome(
        results: Sequence[HandlerAdmissionResult],
    ) -> AdmissionOutcome:
        outcomes = {item.outcome for item in results}
        for outcome in (
            AdmissionOutcome.SUBMISSION_FAILED,
            AdmissionOutcome.SHUTTING_DOWN,
            AdmissionOutcome.SATURATED,
        ):
            if outcome in outcomes:
                return outcome
        return AdmissionOutcome.ACCEPTED

    def _admission_failure_detail(
        self,
        outcome: AdmissionOutcome,
        channel: str,
    ) -> str:
        capacity = self._admission[channel].config.capacity
        if outcome is AdmissionOutcome.SATURATED:
            return f"runtime_admission:saturated: channel={channel} capacity={capacity}"
        return f"runtime_admission:shutting_down: channel={channel}"

    def _log_admission(
        self,
        level: int,
        *,
        event: Event,
        handler_name: str,
        channel: str,
        outcome: AdmissionOutcome,
        exc_info: bool = False,
    ) -> None:
        capacity = self._admission[channel].config.capacity
        logger.log(
            level,
            "event admission | event_id=%s handler=%s topic=%s channel=%s outcome=%s capacity=%s",
            event.id,
            handler_name,
            event.topic,
            channel,
            outcome.value,
            capacity,
            exc_info=exc_info,
            extra={
                "event_id": event.id,
                "handler_name": handler_name,
                "event_topic": event.topic,
                "event_channel": channel,
                "admission_outcome": outcome.value,
                "channel_capacity": capacity,
            },
        )

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

    def _run_handler(
        self,
        handler: Callable[..., None],
        event: Event,
        handler_name: str,
        execution: _OwnedHandlerExecution,
        claim_lost: threading.Event,
    ) -> None:
        t0 = _time.time()
        try:
            execution.permit.mark_active()
            if claim_lost.is_set():
                raise RuntimeError(
                    f"handler claim lost before execution for event_id={event.id} "
                    f"handler={handler_name}"
                )
            # Optionally pass event_id kwarg if the handler accepts it
            kwargs: dict[str, Any] = {}
            if self._handler_accepts_kwarg(handler, "event_id"):
                kwargs["event_id"] = event.id
            if kwargs:
                handler(event, **kwargs)
            else:
                handler(event)
            elapsed = int((_time.time() - t0) * 1000)
            if claim_lost.is_set():
                raise RuntimeError(
                    f"handler completion claim lost for event_id={event.id} handler={handler_name}"
                )
            if not self._db.mark_handler_ok(
                event.id,
                handler_name,
                elapsed,
                claim_token=execution.claim_token,
            ):
                raise RuntimeError(
                    f"handler completion claim lost for event_id={event.id} handler={handler_name}"
                )
            logger.debug(
                "handler %s ok | event_id=%s topic=%s elapsed=%dms",
                handler_name,
                event.id,
                event.topic,
                elapsed,
            )
        except Exception as exc:
            elapsed = int((_time.time() - t0) * 1000)
            error_message = str(exc)
            if isinstance(exc, _RuntimeAdmissionFailure):
                error_message = (
                    f"runtime_admission:{exc.category}: "
                    f"{type(exc.__cause__ or exc).__name__}: {exc}"
                )
            elif error_message.startswith("runtime_admission:"):
                error_message = f"handler_error:{error_message}"
            logger.error(
                "handler %s | event_id=%s topic=%s failed: %s",
                handler_name,
                event.id,
                event.topic,
                exc,
                exc_info=True,
            )
            self._db.mark_handler_error(
                event.id,
                handler_name,
                error_message,
                elapsed,
                claim_token=execution.claim_token,
            )
        finally:
            heartbeat_stopped = self._stop_claim_heartbeat(
                execution.heartbeat_stop,
                execution.heartbeat,
            )
            if heartbeat_stopped:
                self._release_execution(execution)
            else:
                logger.error(
                    "handler heartbeat remained alive after completion | event_id=%s handler=%s",
                    event.id,
                    handler_name,
                )

    @staticmethod
    def _stop_claim_heartbeat(
        stop: threading.Event,
        heartbeat: threading.Thread,
    ) -> bool:
        stop.set()
        heartbeat.join(timeout=_HEARTBEAT_JOIN_TIMEOUT_SECONDS)
        return not heartbeat.is_alive()

    def _release_execution(self, execution: _OwnedHandlerExecution) -> None:
        with execution.cleanup_lock:
            if execution.cleaned:
                return
            execution.cleaned = True
            execution.permit.release()
            self._mark_handler_finished(execution.event_id)
            with self._owned_lock:
                self._owned_executions.pop(
                    (execution.event_id, execution.handler_name),
                    None,
                )

    def _cancel_queued_executions(self) -> int:
        cancelled = 0
        with self._owned_lock:
            executions = tuple(self._owned_executions.values())
        for execution in executions:
            future = execution.future
            if future is None or future.running() or future.done() or not future.cancel():
                continue
            heartbeat_stopped = self._stop_claim_heartbeat(
                execution.heartbeat_stop,
                execution.heartbeat,
            )
            if not heartbeat_stopped:
                logger.error(
                    "queued handler heartbeat did not stop after cancellation | "
                    "event_id=%s handler=%s",
                    execution.event_id,
                    execution.handler_name,
                )
                continue
            if not execution.cancellation_recorded:
                self._db.mark_handler_admission_failed(
                    execution.event_id,
                    execution.handler_name,
                    "runtime_admission:shutdown_cancelled: queued handler preserved for replay",
                    claim_token=execution.claim_token,
                )
                execution.cancellation_recorded = True
            self._release_execution(execution)
            cancelled += 1
        return cancelled

    def _reap_finished_executions(self) -> None:
        with self._owned_lock:
            executions = tuple(self._owned_executions.values())
        for execution in executions:
            future = execution.future
            if future is not None and future.done() and not execution.heartbeat.is_alive():
                self._release_execution(execution)

    def _owned_counts(self) -> tuple[int, int]:
        self._reap_finished_executions()
        with self._owned_lock:
            executions = tuple(self._owned_executions.values())
        handlers = sum(
            1 for execution in executions if execution.future is None or not execution.future.done()
        )
        heartbeats = sum(1 for execution in executions if execution.heartbeat.is_alive())
        return handlers, heartbeats

    def _wait_for_owned_shutdown(self, deadline: float) -> bool:
        while _time.monotonic() < deadline:
            with self._owned_lock:
                executions = tuple(self._owned_executions.values())
            for execution in executions:
                if execution.future is not None and execution.future.done():
                    if self._stop_claim_heartbeat(
                        execution.heartbeat_stop,
                        execution.heartbeat,
                    ):
                        self._release_execution(execution)
            handlers, heartbeats = self._owned_counts()
            if handlers == 0 and heartbeats == 0:
                return True
            _time.sleep(0.01)
        return False

    def _renew_claim_until_stopped(
        self,
        event_id: int,
        handler_name: str,
        claim_token: str,
        stop: threading.Event,
        claim_lost: threading.Event,
    ) -> None:
        delay = _CLAIM_RENEW_INTERVAL_SECONDS
        backoff = _CLAIM_RENEW_INITIAL_BACKOFF_SECONDS
        while not stop.wait(delay):
            try:
                if not self._db.renew_handler_claim(
                    event_id,
                    handler_name,
                    claim_token,
                ):
                    claim_lost.set()
                    logger.error(
                        "handler claim ownership lost | event_id=%s handler=%s",
                        event_id,
                        handler_name,
                    )
                    return
            except Exception:
                logger.exception(
                    "handler claim renewal failed | event_id=%s handler=%s",
                    event_id,
                    handler_name,
                )
                delay = min(backoff, _CLAIM_RENEW_MAX_BACKOFF_SECONDS)
                backoff = min(backoff * 2, _CLAIM_RENEW_MAX_BACKOFF_SECONDS)
                continue
            delay = _CLAIM_RENEW_INTERVAL_SECONDS
            backoff = _CLAIM_RENEW_INITIAL_BACKOFF_SECONDS

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
            return any(
                event_id >= min_event_id and count > 0
                for event_id, count in self._active_tasks_by_event.items()
            )

    def capacity_snapshot(self) -> RuntimeCapacitySnapshot:
        """Return process-local channel capacity without scanning durable data."""
        with self._lifecycle_lock:
            lifecycle = self._lifecycle
        channels = tuple(self._admission[name].snapshot() for name in _CHANNEL_NAMES)
        if lifecycle is BusLifecycle.STOPPING:
            status = RuntimeCapacityStatus.STOPPING
        elif lifecycle is BusLifecycle.STOPPED:
            status = RuntimeCapacityStatus.STOPPED
        elif any(channel.available == 0 for channel in channels):
            status = RuntimeCapacityStatus.SATURATED
        else:
            status = RuntimeCapacityStatus.READY
        return RuntimeCapacitySnapshot(
            generation=self._generation,
            status=status,
            lifecycle=lifecycle,
            started_at=self._started_at,
            channels=channels,
        )

    def replay_pending(self, *, batch_size: int = 100, max_events: int = 1000) -> None:
        """On daemon startup: re-dispatch events stuck in 'pending' state (crash recovery).

        For each pending event, re-dispatches to subscribed handlers; the dispatch
        loop skips handlers already recorded as 'ok' in event_handler_runs, so
        partially-completed events only re-run the handlers that haven't finished.
        Does NOT insert new event_log rows — reuses the existing event id.
        """
        bounded_batch = max(1, min(int(batch_size), 1000))
        bounded_total = max(1, int(max_events))
        with self._replay_lock:
            cycle_start = self._replay_after_id
            after_id = cycle_start
            replayed = 0
            wrapped = False
            while replayed < bounded_total:
                pending = self._db.event_log_replayable(
                    after_id=after_id,
                    limit=min(bounded_batch, bounded_total - replayed),
                )
                if wrapped:
                    pending = [row for row in pending if int(row["id"]) <= cycle_start]
                if not pending:
                    if cycle_start > 0 and not wrapped:
                        after_id = 0
                        self._replay_after_id = 0
                        wrapped = True
                        continue
                    return
                logger.info(
                    "Replaying bus event batch | count=%s after_id=%s wrapped=%s",
                    len(pending),
                    after_id,
                    wrapped,
                )
                for row in pending:
                    after_id = int(row["id"])
                    self._replay_after_id = after_id
                    replayed += 1
                    try:
                        payload_obj = _decode_durable_payload(row["payload"])
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        self._db.mark_replay_payload_invalid(
                            int(row["id"]),
                            f"{type(exc).__name__}: {exc}",
                        )
                        logger.error(
                            "Replay quarantined invalid payload | event_id=%s topic=%s error=%s",
                            row["id"],
                            row["topic"],
                            exc,
                        )
                        continue
                    event = Event(
                        id=int(row["id"]),
                        topic=row["topic"],
                        payload=payload_obj,
                        parent_event_id=row.get("parent_event_id"),
                        created_at=_parse_event_time(row.get("created_at")),
                        bus=self,
                    )
                    logger.info(
                        "Replaying event id=%s topic=%s",
                        event.id,
                        event.topic,
                    )
                    replayable_handlers = self._db.replayable_handler_names(event.id)
                    if replayable_handlers == set():
                        continue
                    handlers: Sequence[Callable[[Event], None]] | None = None
                    if replayable_handlers is not None:
                        with self._subs_lock:
                            handlers = tuple(
                                handler
                                for handler in self._subs.get(event.topic, ())
                                if getattr(handler, "__qualname__", repr(handler))
                                in replayable_handlers
                            )
                        if not handlers:
                            logger.warning(
                                "replay deferred without registered durable handlers | "
                                "event_id=%s topic=%s handlers=%s",
                                event.id,
                                event.topic,
                                sorted(replayable_handlers),
                            )
                            continue
                    results = self._dispatch_to_handlers(
                        event,
                        handlers,
                        preserve_no_handler_error=str(row.get("status") or "") == "error",
                    )
                    if any(result.outcome is AdmissionOutcome.SHUTTING_DOWN for result in results):
                        return

    def wait_for_idle(self, *, min_event_id: int | None = None, timeout_sec: float = 30.0) -> bool:
        deadline = _time.time() + max(0.1, timeout_sec)
        while _time.time() < deadline:
            self._reap_finished_executions()
            pending = self._db.event_log_pending(min_id=min_event_id)
            active = self._has_active_handlers(min_event_id=min_event_id)
            if not pending and not active:
                return True
            _time.sleep(0.1)
        return False

    def shutdown(
        self,
        wait: bool = True,
        *,
        timeout_sec: float = _DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        with self._shutdown_lock:
            self.begin_shutdown()
            self._cancel_queued_executions()
            for pool in self._pools.values():
                pool.shutdown(wait=False, cancel_futures=True)
            if not wait:
                return
            deadline = _time.monotonic() + max(0.01, float(timeout_sec))
            if not self._wait_for_owned_shutdown(deadline):
                handlers, heartbeats = self._owned_counts()
                raise RuntimeError(
                    f"EventBus shutdown incomplete: handlers={handlers} heartbeats={heartbeats}"
                )
            with self._lifecycle_lock:
                self._lifecycle = BusLifecycle.STOPPED
                for admission in self._admission.values():
                    admission.finish_shutdown()
            release_bus(self)

    def begin_shutdown(self) -> None:
        """Close admission before the owner waits for executor shutdown."""
        with self._lifecycle_lock:
            if self._lifecycle is BusLifecycle.STOPPED:
                return
            self._lifecycle = BusLifecycle.STOPPING
            for admission in self._admission.values():
                admission.begin_shutdown()


# ── DAG bootstrap ──────────────────────────────────────────────────────────────


def _make_dag_handler(
    db: TradeDB,
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
        run_id: int | None = None
        run_key = f"dag:{dag_id}"
        try:
            config_error = str(config.get("__dag_config_error__") or "").strip()
            if config_error:
                raise RuntimeError(f"DAG row {dag_id} has invalid config_json: {config_error}")
            succeeded_run = db.job_run_latest_success(
                event.id,
                job_name,
                run_key=run_key,
            )
            if succeeded_run is not None:
                result = str(succeeded_run.get("result_summary") or "")
                logger.info(
                    "dag resume: job=%s event_id=%s reusing successful run_id=%s",
                    job_name,
                    event.id,
                    succeeded_run.get("id"),
                )
            else:
                run_id = db.job_run_start(
                    job_name,
                    stage=stage,
                    trigger_event_id=event.id,
                    run_key=run_key,
                )
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
                run_id = None
                logger.info("dag done: job=%s result=%s", job_name, result)
            if emits:
                try:
                    child = event.bus.publish_child_once(
                        emits,
                        {"result": result},
                        parent_event_id=event.id,
                        handoff_key=f"dag:{dag_id}:{emits}",
                    )
                except Exception as exc:
                    raise _RuntimeAdmissionFailure(
                        "child_handoff",
                        f"DAG child handoff topic={emits}",
                    ) from exc
                if not child.accepted:
                    logger.warning(
                        "dag child deferred | parent_event_id=%s child_event_id=%s "
                        "topic=%s outcome=%s",
                        event.id,
                        child.event.id,
                        emits,
                        child.outcome.value,
                    )
        except Exception as exc:
            elapsed = int((_time.time() - t0) * 1000)
            if run_id is not None:
                db.job_run_finish(
                    run_id,
                    "error",
                    result_summary=str(exc)[:500],
                    elapsed_ms=elapsed,
                )
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


def _make_agenda_handler(db: TradeDB, data_root: str) -> Callable[[Event], None]:
    """Handle claimed agenda rows by publishing a topic or running a single job."""
    from trade_py.event import realize_planned_events
    from trade_py.jobs import JOB_REGISTRY, run_job

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
            if not isinstance(action_payload, dict):
                error = (
                    "agenda trigger payload must be a JSON object, "
                    f"got {type(action_payload).__name__}"
                )
                if agenda_id:
                    db.agenda_queue_update_status(
                        agenda_id,
                        "error",
                        result_summary=error,
                    )
                raise TypeError(error)
            handoff_key = f"agenda:{agenda_id or event.id}:{trigger_topic}"
            try:
                child = event.bus.publish_child_once(
                    trigger_topic,
                    action_payload,
                    parent_event_id=event.id,
                    handoff_key=handoff_key,
                )
            except Exception as first_error:
                try:
                    child = event.bus.publish_child_once(
                        trigger_topic,
                        action_payload,
                        parent_event_id=event.id,
                        handoff_key=handoff_key,
                    )
                except Exception as retry_error:
                    if agenda_id:
                        db.agenda_queue_update_status(
                            agenda_id,
                            "error",
                            result_summary=(
                                f"agenda child handoff failed: topic={trigger_topic} "
                                f"error={type(retry_error).__name__}: {retry_error}"
                            ),
                        )
                    raise _RuntimeAdmissionFailure(
                        "agenda_child_handoff",
                        f"agenda child handoff topic={trigger_topic}",
                    ) from retry_error
                logger.warning(
                    "agenda child recovered ambiguous publish | agenda_id=%s "
                    "parent_event_id=%s child_event_id=%s first_error=%s",
                    agenda_id,
                    event.id,
                    child.event.id,
                    first_error,
                )
            if agenda_id:
                if child.accepted:
                    db.agenda_queue_update_status(
                        agenda_id,
                        "done",
                        result_summary=(
                            f"published {trigger_topic} child_event_id={child.event.id}"
                        ),
                    )
                else:
                    db.agenda_queue_update_status(
                        agenda_id,
                        "error",
                        result_summary=(
                            f"agenda child deferred: topic={trigger_topic} "
                            f"child_event_id={child.event.id} "
                            f"outcome={child.outcome.value} "
                            "action=replay_event_bus_event"
                        ),
                    )
            return

        if job_name:
            effective_job_name = job_name
            if (
                job_name == "event_pipeline"
                and str(
                    payload.get("planned_event_id") or action_payload.get("planned_event_id") or ""
                ).strip()
            ):
                effective_job_name = "planned_event_realize"

            job_spec = JOB_REGISTRY.get(effective_job_name)
            stage = job_spec.stage if job_spec is not None else "compute"
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
                    job_name,
                    effective_job_name,
                    agenda_id,
                    result,
                )
                return
            except Exception as exc:
                elapsed = int((_time.time() - t0) * 1000)
                db.job_run_finish(
                    run_id, "error", result_summary=str(exc)[:500], elapsed_ms=elapsed
                )
                if agenda_id:
                    db.agenda_queue_update_status(agenda_id, "error", result_summary=str(exc)[:500])
                raise

        if agenda_id:
            db.agenda_queue_update_status(
                agenda_id, "skipped", result_summary="no trigger_topic/job_name"
            )

    handler.__name__ = "agenda_due"
    handler.__qualname__ = "agenda.dispatch"
    return handler


def bootstrap_from_dag(
    db: TradeDB,
    data_root: str,
    *,
    bus: EventBus | None = None,
) -> EventBus:
    """Read pipeline_dag table, subscribe handlers for each enabled row.

    This replaces the hardcoded handler registration in bus/handlers/*.py.
    Returns the supplied bus or the global EventBus singleton.
    """
    bus = bus or get_bus(db)
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
    db: TradeDB,
    bus: EventBus,
    data_root: str,
    row: dict,
    payload: dict[str, Any] | object = _PAYLOAD_OMITTED,
    *,
    parent_event_id: int | None = None,
) -> Event:
    """Dispatch a single DAG node as if its source topic just arrived.

    This is used by the Web console to replay a failed node and allow downstream
    emits to continue automatically.
    """
    if not row or not row.get("enabled"):
        raise ValueError("DAG row is missing or disabled")
    payload_json, payload_snapshot = _canonical_payload(payload)
    event_id = db.event_log_insert(
        str(row.get("source") or ""),
        payload_json,
        parent_event_id,
    )
    event = Event(
        id=event_id,
        topic=str(row.get("source") or ""),
        payload=payload_snapshot,
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
    handlers = bus._dispatch_to_handlers(event, [handler])
    outcome = bus._aggregate_outcome(handlers)
    if outcome is not AdmissionOutcome.ACCEPTED:
        result = PublishResult(event=event, outcome=outcome, handlers=handlers)
        error = EventAdmissionError(result)
        cause = next((item.cause for item in handlers if item.cause is not None), None)
        if cause is not None:
            raise error from cause
        raise error
    return event


# ── Singleton accessor ─────────────────────────────────────────────────────────

_BUS: EventBus | None = None
_BUS_LOCK = threading.RLock()


def get_bus(db: TradeDB) -> EventBus:
    """Return the global EventBus instance, creating it if needed."""
    global _BUS
    with _BUS_LOCK:
        if _BUS is None:
            _BUS = EventBus(db)
        return _BUS


def bind_bus(bus: EventBus) -> EventBus:
    """Bind an explicitly owned bus to the backwards-compatible global facade."""
    global _BUS
    with _BUS_LOCK:
        if _BUS is not None and _BUS is not bus:
            raise RuntimeError("EventBus facade is already bound to another runtime owner")
        _BUS = bus
        return bus


def release_bus(bus: EventBus) -> None:
    """Release the facade only when it still points at the supplied owned bus."""
    global _BUS
    with _BUS_LOCK:
        if _BUS is bus:
            _BUS = None
