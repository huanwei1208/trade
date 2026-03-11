"""EventBus — in-process pub/sub with SQLite persistence.

Architecture:
- EventBus.publish(topic, payload)  → writes bus_events row + dispatches handlers async
- EventBus.subscribe(topic, fn)     → registers a handler callable
- EventBus.replay_pending()         → on startup, re-dispatch stuck 'pending' rows

Topic constants are in the Topic class. No CLI commands; query bus_events
directly via SQLite:
  SELECT id, topic, status, handler, created_at FROM bus_events ORDER BY id DESC LIMIT 20;
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)


# ── Topic constants ────────────────────────────────────────────────────────────

class Topic:
    # Schedule gates (time-triggered, one-to-many)
    GATE_MORNING          = "gate.morning"           # 07:00
    GATE_PRE_MARKET       = "gate.pre_market"         # 07:05
    GATE_SIGNAL_AM        = "gate.signal_am"          # 07:35
    GATE_REPORT           = "gate.report"             # 07:45
    GATE_MARKET_CLOSE     = "gate.market_close"       # 15:15
    GATE_EVENING          = "gate.evening"            # 22:00
    GATE_EVENT_EXTRACT    = "gate.event_extract"      # 22:30
    GATE_SECTOR_WEEKLY    = "gate.sector_weekly"      # Sat 07:30
    GATE_FUND_WEEKLY      = "gate.fundamental_weekly" # Sat 08:00
    GATE_MACRO_WEEKLY     = "gate.macro_weekly"       # Sun 08:00

    # Job topics (manual precise trigger, one-to-one)
    JOB_KLINE             = "job.kline_update"
    JOB_CROSS_ASSET       = "job.cross_asset"
    JOB_MARKET_INDEX      = "job.market_index"
    JOB_FUND_FLOW         = "job.fund_flow"
    JOB_NORTHBOUND        = "job.northbound"
    JOB_WINDOW_SCORE      = "job.window_score"
    JOB_MORNING_BRIEF     = "job.morning_brief"
    JOB_SENTIMENT         = "job.sentiment_pipeline"
    JOB_EVENT_PIPELINE    = "job.event_pipeline"
    JOB_EVENT_BACKFILL    = "job.event_backfill"
    JOB_SECTOR_REFRESH    = "job.sector_refresh"
    JOB_FUNDAMENTAL       = "job.fundamental"
    JOB_MACRO             = "job.macro"
    JOB_MODEL_INFERENCE   = "job.model_inference"

    # Downstream data events (result notifications for cascade triggers)
    KLINE_SYNCED          = "data.kline.synced"
    INDEX_SYNCED          = "data.index.synced"
    SILVER_CREATED        = "data.sentiment.silver"
    WINDOW_SCORE_UPDATED  = "signal.window_score"
    MODEL_INFERRED        = "signal.model"
    MORNING_BRIEF_READY   = "report.morning_brief"

    # All gate topics (for dry-run iteration)
    ALL_GATES = [
        GATE_MORNING, GATE_PRE_MARKET, GATE_SIGNAL_AM, GATE_REPORT,
        GATE_MARKET_CLOSE, GATE_EVENING, GATE_EVENT_EXTRACT,
    ]


# ── Event dataclass ────────────────────────────────────────────────────────────

@dataclass
class Event:
    id: int
    topic: str
    payload: dict
    created_at: datetime
    bus: "EventBus"  # back-reference so handlers can publish downstream events


# ── EventBus ───────────────────────────────────────────────────────────────────

class EventBus:
    """In-process pub/sub with SQLite persistence.

    pub path: write DB row (status=pending) → submit handlers to thread pool
    Each handler runs in a separate thread; on completion, updates DB row to ok/error.
    """

    def __init__(self, db: "TradeDB", max_workers: int = 6) -> None:
        self._db = db
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bus")
        self._subs: dict[str, list[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Callable[[Event], None]) -> None:
        """Register a handler for a topic. Handlers run asynchronously."""
        self._subs[topic].append(handler)

    def publish(self, topic: str, payload: dict | None = None) -> Event:
        """Persist event to DB and dispatch to all subscribed handlers asynchronously."""
        payload = payload or {}
        eid = self._db.bus_event_insert(topic, json.dumps(payload))
        event = Event(
            id=eid,
            topic=topic,
            payload=payload,
            created_at=datetime.now(timezone.utc),
            bus=self,
        )
        handlers = self._subs.get(topic, [])
        if not handlers:
            # No handlers: mark as ok immediately (no-op delivery)
            self._db.bus_event_complete(eid, "ok", "<no_handler>")
        else:
            for h in handlers:
                self._pool.submit(self._run_handler, h, event)
        return event

    def _run_handler(self, handler: Callable[[Event], None], event: Event) -> None:
        handler_name = getattr(handler, "__qualname__", repr(handler))
        try:
            handler(event)
            self._db.bus_event_complete(event.id, "ok", handler_name)
        except Exception as exc:
            logger.error(
                "handler %s | topic=%s failed: %s",
                handler_name, event.topic, exc, exc_info=True,
            )
            self._db.bus_event_complete(
                event.id, "error", handler_name, str(exc)[:500]
            )

    def replay_pending(self) -> None:
        """On daemon startup: re-dispatch events stuck in 'pending' state (crash recovery)."""
        pending = self._db.bus_events_pending()
        if pending:
            logger.info("Replaying %d pending bus events", len(pending))
        for row in pending:
            self.publish(row["topic"], json.loads(row["payload"] or "{}"))

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)


# ── Singleton accessor ─────────────────────────────────────────────────────────

_BUS: EventBus | None = None


def get_bus(db: "TradeDB") -> EventBus:
    """Return the global EventBus instance, creating it if needed."""
    global _BUS
    if _BUS is None:
        _BUS = EventBus(db)
    return _BUS
