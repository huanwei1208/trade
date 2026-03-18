"""Generate reasons_json for Recommendation from AttentionScore."""
from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from trade_py.db.trade_db import TradeDB


def build_reasons(
    symbol: str,
    as_of_date: str,
    ranked_row: dict[str, Any],
    db: "TradeDB",
    *,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Build human-readable reasons list from top attention scores.

    Returns list of reason dicts:
        [{"evidence_type": ..., "description": ..., "weight": ..., "detail": ...}]
    """
    reasons: list[dict[str, Any]] = []

    # Get top attention scores
    try:
        attn_rows = db.attention_list(symbol, as_of_date, top_n=top_n)
    except Exception:
        attn_rows = []

    for attn in attn_rows:
        ev_id = attn.get("evidence_id", "")
        weight = float(attn.get("weight", 0.0))
        factors = attn.get("factors_json")
        if isinstance(factors, str):
            try:
                factors = json.loads(factors)
            except Exception:
                factors = {}

        # Lookup evidence type from Evidence table
        ev_type = "unknown"
        ev_direction = 0.0
        try:
            row = db._conn.execute(
                "SELECT evidence_type, direction, strength FROM Evidence WHERE evidence_id=?",
                (ev_id,),
            ).fetchone()
            if row:
                ev_type = row[0] or "unknown"
                ev_direction = float(row[1] or 0.0)
        except Exception:
            pass

        desc = _describe_evidence(ev_type, ev_direction, weight)
        reasons.append({
            "evidence_type": ev_type,
            "description": desc,
            "weight": round(weight, 4),
            "direction": round(ev_direction, 2),
            "factors": factors,
        })

    # Add belief summary if no attention data
    if not reasons:
        mu = ranked_row.get("belief_mu", 0.0)
        sigma = ranked_row.get("belief_sigma", 0.3)
        reasons.append({
            "evidence_type": "belief_summary",
            "description": f"信念μ={mu:+.2f} σ={sigma:.2f}",
            "weight": 1.0,
            "direction": float(mu),
            "factors": {},
        })

    return reasons


def build_data_fingerprint(symbol: str, as_of_date: str) -> str:
    """Simple fingerprint for RecommendationTrace."""
    import hashlib
    return hashlib.md5(f"{symbol}:{as_of_date}".encode()).hexdigest()[:16]


def _describe_evidence(ev_type: str, direction: float, weight: float) -> str:
    """Human-readable description for an evidence type."""
    dir_str = "正向" if direction >= 0 else "负向"
    type_labels = {
        "sentiment_gold":  "情绪金层信号",
        "market_event":    "市场事件",
        "fund_flow":       "资金流向",
        "policy_positive": "政策利好",
        "policy_negative": "政策利空",
        "earnings_beat":   "业绩超预期",
        "earnings_miss":   "业绩不及预期",
        "macro_positive":  "宏观数据利好",
        "macro_negative":  "宏观数据利空",
    }
    label = type_labels.get(ev_type, ev_type)
    return f"{label}（{dir_str}，权重{weight:.2f}）"
