"""Decision layer — produce daily Recommendation + RecommendationTrace records.

Entry point:
    produce_recommendations(asof_date, data_root, db) -> list[dict]
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, TYPE_CHECKING

from trade_py.decision.rank import rank_symbols
from trade_py.decision.explain import (
    build_reasons, build_data_fingerprint,
    build_narrative_text, build_trace_trust_json,
)

if TYPE_CHECKING:
    from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

HORIZON_DAYS = 5

_FRESHNESS_DATASETS = [
    "kline", "fund_flow", "sentiment_gold", "market_events", "factors",
]


def _latest_sync_date(
    db: "TradeDB",
    *,
    datasets: tuple[str, ...] = (),
    sources: tuple[str, ...] = (),
    not_after: str | None = None,
) -> str | None:
    clauses: list[str] = []
    params: list[str] = []
    if datasets:
        placeholders = ",".join("?" for _ in datasets)
        clauses.append(f"dataset IN ({placeholders})")
        params.extend(datasets)
    if sources:
        placeholders = ",".join("?" for _ in sources)
        clauses.append(f"source IN ({placeholders})")
        params.extend(sources)
    if not clauses:
        return None
    filters = [f"({' OR '.join(clauses)})"]
    if not_after:
        filters.append("last_date <= ?")
        params.append(not_after)
    query = f"SELECT MAX(last_date) FROM sync_state WHERE {' AND '.join(filters)}"
    row = db._conn.execute(query, params).fetchone()
    return row[0] if row and row[0] else None


def _latest_sentiment_gold_date(data_root: str) -> str | None:
    gold_root = Path(data_root) / "sentiment" / "gold"
    if not gold_root.exists():
        return None
    latest: str | None = None
    for path in gold_root.rglob("*.parquet"):
        stem = path.stem
        if len(stem) == 10 and stem[4] == "-" and stem[7] == "-":
            latest = max(latest or stem, stem)
    return latest


def _snapshot_metadata_latest(db: "TradeDB", today: str) -> tuple[str | None, dict[str, Any]]:
    row = db._conn.execute(
        """
        SELECT eval_date, metadata_json
        FROM dataset_snapshots
        WHERE eval_date <= ?
        ORDER BY eval_date DESC
        LIMIT 1
        """,
        (today,),
    ).fetchone()
    if not row:
        return None, {}
    try:
        meta = json.loads(row[1] or "{}")
    except Exception:
        meta = {}
    return row[0], meta if isinstance(meta, dict) else {}


def _write_freshness(db: "TradeDB", today: str) -> None:
    """Write FreshnessStatus for known datasets."""
    snapshot_day, snapshot_meta = _snapshot_metadata_latest(db, today)
    records = []
    for ds in _FRESHNESS_DATASETS:
        freshness_date: str | None = None
        coverage_pct: float | None = None
        try:
            if ds == "kline":
                freshness_date = _latest_sync_date(
                    db,
                    datasets=("kline",),
                    sources=("tushare_kline",),
                    not_after=today,
                )
            elif ds == "fund_flow":
                coverage = snapshot_meta.get("fund_flow_coverage")
                if coverage is not None and float(coverage) > 0:
                    freshness_date = snapshot_day
                    coverage_pct = float(coverage)
            elif ds == "sentiment_gold":
                freshness_date = _latest_sentiment_gold_date(getattr(db, "_data_root", "data"))
            elif ds == "market_events":
                row = db._conn.execute("SELECT MAX(event_date) FROM market_events").fetchone()
                freshness_date = row[0] if row and row[0] else None
            elif ds == "factors":
                row = db._conn.execute(
                    """
                    SELECT MAX(latest_date) FROM (
                        SELECT MAX(date) AS latest_date FROM signals
                        UNION ALL
                        SELECT MAX(date) AS latest_date FROM factors
                    )
                    """
                ).fetchone()
                freshness_date = row[0] if row and row[0] else None
        except Exception:
            freshness_date = None

        lag_days: int | None = None
        status = "unknown"
        if freshness_date:
            try:
                lag_days = (date.fromisoformat(today) - date.fromisoformat(freshness_date)).days
                if lag_days <= 1:
                    status = "ok"
                elif lag_days <= 3:
                    status = "partial"
                else:
                    status = "error"
            except Exception:
                status = "unknown"
        else:
            status = "missing"

        records.append({
            "dataset": ds,
            "freshness_date": freshness_date,
            "lag_days": lag_days,
            "coverage_pct": coverage_pct,
            "status": status,
        })

    try:
        db.freshness_status_upsert_batch(today, records)
    except Exception as exc:
        logger.warning("freshness_status write failed: %s", exc)


def produce_recommendations(
    asof_date: str,
    data_root: str,
    db: "TradeDB",
) -> list[dict[str, Any]]:
    """Generate daily Recommendation + RecommendationTrace records.

    Steps:
    1. Write FreshnessStatus
    2. Load BeliefState for today
    3. Load latest signals for each symbol
    4. Rank symbols → score/action/conviction
    5. Write Recommendation + RecommendationTrace
    6. Return sorted recommendations
    """
    today = asof_date

    # Step 1: write freshness
    _write_freshness(db, today)

    # Step 2: load BeliefState
    try:
        belief_states = db.belief_state_list_date(today)
    except Exception as exc:
        logger.warning("produce_recommendations: belief_state load failed: %s", exc)
        belief_states = []

    if not belief_states:
        logger.info("produce_recommendations: no belief states for %s", today)
        return []

    try:
        active_symbols = set(db.get_active_symbols())
    except Exception:
        active_symbols = set()
    if active_symbols:
        belief_states = [row for row in belief_states if str(row.get("symbol") or "") in active_symbols]

    # Step 3: load signals
    signals: dict[str, dict] = {}
    try:
        rows = db._conn.execute(
            "SELECT * FROM signals WHERE date=? ORDER BY window_score DESC",
            (today,),
        ).fetchall()
        if rows:
            for row in rows:
                r = dict(row)
                signals[r["symbol"]] = r
    except Exception:
        pass

    # Also try yesterday's signals if today has none
    if not signals:
        try:
            yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
            rows = db._conn.execute(
                "SELECT * FROM signals WHERE date=? ORDER BY window_score DESC",
                (yesterday,),
            ).fetchall()
            for row in rows:
                r = dict(row)
                signals[r["symbol"]] = r
        except Exception:
            pass

    # Step 4: rank
    ranked = rank_symbols(belief_states, signals)

    # Step 5: write recommendations
    try:
        with db._conn_lock:
            db._conn.execute("DELETE FROM Recommendation WHERE as_of_date = ?", (today,))
            db._conn.execute("DELETE FROM RecommendationTrace WHERE as_of_date = ?", (today,))
            db._conn.commit()
    except Exception as exc:
        logger.warning("produce_recommendations: cleanup failed for %s: %s", today, exc)

    recs = []
    for item in ranked:
        symbol = item["symbol"]
        score = item["score"]
        action = item["action"]
        conviction = item["conviction"]
        risk = item["risk"]

        rec_id = hashlib.md5(f"{today}:{symbol}:rec".encode()).hexdigest()

        # Build reasons
        reasons = build_reasons(symbol, today, item, db)

        expected_return_5d = item.get("expected_return_5d")
        risk_5pct = item.get("risk_5pct")
        horizon_set = item.get("horizon_set")

        try:
            db.recommendation_upsert(
                rec_id=rec_id,
                as_of_date=today,
                symbol=symbol,
                action=action,
                conviction=conviction,
                score=score,
                risk=risk,
                horizon_days=HORIZON_DAYS,
                reasons=reasons,
                expected_return_5d=expected_return_5d,
                risk_5pct=risk_5pct,
                horizon_set=horizon_set,
            )
        except Exception as exc:
            logger.warning("rec upsert failed for %s: %s", symbol, exc)
            continue

        # Build narrative text
        narrative = build_narrative_text(symbol, item, reasons)

        # Write trace
        trace_id = hashlib.md5(f"{today}:{symbol}:trace".encode()).hexdigest()
        try:
            # Get belief transition
            transition = db.belief_transition_get(symbol, today)
            transition_id = transition["transition_id"] if transition else None

            # Top evidence from attention
            top_ev = [
                {"evidence_type": r.get("evidence_type"), "weight": r.get("weight")}
                for r in reasons[:3]
            ]

            db.recommendation_trace_upsert(
                trace_id=trace_id,
                as_of_date=today,
                symbol=symbol,
                rec_id=rec_id,
                top_evidence=top_ev,
                data_fingerprint=build_data_fingerprint(symbol, today),
                belief_transition_id=transition_id,
                model_versions={"belief": "v1", "rank": "three_factor"},
                narrative_text=narrative,
            )
        except Exception as exc:
            logger.warning("trace upsert failed for %s: %s", symbol, exc)

        item["rec_id"] = rec_id
        item["reasons"] = reasons
        recs.append(item)

    logger.info("produce_recommendations: %d recs for %s", len(recs), today)
    return recs
