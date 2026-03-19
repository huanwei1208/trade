"""EBRTCRUDMixin — CRUD methods for all EBRT tables.

Tables covered:
    ArticleEvent, Evidence, BeliefState, AttentionScore, BeliefTransition,
    Recommendation, RecommendationTrace, QualityReport, FreshnessStatus,
    InfluenceSignal (source reliability)

Mixed into TradeDB via multiple inheritance.  All methods rely on
``self._conn`` and ``self._conn_lock`` provided by TradeDB.__init__.
"""
from __future__ import annotations

import json
from typing import Any

from trade_py.db._utils import _json_loads_safe


class EBRTCRUDMixin:
    """EBRT-domain CRUD operations."""

    # ── EBRT: ArticleEvent ─────────────────────────────────────────────────────

    def article_event_upsert(self, article_id: str, published_at: str, source_id: str,
                              symbol: str, extractor: str, extractor_conf: float,
                              **kwargs: Any) -> None:
        cols = ["article_id", "published_at", "source_id", "symbol", "extractor", "extractor_conf"]
        vals: list[Any] = [article_id, published_at, source_id, symbol, extractor, extractor_conf]
        optional = ["feed_name", "url", "title", "event_type", "event_magnitude",
                    "sentiment_score", "sentiment_label", "policy_signal",
                    "entity_density", "novelty_score", "noise_score"]
        for col in optional:
            if col in kwargs:
                cols.append(col)
                vals.append(kwargs[col])
        placeholders = ",".join("?" * len(vals))
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "article_id")
        with self._conn_lock:
            self._conn.execute(
                f"INSERT INTO ArticleEvent ({','.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(article_id) DO UPDATE SET {updates}",
                vals,
            )
            self._conn.commit()

    def article_event_list(self, symbol: str, as_of_date: str,
                            lookback_days: int = 3) -> list[dict]:
        from datetime import date as _date, timedelta
        try:
            start = (_date.fromisoformat(as_of_date) - timedelta(days=lookback_days)).isoformat()
        except Exception:
            start = as_of_date
        with self._conn_lock:
            rows = self._conn.execute(
                "SELECT * FROM ArticleEvent WHERE symbol=? AND published_at>=? AND published_at<=? "
                "ORDER BY published_at DESC",
                (symbol, start, as_of_date),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── EBRT: Evidence ─────────────────────────────────────────────────────────

    def evidence_upsert(self, evidence_id: str, as_of_date: str, symbol: str,
                         evidence_type: str, payload_ref: str,
                         strength: float, direction: float, reliability: float,
                         novelty: float, noise_penalty: float,
                         influence_boost: float) -> None:
        with self._conn_lock:
            self._conn.execute(
                "INSERT INTO Evidence "
                "(evidence_id, as_of_date, symbol, evidence_type, payload_ref, "
                " strength, direction, reliability, novelty, noise_penalty, influence_boost) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(as_of_date, symbol, evidence_type, payload_ref) DO UPDATE SET "
                "strength=excluded.strength, direction=excluded.direction, "
                "reliability=excluded.reliability, novelty=excluded.novelty, "
                "noise_penalty=excluded.noise_penalty, influence_boost=excluded.influence_boost",
                (evidence_id, as_of_date, symbol, evidence_type, payload_ref,
                 strength, direction, reliability, novelty, noise_penalty, influence_boost),
            )
            self._conn.commit()

    def evidence_list(self, symbol: str, as_of_date: str,
                       lookback_days: int = 3) -> list[dict]:
        from datetime import date as _date, timedelta
        try:
            start = (_date.fromisoformat(as_of_date) - timedelta(days=lookback_days)).isoformat()
        except Exception:
            start = as_of_date
        with self._conn_lock:
            rows = self._conn.execute(
                "SELECT * FROM Evidence WHERE symbol=? AND as_of_date>=? AND as_of_date<=? "
                "ORDER BY as_of_date DESC, strength DESC",
                (symbol, start, as_of_date),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── EBRT: BeliefState ──────────────────────────────────────────────────────

    def belief_state_upsert(self, as_of_date: str, symbol: str,
                             belief_vec: dict, belief_version: str,
                             confidence: float, uncertainty: float) -> None:
        with self._conn_lock:
            self._conn.execute(
                "INSERT INTO BeliefState "
                "(as_of_date, symbol, belief_vec_json, belief_version, confidence, uncertainty) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(as_of_date, symbol) DO UPDATE SET "
                "belief_vec_json=excluded.belief_vec_json, "
                "belief_version=excluded.belief_version, "
                "confidence=excluded.confidence, uncertainty=excluded.uncertainty, "
                "updated_at=CURRENT_TIMESTAMP",
                (as_of_date, symbol, json.dumps(belief_vec, ensure_ascii=False),
                 belief_version, confidence, uncertainty),
            )
            self._conn.commit()

    def belief_state_get(self, as_of_date: str, symbol: str) -> dict | None:
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT * FROM BeliefState WHERE as_of_date=? AND symbol=?",
                (as_of_date, symbol),
            ).fetchone()
        if row is None:
            return None
        r = dict(row)
        r["belief_vec"] = _json_loads_safe(r.get("belief_vec_json"), {})
        return r

    def belief_state_get_prev(self, before_date: str, symbol: str) -> dict | None:
        """Get the most recent BeliefState before before_date for a symbol."""
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT * FROM BeliefState WHERE symbol=? AND as_of_date<? "
                "ORDER BY as_of_date DESC LIMIT 1",
                (symbol, before_date),
            ).fetchone()
        if row is None:
            return None
        r = dict(row)
        r["belief_vec"] = _json_loads_safe(r.get("belief_vec_json"), {})
        return r

    def belief_state_list_date(self, as_of_date: str) -> list[dict]:
        with self._conn_lock:
            rows = self._conn.execute(
                "SELECT * FROM BeliefState WHERE as_of_date=? ORDER BY symbol",
                (as_of_date,),
            ).fetchall()
        result = []
        for row in rows:
            r = dict(row)
            r["belief_vec"] = _json_loads_safe(r.get("belief_vec_json"), {})
            result.append(r)
        return result

    # ── EBRT: AttentionScore ───────────────────────────────────────────────────

    def attention_upsert_batch(self, records: list[dict]) -> None:
        """Insert/replace attention score records in bulk."""
        with self._conn_lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO AttentionScore "
                "(attention_id, as_of_date, symbol, evidence_id, logit, weight, factors_json) "
                "VALUES (:attention_id, :as_of_date, :symbol, :evidence_id, "
                " :logit, :weight, :factors_json)",
                records,
            )
            self._conn.commit()

    def attention_list(self, symbol: str, as_of_date: str,
                        top_n: int = 10) -> list[dict]:
        with self._conn_lock:
            rows = self._conn.execute(
                "SELECT * FROM AttentionScore WHERE symbol=? AND as_of_date=? "
                "ORDER BY weight DESC LIMIT ?",
                (symbol, as_of_date, top_n),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── EBRT: BeliefTransition ─────────────────────────────────────────────────

    def belief_transition_insert(self, transition_id: str, symbol: str,
                                   t_date: str, t1_date: str,
                                   prev_belief_ref: str, next_belief_ref: str,
                                   delta_vec: dict, decay_lambda: float,
                                   gain_eta: float, conflict_score: float,
                                   attention_set_id: str) -> None:
        with self._conn_lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO BeliefTransition "
                "(transition_id, symbol, t_date, t1_date, prev_belief_ref, next_belief_ref, "
                " delta_vec_json, decay_lambda, gain_eta, conflict_score, attention_set_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (transition_id, symbol, t_date, t1_date, prev_belief_ref, next_belief_ref,
                 json.dumps(delta_vec, ensure_ascii=False),
                 decay_lambda, gain_eta, conflict_score, attention_set_id),
            )
            self._conn.commit()

    def belief_transition_get(self, symbol: str, t1_date: str) -> dict | None:
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT * FROM BeliefTransition WHERE symbol=? AND t1_date=? "
                "ORDER BY created_at DESC LIMIT 1",
                (symbol, t1_date),
            ).fetchone()
        if row is None:
            return None
        r = dict(row)
        r["delta_vec"] = _json_loads_safe(r.get("delta_vec_json"), {})
        return r

    # ── EBRT: Recommendation ──────────────────────────────────────────────────

    def recommendation_upsert(self, rec_id: str, as_of_date: str, symbol: str,
                                action: str, conviction: str,
                                score: float, risk: float, horizon_days: int,
                                reasons: dict | list,
                                expected_return_5d: float | None = None,
                                risk_5pct: float | None = None,
                                position_weight: float | None = None,
                                horizon_set: dict | None = None) -> None:
        with self._conn_lock:
            self._conn.execute(
                "INSERT INTO Recommendation "
                "(rec_id, as_of_date, symbol, action, conviction, score, risk, "
                " horizon_days, reasons_json, expected_return_5d, risk_5pct, "
                " position_weight, horizon_set_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(as_of_date, symbol) DO UPDATE SET "
                "rec_id=excluded.rec_id, action=excluded.action, "
                "conviction=excluded.conviction, score=excluded.score, "
                "risk=excluded.risk, horizon_days=excluded.horizon_days, "
                "reasons_json=excluded.reasons_json, "
                "expected_return_5d=excluded.expected_return_5d, "
                "risk_5pct=excluded.risk_5pct, "
                "position_weight=excluded.position_weight, "
                "horizon_set_json=excluded.horizon_set_json, "
                "created_at=CURRENT_TIMESTAMP",
                (rec_id, as_of_date, symbol, action, conviction, score, risk,
                 horizon_days, json.dumps(reasons, ensure_ascii=False),
                 expected_return_5d, risk_5pct, position_weight,
                 json.dumps(horizon_set, ensure_ascii=False) if horizon_set is not None else None),
            )
            self._conn.commit()

    def recommendation_list(self, as_of_date: str,
                             action: str | None = None) -> list[dict]:
        with self._conn_lock:
            if action:
                rows = self._conn.execute(
                    "SELECT * FROM Recommendation WHERE as_of_date=? AND action=? "
                    "ORDER BY score DESC",
                    (as_of_date, action),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM Recommendation WHERE as_of_date=? ORDER BY score DESC",
                    (as_of_date,),
                ).fetchall()
        result = []
        for row in rows:
            r = dict(row)
            r["reasons"] = _json_loads_safe(r.get("reasons_json"), [])
            r["horizon_set"] = _json_loads_safe(r.get("horizon_set_json"), {})
            result.append(r)
        return result

    # ── EBRT: RecommendationTrace ─────────────────────────────────────────────

    def recommendation_trace_upsert(self, trace_id: str, as_of_date: str,
                                     symbol: str, rec_id: str,
                                     top_evidence: list, data_fingerprint: str,
                                     belief_transition_id: str | None = None,
                                     model_versions: dict | None = None,
                                     trust_json: dict | None = None,
                                     narrative_text: str | None = None) -> None:
        with self._conn_lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO RecommendationTrace "
                "(trace_id, as_of_date, symbol, rec_id, belief_transition_id, "
                " top_evidence_json, model_versions_json, data_fingerprint, "
                " trust_json, narrative_text) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (trace_id, as_of_date, symbol, rec_id, belief_transition_id,
                 json.dumps(top_evidence, ensure_ascii=False),
                 json.dumps(model_versions or {}, ensure_ascii=False),
                 data_fingerprint,
                 json.dumps(trust_json, ensure_ascii=False) if trust_json is not None else None,
                 narrative_text),
            )
            self._conn.commit()

    # ── EBRT: QualityReport ───────────────────────────────────────────────────

    def quality_report_upsert(self, eval_date: str, operational_status: str,
                                research_status: str, reasons: dict | list,
                                metrics: dict,
                                brier_score: float | None = None,
                                drift_mmd: float | None = None,
                                calibration: dict | None = None) -> None:
        with self._conn_lock:
            self._conn.execute(
                "INSERT INTO QualityReport "
                "(eval_date, operational_status, research_status, brier_score, "
                " calibration_json, drift_mmd, reasons_json, metrics_json) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(eval_date) DO UPDATE SET "
                "operational_status=excluded.operational_status, "
                "research_status=excluded.research_status, "
                "brier_score=excluded.brier_score, "
                "calibration_json=excluded.calibration_json, "
                "drift_mmd=excluded.drift_mmd, "
                "reasons_json=excluded.reasons_json, "
                "metrics_json=excluded.metrics_json",
                (eval_date, operational_status, research_status, brier_score,
                 json.dumps(calibration or {}, ensure_ascii=False),
                 drift_mmd,
                 json.dumps(reasons, ensure_ascii=False),
                 json.dumps(metrics, ensure_ascii=False)),
            )
            self._conn.commit()

    def quality_report_get(self, eval_date: str) -> dict | None:
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT * FROM QualityReport WHERE eval_date=?",
                (eval_date,),
            ).fetchone()
        if row is None:
            return None
        r = dict(row)
        r["reasons"] = _json_loads_safe(r.get("reasons_json"), {})
        r["metrics"] = _json_loads_safe(r.get("metrics_json"), {})
        return r

    def quality_report_latest(self) -> dict | None:
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT * FROM QualityReport ORDER BY eval_date DESC LIMIT 1",
            ).fetchone()
        if row is None:
            return None
        r = dict(row)
        r["reasons"] = _json_loads_safe(r.get("reasons_json"), {})
        r["metrics"] = _json_loads_safe(r.get("metrics_json"), {})
        return r

    # ── EBRT: FreshnessStatus ─────────────────────────────────────────────────

    def freshness_status_upsert_batch(self, as_of_date: str,
                                       records: list[dict]) -> None:
        """Upsert freshness status for multiple datasets at once."""
        with self._conn_lock:
            self._conn.executemany(
                "INSERT INTO FreshnessStatus "
                "(as_of_date, dataset, freshness_date, lag_days, coverage_pct, "
                " status, details_json) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(as_of_date, dataset) DO UPDATE SET "
                "freshness_date=excluded.freshness_date, lag_days=excluded.lag_days, "
                "coverage_pct=excluded.coverage_pct, status=excluded.status, "
                "details_json=excluded.details_json, updated_at=CURRENT_TIMESTAMP",
                [
                    (as_of_date,
                     r["dataset"],
                     r.get("freshness_date"),
                     r.get("lag_days"),
                     r.get("coverage_pct"),
                     r.get("status", "unknown"),
                     json.dumps(r.get("details") or {}, ensure_ascii=False))
                    for r in records
                ],
            )
            self._conn.commit()

    def freshness_status_list(self, as_of_date: str) -> list[dict]:
        with self._conn_lock:
            rows = self._conn.execute(
                "SELECT * FROM FreshnessStatus WHERE as_of_date=? ORDER BY dataset",
                (as_of_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── EBRT: Source Reliability (InfluenceSignal) ─────────────────────────────

    def source_reliability_upsert(self, source_id: str,
                                   reliability: float,
                                   eval_date: str) -> None:
        """Update reputation_score for a source in InfluenceSignal (most recent row)."""
        with self._conn_lock:
            self._conn.execute(
                "UPDATE InfluenceSignal SET reputation_score=? "
                "WHERE source_id=? AND published_at=("
                "  SELECT MAX(published_at) FROM InfluenceSignal WHERE source_id=?"
                ")",
                (round(reliability, 6), source_id, source_id),
            )
            self._conn.commit()

    def source_reliability_get(self, source_id: str) -> float:
        """Return the most recent reputation_score for a source (default 0.5)."""
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT reputation_score FROM InfluenceSignal "
                "WHERE source_id=? ORDER BY published_at DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        if row is None or row[0] is None:
            return 0.5
        return float(row[0])
