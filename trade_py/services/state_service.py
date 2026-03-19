"""StateService — assembles WorldState for a symbol from DB + factor context.

Responsibilities:
- Query DB for belief, signals, events, kline-derived technicals
- Build FreshnessReport via sync_state
- Compute TrustBreakdown (or load from inference layer)
- Delegate regime inference to build_world_state()

All DB reads are read-only.  No writes happen here.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from trade_py.decision.world_state import WorldState, build_world_state

logger = logging.getLogger(__name__)


class StateService:
    """Build a WorldState for a symbol on a given date.

    Parameters
    ----------
    data_root : str
        Root data directory (same as TRADE_DATA_ROOT).
    db
        Optional pre-opened TradeDB instance.  If omitted, a new one is
        opened on every call (suitable for request-scoped usage).
    """

    def __init__(self, data_root: str = "data", db=None) -> None:
        self._data_root = data_root
        self._db = db

    # ── Public API ────────────────────────────────────────────────────────────

    def build(
        self,
        symbol: str,
        *,
        as_of_date: str | None = None,
        trust_score: float | None = None,
    ) -> WorldState:
        """Return a WorldState for *symbol* on *as_of_date* (defaults today).

        Reads:
        - signals table  → window_score, event_kg_score, rsi_14, net_sentiment
        - belief_state   → belief_mu, belief_sigma
        - sync_state     → freshness per dataset
        - market_events  → recent event count + top event type
        """
        as_of = as_of_date or date.today().isoformat()
        db = self._db or self._open_db()

        # ── Signals row ───────────────────────────────────────────────────────
        sig = self._read_signals(db, symbol, as_of)

        # ── Belief state ──────────────────────────────────────────────────────
        belief = self._read_belief(db, symbol, as_of)

        # ── Event state ───────────────────────────────────────────────────────
        event_info = self._read_events(db, symbol, as_of)

        # ── Freshness / data quality ──────────────────────────────────────────
        freshness = self._read_freshness(db, as_of)

        # ── Trust score ───────────────────────────────────────────────────────
        effective_trust = trust_score
        if effective_trust is None:
            # Derive from freshness if not externally provided
            effective_trust = freshness.get("score", 0.5)

        ws = build_world_state(
            symbol=symbol,
            as_of_date=as_of,
            window_score=sig.get("window_score"),
            vol_ratio=sig.get("vol_ratio"),
            kg_score=event_info.get("kg_score"),
            top_event_type=event_info.get("top_event_type", ""),
            event_count=event_info.get("event_count", 0),
            belief_mu=belief.get("belief_mu"),
            net_sentiment=sig.get("net_sentiment"),
            belief_sigma=belief.get("belief_sigma"),
            rsi_14=sig.get("rsi_14"),
            macd_signal=sig.get("macd_signal"),
            trust_score=effective_trust,
            freshness_score=freshness.get("score"),
            freshness_missing=freshness.get("missing", []),
            freshness_stale=freshness.get("stale", []),
        )
        return ws

    # ── Private helpers ───────────────────────────────────────────────────────

    def _open_db(self):
        from trade_py.db.trade_db import TradeDB
        return TradeDB(self._data_root)

    def _read_signals(self, db, symbol: str, as_of: str) -> dict[str, Any]:
        """Read the most recent signals row for (symbol, as_of)."""
        try:
            with db._conn_lock:
                row = db._conn.execute(
                    """
                    SELECT window_score, event_kg_score, rsi_14, net_sentiment,
                           vol_ratio, macd_signal
                    FROM signals
                    WHERE symbol = ? AND date <= ?
                    ORDER BY date DESC LIMIT 1
                    """,
                    (symbol, as_of),
                ).fetchone()
            if row:
                return {
                    "window_score":   row[0],
                    "event_kg_score": row[1],
                    "rsi_14":         row[2],
                    "net_sentiment":  row[3],
                    "vol_ratio":      row[4],
                    "macd_signal":    row[5],
                }
        except Exception as exc:
            logger.debug("state_service signals read failed for %s: %s", symbol, exc)
        return {}

    def _read_belief(self, db, symbol: str, as_of: str) -> dict[str, Any]:
        """Read belief_state for (symbol, as_of) via TradeDB helper."""
        try:
            row = db.belief_state_get(as_of, symbol)
            if row:
                bv = row.get("belief_vec") or {}
                return {
                    "belief_mu":    bv.get("mu"),
                    "belief_sigma": bv.get("sigma"),
                }
        except Exception as exc:
            logger.debug("state_service belief read failed for %s: %s", symbol, exc)
        return {}

    def _read_events(self, db, symbol: str, as_of: str) -> dict[str, Any]:
        """Read recent market_events for the symbol."""
        try:
            with db._conn_lock:
                rows = db._conn.execute(
                    """
                    SELECT event_type, kg_score
                    FROM market_events
                    WHERE symbol = ? AND event_date <= ?
                    ORDER BY event_date DESC LIMIT 5
                    """,
                    (symbol, as_of),
                ).fetchall()
            if rows:
                top_type = rows[0][0] or ""
                # Average kg_score across recent events
                scores = [float(r[1]) for r in rows if r[1] is not None]
                kg_score = sum(scores) / len(scores) if scores else None
                return {
                    "kg_score":       kg_score,
                    "top_event_type": top_type,
                    "event_count":    len(rows),
                }
        except Exception as exc:
            logger.debug("state_service events read failed for %s: %s", symbol, exc)
        return {}

    def _read_freshness(self, db, as_of: str) -> dict[str, Any]:
        """Compute a lightweight freshness score from sync_state."""
        datasets = ["tushare_kline", "tushare_fund_flow", "tushare_fundamental"]
        weights  = [0.50, 0.25, 0.25]
        missing: list[str] = []
        stale:   list[str] = []
        score_acc = 0.0
        try:
            for ds, w in zip(datasets, weights):
                with db._conn_lock:
                    row = db._conn.execute(
                        "SELECT MAX(last_date) FROM sync_state WHERE dataset = ?",
                        (ds,),
                    ).fetchone()
                last_date = row[0] if row else None
                if not last_date:
                    missing.append(ds)
                    continue
                from datetime import date as _date
                try:
                    lag = (_date.fromisoformat(as_of) - _date.fromisoformat(last_date)).days
                except ValueError:
                    lag = 99
                if lag > 7:
                    stale.append(ds)
                    score_acc += max(0.0, 1.0 - lag * 0.10) * w
                else:
                    score_acc += max(0.0, 1.0 - lag * 0.05) * w
        except Exception as exc:
            logger.debug("state_service freshness read failed: %s", exc)
            return {"score": 0.5, "missing": [], "stale": []}

        total_w = sum(w for ds, w in zip(datasets, weights) if ds not in missing)
        if total_w > 0:
            score = score_acc / total_w
        else:
            score = 0.0

        return {
            "score":   round(min(1.0, max(0.0, score)), 4),
            "missing": missing,
            "stale":   stale,
        }
