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
from trade_py.decision.explain import build_reasons, build_data_fingerprint

if TYPE_CHECKING:
    from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

HORIZON_DAYS = 5

_FRESHNESS_DATASETS = [
    "kline", "fund_flow", "sentiment_gold", "market_events", "factors",
]


def _write_freshness(db: "TradeDB", today: str) -> None:
    """Write FreshnessStatus for known datasets."""
    records = []
    for ds in _FRESHNESS_DATASETS:
        try:
            # Try to get last sync date from sync_state
            row = db._conn.execute(
                "SELECT MAX(last_date) as last_date FROM sync_state WHERE dataset=?",
                (ds,),
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
            "coverage_pct": None,
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
            )
        except Exception as exc:
            logger.warning("rec upsert failed for %s: %s", symbol, exc)
            continue

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
            )
        except Exception as exc:
            logger.warning("trace upsert failed for %s: %s", symbol, exc)

        item["rec_id"] = rec_id
        item["reasons"] = reasons
        recs.append(item)

    logger.info("produce_recommendations: %d recs for %s", len(recs), today)
    return recs
