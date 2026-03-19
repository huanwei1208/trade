"""Shared utilities for the evaluation package.

Includes: constants, EvalOutcome, cache-hit helpers, date/window helpers,
watermark helpers, parquet IO, and statistical helpers.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trade_py.db.trade_db import TradeDB
from trade_py.infra.settings import default_data_root

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

RECENT_OPERATIONAL_DAYS = 3
MATURED_RESEARCH_DAYS = 120
LABEL_SETTLE_DAYS = 28
MIN_SOURCE_IC_LOOKBACK_DAYS = 10


# ── EvalOutcome ────────────────────────────────────────────────────────────────

@dataclass
class EvalOutcome:
    status: str
    summary: str
    payload: dict[str, Any]
    exit_code: int = 0
    gate_ok: bool = False


# ── Cache-hit helpers ──────────────────────────────────────────────────────────

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
                          start_date: str, end_date: str) -> EvalOutcome | None:
    row = db.event_eval_get(eval_date, start_date, end_date)
    if not row:
        return None
    payload = {
        "eval_date": eval_date,
        "start_date": start_date,
        "end_date": end_date,
        "event_count": int(row.get("event_count") or 0),
        "effective_event_rate": float(row.get("effective_event_rate") or 0.0),
        "sw_unknown_ratio": float(row.get("sw_unknown_ratio") or 0.0),
        "propagations_per_event": float(row.get("propagations_per_event") or 0.0),
        "labeled_propagation_ratio": float(row.get("labeled_propagation_ratio") or 0.0),
        "avg_actual_return_5d": float(row.get("avg_actual_return_5d") or 0.0),
        "avg_actual_return_20d": float(row.get("avg_actual_return_20d") or 0.0),
        "event_type_distribution": {},
    }
    status = str(row.get("status") or "ok")
    summary = (
        f"event eval {start_date}->{end_date}: events={payload['event_count']}, "
        f"effective={payload['effective_event_rate']:.2%}, labeled={payload['labeled_propagation_ratio']:.2%} [cached]"
    )
    return EvalOutcome(status=status, summary=summary, payload=payload)


def _cached_model_outcome(db: TradeDB, eval_date: str) -> EvalOutcome | None:
    rows = db.model_eval_list(eval_date=eval_date)
    if not rows:
        return None
    overall_status = "ok" if all(str(r.get("status") or "ok") == "ok" for r in rows) else "partial"
    return EvalOutcome(
        status=overall_status,
        summary=f"model eval {eval_date}: models={len(rows)} [cached]",
        payload={"eval_date": eval_date, "rows": rows},
    )


def _cached_gate_outcome(db: TradeDB, eval_date: str) -> EvalOutcome | None:
    row = db.quality_gate_get(eval_date)
    if not row:
        return None
    status = str(row.get("status") or "ok")
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    reasons = row.get("reasons") if isinstance(row.get("reasons"), list) else []
    return EvalOutcome(
        status=status,
        summary=f"quality gate {eval_date}: overall={status} [cached]",
        payload={"eval_date": eval_date, "status": status, "reasons": reasons, "metrics": metrics},
    )


# ── Date helpers ───────────────────────────────────────────────────────────────

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


# ── Watermark helpers ──────────────────────────────────────────────────────────

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


# ── IO helpers ─────────────────────────────────────────────────────────────────

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


# ── Statistical helpers ────────────────────────────────────────────────────────

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
