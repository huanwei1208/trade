"""ExplanationService — builds DecisionExplanation + kline context.

Orchestrates the full explain path for a symbol:
  1. StateService  → WorldState
  2. DecisionService → ScenarioSummary + ActionDecision
  3. Trust (from InferenceService) → TrustBreakdown
  4. build_explanation() → DecisionExplanation

Also provides `build_kline_context()` so that /api/kline/{symbol} can
call a service instead of embedding business logic in the route handler.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class ExplanationService:
    """Build DecisionExplanation and kline context for a symbol.

    Parameters
    ----------
    state_svc : StateService
    decision_svc : DecisionService
    inference
        Optional InferenceService for trust enrichment.
    """

    def __init__(self, state_svc, decision_svc, inference=None) -> None:
        self._state_svc    = state_svc
        self._decision_svc = decision_svc
        self._inference    = inference

    # ── Public API ────────────────────────────────────────────────────────────

    def explain(
        self,
        symbol: str,
        *,
        as_of_date: str | None = None,
        has_position: bool = False,
        raw_reasons: list[dict] | None = None,
    ):
        """Return a DecisionExplanation for *symbol*.

        Returns the DecisionExplanation dataclass; call `.to_dict()` for JSON.
        """
        from trade_py.decision.explanation import build_explanation

        db = self._state_svc._db or self._state_svc._open_db()
        as_of = as_of_date
        if not as_of:
            try:
                as_of = db.get_latest_market_asof()
            except Exception:
                as_of = None
        as_of = as_of or date.today().isoformat()

        # 1. WorldState
        trust_score, trust_breakdown = self._get_trust(symbol)
        ws = self._state_svc.build(symbol, as_of_date=as_of, trust_score=trust_score)

        # 2. Scenario + Action
        scenario, action = self._decision_svc.decide(ws, has_position=has_position)

        # 3. Build explanation
        exp = build_explanation(
            ws,
            action,
            trust_breakdown=trust_breakdown,
            scenario=scenario,
            raw_reasons=raw_reasons,
        )
        return exp

    def build_kline_context(
        self,
        symbol: str,
        *,
        days: int = 60,
        as_of_date: str | None = None,
        db=None,
        data_root: str = "data",
    ) -> dict[str, Any]:
        """Return kline enrichment payload for /api/kline/{symbol}.

        Reads OHLCV from the kline parquet files, computes indicators,
        then appends:
        - belief_overlay (from BeliefState history)
        - prediction block (from InferenceService)
        - recommendation context (from Recommendation table)
        - world_state summary
        - action_decision summary

        The format matches what the frontend expects.
        """
        import math

        _db = db or self._state_svc._open_db()
        as_of = as_of_date
        if not as_of:
            try:
                as_of = _db.get_latest_market_asof()
            except Exception:
                as_of = None
        as_of = as_of or date.today().isoformat()
        today = as_of

        # ── OHLCV + technical indicators ──────────────────────────────────────
        ohlcv_rows, indicators_meta = self._read_ohlcv(data_root, symbol, days, end_date=as_of)

        # ── Event markers ─────────────────────────────────────────────────────
        event_markers = self._read_event_markers(_db, symbol, days, today)

        # ── Belief overlay ────────────────────────────────────────────────────
        belief_overlay = self._read_belief_overlay(_db, symbol, days, today)

        # ── Prediction from inference ─────────────────────────────────────────
        prediction: dict[str, Any] = {}
        try:
            if self._inference is not None:
                pred_map = self._inference.predict([symbol])
                prediction = pred_map.get(symbol) or {}
        except Exception:
            pass

        # ── World state + action summary ──────────────────────────────────────
        try:
            ws = self._state_svc.build(symbol, as_of_date=as_of)
            _, action_decision = self._decision_svc.decide(ws)
            state_summary = ws.to_dict()
            action_summary = action_decision.to_dict()
        except Exception as exc:
            logger.debug("kline_context: state/decision failed for %s: %s", symbol, exc)
            state_summary = {}
            action_summary = {}

        # ── Recommendation context ─────────────────────────────────────────────
        rec_context = self._read_recommendation(_db, symbol, today)

        return {
            "symbol":         symbol,
            "as_of":          as_of,
            "ohlcv":          ohlcv_rows,
            "indicators":     indicators_meta,
            "event_markers":  event_markers,
            "belief_overlay": belief_overlay,
            "prediction":     prediction,
            "world_state":    state_summary,
            "action":         action_summary,
            "recommendation": rec_context,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_trust(self, symbol: str) -> tuple[float | None, Any]:
        """Return (trust_score, TrustBreakdown | None) from inference layer."""
        if self._inference is None:
            return None, None
        try:
            pred_map = self._inference.predict([symbol])
            p = pred_map.get(symbol) or {}
            trust_dict = p.get("trust") or {}
            score = trust_dict.get("trust_score")
            # Reconstruct a TrustBreakdown if possible
            try:
                from trade_py.trust.breakdown import TrustBreakdown
                tb = TrustBreakdown(
                    trust_score=float(trust_dict.get("trust_score", 0.5)),
                    trust_level=str(trust_dict.get("trust_level", "MEDIUM")),
                    feature_coverage=float(trust_dict.get("feature_coverage", 0.5)),
                    data_freshness_score=float(trust_dict.get("data_freshness_score", 1.0)),
                    warnings=list(trust_dict.get("warnings", [])),
                )
                return score, tb
            except Exception:
                return score, None
        except Exception:
            return None, None

    def _read_ohlcv(
        self, data_root: str, symbol: str, days: int, *, end_date: str | None = None
    ) -> tuple[list[dict], dict[str, Any]]:
        """Read OHLCV rows from kline parquet for the last *days* trading days."""
        try:
            from trade_py.data.access import DataGateway
            resolved_end = date.fromisoformat(end_date) if end_date else date.today()
            gateway = DataGateway(data_root)
            df, _report = gateway.get_kline(symbol, lookback_bars=max(days, 60), end_date=resolved_end)
            df = df.tail(days)
            rows = df.to_dict(orient="records") if not df.empty else []
            meta: dict[str, Any] = {
                "rows": len(rows),
                "start": rows[0].get("date") if rows else None,
                "end":   rows[-1].get("date") if rows else None,
            }
            return rows, meta
        except Exception as exc:
            logger.debug("kline_context: ohlcv read failed for %s: %s", symbol, exc)
            return [], {}

    def _read_event_markers(
        self, db, symbol: str, days: int, as_of: str
    ) -> list[dict[str, Any]]:
        """Read recent market_events for event markers overlay."""
        markers: list[dict[str, Any]] = []
        try:
            cutoff = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
            with db._conn_lock:
                rows = db._conn.execute(
                    """
                    SELECT me.event_date, me.event_type, ep.kg_score, me.summary
                    FROM event_propagations ep
                    JOIN market_events me ON me.event_id = ep.event_id
                    WHERE ep.symbol = ? AND me.event_date >= ? AND me.event_date <= ?
                    ORDER BY me.event_date, ep.kg_score DESC
                    LIMIT 24
                    """,
                    (symbol, cutoff, as_of),
                ).fetchall()
            for r in rows:
                markers.append({
                    "date":       r[0],
                    "event_type": r[1],
                    "kg_score":   round(float(r[2] or 0.0), 4),
                    "title":      r[3] or "",
                })
        except Exception as exc:
            logger.debug("kline_context: event markers read failed for %s: %s", symbol, exc)
        return markers

    def _read_belief_overlay(
        self, db, symbol: str, days: int, today: str
    ) -> list[dict[str, Any]]:
        """Read belief_state history for overlay chart."""
        overlay: list[dict[str, Any]] = []
        try:
            cur = date.fromisoformat(today)
            for _ in range(days):
                dstr = cur.isoformat()
                row = db.belief_state_get(dstr, symbol)
                if row:
                    bv = row.get("belief_vec") or {}
                    overlay.append({
                        "date":  dstr,
                        "mu":    round(float(bv.get("mu", 0.0)), 4),
                        "sigma": round(float(bv.get("sigma", 0.3)), 4),
                    })
                cur -= timedelta(days=1)
            overlay.sort(key=lambda x: x["date"])
        except Exception as exc:
            logger.debug("kline_context: belief overlay read failed for %s: %s", symbol, exc)
        return overlay

    def _read_recommendation(
        self, db, symbol: str, as_of: str
    ) -> dict[str, Any]:
        """Read latest Recommendation row for the symbol."""
        try:
            with db._conn_lock:
                row = db._conn.execute(
                    """
                    SELECT as_of_date, action, conviction, score, expected_return_5d,
                           confidence_interval_low, confidence_interval_high
                    FROM Recommendation
                    WHERE symbol = ? AND as_of_date <= ?
                    ORDER BY as_of_date DESC LIMIT 1
                    """,
                    (symbol, as_of),
                ).fetchone()
            if row:
                return {
                    "as_of_date":              row[0],
                    "action":                  row[1],
                    "conviction":              row[2],
                    "score":                   round(float(row[3] or 0.0), 4),
                    "expected_return_5d":       round(float(row[4] or 0.0), 4),
                    "confidence_interval_low":  row[5],
                    "confidence_interval_high": row[6],
                }
        except Exception as exc:
            logger.debug("kline_context: recommendation read failed for %s: %s", symbol, exc)
        return {}
