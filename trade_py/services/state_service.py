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
import json
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
        self._signals_columns: set[str] | None = None

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
        db = self._db or self._open_db()
        as_of = as_of_date
        if not as_of:
            try:
                as_of = db.get_latest_market_asof()
            except Exception:
                as_of = None
        as_of = as_of or date.today().isoformat()

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
            columns = self._signal_columns(db)
            factor_fallback = self._read_factor_fallback(db, symbol)
            if not columns:
                return factor_fallback
            desired = [
                "window_score",
                "event_kg_score",
                "rsi_14",
                "net_sentiment",
                "vol_ratio",
                "macd_signal",
                "event_type",
            ]
            present = [name for name in desired if name in columns]
            with db._conn_lock:
                rows = db._conn.execute(
                    """
                    SELECT {columns}
                    FROM signals
                    WHERE symbol = ? AND date <= ?
                    ORDER BY date DESC LIMIT 5
                    """.format(columns=", ".join(present)),
                    (symbol, as_of),
                ).fetchall()
            if rows:
                latest = rows[0]
                index = {name: pos for pos, name in enumerate(present)}

                def _latest_non_null(idx: int):
                    for row in rows:
                        if row[idx] is not None:
                            return row[idx]
                    return None
                return {
                    "window_score":   latest[index["window_score"]] if "window_score" in index else factor_fallback.get("window_score"),
                    "event_kg_score": _latest_non_null(index["event_kg_score"]) if "event_kg_score" in index else factor_fallback.get("event_kg_score"),
                    "rsi_14":         _latest_non_null(index["rsi_14"]) if "rsi_14" in index else factor_fallback.get("rsi_14"),
                    "net_sentiment":  _latest_non_null(index["net_sentiment"]) if "net_sentiment" in index else factor_fallback.get("net_sentiment"),
                    "vol_ratio":      _latest_non_null(index["vol_ratio"]) if "vol_ratio" in index else factor_fallback.get("vol_ratio"),
                    "macd_signal":    _latest_non_null(index["macd_signal"]) if "macd_signal" in index else factor_fallback.get("macd_signal"),
                    "event_type":     (_latest_non_null(index["event_type"]) or "") if "event_type" in index else "",
                }
        except Exception as exc:
            logger.debug("state_service signals read failed for %s: %s", symbol, exc)
        return self._read_factor_fallback(db, symbol)

    def _signal_columns(self, db) -> set[str]:
        if self._signals_columns is not None:
            return self._signals_columns
        columns: set[str] = set()
        try:
            with db._conn_lock:
                rows = db._conn.execute("PRAGMA table_info(signals)").fetchall()
            columns = {str(row[1]) for row in rows}
        except Exception as exc:
            logger.debug("state_service signal schema read failed: %s", exc)
        self._signals_columns = columns
        return columns

    def _read_factor_fallback(self, db, symbol: str) -> dict[str, Any]:
        """Fallback to latest factor-store values when signals schema is sparse."""
        try:
            factors = db.factor_get_latest(
                symbol,
                [
                    "window_score",
                    "kg_score",
                    "net_sentiment",
                    "tech_rsi_14",
                    "tech_macd_cross",
                    "tech_volume_ratio_5_20",
                ],
            )
            return {
                "window_score": factors.get("window_score"),
                "event_kg_score": factors.get("kg_score"),
                "rsi_14": factors.get("tech_rsi_14"),
                "net_sentiment": factors.get("net_sentiment"),
                "vol_ratio": factors.get("tech_volume_ratio_5_20"),
                "macd_signal": factors.get("tech_macd_cross"),
                "event_type": "",
            }
        except Exception as exc:
            logger.debug("state_service factor fallback failed for %s: %s", symbol, exc)
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
                    SELECT me.event_type, ep.kg_score
                    FROM event_propagations ep
                    JOIN market_events me ON me.event_id = ep.event_id
                    WHERE ep.symbol = ? AND me.event_date <= ?
                    ORDER BY me.event_date DESC, ep.kg_score DESC
                    LIMIT 5
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
        try:
            sig = self._read_signals(db, symbol, as_of)
            if sig.get("event_kg_score") is not None or sig.get("event_type"):
                return {
                    "kg_score": sig.get("event_kg_score"),
                    "top_event_type": str(sig.get("event_type") or ""),
                    "event_count": 1 if sig.get("event_type") or sig.get("event_kg_score") is not None else 0,
                }
        except Exception:
            pass
        return {}

    def _read_freshness(self, db, as_of: str) -> dict[str, Any]:
        """Compute a lightweight freshness score from sync_state."""
        datasets = ["tushare_kline", "tushare_fund_flow", "tushare_fundamental"]
        weights  = [0.50, 0.25, 0.25]
        missing: list[str] = []
        stale:   list[str] = []
        score_acc = 0.0
        try:
            snapshot_row = None
            with db._conn_lock:
                snapshot_row = db._conn.execute(
                    """
                    SELECT eval_date, metadata_json
                    FROM dataset_snapshots
                    WHERE eval_date <= ?
                    ORDER BY eval_date DESC
                    LIMIT 1
                    """,
                    (as_of,),
                ).fetchone()
            snapshot_day = str(snapshot_row["eval_date"]) if snapshot_row else None
            snapshot_meta = {}
            if snapshot_row and snapshot_row["metadata_json"]:
                try:
                    snapshot_meta = json.loads(snapshot_row["metadata_json"])
                except Exception:
                    snapshot_meta = {}
            for ds, w in zip(datasets, weights):
                with db._conn_lock:
                    row = db._conn.execute(
                        "SELECT MAX(last_date) FROM sync_state WHERE source = ?",
                        (ds,),
                    ).fetchone()
                last_date = row[0] if row else None
                if not last_date and ds in {"tushare_fund_flow", "tushare_fundamental"} and snapshot_day:
                    coverage_key = "fund_flow_coverage" if ds == "tushare_fund_flow" else "fundamental_coverage"
                    coverage = snapshot_meta.get(coverage_key)
                    if coverage is not None and float(coverage) > 0:
                        last_date = snapshot_day
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
