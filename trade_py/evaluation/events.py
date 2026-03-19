"""Event propagation evaluation: quality and coverage metrics."""
from __future__ import annotations

import logging
from typing import Any

from trade_py.db.trade_db import TradeDB
from trade_py.infra.settings import default_data_root
from trade_py.evaluation.utils import (
    EvalOutcome,
    _cached_event_outcome,
    _resolve_window,
    _safe_float,
    _safe_int,
    resolve_eval_date,
)

logger = logging.getLogger(__name__)


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

    payload: dict[str, Any] = {
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
