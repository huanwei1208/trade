"""Engine API — the single public entry point for all trade system operations.

All jobs, CLI commands, and DAG nodes should go through this module.
This is a thin delegation layer; the heavy logic lives in domain modules.

Functions:
    run_node(job_name, data_root, **kwargs) -> str
    run_daily(data_root) -> dict
    update_belief(asof_date, data_root) -> dict
    produce_picks(asof_date, data_root) -> list
    evaluate_daily(asof_date, data_root) -> dict
    ingest_articles(source, data_root, **kwargs) -> dict
    build_silver(asof_date, data_root, **kwargs) -> dict
    build_gold(asof_date, data_root) -> dict
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Node runner ────────────────────────────────────────────────────────────────

def run_node(
    job_name: str,
    data_root: str,
    *,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    dry_run: bool = False,
) -> str:
    """Execute a single pipeline job by name.

    This is the canonical way to trigger any job — from CLI, DAG handlers,
    or tests. Delegates to trade_py.jobs.run_job under the hood.
    """
    if dry_run:
        logger.info("[dry_run] would run job=%s data_root=%s", job_name, data_root)
        return f"dry_run: {job_name}"

    from trade_py.jobs import run_job
    return run_job(job_name, data_root, config=config, date_from=date_from, date_to=date_to)


# ── Daily pipeline ─────────────────────────────────────────────────────────────

def run_daily(data_root: str) -> dict[str, Any]:
    """Run the full daily pipeline in stage order: fetch → compute → train.

    Returns a summary dict with per-job results and any errors.
    """
    from trade_py.jobs import JOB_REGISTRY, run_job

    stages = ["fetch", "compute", "train"]
    results: dict[str, Any] = {"ok": [], "error": [], "skipped": []}

    for stage in stages:
        stage_jobs = [name for name, jd in JOB_REGISTRY.items() if jd.stage == stage]
        for name in stage_jobs:
            try:
                summary = run_job(name, data_root)
                results["ok"].append({"job": name, "summary": summary})
                logger.info("run_daily: %s ok — %s", name, summary)
            except Exception as exc:
                results["error"].append({"job": name, "error": str(exc)})
                logger.error("run_daily: %s failed — %s", name, exc)

    return results


# ── Evidence ingestion ─────────────────────────────────────────────────────────

def ingest_articles(
    source: str,
    data_root: str,
    *,
    fetch_mode: str = "incremental",
    semantic_mode: str = "base",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Fetch raw news articles to the Bronze layer.

    source: "rss" | "gdelt" | "tushare" | etc.
    fetch_mode: "incremental" | "streaming"
    semantic_mode: "base" | "hybrid" | "llm"

    For streaming mode, delegates to GdeltSource.fetch_streaming.
    For incremental/batch mode, delegates to the sentiment CLI pipeline.
    """
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    _sem_mode = str(
        semantic_mode or
        db.get("sentiment.scheduler_semantic_mode", "base") or "base"
    ).strip().lower()
    if _sem_mode not in {"base", "hybrid", "llm"}:
        _sem_mode = "base"

    if fetch_mode == "streaming":
        from trade_py.data.news.gdelt.source import GdeltSource
        src = GdeltSource()
        result = src.fetch_streaming(
            data_root, db,
            progress_cb=lambda msg: logger.info(msg),
        )
        return result if isinstance(result, dict) else {"summary": str(result)}

    # incremental / batch path
    from trade_py.cli._sentiment import main as sentiment_main
    args = [
        "--fetch-mode", fetch_mode,
        "--data-root", data_root,
        "--semantic-mode", _sem_mode,
    ]
    if date_from:
        args.extend(["--date-from", date_from])
    if date_to:
        args.extend(["--date-to", date_to])
    sentiment_main(args)
    return {"summary": f"情绪抓取完成: fetch_mode={fetch_mode} semantic_mode={_sem_mode}"}


# ── Silver layer ───────────────────────────────────────────────────────────────

def build_silver(
    asof_date: str,
    data_root: str,
    *,
    semantic_mode: str = "base",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Bronze → Silver: per-article sentiment scoring (checkpoint layer).

    Currently implemented as a file-count check; full per-article re-processing
    is handled by the ingest_articles incremental path.
    """
    from pathlib import Path as _Path
    silver_root = _Path(data_root) / "sentiment" / "silver"
    files = list(silver_root.rglob("*.parquet")) if silver_root.exists() else []
    return {"summary": f"Silver: {len(files)} parquet files", "file_count": len(files)}


# ── Gold layer ─────────────────────────────────────────────────────────────────

def build_gold(asof_date: str, data_root: str) -> dict[str, Any]:
    """Silver → Gold: per-symbol/date aggregation (checkpoint layer)."""
    from pathlib import Path as _Path
    gold_root = _Path(data_root) / "sentiment" / "gold"
    files = list(gold_root.rglob("*.parquet")) if gold_root.exists() else []
    return {"summary": f"Gold: {len(files)} parquet files", "file_count": len(files)}


# ── Belief update ──────────────────────────────────────────────────────────────

def update_belief(asof_date: str, data_root: str) -> dict[str, Any]:
    """Run the BeliefEngine for a given date.

    Reads Evidence rows, computes attention weights, applies residual
    belief update, and writes BeliefState + AttentionScore + BeliefTransition.
    """
    from trade_py.belief import BeliefEngine
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    engine = BeliefEngine(db)
    try:
        result = engine.run(asof_date=asof_date, data_root=data_root)
    finally:
        db.close()
    return result


# ── Picks / Recommendations ────────────────────────────────────────────────────

def produce_picks(asof_date: str, data_root: str) -> list[dict[str, Any]]:
    """Generate daily Recommendation records from BeliefState.

    Returns list of recommendation dicts sorted by score desc.
    """
    from trade_py.decision import produce_recommendations
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    try:
        recs = produce_recommendations(asof_date=asof_date, data_root=data_root, db=db)
    finally:
        db.close()
    return recs


# ── Daily evaluation ───────────────────────────────────────────────────────────

def evaluate_daily(asof_date: str, data_root: str) -> dict[str, Any]:
    """Run the full daily quality evaluation and write QualityReport."""
    from trade_py.evaluation.service import evaluate_daily as _eval_daily

    outcome = _eval_daily(data_root, eval_date=asof_date, use_cache=False)
    return {
        "summary": outcome.summary,
        "gate_ok": outcome.gate_ok,
        "details": getattr(outcome, "details", {}),
    }
