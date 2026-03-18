from __future__ import annotations

import json
import hashlib
import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trade_py.analysis.propagation_runtime import FEATURE_COLS
from trade_py.analysis.sentiment_ic import compute_ic
from trade_py.infra.settings import default_data_root
from trade_py.db.pipeline_db import PipelineDb
from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

RECENT_OPERATIONAL_DAYS = 3
MATURED_RESEARCH_DAYS = 120
LABEL_SETTLE_DAYS = 28
MIN_SOURCE_IC_LOOKBACK_DAYS = 10


@dataclass
class EvalOutcome:
    status: str
    summary: str
    payload: dict[str, Any]
    exit_code: int = 0


def _cached_source_outcome(db: TradeDB, eval_date: str) -> EvalOutcome | None:
    health_rows = db.source_health_list(eval_date)
    eval_rows = db.source_eval_list(eval_date)
    if not health_rows or not eval_rows:
        return None
    healthy_count = sum(1 for row in health_rows if row.get("healthy"))
    status = "partial" if any(int(row.get("silver_rows") or 0) == 0 for row in eval_rows) else "ok"
    payload = {
        "eval_date": eval_date,
        "start_date": None,
        "end_date": eval_date,
        "health_rows": health_rows,
        "eval_rows": eval_rows,
        "ic_payload": {"cached": True},
    }
    summary = f"source eval {eval_date}: healthy={healthy_count}/{len(health_rows)}, sources={len(eval_rows)} [cached]"
    return EvalOutcome(status=status, summary=summary, payload=payload)


def _cached_event_outcome(db: TradeDB, eval_date: str,
                          start_date: str | None = None,
                          end_date: str | None = None) -> EvalOutcome | None:
    row = db.event_eval_get(eval_date, start_date, end_date) if start_date and end_date else db.event_eval_latest(eval_date)
    if not row:
        return None
    details = row.get("details_json") or {}
    payload = {
        "eval_date": row.get("eval_date", eval_date),
        "start_date": row.get("start_date"),
        "end_date": row.get("end_date"),
        "event_count": _safe_int(row.get("event_count")),
        "effective_event_rate": _safe_float(row.get("effective_event_rate")),
        "sw_unknown_ratio": _safe_float(row.get("sw_unknown_ratio")),
        "propagations_per_event": _safe_float(row.get("propagations_per_event")),
        "labeled_propagation_ratio": _safe_float(row.get("labeled_propagation_ratio")),
        "avg_actual_return_5d": row.get("avg_actual_return_5d"),
        "avg_actual_return_20d": row.get("avg_actual_return_20d"),
        "event_type_distribution": details.get("event_type_distribution", {}),
    }
    summary = (
        f"event eval {payload['start_date']}->{payload['end_date']}: events={payload['event_count']}, "
        f"effective={payload['effective_event_rate']:.2%}, labeled={payload['labeled_propagation_ratio']:.2%} [cached]"
    )
    return EvalOutcome(status=str(row.get("status") or "ok"), summary=summary, payload=payload)


def _cached_model_outcome(db: TradeDB, eval_date: str) -> EvalOutcome | None:
    rows = db.model_eval_list(eval_date=eval_date)
    if not rows:
        return None
    model_status: dict[str, str] = {}
    for row in rows:
        model_name = str(row.get("model_name") or "")
        status = str(row.get("status") or "partial")
        prev = model_status.get(model_name)
        if prev == "ok":
            continue
        if status == "ok":
            model_status[model_name] = "ok"
        elif prev is None:
            model_status[model_name] = status
    status = "ok" if all(state == "ok" for state in model_status.values()) else "partial"
    summary = f"model eval {eval_date}: models={len(rows)}, status={status} [cached]"
    return EvalOutcome(status=status, summary=summary, payload={"eval_date": eval_date, "rows": rows})


def _cached_gate_outcome(db: TradeDB, eval_date: str) -> EvalOutcome | None:
    row = db.quality_gate_get(eval_date)
    if not row:
        return None
    payload = {
        "eval_date": row.get("eval_date", eval_date),
        "status": row.get("status", "blocked_by_dependency"),
        "reasons": row.get("reasons_json") or [],
        "metrics": row.get("metrics_json") or {},
    }
    return EvalOutcome(
        status=str(payload["status"]),
        summary=(
            f"quality gate {eval_date}: overall={payload['status']} "
            f"op={payload['metrics'].get('operational_status', '—')} "
            f"research={payload['metrics'].get('research_status', '—')} [cached]"
        ),
        payload=payload,
    )


def resolve_eval_date(data_root: str, explicit_date: str | None = None) -> str:
    if explicit_date:
        return explicit_date
    db = TradeDB(data_root)
    row = db._conn.execute(
        """
        SELECT COALESCE(
            (SELECT MAX(date) FROM signals),
            (SELECT MAX(event_date) FROM market_events),
            date('now', 'localtime')
        )
        """
    ).fetchone()
    return str(row[0]) if row and row[0] else date.today().isoformat()


def _parse_iso(d: str) -> date:
    return date.fromisoformat(str(d)[:10])


def _resolve_window(eval_date: str, lookback_days: int) -> tuple[str, str]:
    end = _parse_iso(eval_date)
    start = end - timedelta(days=max(0, lookback_days - 1))
    return start.isoformat(), end.isoformat()


def _resolve_matured_window(eval_date: str,
                            lookback_days: int = MATURED_RESEARCH_DAYS,
                            settle_days: int = LABEL_SETTLE_DAYS) -> tuple[str, str]:
    end = _parse_iso(eval_date) - timedelta(days=max(0, settle_days))
    start = end - timedelta(days=max(0, lookback_days - 1))
    return start.isoformat(), end.isoformat()


def _date_iter(start_date: str, end_date: str) -> list[str]:
    start = _parse_iso(start_date)
    end = _parse_iso(end_date)
    out: list[str] = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _pipeline_db_path(data_root: str) -> Path:
    root = Path(data_root)
    new_path = root / ".db" / "pipeline.db"
    legacy = root / ".pipeline" / "state.db"
    if new_path.exists() or not legacy.exists():
        return new_path
    duck_new = root / ".db" / "pipeline.duckdb"
    duck_legacy = root / ".pipeline" / "state.duckdb"
    if legacy.exists():
        return legacy
    if duck_new.exists():
        return duck_new
    return duck_legacy


def _window_file_watermark(paths: list[Path]) -> dict[str, int]:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return {"files": 0, "mtime_ns": 0, "bytes": 0}
    return {
        "files": len(existing),
        "mtime_ns": max(path.stat().st_mtime_ns for path in existing),
        "bytes": int(sum(path.stat().st_size for path in existing)),
    }


def _content_window_watermark(data_root: str, start_date: str, end_date: str) -> dict[str, dict[str, int]]:
    root = Path(data_root)
    dates = _date_iter(start_date, end_date)
    bronze_sources = ["rss", "gdelt", "cls", "cctv"]
    bronze_paths: list[Path] = []
    for source_id in bronze_sources:
        bronze_paths.extend(
            root / "sentiment" / "bronze" / source_id / d[:4] / d[5:7] / f"{d}.parquet"
            for d in dates
        )
    silver_paths = [root / "sentiment" / "silver" / d[:4] / d[5:7] / f"{d}.parquet" for d in dates]
    gold_paths = [root / "sentiment" / "gold" / d[:4] / d[5:7] / f"{d}.parquet" for d in dates]
    return {
        "bronze": _window_file_watermark(bronze_paths),
        "silver": _window_file_watermark(silver_paths),
        "gold": _window_file_watermark(gold_paths),
    }


def _db_watermark(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
    row = conn.execute(sql, params).fetchone()
    if not row:
        return {"count": 0, "latest": None}
    return {"count": _safe_int(row[0]), "latest": row[1]}


def _active_model_watermark(db: TradeDB) -> dict[str, Any]:
    row = db._conn.execute(
        """
        SELECT COUNT(*) AS cnt, MAX(trained_at) AS latest
        FROM model_registry
        WHERE is_active=1 OR promotion_state='active'
        """
    ).fetchone()
    return {"count": _safe_int(row["cnt"] if row else 0), "latest": row["latest"] if row else None}


def _features_watermark(data_root: str) -> dict[str, Any]:
    path = Path(data_root) / "events" / "features.parquet"
    if not path.exists():
        return {"exists": False, "mtime_ns": 0, "bytes": 0}
    stat = path.stat()
    return {"exists": True, "mtime_ns": stat.st_mtime_ns, "bytes": int(stat.st_size)}


def _cache_fingerprint(data_root: str, eval_date: str,
                       recent_start: str, recent_end: str,
                       research_start: str, research_end: str) -> dict[str, Any]:
    db = TradeDB(data_root)
    payload = {
        "eval_date": eval_date,
        "recent_files": _content_window_watermark(data_root, recent_start, recent_end),
        "research_files": _content_window_watermark(data_root, research_start, research_end),
        "features": _features_watermark(data_root),
        "active_models": _active_model_watermark(db),
        "recent_market_events": _db_watermark(
            db._conn,
            "SELECT COUNT(*), MAX(created_at) FROM market_events WHERE event_date>=? AND event_date<=?",
            (recent_start, recent_end),
        ),
        "recent_propagations": _db_watermark(
            db._conn,
            """
            SELECT COUNT(*), MAX(COALESCE(validated_at, ep.created_at))
            FROM event_propagations ep
            JOIN market_events me ON me.event_id = ep.event_id
            WHERE me.event_date>=? AND me.event_date<=?
            """,
            (recent_start, recent_end),
        ),
        "research_market_events": _db_watermark(
            db._conn,
            "SELECT COUNT(*), MAX(created_at) FROM market_events WHERE event_date>=? AND event_date<=?",
            (research_start, research_end),
        ),
        "research_propagations": _db_watermark(
            db._conn,
            """
            SELECT COUNT(*), MAX(COALESCE(validated_at, ep.created_at))
            FROM event_propagations ep
            JOIN market_events me ON me.event_id = ep.event_id
            WHERE me.event_date>=? AND me.event_date<=?
            """,
            (research_start, research_end),
        ),
    }
    payload["hash"] = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return payload


def _fingerprint_matches(stored: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if not stored:
        return False
    return str(stored.get("hash") or "") == str(current.get("hash") or "")


def _read_parquet_frame(path_glob: str, columns: list[str] | None = None) -> pd.DataFrame:
    try:
        import duckdb

        con = duckdb.connect()
        select_cols = ", ".join(columns) if columns else "*"
        df = con.execute(
            f"SELECT {select_cols} FROM read_parquet('{path_glob}', union_by_name=true)"
        ).df()
        con.close()
        return df
    except Exception as exc:
        logger.debug("duckdb parquet read failed for %s: %s", path_glob, exc)
        return pd.DataFrame(columns=columns or [])


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return default
        return int(value)
    except Exception:
        return default


def _rank_ic_by_group(df: pd.DataFrame, score_col: str, target_col: str,
                      group_col: str = "event_date") -> tuple[float | None, int]:
    valid: list[float] = []
    for _, grp in df[[group_col, score_col, target_col]].dropna().groupby(group_col):
        if len(grp) < 5:
            continue
        score_rank = grp[score_col].rank()
        target_rank = grp[target_col].rank()
        ic = score_rank.corr(target_rank, method="pearson")
        if ic is not None and not math.isnan(float(ic)):
            valid.append(float(ic))
    if not valid:
        return None, 0
    return float(np.mean(valid)), len(valid)


def _topk_hit_rate(df: pd.DataFrame, score_col: str, target_col: str,
                   group_col: str = "event_date", k: int = 10) -> float | None:
    hits: list[float] = []
    for _, grp in df[[group_col, score_col, target_col]].dropna().groupby(group_col):
        if grp.empty:
            continue
        top = grp.sort_values(score_col, ascending=False).head(k)
        if top.empty:
            continue
        hits.append(float((top[target_col] > 0).mean()))
    if not hits:
        return None
    return float(np.mean(hits))


def _sector_concentration(df: pd.DataFrame, score_col: str, sector_col: str = "industry",
                          topn: int = 100) -> float | None:
    work = df[[score_col, sector_col]].dropna()
    if work.empty:
        return None
    top = work.sort_values(score_col, ascending=False).head(topn)
    if top.empty:
        return None
    counts = top[sector_col].value_counts(normalize=True)
    return float(counts.iloc[0]) if not counts.empty else None


def _brier_score(pred: pd.Series, actual: pd.Series) -> float | None:
    aligned = pd.concat([pred, actual], axis=1).dropna()
    if aligned.empty:
        return None
    return float(np.mean((aligned.iloc[:, 0] - aligned.iloc[:, 1]) ** 2))


def _calibration_bins(pred: pd.Series, actual: pd.Series, bins: int = 10) -> list[dict[str, Any]]:
    aligned = pd.concat([pred, actual], axis=1).dropna()
    if aligned.empty:
        return []
    frame = aligned.copy()
    frame.columns = ["pred", "actual"]
    try:
        frame["bucket"] = pd.qcut(frame["pred"], q=min(bins, len(frame)), duplicates="drop")
    except Exception:
        return []
    result: list[dict[str, Any]] = []
    for bucket, grp in frame.groupby("bucket", observed=False):
        result.append({
            "pred_low": float(bucket.left),
            "pred_high": float(bucket.right),
            "pred_mean": float(grp["pred"].mean()),
            "actual_freq": float(grp["actual"].mean()),
            "count": int(len(grp)),
        })
    return result


def _coverage_ratio(market_dir: Path, instrument_total: int) -> float:
    if instrument_total <= 0 or not market_dir.exists():
        return 0.0
    files = len(list(market_dir.glob("*.parquet")))
    return round(files / instrument_total, 4)


def _instrument_total(data_root: str) -> int:
    try:
        from trade_py.db.instruments_db import InstrumentsDB

        return len(InstrumentsDB(data_root).get_all_symbols())
    except Exception as exc:
        logger.debug("failed to count instruments: %s", exc)
        return 0


def _ingest_key(source_name: str, source_family: str) -> str:
    lower = source_name.strip().lower()
    family = source_family.strip().lower()
    if lower.startswith("gdelt") or family == "gdelt":
        return "gdelt"
    if lower.startswith("cls") or family == "cls":
        return "cls"
    if lower.startswith("cctv") or family == "cctv":
        return "cctv"
    return "rss"


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
        # Operational gates only need recent source health and event yield; skip heavy IC scans.
        ic_payload = {
            "skipped": True,
            "reason": f"lookback_days<{MIN_SOURCE_IC_LOOKBACK_DAYS}",
            "lookback_days": lookback_days,
        }
        ic_by_source = {}
    matured_cutoff = (_parse_iso(target_date) - timedelta(days=7)).isoformat()

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


def evaluate_events(data_root: str = str(default_data_root()),
                    eval_date: str | None = None,
                    lookback_days: int = 30,
                    start_date: str | None = None,
                    end_date: str | None = None,
                    persist: bool = True,
                    use_cache: bool = True) -> EvalOutcome:
    target_date = resolve_eval_date(data_root, eval_date)
    db = TradeDB(data_root)
    if not start_date or not end_date:
        start_date, end_date = _resolve_window(target_date, lookback_days)
    if use_cache:
        cached = _cached_event_outcome(db, target_date, start_date, end_date)
        if cached is not None:
            return cached
    row = db._conn.execute(
        """
        WITH event_base AS (
            SELECT
                me.event_id,
                me.event_type,
                me.entity_id,
                COUNT(ep.id) AS propagation_count,
                SUM(CASE WHEN ep.actual_return_5d IS NOT NULL OR ep.actual_return_20d IS NOT NULL THEN 1 ELSE 0 END) AS labeled_count
            FROM market_events me
            LEFT JOIN event_propagations ep ON ep.event_id = me.event_id
            WHERE me.event_date >= ? AND me.event_date <= ?
            GROUP BY me.event_id, me.event_type, me.entity_id
        ),
        propagation_stats AS (
            SELECT
                AVG(CASE WHEN actual_return_5d IS NOT NULL THEN actual_return_5d END) AS avg_return_5d,
                AVG(CASE WHEN actual_return_20d IS NOT NULL THEN actual_return_20d END) AS avg_return_20d,
                COUNT(*) AS propagation_total,
                SUM(CASE WHEN actual_return_5d IS NOT NULL OR actual_return_20d IS NOT NULL THEN 1 ELSE 0 END) AS propagation_labeled
            FROM event_propagations ep
            JOIN market_events me ON me.event_id = ep.event_id
            WHERE me.event_date >= ? AND me.event_date <= ?
        )
        SELECT
            COUNT(*) AS event_count,
            AVG(CASE WHEN propagation_count > 0 THEN 1.0 ELSE 0.0 END) AS effective_event_rate,
            AVG(CASE WHEN entity_id = 'SW_Unknown' THEN 1.0 ELSE 0.0 END) AS sw_unknown_ratio,
            AVG(CAST(propagation_count AS DOUBLE)) AS propagations_per_event,
            COALESCE((SELECT CAST(propagation_labeled AS DOUBLE) / NULLIF(propagation_total, 0) FROM propagation_stats), 0.0) AS labeled_propagation_ratio,
            (SELECT avg_return_5d FROM propagation_stats) AS avg_actual_return_5d,
            (SELECT avg_return_20d FROM propagation_stats) AS avg_actual_return_20d
        FROM event_base
        """,
        (start_date, end_date, start_date, end_date),
    ).fetchone()

    dist_rows = db._conn.execute(
        """
        SELECT event_type, COUNT(*) AS cnt
        FROM market_events
        WHERE event_date >= ? AND event_date <= ?
        GROUP BY event_type
        ORDER BY cnt DESC, event_type
        LIMIT 20
        """,
        (start_date, end_date),
    ).fetchall()
    distribution = {str(r["event_type"]): int(r["cnt"]) for r in dist_rows}

    payload = {
        "eval_date": target_date,
        "start_date": start_date,
        "end_date": end_date,
        "event_count": _safe_int(row["event_count"]) if row else 0,
        "effective_event_rate": round(_safe_float(row["effective_event_rate"]), 4) if row else 0.0,
        "sw_unknown_ratio": round(_safe_float(row["sw_unknown_ratio"]), 4) if row else 0.0,
        "propagations_per_event": round(_safe_float(row["propagations_per_event"]), 4) if row else 0.0,
        "labeled_propagation_ratio": round(_safe_float(row["labeled_propagation_ratio"]), 4) if row else 0.0,
        "avg_actual_return_5d": round(_safe_float(row["avg_actual_return_5d"]), 4), 
        "avg_actual_return_20d": round(_safe_float(row["avg_actual_return_20d"]), 4),
        "event_type_distribution": distribution,
    }
    status = "ok"
    if payload["event_count"] <= 0:
        status = "blocked_by_dependency"
    elif payload["labeled_propagation_ratio"] <= 0:
        status = "partial"
    if persist:
        db.event_eval_upsert({
            "eval_date": target_date,
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
            "event_count": payload["event_count"],
            "effective_event_rate": payload["effective_event_rate"],
            "sw_unknown_ratio": payload["sw_unknown_ratio"],
            "propagations_per_event": payload["propagations_per_event"],
            "labeled_propagation_ratio": payload["labeled_propagation_ratio"],
            "avg_actual_return_5d": payload["avg_actual_return_5d"],
            "avg_actual_return_20d": payload["avg_actual_return_20d"],
            "details_json": {"event_type_distribution": distribution},
        })
    summary = (
        f"event eval {start_date}->{end_date}: events={payload['event_count']}, "
        f"effective={payload['effective_event_rate']:.2%}, labeled={payload['labeled_propagation_ratio']:.2%}"
    )
    return EvalOutcome(status=status, summary=summary, payload=payload)


def _load_feature_frame(data_root: str, eval_date: str,
                        start_date: str | None = None,
                        end_date: str | None = None) -> pd.DataFrame:
    path = Path(data_root) / "events" / "features.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if "event_date" in df.columns:
        df["event_date"] = df["event_date"].astype(str).str.slice(0, 10)
        df = df[df["event_date"] <= eval_date].copy()
        if start_date:
            df = df[df["event_date"] >= start_date].copy()
        if end_date:
            df = df[df["event_date"] <= end_date].copy()
    return df


def _model_feature_matrix(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    available = [col for col in feature_cols if col in df.columns]
    return df[available].fillna(0.0).astype(np.float32)


def _model_version(row: dict[str, Any]) -> str:
    if row.get("trained_at"):
        return f"{row.get('id', 'model')}@{row['trained_at']}"
    return str(row.get("id", "model"))


def evaluate_models(data_root: str = str(default_data_root()),
                    eval_date: str | None = None,
                    start_date: str | None = None,
                    end_date: str | None = None,
                    persist: bool = True,
                    use_cache: bool = True) -> EvalOutcome:
    target_date = resolve_eval_date(data_root, eval_date)
    db = TradeDB(data_root)
    persist = persist and not (start_date or end_date)
    if use_cache and not start_date and not end_date:
        cached = _cached_model_outcome(db, target_date)
        if cached is not None:
            return cached
    df = _load_feature_frame(data_root, target_date, start_date, end_date)
    if df.empty:
        return EvalOutcome(
            status="blocked_by_dependency",
            summary="model eval skipped: features.parquet missing or empty",
            payload={"eval_date": target_date, "rows": []},
        )

    metrics_rows: list[dict[str, Any]] = []
    model_rows = [
        row
        for row in db.model_registry_list()
        if int(row.get("is_active", 0) or 0) == 1 or str(row.get("promotion_state", "")) == "active"
    ]
    if not model_rows:
        return EvalOutcome(
            status="blocked_by_dependency",
            summary="model eval skipped: no active models",
            payload={"eval_date": target_date, "rows": []},
        )

    try:
        import joblib
    except Exception as exc:
        return EvalOutcome(
            status="error",
            summary=f"model eval failed: joblib unavailable ({exc})",
            payload={"eval_date": target_date, "rows": []},
            exit_code=1,
        )

    baseline_direction = np.sign(pd.to_numeric(df.get("net_sentiment"), errors="coerce").fillna(0.0))
    kg_direction = np.sign(pd.to_numeric(df.get("kg_score"), errors="coerce").fillna(0.0))
    baseline_direction = np.where(baseline_direction == 0, kg_direction, baseline_direction)
    baseline_direction = np.where(baseline_direction == 0, 1.0, baseline_direction)
    df["_baseline_event_only"] = pd.to_numeric(df.get("magnitude"), errors="coerce").fillna(0.0) * baseline_direction
    df["_baseline_static_kg"] = pd.to_numeric(df.get("kg_score"), errors="coerce").fillna(0.0)

    overall_status = "ok"
    for row in model_rows:
        model_name = str(row.get("target_name") or row["model_name"])
        file_path = Path(str(row["file_path"]))
        if not file_path.exists():
            metrics_rows.append({
                "eval_date": target_date,
                "model_name": model_name,
                "target_name": model_name,
                "model_version": _model_version(row),
                "status": "blocked_by_dependency",
                "sample_count": 0,
                "valid_days": 0,
                "rank_ic": None,
                "mae": None,
                "topk_hit_rate": None,
                "sector_concentration": None,
                "risk_brier_score": None,
                "baseline_json": {},
                "calibration_json": [],
                "details_json": {"reason": f"missing model file {file_path}"},
            })
            overall_status = "partial"
            continue

        model = joblib.load(file_path)
        feature_cols = FEATURE_COLS
        row_metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        if row_metrics and row_metrics.get("feature_cols"):
            feature_cols = list(row_metrics["feature_cols"])

        target_col = "actual_return_5d" if "5d" in model_name else "actual_return_20d" if "20d" in model_name else "actual_return_5d"
        work = df.dropna(subset=[target_col]).copy()
        if work.empty:
            metrics_rows.append({
                "eval_date": target_date,
                "model_name": model_name,
                "target_name": target_col,
                "model_version": _model_version(row),
                "status": "partial",
                "sample_count": 0,
                "valid_days": 0,
                "rank_ic": None,
                "mae": None,
                "topk_hit_rate": None,
                "sector_concentration": None,
                "risk_brier_score": None,
                "baseline_json": {},
                "calibration_json": [],
                "details_json": {"reason": f"no labeled rows for {target_col}"},
            })
            overall_status = "partial"
            continue

        X = _model_feature_matrix(work, feature_cols)
        if model_name == "kg_risk_5pct":
            if not hasattr(model, "predict_proba"):
                pred = pd.Series(model.predict(X), index=work.index, dtype=float)
            else:
                pred = pd.Series(model.predict_proba(X)[:, 1], index=work.index, dtype=float)
            actual = (work["actual_return_5d"] < -5.0).astype(float)
            brier = _brier_score(pred, actual)
            calibration = _calibration_bins(pred, actual)
            rank_ic, valid_days = _rank_ic_by_group(
                pd.DataFrame({"event_date": work["event_date"], "score": pred, "target": actual}),
                "score",
                "target",
            )
            model_row = {
                "eval_date": target_date,
                "model_name": model_name,
                "target_name": "risk_5pct",
                "model_version": _model_version(row),
                "status": "ok" if brier is not None else "partial",
                "sample_count": int(len(work)),
                "valid_days": valid_days,
                "rank_ic": round(rank_ic, 4) if rank_ic is not None else None,
                "mae": None,
                "topk_hit_rate": None,
                "sector_concentration": None,
                "risk_brier_score": round(brier, 4) if brier is not None else None,
                "baseline_json": {},
                "calibration_json": calibration,
                "details_json": {"positive_rate": round(float(actual.mean()), 4)},
            }
        else:
            pred = pd.Series(model.predict(X), index=work.index, dtype=float)
            work["_model_pred"] = pred
            rank_ic, valid_days = _rank_ic_by_group(work, "_model_pred", target_col)
            mae = float(np.mean(np.abs(work[target_col] - work["_model_pred"])))
            topk = _topk_hit_rate(work, "_model_pred", target_col)
            sector_conc = _sector_concentration(work, "_model_pred")
            event_only_ic, _ = _rank_ic_by_group(work.assign(_pred=work["_baseline_event_only"]), "_pred", target_col)
            static_kg_ic, _ = _rank_ic_by_group(work.assign(_pred=work["_baseline_static_kg"]), "_pred", target_col)
            best_baseline = max(v for v in [event_only_ic, static_kg_ic] if v is not None) if any(v is not None for v in [event_only_ic, static_kg_ic]) else None
            model_row = {
                "eval_date": target_date,
                "model_name": model_name,
                "target_name": target_col,
                "model_version": _model_version(row),
                "status": "ok" if rank_ic is not None else "partial",
                "sample_count": int(len(work)),
                "valid_days": valid_days,
                "rank_ic": round(rank_ic, 4) if rank_ic is not None else None,
                "mae": round(mae, 4),
                "topk_hit_rate": round(topk, 4) if topk is not None else None,
                "sector_concentration": round(sector_conc, 4) if sector_conc is not None else None,
                "risk_brier_score": None,
                "baseline_json": {
                    "event_only": {"rank_ic": round(event_only_ic, 4) if event_only_ic is not None else None},
                    "event_static_kg": {"rank_ic": round(static_kg_ic, 4) if static_kg_ic is not None else None},
                    "best_baseline_rank_ic": round(best_baseline, 4) if best_baseline is not None else None,
                    "baseline_delta": round((rank_ic - best_baseline), 4) if rank_ic is not None and best_baseline is not None else None,
                },
                "calibration_json": [],
                "details_json": {
                    "feature_cols": feature_cols,
                },
            }
        if model_row["status"] != "ok":
            overall_status = "partial"
        metrics_rows.append(model_row)

    if persist:
        for row in metrics_rows:
            db.model_eval_upsert(row)

    summary = (
        f"model eval {start_date or 'begin'}->{end_date or target_date}: "
        f"models={len(metrics_rows)}, status={overall_status}"
    )
    return EvalOutcome(status=overall_status, summary=summary, payload={"eval_date": target_date, "rows": metrics_rows})


def _latest_model_eval(db: TradeDB, eval_date: str, model_name: str) -> dict[str, Any] | None:
    rows = db.model_eval_list(eval_date=eval_date, model_name=model_name)
    return rows[0] if rows else None


def _dataset_snapshot(data_root: str, eval_date: str,
                      start_date: str | None = None,
                      metadata_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    db = TradeDB(data_root)
    features_path = Path(data_root) / "events" / "features.parquet"
    instrument_total = _instrument_total(data_root)
    feature_rows = labeled_rows_5d = labeled_rows_20d = 0
    if features_path.exists():
        df = pd.read_parquet(features_path)
        if "event_date" in df.columns:
            df["event_date"] = df["event_date"].astype(str).str.slice(0, 10)
            df = df[df["event_date"] <= eval_date]
            if start_date:
                df = df[df["event_date"] >= start_date]
        feature_rows = int(len(df))
        labeled_rows_5d = int(df["actual_return_5d"].notna().sum()) if "actual_return_5d" in df.columns else 0
        labeled_rows_20d = int(df["actual_return_20d"].notna().sum()) if "actual_return_20d" in df.columns else 0
    signal_dates = _safe_int(db._conn.execute("SELECT COUNT(DISTINCT date) FROM signals").fetchone()[0], 0)
    source_count = _safe_int(db._conn.execute(
        "SELECT COUNT(DISTINCT source_name) FROM source_eval_daily WHERE eval_date=?",
        (eval_date,),
    ).fetchone()[0], 0)
    event_row = db._conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT me.event_id) FROM event_propagations ep JOIN market_events me ON me.event_id = ep.event_id WHERE me.event_date <= ?",
        (eval_date,),
    ).fetchone()
    propagation_count = _safe_int(event_row[0], 0) if event_row else 0
    event_count = _safe_int(event_row[1], 0) if event_row else 0
    metadata = {
        "instrument_total": instrument_total,
        "fund_flow_coverage": _coverage_ratio(Path(data_root) / "market" / "fund_flow", instrument_total),
        "fundamental_coverage": _coverage_ratio(Path(data_root) / "market" / "fundamental", instrument_total),
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    return {
        "snapshot_name": "daily",
        "eval_date": eval_date,
        "start_date": start_date,
        "end_date": eval_date,
        "source_count": source_count,
        "market_event_count": event_count,
        "propagation_count": propagation_count,
        "feature_rows": feature_rows,
        "labeled_rows_5d": labeled_rows_5d,
        "labeled_rows_20d": labeled_rows_20d,
        "signal_dates": signal_dates,
        "metadata_json": metadata,
    }


def evaluate_gate(data_root: str = str(default_data_root()),
                  eval_date: str | None = None,
                  source_outcome: EvalOutcome | None = None,
                  recent_event_outcome: EvalOutcome | None = None,
                  research_event_outcome: EvalOutcome | None = None,
                  research_model_outcome: EvalOutcome | None = None,
                  cache_fingerprint: dict[str, Any] | None = None,
                  persist: bool = True,
                  use_cache: bool = True) -> EvalOutcome:
    target_date = resolve_eval_date(data_root, eval_date)
    db = TradeDB(data_root)
    recent_start, recent_end = _resolve_window(target_date, RECENT_OPERATIONAL_DAYS)
    research_start, research_end = _resolve_matured_window(target_date)
    current_fingerprint = cache_fingerprint or _cache_fingerprint(
        data_root, target_date, recent_start, recent_end, research_start, research_end
    )
    if use_cache:
        cached = _cached_gate_outcome(db, target_date)
        cached_metrics = cached.payload.get("metrics", {}) if cached is not None else {}
        if cached is not None and _fingerprint_matches(cached_metrics.get("cache_fingerprint"), current_fingerprint):
            return cached
    source_outcome = source_outcome or evaluate_sources(
        data_root,
        eval_date=target_date,
        lookback_days=RECENT_OPERATIONAL_DAYS,
        persist=True,
        use_cache=use_cache,
    )
    recent_event_outcome = recent_event_outcome or evaluate_events(
        data_root,
        eval_date=target_date,
        start_date=recent_start,
        end_date=recent_end,
        persist=True,
        use_cache=use_cache,
    )
    research_event_outcome = research_event_outcome or evaluate_events(
        data_root,
        eval_date=target_date,
        start_date=research_start,
        end_date=research_end,
        persist=True,
        use_cache=use_cache,
    )
    research_model_outcome = research_model_outcome or evaluate_models(
        data_root,
        eval_date=target_date,
        start_date=research_start,
        end_date=research_end,
        persist=False,
        use_cache=False,
    )
    snapshot = _dataset_snapshot(
        data_root,
        target_date,
        start_date=research_start,
        metadata_extra={"cache_fingerprint": current_fingerprint},
    )

    latest_reasons: list[str] = []
    matured_reasons: list[str] = []
    missing: list[str] = []
    latest_metrics: dict[str, Any] = {
        "eval_date": target_date,
        "window_start": recent_start,
        "window_end": recent_end,
        "fund_flow_coverage": snapshot["metadata_json"].get("fund_flow_coverage", 0.0),
        "fundamental_coverage": snapshot["metadata_json"].get("fundamental_coverage", 0.0),
        "source_healthy_ratio": (
            sum(1 for row in source_outcome.payload.get("health_rows", []) if row.get("healthy"))
            / max(1, len(source_outcome.payload.get("health_rows", [])))
            if source_outcome.payload.get("health_rows")
            else None
        ),
        "event_count": recent_event_outcome.payload.get("event_count", 0),
    }
    matured_metrics: dict[str, Any] = {
        "window_start": research_start,
        "window_end": research_end,
        "labeled_propagation_ratio": research_event_outcome.payload.get("labeled_propagation_ratio", 0.0),
    }

    min_fund_flow = _safe_float(db.get("eval.min_fund_flow_coverage", 0.85), 0.85)
    min_fundamental = _safe_float(db.get("eval.min_fundamental_coverage", 0.85), 0.85)
    min_event_count = _safe_int(db.get("eval.min_event_count", 5), 5)
    min_labeled_ratio = _safe_float(db.get("eval.min_labeled_propagation_ratio", 0.05), 0.05)
    min_rank_ic = _safe_float(db.get("eval.min_model_rank_ic_5d", 0.02), 0.02)

    if source_outcome.status == "blocked_by_dependency":
        missing.append("source evaluation missing")
    if recent_event_outcome.status == "blocked_by_dependency":
        missing.append("recent event evaluation missing")
    if research_model_outcome.status == "blocked_by_dependency":
        missing.append("research model evaluation missing")

    if latest_metrics["fund_flow_coverage"] < min_fund_flow:
        latest_reasons.append(f"fund_flow coverage {latest_metrics['fund_flow_coverage']:.1%} < {min_fund_flow:.0%}")
    if latest_metrics["fundamental_coverage"] < min_fundamental:
        latest_reasons.append(f"fundamental coverage {latest_metrics['fundamental_coverage']:.1%} < {min_fundamental:.0%}")
    if _safe_int(recent_event_outcome.payload.get("event_count"), 0) < min_event_count:
        latest_reasons.append(f"event_count {recent_event_outcome.payload.get('event_count', 0)} < {min_event_count}")
    if source_outcome.status in {"partial", "blocked_by_dependency"}:
        latest_reasons.append(f"source status={source_outcome.status}")
    if recent_event_outcome.status in {"partial", "blocked_by_dependency"} and _safe_int(recent_event_outcome.payload.get("event_count"), 0) <= 0:
        latest_reasons.append(f"recent event status={recent_event_outcome.status}")

    model_rows = research_model_outcome.payload.get("rows", [])
    model_5d = next((row for row in model_rows if row.get("model_name") == "kg_return_5d"), None)
    if model_5d:
        matured_metrics["model_rank_ic_5d"] = model_5d.get("rank_ic")
        baseline = model_5d.get("baseline_json") or {}
        matured_metrics["model_baseline_delta"] = baseline.get("baseline_delta")
        rank_ic = model_5d.get("rank_ic")
        if rank_ic is None or _safe_float(rank_ic, -1.0) < min_rank_ic:
            matured_reasons.append(f"model rank_ic_5d {_safe_float(rank_ic, -1.0):.4f} < {min_rank_ic:.4f}")
        delta = baseline.get("baseline_delta")
        if delta is not None and _safe_float(delta) < 0:
            matured_reasons.append(f"model below baseline ({_safe_float(delta):.4f})")
    else:
        matured_reasons.append("kg_return_5d evaluation missing")
    if _safe_float(research_event_outcome.payload.get("labeled_propagation_ratio"), 0.0) < min_labeled_ratio:
        matured_reasons.append(
            f"labeled_propagation_ratio {_safe_float(research_event_outcome.payload.get('labeled_propagation_ratio')):.1%} < {min_labeled_ratio:.0%}"
        )
    if research_event_outcome.status == "blocked_by_dependency":
        matured_reasons.append("research event evaluation missing")

    operational_status = "ok"
    if missing and not latest_reasons:
        operational_status = "blocked_by_dependency"
    elif latest_reasons:
        operational_status = "degraded"

    research_status = "ok"
    if research_event_outcome.status == "blocked_by_dependency" or research_model_outcome.status == "blocked_by_dependency":
        research_status = "blocked_by_dependency"
    elif matured_reasons or research_event_outcome.status == "partial" or research_model_outcome.status == "partial":
        research_status = "partial"

    if operational_status in {"degraded", "blocked_by_dependency"}:
        status = operational_status
    elif research_status in {"partial", "blocked_by_dependency"}:
        status = "partial"
    else:
        status = "ok"

    reasons = [f"latest: {reason}" for reason in latest_reasons] + [f"matured: {reason}" for reason in matured_reasons]
    if missing:
        reasons = missing + reasons
    metrics = {
        "operational_status": operational_status,
        "research_status": research_status,
        "overall_status": status,
        "latest_reasons": latest_reasons,
        "matured_reasons": matured_reasons,
        "latest_metrics": latest_metrics,
        "matured_metrics": matured_metrics,
        "missing": missing,
        "cache_fingerprint": current_fingerprint,
        # Backward-compatible top-level metrics.
        "fund_flow_coverage": latest_metrics.get("fund_flow_coverage"),
        "fundamental_coverage": latest_metrics.get("fundamental_coverage"),
        "source_healthy_ratio": latest_metrics.get("source_healthy_ratio"),
        "event_count": latest_metrics.get("event_count"),
        "labeled_propagation_ratio": matured_metrics.get("labeled_propagation_ratio"),
        "model_rank_ic_5d": matured_metrics.get("model_rank_ic_5d"),
        "model_baseline_delta": matured_metrics.get("model_baseline_delta"),
    }
    if persist:
        db.quality_gate_upsert(target_date, status, reasons, metrics)
    summary = f"quality gate {target_date}: overall={status} op={operational_status} research={research_status}"
    return EvalOutcome(status=status, summary=summary, payload={"eval_date": target_date, "status": status, "reasons": reasons, "metrics": metrics})


def evaluate_daily(data_root: str = str(default_data_root()),
                   eval_date: str | None = None,
                   lookback_days: int = 30,
                   use_cache: bool = True) -> EvalOutcome:
    target_date = resolve_eval_date(data_root, eval_date)
    recent_start, recent_end = _resolve_window(target_date, RECENT_OPERATIONAL_DAYS)
    research_start, research_end = _resolve_matured_window(target_date)
    cache_fp = _cache_fingerprint(data_root, target_date, recent_start, recent_end, research_start, research_end)
    db = TradeDB(data_root)

    if use_cache:
        snapshot = db.dataset_snapshot_get(target_date, snapshot_name="daily")
        source_outcome = _cached_source_outcome(db, target_date)
        event_outcome = _cached_event_outcome(db, target_date, recent_start, recent_end)
        model_outcome = _cached_model_outcome(db, target_date)
        gate_outcome = _cached_gate_outcome(db, target_date)
        snapshot_meta = snapshot.get("metadata_json") if snapshot else {}
        gate_metrics = gate_outcome.payload.get("metrics", {}) if gate_outcome else {}
        if (
            snapshot and source_outcome and event_outcome and model_outcome and gate_outcome
            and _fingerprint_matches(snapshot_meta.get("cache_fingerprint"), cache_fp)
            and _fingerprint_matches(gate_metrics.get("cache_fingerprint"), cache_fp)
        ):
            payload = {
                "eval_date": target_date,
                "source": source_outcome.payload,
                "event": event_outcome.payload,
                "model": model_outcome.payload,
                "gate": gate_outcome.payload,
                "snapshot": snapshot,
            }
            summary = (
                f"daily eval {target_date}: "
                f"source={source_outcome.status}, event={event_outcome.status}, "
                f"model={model_outcome.status}, gate={gate_outcome.status} [cached]"
            )
            status = gate_outcome.status
            if status == "ok" and any(out.status in {"partial", "blocked_by_dependency"} for out in [source_outcome, event_outcome, model_outcome]):
                status = "partial"
            return EvalOutcome(status=status, summary=summary, payload=payload)

    source_outcome = evaluate_sources(
        data_root, eval_date=target_date, lookback_days=RECENT_OPERATIONAL_DAYS, persist=True, use_cache=use_cache
    )
    event_outcome = evaluate_events(
        data_root, eval_date=target_date, start_date=recent_start, end_date=recent_end, persist=True, use_cache=use_cache
    )
    model_outcome = evaluate_models(
        data_root, eval_date=target_date, start_date=None, persist=True, use_cache=use_cache
    )
    research_event_outcome = evaluate_events(
        data_root, eval_date=target_date, start_date=research_start, end_date=research_end, persist=True, use_cache=use_cache
    )
    research_model_outcome = evaluate_models(
        data_root, eval_date=target_date, start_date=research_start, end_date=research_end, persist=False, use_cache=False
    )

    snapshot = _dataset_snapshot(
        data_root,
        target_date,
        start_date=research_start,
        metadata_extra={"cache_fingerprint": cache_fp},
    )
    db.dataset_snapshot_upsert(snapshot)

    gate_outcome = evaluate_gate(
        data_root,
        eval_date=target_date,
        source_outcome=source_outcome,
        recent_event_outcome=event_outcome,
        research_event_outcome=research_event_outcome,
        research_model_outcome=research_model_outcome,
        cache_fingerprint=cache_fp,
        persist=True,
        use_cache=False,
    )
    payload = {
        "eval_date": target_date,
        "source": source_outcome.payload,
        "event": event_outcome.payload,
        "model": model_outcome.payload,
        "research_event": research_event_outcome.payload,
        "research_model": research_model_outcome.payload,
        "gate": gate_outcome.payload,
        "snapshot": snapshot,
    }
    summary = (
        f"daily eval {target_date}: "
        f"source={source_outcome.status}, event={event_outcome.status}, model={model_outcome.status}, "
        f"research_event={research_event_outcome.status}, research_model={research_model_outcome.status}, gate={gate_outcome.status}"
    )
    status = gate_outcome.status
    if status == "ok" and any(out.status in {"partial", "blocked_by_dependency"} for out in [source_outcome, event_outcome, model_outcome]):
        status = "partial"
    return EvalOutcome(status=status, summary=summary, payload=payload)
