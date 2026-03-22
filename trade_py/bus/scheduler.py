"""Scheduler — thin time-gate layer.

Registers schedule entries that publish gate.* events on the EventBus.
Contains NO business logic; all job execution is driven by pipeline_dag
via bootstrap_from_dag().
"""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import TYPE_CHECKING, Any

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

_SCHEDULE_BLUEPRINT: list[dict[str, Any]] = [
    {
        "id": "gate_morning",
        "topic": Topic.GATE_MORNING,
        "label": "Morning data refresh",
        "time": "07:00",
        "cadence": "daily",
        "trading_day_only": True,
        "market_hours_only": False,
        "description": "Kick off the pre-open source refresh for the current trading day.",
    },
    {
        "id": "gate_pre_market",
        "topic": Topic.GATE_PRE_MARKET,
        "label": "Pre-market compute",
        "time": "07:05",
        "cadence": "daily",
        "trading_day_only": True,
        "market_hours_only": False,
        "description": "Run the pre-market feature and score preparation chain.",
    },
    {
        "id": "gate_signal_am",
        "topic": Topic.GATE_SIGNAL_AM,
        "label": "Morning recommendation refresh",
        "time": "07:35",
        "cadence": "daily",
        "trading_day_only": True,
        "market_hours_only": False,
        "description": "Refresh the morning recommendation snapshot before the session.",
    },
    {
        "id": "gate_intraday",
        "topic": Topic.GATE_INTRADAY,
        "label": "Intraday compute",
        "time": "every 1 minute",
        "cadence": "minute",
        "trading_day_only": True,
        "market_hours_only": True,
        "description": "Update intraday quotes and derived intraday calculations during the trading session.",
    },
    {
        "id": "agenda_due",
        "topic": Topic.AGENDA_DUE,
        "label": "Due agenda dispatch",
        "time": "every 1 minute",
        "cadence": "minute",
        "trading_day_only": False,
        "market_hours_only": False,
        "description": "Dispatch due agenda items and planned-event realization jobs.",
    },
    {
        "id": "gate_market_close",
        "topic": Topic.GATE_MARKET_CLOSE,
        "label": "Market close snapshot",
        "time": "15:15",
        "cadence": "daily",
        "trading_day_only": True,
        "market_hours_only": False,
        "description": "Capture the close-of-day state after the regular trading session.",
    },
    {
        "id": "gate_evening",
        "topic": Topic.GATE_EVENING,
        "label": "Evening source refresh",
        "time": "22:00",
        "cadence": "daily",
        "trading_day_only": False,
        "market_hours_only": False,
        "description": "Run the evening refresh for daily source data and downstream refresh gates.",
    },
    {
        "id": "gate_event_extract",
        "topic": Topic.GATE_EVENT_EXTRACT,
        "label": "Event extraction",
        "time": "22:30",
        "cadence": "daily",
        "trading_day_only": False,
        "market_hours_only": False,
        "description": "Extract and normalize daily events after the evening source refresh.",
    },
    {
        "id": "gate_evaluate_daily",
        "topic": Topic.GATE_EVALUATE_DAILY,
        "label": "Daily validation and audit",
        "time": "22:45",
        "cadence": "daily",
        "trading_day_only": False,
        "market_hours_only": False,
        "description": "Refresh daily evaluation, quality gate, and audit artifacts.",
    },
    {
        "id": "gate_sector_weekly",
        "topic": Topic.GATE_SECTOR_WEEKLY,
        "label": "Weekly sector refresh",
        "time": "Saturday 07:30",
        "cadence": "weekly",
        "trading_day_only": False,
        "market_hours_only": False,
        "description": "Refresh weekly sector structure and board-level signals.",
    },
    {
        "id": "gate_fund_weekly",
        "topic": Topic.GATE_FUND_WEEKLY,
        "label": "Weekly fundamentals refresh",
        "time": "Saturday 08:00",
        "cadence": "weekly",
        "trading_day_only": False,
        "market_hours_only": False,
        "description": "Refresh weekly fundamental data dependencies.",
    },
    {
        "id": "gate_macro_weekly",
        "topic": Topic.GATE_MACRO_WEEKLY,
        "label": "Weekly macro refresh",
        "time": "Sunday 08:00",
        "cadence": "weekly",
        "trading_day_only": False,
        "market_hours_only": False,
        "description": "Refresh weekly macro and sentiment context.",
    },
    {
        "id": "gate_model_weekly",
        "topic": Topic.GATE_MODEL_WEEKLY,
        "label": "Weekly model refresh",
        "time": "Sunday 09:00",
        "cadence": "weekly",
        "trading_day_only": False,
        "market_hours_only": False,
        "description": "Run weekly model refresh and maintenance tasks.",
    },
]


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


def describe_schedule(db: "TradeDB", now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now()
    items: list[dict[str, Any]] = []
    is_trading_day = _is_trading_day(db, now)
    market_open = _market_session_open(db, now)
    for item in _SCHEDULE_BLUEPRINT:
        current = dict(item)
        current["currently_eligible"] = (
            (not current["trading_day_only"] or is_trading_day)
            and (not current["market_hours_only"] or market_open)
        )
        current["state_hint"] = (
            "waiting_market_session"
            if current["market_hours_only"] and not market_open
            else "waiting_trading_day"
            if current["trading_day_only"] and not is_trading_day
            else "eligible"
        )
        items.append(current)
    return items


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
