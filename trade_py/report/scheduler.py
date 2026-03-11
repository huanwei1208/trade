from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from pathlib import Path

import schedule

from trade_py.config import default_data_root
from trade_py.jobs import JOB_REGISTRY, run_job
from trade_py.report.notify import dispatch

logger = logging.getLogger(__name__)
_CST = timezone(timedelta(hours=8))
_pool = ThreadPoolExecutor(max_workers=6)


def _wrap_job(name: str, data_root: str):
    """Wrap a job with tracking/notification; returns a zero-arg callable."""
    def _inner():
        now = datetime.now(_CST).strftime("%H:%M:%S")
        logger.info("[%s] Starting job: %s", now, name)
        dispatch("start", name, f"开始: {name}", data_root)

        run_id: int | None = None
        try:
            from trade_py.db.settings_db import SettingsDB
            run_id = SettingsDB(data_root).job_run_start(name)
        except Exception:
            pass

        try:
            result = run_job(name, data_root)
            msg = result or f"完成: {name}"
            logger.info("[%s] Finished job: %s — %s", now, name, msg)
            dispatch("success", name, msg, data_root)
            if run_id is not None:
                try:
                    from trade_py.db.settings_db import SettingsDB
                    db = SettingsDB(data_root)
                    db.job_run_finish(run_id, "success", msg)
                    db.job_schedule_update_last(name, "success", datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"))
                except Exception:
                    pass
        except Exception as exc:
            err_msg = f"失败: {name}\n{exc}"
            logger.error("[%s] Job FAILED: %s - %s", now, name, exc, exc_info=True)
            dispatch("failure", name, err_msg, data_root)
            if run_id is not None:
                try:
                    from trade_py.db.settings_db import SettingsDB
                    db = SettingsDB(data_root)
                    db.job_run_finish(run_id, "failure", err_msg[:500])
                    db.job_schedule_update_last(name, "failure", datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"))
                except Exception:
                    pass
            raise

    _inner.__name__ = name
    return _inner


def _async(fn):
    """Submit fn to thread pool so same-slot jobs run concurrently."""
    def _submit():
        _pool.submit(fn)
    _submit.__name__ = getattr(fn, "__name__", "?")
    return _submit


def register_jobs(data_root: str) -> None:
    wrapped = {name: _wrap_job(name, data_root) for name in JOB_REGISTRY}

    # Overnight
    schedule.every().day.at("22:00").do(_async(wrapped["sentiment_pipeline"]))
    schedule.every().day.at("22:30").do(_async(wrapped["event_pipeline"]))

    # Pre-market (07:00 slot: kline + cross_asset run concurrently)
    schedule.every().day.at("07:00").do(_async(wrapped["cross_asset_fetch"]))
    schedule.every().day.at("07:00").do(_async(wrapped["kline_update"]))
    schedule.every().day.at("07:05").do(_async(wrapped["market_index"]))
    schedule.every().day.at("07:10").do(_async(wrapped["model_inference"]))
    schedule.every().day.at("07:30").do(_async(wrapped["fund_flow_update"]))
    schedule.every().day.at("07:35").do(_async(wrapped["window_score"]))
    schedule.every().day.at("07:45").do(_async(wrapped["morning_brief"]))

    # Post-market
    schedule.every().day.at("15:15").do(_async(wrapped["fund_flow_update"]))
    schedule.every().day.at("15:20").do(_async(wrapped["northbound"]))
    schedule.every().day.at("15:30").do(_async(wrapped["window_score"]))
    schedule.every().day.at("15:35").do(_async(wrapped["event_backfill"]))

    # Weekly
    schedule.every().saturday.at("07:30").do(_async(wrapped["sector_refresh"]))
    schedule.every().saturday.at("08:00").do(_async(wrapped["fundamental"]))
    schedule.every().sunday.at("08:00").do(_async(wrapped["macro"]))

    logger.info("Registered %d scheduled jobs", len(schedule.jobs))

    _PLAN = [
        ("sentiment_pipeline",  "每天 22:00"),
        ("cross_asset_fetch",   "每天 07:00"),
        ("kline_update",        "每天 07:00"),
        ("market_index",        "每天 07:05"),
        ("fund_flow_update",    "每天 07:30 / 15:15"),
        ("northbound",          "每天 15:20"),
        ("window_score",        "每天 07:35 / 15:30"),
        ("morning_brief",       "每天 07:45"),
        ("fundamental",         "每周六 08:00"),
        ("macro",               "每周日 08:00"),
        ("event_pipeline",      "每天 22:30"),
        ("event_backfill",      "每天 15:35"),
        ("sector_refresh",      "每周六 07:30"),
        ("model_inference",     "每天 07:10"),
    ]
    try:
        from trade_py.db.settings_db import SettingsDB
        db = SettingsDB(data_root)
        for job_name, cron_desc in _PLAN:
            next_run = None
            for j in schedule.jobs:
                if getattr(j.job_func, "__name__", None) == job_name and j.next_run:
                    next_run = j.next_run.strftime("%Y-%m-%d %H:%M:%S")
                    break
            db.job_schedule_upsert(job_name, cron_desc, next_run)
    except Exception as exc:
        logger.warning("Failed to persist schedule plan: %s", exc)


def run_all_once(data_root: str) -> None:
    logger.info("=== DRY RUN: executing all jobs immediately ===")
    for name in JOB_REGISTRY:
        fn = _wrap_job(name, data_root)
        try:
            fn()
        except Exception as exc:
            logger.error("DRY RUN job %s failed: %s", name, exc)
    logger.info("=== DRY RUN complete ===")
