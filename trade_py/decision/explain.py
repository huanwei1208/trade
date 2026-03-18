"""Generate reasons_json / narrative_text / trust_json for Recommendation."""
from __future__ import annotations

import json
import math
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


def build_narrative_text(
    symbol: str,
    ranked_row: dict[str, Any],
    reasons: list[dict[str, Any]],
) -> str:
    """Build a Chinese-language narrative paragraph for the recommendation.

    Combines action, belief horizon, and top evidence into a readable sentence.
    """
    action = ranked_row.get("action", "watch")
    conviction = ranked_row.get("conviction", "low")
    mu_5d = ranked_row.get("expected_return_5d", ranked_row.get("belief_mu", 0.0))
    sigma = ranked_row.get("belief_sigma", 0.3)
    score = ranked_row.get("score", 0.5)

    action_map = {"buy": "买入", "watch": "观察", "avoid": "回避"}
    conv_map = {"high": "高", "mid": "中", "low": "低"}
    action_cn = action_map.get(action, action)
    conv_cn = conv_map.get(conviction, conviction)

    mu_sign = "+" if mu_5d >= 0 else ""
    lines = [
        f"【{symbol}】综合评分 {score:.2f}，建议{action_cn}（置信度{conv_cn}）。",
        f"5日信念均值 μ={mu_sign}{mu_5d:.3f}，不确定度 σ={sigma:.2f}。",
    ]
    if reasons:
        top = reasons[0]
        lines.append(f"主要驱动：{top.get('description', '')}（权重{top.get('weight', 0):.2f}）。")
    if len(reasons) > 1:
        others = "，".join(r.get("evidence_type", "") for r in reasons[1:3])
        lines.append(f"辅助信号：{others}。")
    return "".join(lines)


def build_trace_trust_json(trust_vec: dict[str, float] | None) -> dict[str, Any] | None:
    """Wrap 7-component trust vector into a trace-level trust_json dict.

    Args:
        trust_vec: dict with keys fresh/evidence/model/calib/drift/ops/explain
                   and scalar T_star

    Returns trust_json dict for RecommendationTrace, or None if no vector.
    """
    if not trust_vec:
        return None
    return {
        "T_fresh":    round(float(trust_vec.get("fresh", 0.5)), 4),
        "T_evidence": round(float(trust_vec.get("evidence", 0.5)), 4),
        "T_model":    round(float(trust_vec.get("model", 0.5)), 4),
        "T_calib":    round(float(trust_vec.get("calib", 0.5)), 4),
        "T_drift":    round(float(trust_vec.get("drift", 0.5)), 4),
        "T_ops":      round(float(trust_vec.get("ops", 0.5)), 4),
        "T_explain":  round(float(trust_vec.get("explain", 0.5)), 4),
        "T_star":     round(float(trust_vec.get("T_star", 0.5)), 4),
    }


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
