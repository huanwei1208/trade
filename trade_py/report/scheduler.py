from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

import schedule

from trade_py.config import default_data_root

logger = logging.getLogger(__name__)
_CST = timezone(timedelta(hours=8))


def _job(name: str):
    def decorator(fn):
        def wrapper():
            now = datetime.now(_CST).strftime("%H:%M:%S")
            logger.info("[%s] Starting job: %s", now, name)
            try:
                fn()
                logger.info("[%s] Finished job: %s", now, name)
            except Exception as exc:
                logger.error("[%s] Job FAILED: %s - %s", now, name, exc, exc_info=True)
        wrapper.__name__ = name
        return wrapper
    return decorator


def _build_jobs(data_root: str):
    @_job("cross_asset_fetch")
    def job_cross_asset() -> None:
        from trade_py.data.market.cross_asset import fetch_all
        fetch_all(data_root)

    @_job("kline_update")
    def job_kline() -> None:
        from trade_py.data.market.kline import KlineFetcher
        from trade_py.db.instruments_db import InstrumentsDB

        db = InstrumentsDB(data_root)
        fetcher = KlineFetcher(data_root)
        symbols = db.get_all_symbols()
        logger.info("Updating kline for %d symbols (incremental)", len(symbols))
        for sym in symbols:
            fetcher.update(sym)

    @_job("fund_flow_update")
    def job_fund_flow() -> None:
        from trade_py.data.market.fund_flow import FundFlowFetcher
        from trade_py.db.instruments_db import InstrumentsDB
        from trade_py.db.settings_db import SettingsDB

        db = InstrumentsDB(data_root)
        fetcher = FundFlowFetcher(data_root)
        watchlist = SettingsDB(data_root).watchlist_get()
        symbols = watchlist or db.get_all_symbols()[:50]
        logger.info("Updating fund flow for %d symbols", len(symbols))
        fetcher.fetch_batch(symbols)

    @_job("window_score")
    def job_window_score() -> None:
        from trade_py.signals.window_scorer import score_watchlist
        scores = score_watchlist(data_root)
        logger.info("Window scores computed for %d symbols", len(scores))

    @_job("morning_brief")
    def job_morning_brief() -> None:
        from trade_py.report.morning_brief import generate
        path = generate(data_root)
        logger.info("Morning brief: %s", path)

    return [job_cross_asset, job_kline, job_fund_flow, job_window_score, job_morning_brief]


def register_jobs(data_root: str) -> None:
    job_cross_asset, job_kline, job_fund_flow, job_window_score, job_morning_brief = _build_jobs(data_root)
    schedule.every().day.at("02:00").do(job_cross_asset)
    schedule.every().day.at("09:05").do(job_kline)
    schedule.every().day.at("09:05").do(job_fund_flow)
    schedule.every().day.at("09:10").do(job_window_score)
    schedule.every().day.at("09:15").do(job_morning_brief)
    schedule.every().day.at("15:15").do(job_fund_flow)

    logger.info("Registered %d scheduled jobs", len(schedule.jobs))


def run_all_once(data_root: str) -> None:
    logger.info("=== DRY RUN: executing all jobs immediately ===")
    for fn in _build_jobs(data_root):
        fn()
    logger.info("=== DRY RUN complete ===")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trade daily scheduler")
    parser.add_argument("--data-root", default=str(default_data_root()), help="Data root directory")
    parser.add_argument("--dry-run", action="store_true", help="Run all jobs once immediately and exit")
    args = parser.parse_args(argv)

    if args.dry_run:
        run_all_once(args.data_root)
        return 0

    register_jobs(args.data_root)
    logger.info("Scheduler running (CST timezone). Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
        return 0
