"""Scheduler — thin time-gate layer.

Registers schedule entries that publish gate.* events on the EventBus.
Contains NO business logic; all job execution is driven by pipeline_dag
via bootstrap_from_dag().
"""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import TYPE_CHECKING

import schedule

from trade_py.bus import EventBus, Topic

if TYPE_CHECKING:
    from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

_AGENDA_JOB_LIMITS = {
    "realtime_quote_sync": 1,
    "realtime_compute": 1,
    "planned_event_realize": 6,
    "event_pipeline": 2,
}


def _is_trading_day(db: "TradeDB", now: datetime | None = None, exchange: str = "SSE") -> bool:
    now = now or datetime.now()
    is_open = db.trading_calendar_is_open(now.date(), exchange=exchange)
    if is_open is None:
        return now.weekday() < 5
    return bool(is_open)


def _market_session_open(db: "TradeDB", now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if not _is_trading_day(db, now):
        return False
    current = now.time()
    row = db.trading_calendar_get(now.date(), exchange="SSE") or {}
    am_open = time.fromisoformat(str(row.get("session_am_open") or "09:30:00"))
    am_close = time.fromisoformat(str(row.get("session_am_close") or "11:30:00"))
    pm_open = time.fromisoformat(str(row.get("session_pm_open") or "13:00:00"))
    pm_close = time.fromisoformat(str(row.get("session_pm_close") or "15:00:00"))
    in_am = max(am_open, time(9, 31)) <= current <= am_close
    in_pm = max(pm_open, time(13, 1)) <= current <= pm_close
    return in_am or in_pm


def drain_due_agenda(bus: EventBus, db: "TradeDB", *, limit: int = 20) -> int:
    expired = db.agenda_queue_expire_stale(grace_minutes=120)
    if expired:
        logger.info("Expired %d stale agenda items before dispatch", expired)
    rows = db.agenda_queue_claim_due(limit=limit, job_limits=_AGENDA_JOB_LIMITS)
    if not rows:
        return 0
    logger.info("Dispatching %d due agenda items", len(rows))
    for row in rows:
        bus.publish(Topic.AGENDA_DUE, dict(row))
    return len(rows)


def register_schedule(bus: EventBus, db: "TradeDB") -> None:
    """Register time-based gate events. Scheduler fires timing; bus handles dispatch."""
    _p = lambda t: (lambda: bus.publish(t))  # noqa: E731
    _guarded = lambda t: (lambda: bus.publish(t) if _is_trading_day(db) else logger.debug("Skipping %s: non-trading day", t))  # noqa: E731

    def _publish_intraday() -> None:
        if _market_session_open(db):
            bus.publish(Topic.GATE_INTRADAY)

    def _publish_due_agenda() -> None:
        drain_due_agenda(bus, db, limit=20)

    schedule.every().day.at("07:00").do(_guarded(Topic.GATE_MORNING))
    schedule.every(1).minutes.do(_publish_intraday)
    schedule.every(1).minutes.do(_publish_due_agenda)
    schedule.every().day.at("07:05").do(_guarded(Topic.GATE_PRE_MARKET))
    schedule.every().day.at("07:35").do(_guarded(Topic.GATE_SIGNAL_AM))
    schedule.every().day.at("07:45").do(_guarded(Topic.GATE_REPORT))
    schedule.every().day.at("15:15").do(_guarded(Topic.GATE_MARKET_CLOSE))
    schedule.every().day.at("22:00").do(_p(Topic.GATE_EVENING))
    schedule.every().day.at("22:30").do(_p(Topic.GATE_EVENT_EXTRACT))
    schedule.every().day.at("22:45").do(_p(Topic.GATE_EVALUATE_DAILY))
    schedule.every().saturday.at("07:30").do(_p(Topic.GATE_SECTOR_WEEKLY))
    schedule.every().saturday.at("08:00").do(_p(Topic.GATE_FUND_WEEKLY))
    schedule.every().sunday.at("08:00").do(_p(Topic.GATE_MACRO_WEEKLY))
    schedule.every().sunday.at("09:00").do(_p(Topic.GATE_MODEL_WEEKLY))

    logger.info("Registered %d schedule gates", len(schedule.jobs))
    bus.replay_pending()  # crash recovery: re-dispatch stuck pending events
