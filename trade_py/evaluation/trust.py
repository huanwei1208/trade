"""Trust vector computation, Brier/drift metrics, source reliability update,
and QualityReport writing.

Public API:
    compute_trust_vector(db, eval_date, brier_score, drift_mmd) -> dict[str, float]
    scalar_trust(trust_vec) -> float
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.db.trade_db import TradeDB
from trade_py.evaluation.utils import _brier_score

logger = logging.getLogger(__name__)


# ── Brier score from Recommendations ──────────────────────────────────────────

def _compute_brier_from_recommendations(db: TradeDB, eval_date: str,
                                        horizon_days: int = 5) -> float | None:
    """Compare Recommendation.score (T-horizon) vs actual return direction."""
    try:
        t_minus = (date.fromisoformat(eval_date) - timedelta(days=horizon_days)).isoformat()
        recs = db.recommendation_list(t_minus)
        if not recs:
            return None

        scores: list[float] = []
        actuals: list[float] = []
        for r in recs:
            sym = str(r.get("symbol") or "")
            pred_score = float(r.get("score") or 0.5)
            try:
                ep = db._conn.execute("""
                    SELECT actual_return_5d FROM event_propagations ep
                    JOIN market_events me ON ep.event_id = me.event_id
                    WHERE ep.symbol=? AND me.event_date=?
                    LIMIT 1
                """, (sym, t_minus)).fetchone()
                if ep and ep[0] is not None:
                    actual_positive = 1.0 if float(ep[0]) > 0 else 0.0
                    scores.append(pred_score)
                    actuals.append(actual_positive)
            except Exception:
                pass

        if len(scores) < 5:
            return None

        return _brier_score(pd.Series(scores), pd.Series(actuals))
    except Exception as exc:
        logger.debug("Brier computation failed: %s", exc)
        return None


# ── MMD drift detector ─────────────────────────────────────────────────────────

def _compute_drift_mmd(db: TradeDB, eval_date: str, lookback_days: int = 7) -> float | None:
    """Proxy MMD: compare net_sentiment distribution this week vs last week."""
    try:
        end = date.fromisoformat(eval_date)
        week1_end = end - timedelta(days=lookback_days)

        week1_scores: list[float] = []
        week2_scores: list[float] = []

        for d_offset in range(lookback_days):
            d = end - timedelta(days=d_offset)
            gold_path = (
                Path(db._data_root) / "sentiment" / "gold"
                / f"{d.year:04d}" / f"{d.month:02d}"
                / f"{d.isoformat()}.parquet"
            )
            if gold_path.exists():
                try:
                    df = pd.read_parquet(gold_path)
                    if "net_sentiment" in df.columns:
                        week1_scores.extend(df["net_sentiment"].dropna().tolist())
                except Exception:
                    pass
        for d_offset in range(lookback_days):
            d = week1_end - timedelta(days=d_offset)
            gold_path = (
                Path(db._data_root) / "sentiment" / "gold"
                / f"{d.year:04d}" / f"{d.month:02d}"
                / f"{d.isoformat()}.parquet"
            )
            if gold_path.exists():
                try:
                    df = pd.read_parquet(gold_path)
                    if "net_sentiment" in df.columns:
                        week2_scores.extend(df["net_sentiment"].dropna().tolist())
                except Exception:
                    pass

        if not week1_scores or not week2_scores:
            return None

        s1 = pd.Series(week1_scores)
        s2 = pd.Series(week2_scores)
        mmd_proxy = abs(float(s1.mean()) - float(s2.mean())) + abs(float(s1.std()) - float(s2.std()))
        return round(float(mmd_proxy), 4)
    except Exception as exc:
        logger.debug("MMD drift computation failed: %s", exc)
        return None


# ── Trust vector (public) ──────────────────────────────────────────────────────

def compute_trust_vector(
    db: TradeDB,
    eval_date: str,
    brier_score: float | None,
    drift_mmd: float | None,
) -> dict[str, float]:
    """Compute 7-component Trust vector (EBRT_02 §Trust Vector).

    Components:
        T_fresh    = 1 - max(lag_days) / 7
        T_evidence = mean(reliability) from Evidence for eval_date
        T_model    = clip(rank_ic_5d / 0.05, 0, 1)
        T_calib    = 1 - brier_score
        T_drift    = 1 - clip(drift_mmd / 0.2, 0, 1)
        T_ops      = 1 - pipeline_error_rate (from job_runs)
        T_explain  = fraction of Recommendations with a RecommendationTrace
    """
    T_fresh = 0.5
    try:
        rows = db._conn.execute(
            "SELECT lag_days FROM FreshnessStatus WHERE as_of_date=? AND lag_days IS NOT NULL",
            (eval_date,),
        ).fetchall()
        if rows:
            max_lag = max(float(r[0]) for r in rows)
            T_fresh = max(0.0, 1.0 - max_lag / 7.0)
        else:
            T_fresh = 1.0
    except Exception:
        pass

    T_evidence = 0.5
    try:
        row = db._conn.execute(
            "SELECT AVG(reliability) FROM Evidence WHERE as_of_date=?",
            (eval_date,),
        ).fetchone()
        if row and row[0] is not None:
            T_evidence = float(row[0])
    except Exception:
        pass

    T_model = 0.5
    try:
        rows = db.model_eval_list(eval_date=eval_date, model_name="kg_return_5d")
        if rows:
            rank_ic = rows[0].get("rank_ic")
            if rank_ic is not None:
                T_model = max(0.0, min(1.0, float(rank_ic) / 0.05))
    except Exception:
        pass

    T_calib = 0.5 if brier_score is None else max(0.0, 1.0 - float(brier_score))
    T_drift = 0.5 if drift_mmd is None else max(0.0, 1.0 - min(1.0, float(drift_mmd) / 0.2))

    T_ops = 1.0
    try:
        rows = db._conn.execute(
            "SELECT status FROM job_runs WHERE started_at >= date(?, '-3 days')",
            (eval_date,),
        ).fetchall()
        if rows:
            errors = sum(1 for r in rows if str(r[0]) == "error")
            T_ops = max(0.0, 1.0 - errors / len(rows))
    except Exception:
        pass

    T_explain = 0.5
    try:
        total = db._conn.execute(
            "SELECT COUNT(*) FROM Recommendation WHERE as_of_date=?",
            (eval_date,),
        ).fetchone()[0]
        traced = db._conn.execute(
            "SELECT COUNT(DISTINCT rec_id) FROM RecommendationTrace WHERE as_of_date=?",
            (eval_date,),
        ).fetchone()[0]
        if total and total > 0:
            T_explain = float(traced) / float(total)
    except Exception:
        pass

    return {
        "fresh":    round(T_fresh, 4),
        "evidence": round(T_evidence, 4),
        "model":    round(T_model, 4),
        "calib":    round(T_calib, 4),
        "drift":    round(T_drift, 4),
        "ops":      round(T_ops, 4),
        "explain":  round(T_explain, 4),
    }


def scalar_trust(trust_vec: dict[str, float]) -> float:
    """Collapse 7-component vector to scalar T* via sigmoid of weighted sum.

    Weights: [1.0, 0.8, 1.0, 1.0, 0.8, 0.6, 0.4]
    for [fresh, evidence, model, calib, drift, ops, explain]
    """
    w = [1.0, 0.8, 1.0, 1.0, 0.8, 0.6, 0.4]
    keys = ["fresh", "evidence", "model", "calib", "drift", "ops", "explain"]
    phi = [float(trust_vec.get(k, 0.5)) for k in keys]
    dot = sum(wi * pi for wi, pi in zip(w, phi))
    w_sum = sum(w)
    centred = dot - w_sum / 2.0
    t_star = 1.0 / (1.0 + math.exp(-centred))
    return round(t_star, 4)


# ── Source reliability update ──────────────────────────────────────────────────

def _update_source_reliabilities(db: TradeDB, eval_date: str, lr: float = 0.1) -> int:
    """Update per-source reliability weights using Brier loss from T-5 recommendations."""
    t_minus_5 = (date.fromisoformat(eval_date) - timedelta(days=5)).isoformat()
    recs = db.recommendation_list(t_minus_5)
    if not recs:
        return 0

    source_losses: dict[str, list[float]] = {}
    for r in recs:
        sym = str(r.get("symbol") or "")
        pred_score = float(r.get("score") or 0.5)
        try:
            ep = db._conn.execute(
                "SELECT actual_return_5d FROM event_propagations ep "
                "JOIN market_events me ON ep.event_id = me.event_id "
                "WHERE ep.symbol=? AND me.event_date=? LIMIT 1",
                (sym, t_minus_5),
            ).fetchone()
            if ep and ep[0] is not None:
                actual = 1.0 if float(ep[0]) > 0 else 0.0
                loss = (pred_score - actual) ** 2
                # Find sources linked to this recommendation
                try:
                    ev_rows = db._conn.execute(
                        "SELECT DISTINCT e.evidence_id FROM Evidence e WHERE e.as_of_date=? AND e.symbol=?",
                        (t_minus_5, sym),
                    ).fetchall()
                    # Use symbol as proxy source key if no evidence
                    source_key = f"sym:{sym}" if not ev_rows else f"ev:{len(ev_rows)}"
                    source_losses.setdefault(source_key, []).append(loss)
                except Exception:
                    pass
        except Exception:
            pass

    if not source_losses:
        return 0

    updated = 0
    for source_id, losses in source_losses.items():
        avg_loss = sum(losses) / len(losses)
        try:
            existing = db._conn.execute(
                "SELECT reputation_score FROM InfluenceSignal WHERE source_id=? LIMIT 1",
                (source_id,),
            ).fetchone()
            if existing and existing[0] is not None:
                old_rep = float(existing[0])
                new_rep = max(0.0, min(1.0, old_rep * (1 - lr) + (1 - avg_loss) * lr))
                db._conn.execute(
                    "UPDATE InfluenceSignal SET reputation_score=?, updated_at=datetime('now') WHERE source_id=?",
                    (new_rep, source_id),
                )
                updated += 1
        except Exception:
            pass
    db._conn.commit()
    return updated


# ── QualityReport writer ───────────────────────────────────────────────────────

def write_quality_report(db: TradeDB, eval_date: str, overall_status: str,
                         gate_outcome: Any,
                         model_outcome: Any) -> None:
    """Compute trust vector and write QualityReport row."""
    gate_metrics = gate_outcome.payload.get("metrics", {}) if gate_outcome else {}
    gate_reasons = gate_outcome.payload.get("reasons", []) if gate_outcome else []

    op_status_raw = str(gate_metrics.get("operational_status") or overall_status)
    if op_status_raw in ("ok",):
        operational_status = "ok"
    elif op_status_raw in ("partial", "degraded"):
        operational_status = "degraded"
    else:
        operational_status = "blocked"

    model_rows = model_outcome.payload.get("rows", []) if model_outcome else []
    best_brier: float | None = None
    for mr in model_rows:
        rb = mr.get("risk_brier_score")
        if rb is not None:
            best_brier = float(rb) if best_brier is None else min(best_brier, float(rb))

    rec_brier = _compute_brier_from_recommendations(db, eval_date)
    brier_score = rec_brier if rec_brier is not None else best_brier
    drift_mmd = _compute_drift_mmd(db, eval_date)

    research_ok = (
        (brier_score is None or brier_score < 0.35)
        and (drift_mmd is None or drift_mmd < 0.1)
    )
    research_partial = (
        brier_score is not None and brier_score < 0.35
    ) or (drift_mmd is not None and drift_mmd < 0.2)
    if research_ok:
        research_status = "ok"
    elif research_partial:
        research_status = "partial"
    else:
        research_status = "blocked"

    trust_vec = compute_trust_vector(db, eval_date, brier_score, drift_mmd)
    t_star = scalar_trust(trust_vec)
    trust_vec["T_star"] = t_star

    metrics = {
        "operational_status": operational_status,
        "research_status": research_status,
        "brier_score": brier_score,
        "drift_mmd": drift_mmd,
        "cache_fingerprint": gate_metrics.get("cache_fingerprint", ""),
        "trust_vector": trust_vec,
        "trust_scalar": t_star,
    }

    db.quality_report_upsert(
        eval_date=eval_date,
        operational_status=operational_status,
        research_status=research_status,
        reasons=gate_reasons,
        metrics=metrics,
        brier_score=brier_score,
        drift_mmd=drift_mmd,
    )
    logger.info(
        "QualityReport written: %s op=%s research=%s brier=%s mmd=%s T*=%.3f",
        eval_date, operational_status, research_status, brier_score, drift_mmd, t_star
    )

    try:
        n_updated = _update_source_reliabilities(db, eval_date)
        logger.info("Source reliabilities updated: %d sources", n_updated)
    except Exception as exc:
        logger.warning("Source reliability update failed: %s", exc)
