#!/usr/bin/env python3
from __future__ import annotations

"""Daily trading scheduler.

Runs the full daily data pipeline at scheduled times (CST, Beijing time).
Does not require cron — uses the `schedule` library with a blocking loop.

Daily schedule:
  02:00  cross_asset_fetcher  → gold/BTC/FX (overnight data)
  09:05  kline + fund_flow    → yesterday's A-share data (T+1)
  09:10  window_scorer        → watchlist window quality scores
  09:15  morning_brief        → generate daily brief markdown
  15:15  fund_flow (post)     → end-of-day fund flow update

Usage:
    uv run python python/scripts/scheduler.py [--data-root DATA]
    uv run python python/scripts/scheduler.py --dry-run   # run all jobs once immediately
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import schedule
from config_context import default_data_root

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("scheduler")

# Beijing timezone (UTC+8)
_CST = timezone(timedelta(hours=8))

_DATA_ROOT = str(default_data_root())  # overridden by --data-root argument


def _job(name: str):
    """Decorator that wraps a job function with logging and error handling."""
    def decorator(fn):
        def wrapper():
            now = datetime.now(_CST).strftime("%H:%M:%S")
            logger.info("[%s] Starting job: %s", now, name)
            try:
                fn()
                logger.info("[%s] Finished job: %s", now, name)
            except Exception as e:
                logger.error("[%s] Job FAILED: %s — %s", now, name, e, exc_info=True)
        wrapper.__name__ = name
        return wrapper
    return decorator


@_job("cross_asset_fetch")
def job_cross_asset():
    from trade_py.data.cross_asset_fetcher import fetch_all
    fetch_all(_DATA_ROOT)


@_job("kline_update")
def job_kline():
    from trade_py.data.kline_fetcher import KlineFetcher
    from trade_py.db.instruments_db import InstrumentsDB

    db = InstrumentsDB(_DATA_ROOT)
    fetcher = KlineFetcher(_DATA_ROOT)
    symbols = db.get_all_symbols()
    logger.info("Updating kline for %d symbols (incremental)", len(symbols))
    for sym in symbols:
        fetcher.update(sym)


@_job("fund_flow_update")
def job_fund_flow():
    from trade_py.data.fund_flow_fetcher import FundFlowFetcher
    from trade_py.db.instruments_db import InstrumentsDB

    db = InstrumentsDB(_DATA_ROOT)
    fetcher = FundFlowFetcher(_DATA_ROOT)
    # Use watchlist symbols for fund flow (full universe is too slow)
    from trade_py.db.settings_db import SettingsDB
    sdb = SettingsDB(_DATA_ROOT)
    symbols = sdb.watchlist_get() or db.get_all_symbols()[:50]
    logger.info("Updating fund flow for %d symbols", len(symbols))
    fetcher.fetch_batch(symbols)


@_job("window_score")
def job_window_score():
    from trade_py.signals.window_scorer import score_watchlist
    scores = score_watchlist(_DATA_ROOT)
    logger.info("Window scores computed for %d symbols", len(scores))


@_job("morning_brief")
def job_morning_brief():
    from trade_py.journal.morning_brief import generate
    path = generate(_DATA_ROOT)
    logger.info("Morning brief: %s", path)


def register_jobs() -> None:
    """Register all daily jobs with their scheduled times (CST)."""
    schedule.every().day.at("02:00").do(job_cross_asset)
    schedule.every().day.at("09:05").do(job_kline)
    schedule.every().day.at("09:05").do(job_fund_flow)
    schedule.every().day.at("09:10").do(job_window_score)
    schedule.every().day.at("09:15").do(job_morning_brief)
    schedule.every().day.at("15:15").do(job_fund_flow)   # post-market fund flow

    logger.info("Registered %d scheduled jobs", len(schedule.jobs))
    for j in schedule.jobs:
        logger.info("  %s", j)


def run_all_once() -> None:
    """Run all jobs immediately (dry-run / manual trigger)."""
    logger.info("=== DRY RUN: executing all jobs immediately ===")
    for fn in [job_cross_asset, job_kline, job_fund_flow, job_window_score, job_morning_brief]:
        fn()
    logger.info("=== DRY RUN complete ===")


def main() -> None:
    global _DATA_ROOT
    parser = argparse.ArgumentParser(description="Trade daily scheduler")
    parser.add_argument("--data-root", default=str(default_data_root()), help="Data root directory")
    parser.add_argument("--dry-run", action="store_true", help="Run all jobs once immediately and exit")
    args = parser.parse_args()
    _DATA_ROOT = args.data_root

    if args.dry_run:
        run_all_once()
        return

    register_jobs()
    logger.info("Scheduler running (CST timezone). Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)  # check every 30 seconds
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    main()
