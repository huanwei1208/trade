"""Data-source evaluation: health metrics and IC analysis per source."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.analysis.sentiment_ic import compute_ic
from trade_py.db.trade_db import TradeDB
from trade_py.infra.settings import default_data_root
from trade_py.evaluation.utils import (
    EvalOutcome,
    MIN_SOURCE_IC_LOOKBACK_DAYS,
    _cached_source_outcome,
    _ingest_key,
    _parse_iso,
    _pipeline_db_path,
    _read_parquet_frame,
    _resolve_window,
    _safe_float,
    _safe_int,
    resolve_eval_date,
)

logger = logging.getLogger(__name__)


def _source_health_rows(data_root: str, eval_date: str, start_date: str,
                        end_date: str, lookback_days: int) -> list[dict[str, Any]]:
    bronze_glob = str(Path(data_root) / "sentiment" / "bronze" / "**" / "*.parquet")
    bronze = _read_parquet_frame(
        bronze_glob,
        [
            "source",
            "feed_name",
            "feed_catalog",
            "provider_kind",
            "published_at",
            "content_hash",
        ],
    )
    if bronze.empty:
        return []

    bronze["article_date"] = bronze["published_at"].astype(str).str.slice(0, 10)
    bronze = bronze[
        (bronze["article_date"] >= start_date) &
        (bronze["article_date"] <= end_date)
    ].copy()
    if bronze.empty:
        return []

    bronze["source_name"] = bronze.get("feed_name", bronze["source"]).fillna(bronze["source"]).astype(str)
    bronze["source_family"] = bronze.get("feed_catalog", bronze["source"]).fillna(bronze["source"]).astype(str)
    bronze["provider_kind"] = bronze.get("provider_kind", pd.Series(dtype=object)).fillna("unknown").astype(str)

    pipeline_runs: dict[str, dict[str, Any]] = {}
    pipeline_path = _pipeline_db_path(data_root)
    if pipeline_path.exists():
        try:
            import sqlite3
            if pipeline_path.suffix == ".duckdb":
                import duckdb

                con = duckdb.connect(str(pipeline_path), read_only=True)
                runs = con.execute(
                    """
                    SELECT source_id,
                           COUNT(*) AS ingest_runs,
                           SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS ingest_errors,
                           SUM(records_fetched) AS records_fetched,
                           SUM(records_new) AS records_new
                    FROM ingest_runs
                    WHERE CAST(date_range_end AS VARCHAR) >= ? AND CAST(date_range_start AS VARCHAR) <= ?
                    GROUP BY source_id
                    """,
                    [start_date, end_date],
                ).fetchall()
                con.close()
                for source_id, ingest_runs, ingest_errors, records_fetched, records_new in runs:
                    pipeline_runs[str(source_id)] = {
                        "ingest_runs": _safe_int(ingest_runs),
                        "ingest_errors": _safe_int(ingest_errors),
                        "records_fetched": _safe_int(records_fetched),
                        "records_new": _safe_int(records_new),
                    }
            else:
                con = sqlite3.connect(str(pipeline_path), timeout=30)
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    """
                    SELECT source_id,
                           COUNT(*) AS ingest_runs,
                           SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS ingest_errors,
                           SUM(records_fetched) AS records_fetched,
                           SUM(records_new) AS records_new
                    FROM ingest_runs
                    WHERE date_range_end >= ? AND date_range_start <= ?
                    GROUP BY source_id
                    """,
                    (start_date, end_date),
                ).fetchall()
                con.close()
                for row in rows:
                    pipeline_runs[str(row["source_id"])] = {
                        "ingest_runs": _safe_int(row["ingest_runs"]),
                        "ingest_errors": _safe_int(row["ingest_errors"]),
                        "records_fetched": _safe_int(row["records_fetched"]),
                        "records_new": _safe_int(row["records_new"]),
                    }
        except Exception as exc:
            logger.debug("failed to read pipeline db: %s", exc)

    rows: list[dict[str, Any]] = []
    for source_name, grp in bronze.groupby("source_name"):
        source_family = str(grp["source_family"].iloc[0])
        provider_kind = str(grp["provider_kind"].iloc[0])
        total_rows = int(len(grp))
        unique_articles = int(grp["content_hash"].astype(str).nunique())
        bronze_days = int(grp["article_date"].nunique())
        duplicate_rate = max(0.0, 1.0 - (unique_articles / total_rows)) if total_rows else 0.0
        empty_day_rate = max(0.0, 1.0 - (bronze_days / max(1, lookback_days)))
        ingest = pipeline_runs.get(_ingest_key(source_name, source_family), {})
        ingest_runs = _safe_int(ingest.get("ingest_runs"))
        ingest_errors = _safe_int(ingest.get("ingest_errors"))
        ingest_error_rate = (ingest_errors / ingest_runs) if ingest_runs else 0.0
        healthy = int(bronze_days > 0 and ingest_error_rate < 0.5)
        rows.append({
            "eval_date": eval_date,
            "source_name": source_name,
            "source_family": source_family,
            "provider_kind": provider_kind,
            "bronze_days": bronze_days,
            "article_rows": total_rows,
            "unique_articles": unique_articles,
            "duplicate_rate": round(duplicate_rate, 4),
            "empty_day_rate": round(empty_day_rate, 4),
            "ingest_runs": ingest_runs,
            "ingest_error_rate": round(ingest_error_rate, 4),
            "records_fetched": _safe_int(ingest.get("records_fetched"), total_rows),
            "records_new": _safe_int(ingest.get("records_new"), unique_articles),
            "healthy": healthy,
            "details_json": {
                "lookback_days": lookback_days,
                "start_date": start_date,
                "end_date": end_date,
            },
        })
    return rows


def evaluate_sources(data_root: str = str(default_data_root()),
                     eval_date: str | None = None,
                     lookback_days: int = 30,
                     persist: bool = True,
                     use_cache: bool = True) -> EvalOutcome:
    target_date = resolve_eval_date(data_root, eval_date)
    db = TradeDB(data_root)
    if use_cache:
        cached = _cached_source_outcome(db, target_date)
        if cached is not None:
            return cached
    start_date, end_date = _resolve_window(target_date, lookback_days)

    health_rows = _source_health_rows(data_root, target_date, start_date, end_date, lookback_days)

    silver_glob = str(Path(data_root) / "sentiment" / "silver" / "**" / "*.parquet")
    silver = _read_parquet_frame(
        silver_glob,
        ["date", "source", "event_type", "event_magnitude", "content_hash"],
    )
    if not silver.empty:
        silver["date"] = silver["date"].astype(str).str.slice(0, 10)
        silver = silver[(silver["date"] >= start_date) & (silver["date"] <= end_date)].copy()
        silver["source_name"] = silver["source"].fillna("unknown").astype(str)
        silver["event_magnitude"] = pd.to_numeric(silver["event_magnitude"], errors="coerce").fillna(0.0)
    ic_payload: dict[str, Any]
    ic_by_source: dict[str, Any]
    if lookback_days >= MIN_SOURCE_IC_LOOKBACK_DAYS:
        ic_payload = compute_ic(data_root=data_root, lookback=lookback_days, forward_days=5, by_source=True)
        ic_by_source = ic_payload.get("by_source", {}) if isinstance(ic_payload, dict) else {}
    else:
        ic_payload = {
            "skipped": True,
            "reason": f"lookback_days<{MIN_SOURCE_IC_LOOKBACK_DAYS}",
            "lookback_days": lookback_days,
        }
        ic_by_source = {}
    matured_cutoff = (_parse_iso(target_date) - __import__("datetime").timedelta(days=7)).isoformat()

    health_by_name = {row["source_name"]: row for row in health_rows}
    eval_rows: list[dict[str, Any]] = []
    for source_name, health in health_by_name.items():
        source_silver = silver[silver["source_name"] == source_name] if not silver.empty else pd.DataFrame()
        silver_rows = int(len(source_silver))
        event_rows = 0
        labeled_rows = 0
        if not source_silver.empty:
            event_rows = int(source_silver[
                (source_silver["event_type"].fillna("").astype(str) != "") &
                (source_silver["event_type"].fillna("").astype(str) != "other") &
                (source_silver["event_magnitude"] >= _safe_float(db.get("event.min_magnitude", 0.4), 0.4))
            ]["content_hash"].astype(str).nunique())
            labeled_rows = int(source_silver[source_silver["date"] <= matured_cutoff]["content_hash"].astype(str).nunique())
        event_yield = (event_rows / silver_rows * 100.0) if silver_rows else 0.0
        eval_rows.append({
            "eval_date": target_date,
            "source_name": source_name,
            "source_family": health["source_family"],
            "provider_kind": health["provider_kind"],
            "silver_rows": silver_rows,
            "event_rows": event_rows,
            "event_yield_per_100": round(event_yield, 4),
            "labeled_rows": labeled_rows,
            "rank_ic_5d": ic_by_source.get(source_name),
            "details_json": {
                "ic_lookback_days": lookback_days,
                "ic_forward_days": 5,
            },
        })

    if persist:
        db.source_health_upsert_batch(health_rows)
        db.source_eval_upsert_batch(eval_rows)

    healthy_count = sum(1 for row in health_rows if row["healthy"])
    status = "ok"
    if not health_rows:
        status = "blocked_by_dependency"
    elif any(row["silver_rows"] == 0 for row in eval_rows):
        status = "partial"
    summary = f"source eval {target_date}: healthy={healthy_count}/{len(health_rows)}, sources={len(eval_rows)}"
    payload = {
        "eval_date": target_date,
        "start_date": start_date,
        "end_date": end_date,
        "health_rows": health_rows,
        "eval_rows": eval_rows,
        "ic_payload": ic_payload,
    }
    return EvalOutcome(status=status, summary=summary, payload=payload)
