"""BeliefEngine — daily belief state update pipeline.

Flow for each symbol with evidence:
  1. b_prev = db.belief_state_get_prev(yesterday, symbol) or cold_start
  2. evidence_list = collect from ArticleEvent + Gold + market_events
  3. logits = attention.compute_logits(evidence_list, b_prev)
  4. weights = softmax already in logits output
  5. delta_vec = Σ(w_i × Δ(e_i))
  6. conflict_score, conflict_details = conflict.detect_conflict(...)
  7. gain η = compute_gain_eta(trust_gate, drift, mean_reliability)
  8. b_new = residual_update(b_prev, weighted_evidence, decay_lambda, gain_eta)
  9. db.belief_state_upsert(today, symbol, b_new, ...)
 10. db.attention_upsert_batch(top-10 attention records)
 11. db.belief_transition_insert(...)

Market-level beliefs (_MARKET_) also written using regulatory tone + macro signals.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trade_py.belief.attention import compute_logits
from trade_py.belief.update import (
    cold_start_belief, compute_gain_eta, residual_update,
    DECAY_LAMBDA, GAIN_ETA_0, BELIEF_VERSION,
)
from trade_py.belief.conflict import detect_conflict

if TYPE_CHECKING:
    from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

_TRUST_GATE_DEFAULT = 1.0
_DRIFT_DEFAULT = 0.0


class BeliefEngine:
    """Runs the daily belief update pipeline."""

    def __init__(self, db: "TradeDB") -> None:
        self._db = db

    def run(self, asof_date: str, data_root: str) -> dict[str, Any]:
        """Run belief updates for all symbols with evidence on asof_date.

        Returns summary dict with counts.
        """
        db = self._db
        data_path = Path(data_root)
        today = asof_date
        try:
            yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        except Exception:
            yesterday = today

        # Collect symbols with evidence (from Gold parquet if available)
        symbols = self._collect_symbols(data_path, today)
        if not symbols:
            logger.info("belief_engine: no symbols with evidence for %s", today)

        # Get trust gate from latest QualityReport
        trust_gate = _TRUST_GATE_DEFAULT
        drift = _DRIFT_DEFAULT
        try:
            qr = db.quality_report_latest()
            if qr:
                trust_gate = 1.0 if qr.get("operational_status") == "ok" else 0.7
                drift = float(qr.get("metrics", {}).get("drift_mmd") or 0.0)
        except Exception:
            pass

        updated = 0
        skipped = 0
        errors = 0

        for symbol in symbols:
            try:
                self._update_symbol(
                    symbol=symbol,
                    today=today,
                    yesterday=yesterday,
                    data_path=data_path,
                    trust_gate=trust_gate,
                    drift=drift,
                )
                updated += 1
            except Exception as exc:
                logger.warning("belief_engine: symbol=%s error=%s", symbol, exc)
                errors += 1

        # Market-level belief (_MARKET_)
        try:
            self._update_market(today=today, yesterday=yesterday,
                                data_path=data_path, trust_gate=trust_gate)
        except Exception as exc:
            logger.warning("belief_engine: market belief error=%s", exc)

        summary = {
            "asof_date": today,
            "symbols_updated": updated,
            "symbols_skipped": skipped,
            "errors": errors,
            "trust_gate": trust_gate,
        }
        logger.info("belief_engine done: %s", summary)
        return summary

    def _collect_symbols(self, data_path: Path, today: str) -> list[str]:
        """Collect symbols that have Gold sentiment data for today."""
        symbols: set[str] = set()

        # From Gold parquet
        try:
            from datetime import date as _date
            d = _date.fromisoformat(today)
            gold_path = (
                data_path / "sentiment" / "gold"
                / f"{d.year:04d}" / f"{d.month:02d}"
                / f"{today}.parquet"
            )
            if gold_path.exists():
                import pandas as pd
                df = pd.read_parquet(gold_path)
                if "symbol" in df.columns:
                    symbols.update(df["symbol"].dropna().unique().tolist())
        except Exception as exc:
            logger.debug("belief_engine: could not read gold for %s: %s", today, exc)

        # From ArticleEvent table
        try:
            rows = self._db._conn.execute(
                "SELECT DISTINCT symbol FROM ArticleEvent WHERE published_at LIKE ?",
                (f"{today}%",),
            ).fetchall()
            symbols.update(r[0] for r in rows if r[0])
        except Exception:
            pass

        # From market_events
        try:
            rows = self._db._conn.execute(
                "SELECT DISTINCT entity_id FROM market_events WHERE event_date=?",
                (today,),
            ).fetchall()
            symbols.update(r[0] for r in rows if r[0] and r[0] != "_MARKET_")
        except Exception:
            pass

        return sorted(symbols)

    def _build_evidence_list(
        self,
        symbol: str,
        today: str,
        data_path: Path,
    ) -> list[dict[str, Any]]:
        """Build Evidence rows for a symbol on today from multiple sources."""
        db = self._db
        evidence: list[dict[str, Any]] = []

        # 1. From Gold sentiment (most trusted)
        try:
            from datetime import date as _date
            d = _date.fromisoformat(today)
            gold_path = (
                data_path / "sentiment" / "gold"
                / f"{d.year:04d}" / f"{d.month:02d}"
                / f"{today}.parquet"
            )
            if gold_path.exists():
                import pandas as pd
                df = pd.read_parquet(gold_path)
                if "symbol" in df.columns:
                    sym_rows = df[df["symbol"] == symbol]
                    for _, row in sym_rows.iterrows():
                        ev_id = f"gold:{symbol}:{today}"
                        mag = float(row.get("event_magnitude") or 0.0)
                        sent = float(row.get("net_sentiment") or row.get("sentiment_score") or 0.0)
                        strength = abs(mag) * abs(sent) if mag != 0 else abs(sent)
                        direction = 1.0 if sent >= 0 else -1.0
                        sig_strength = float(row.get("signal_strength") or 0.5)
                        ev = {
                            "evidence_id": ev_id,
                            "as_of_date": today,
                            "symbol": symbol,
                            "evidence_type": "sentiment_gold",
                            "payload_ref": ev_id,
                            "strength": min(1.0, strength),
                            "direction": direction,
                            "reliability": min(1.0, sig_strength),
                            "novelty": 0.5,
                            "noise_penalty": 0.1,
                            "influence_boost": 0.0,
                        }
                        try:
                            db.evidence_upsert(**ev)
                        except Exception:
                            pass
                        evidence.append(ev)
        except Exception as exc:
            logger.debug("belief_engine: gold evidence error for %s: %s", symbol, exc)

        # 2. From market_events
        try:
            rows = db._conn.execute(
                "SELECT * FROM market_events WHERE entity_id=? AND event_date=?",
                (symbol, today),
            ).fetchall()
            for row in rows:
                r = dict(row)
                ev_id = f"event:{r.get('event_id', symbol)}:{today}"
                mag = float(r.get("magnitude") or 0.0)
                sent = float(r.get("sentiment_score") or 0.0)
                ev = {
                    "evidence_id": ev_id,
                    "as_of_date": today,
                    "symbol": symbol,
                    "evidence_type": "market_event",
                    "payload_ref": str(r.get("event_id", ev_id)),
                    "strength": min(1.0, abs(mag)),
                    "direction": 1.0 if (mag > 0 or sent > 0) else -1.0,
                    "reliability": 0.7,
                    "novelty": 0.6,
                    "noise_penalty": 0.05,
                    "influence_boost": 0.0,
                }
                try:
                    db.evidence_upsert(**ev)
                except Exception:
                    pass
                evidence.append(ev)
        except Exception as exc:
            logger.debug("belief_engine: market_events error for %s: %s", symbol, exc)

        return evidence

    def _update_symbol(
        self,
        symbol: str,
        today: str,
        yesterday: str,
        data_path: Path,
        trust_gate: float,
        drift: float,
    ) -> None:
        db = self._db

        # Get previous belief (or cold start)
        prev = db.belief_state_get_prev(today, symbol)
        b_prev = prev["belief_vec"] if prev else cold_start_belief()

        # Collect evidence
        evidence = self._build_evidence_list(symbol, today, data_path)

        if not evidence:
            # Decay only — no evidence update
            b_new = residual_update(b_prev, [], decay_lambda=DECAY_LAMBDA, gain_eta=0.0)
            db.belief_state_upsert(
                today, symbol, b_new, BELIEF_VERSION,
                confidence=0.3,
                uncertainty=float(b_new.get("sigma", 0.3)),
            )
            return

        # Compute attention logits and weights
        weighted_ev = compute_logits(evidence, b_prev)

        # Detect conflict
        conflict_score, _ = detect_conflict(weighted_ev, b_prev)

        # Compute adaptive gain
        mean_reliability = (
            sum(float(e.get("reliability", 0.5)) for e in evidence) / len(evidence)
        )
        gain_eta = compute_gain_eta(
            GAIN_ETA_0,
            trust_gate=trust_gate,
            drift=drift,
            mean_reliability=mean_reliability,
        )
        # Reduce gain when conflict is high
        gain_eta *= (1.0 - 0.5 * conflict_score)

        # Residual update
        b_new = residual_update(b_prev, weighted_ev, decay_lambda=DECAY_LAMBDA, gain_eta=gain_eta)

        # Compute calibrated confidence
        n_evidence = len(evidence)
        confidence = min(0.95, 0.3 + 0.1 * min(n_evidence, 5) - 0.3 * conflict_score)

        db.belief_state_upsert(
            today, symbol, b_new, BELIEF_VERSION,
            confidence=round(confidence, 4),
            uncertainty=float(b_new.get("sigma", 0.3)),
        )

        # Write top-10 attention scores
        top_10 = sorted(weighted_ev, key=lambda x: x.get("weight", 0.0), reverse=True)[:10]
        attention_set_id = hashlib.md5(f"{symbol}:{today}".encode()).hexdigest()[:8]
        attn_records = []
        for ev in top_10:
            ev_id = str(ev.get("evidence_id", ""))
            attn_id = hashlib.md5(f"{attention_set_id}:{ev_id}".encode()).hexdigest()
            attn_records.append({
                "attention_id": attn_id,
                "as_of_date": today,
                "symbol": symbol,
                "evidence_id": ev_id,
                "logit": float(ev.get("logit", 0.0)),
                "weight": float(ev.get("weight", 0.0)),
                "factors_json": json.dumps(ev.get("factors", {}), ensure_ascii=False),
            })
        if attn_records:
            db.attention_upsert_batch(attn_records)

        # Write belief transition
        prev_ref = prev["as_of_date"] if prev else "cold_start"
        delta_vec = {
            "mu_delta": round(float(b_new.get("mu", 0.0)) - float(b_prev.get("mu", 0.0)), 6),
        }
        transition_id = hashlib.md5(f"{symbol}:{today}:transition".encode()).hexdigest()
        db.belief_transition_insert(
            transition_id=transition_id,
            symbol=symbol,
            t_date=prev_ref if prev else yesterday,
            t1_date=today,
            prev_belief_ref=prev_ref,
            next_belief_ref=today,
            delta_vec=delta_vec,
            decay_lambda=DECAY_LAMBDA,
            gain_eta=round(gain_eta, 6),
            conflict_score=conflict_score,
            attention_set_id=attention_set_id,
        )

    def _update_market(self, today: str, yesterday: str, data_path: Path,
                        trust_gate: float) -> None:
        """Write a market-level belief state (_MARKET_) using macro/policy signals."""
        db = self._db

        prev = db.belief_state_get_prev(today, "_MARKET_")
        b_prev = prev["belief_vec"] if prev else {"mu": 0.0, "sigma": 0.3,
                                                    "policy_dim": 0.0, "macro_dim": 0.0}

        # Try to get regulatory tone signal
        policy_dim = float(b_prev.get("policy_dim", 0.0))
        try:
            from trade_py.signals.regulatory_tone_monitor import RegulatoryToneMonitor
            monitor = RegulatoryToneMonitor(data_path)
            result = monitor.analyze_latest()
            if result:
                # tightening_score > 0.5 → negative, < 0.5 → positive
                ts = float(getattr(result, "tightening_score", 0.5))
                policy_dim = round((0.5 - ts) * 2.0, 4)  # map [0,1] → [1,-1]
        except Exception:
            pass

        b_prev["policy_dim"] = policy_dim
        b_new = residual_update(b_prev, [], decay_lambda=DECAY_LAMBDA * 0.5, gain_eta=0.0)
        b_new["policy_dim"] = policy_dim

        db.belief_state_upsert(
            today, "_MARKET_", b_new, BELIEF_VERSION,
            confidence=0.5,
            uncertainty=float(b_new.get("sigma", 0.3)),
        )
