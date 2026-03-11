"""Scheduler — thin time-gate layer.

Registers schedule entries that publish gate.* events on the EventBus.
Contains NO business logic; all job execution lives in bus/handlers/.

For backward compatibility, also exposes register_jobs() and run_all_once()
used by the legacy 'trade run start' / 'trade run dry-run' commands.
"""
from __future__ import annotations

import logging

import schedule

from trade_py.bus import EventBus, Topic

logger = logging.getLogger(__name__)


def register_schedule(bus: EventBus) -> None:
    """Register time-based gate events. Scheduler fires timing; bus handles dispatch."""
    _p = lambda t: (lambda: bus.publish(t))  # noqa: E731

    schedule.every().day.at("07:00").do(_p(Topic.GATE_MORNING))
    schedule.every().day.at("07:05").do(_p(Topic.GATE_PRE_MARKET))
    schedule.every().day.at("07:35").do(_p(Topic.GATE_SIGNAL_AM))
    schedule.every().day.at("07:45").do(_p(Topic.GATE_REPORT))
    schedule.every().day.at("15:15").do(_p(Topic.GATE_MARKET_CLOSE))
    schedule.every().day.at("22:00").do(_p(Topic.GATE_EVENING))
    schedule.every().day.at("22:30").do(_p(Topic.GATE_EVENT_EXTRACT))
    schedule.every().saturday.at("07:30").do(_p(Topic.GATE_SECTOR_WEEKLY))
    schedule.every().saturday.at("08:00").do(_p(Topic.GATE_FUND_WEEKLY))
    schedule.every().sunday.at("08:00").do(_p(Topic.GATE_MACRO_WEEKLY))

    logger.info("Registered %d schedule gates", len(schedule.jobs))
    bus.replay_pending()  # crash recovery: re-dispatch stuck pending events


# ── Legacy compatibility (used by trade run start / dry-run) ───────────────────

def register_jobs(data_root: str) -> None:
    """Legacy entry point. Creates a TradeDB + EventBus + handlers + schedule."""
    from trade_py.db.trade_db import TradeDB
    from trade_py.bus import get_bus
    from trade_py.bus.handlers import market, sentiment, signals, report as rpt

    db = TradeDB(data_root)
    bus = get_bus(db)
    for mod in [market, sentiment, signals, rpt]:
        mod.register(bus, data_root)
    register_schedule(bus)


def run_all_once(data_root: str) -> None:
    """Legacy dry-run: execute all jobs via the registry directly (no bus)."""
    from trade_py.jobs import JOB_REGISTRY, run_job
    logger.info("=== DRY RUN: executing all jobs immediately ===")
    for name in JOB_REGISTRY:
        try:
            result = run_job(name, data_root)
            logger.info("DRY RUN job %s: %s", name, result)
        except Exception as exc:
            logger.error("DRY RUN job %s failed: %s", name, exc)
    logger.info("=== DRY RUN complete ===")
