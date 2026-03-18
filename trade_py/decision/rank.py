"""Three-factor ranking for Recommendation generation.

Score = (0.4 × belief_mu
       + 0.3 × window_score / 100
       + 0.3 × event_kg_score / 100
       ) × (1 - risk × 0.5)

action/conviction rules from EBRT plan.
"""
from __future__ import annotations

from typing import Any


def compute_score(
    belief_mu: float,
    window_score: float | None,
    event_kg_score: float | None,
    risk: float = 0.0,
    *,
    w_belief: float = 0.4,
    w_window: float = 0.3,
    w_event: float = 0.3,
) -> float:
    """Compute composite recommendation score in [0, 1]."""
    ws = float(window_score or 50.0) / 100.0
    es = float(event_kg_score or 50.0) / 100.0
    bm = float(belief_mu)

    # Normalise belief_mu from [-1,1] to [0,1]
    bm_norm = (bm + 1.0) / 2.0

    raw = w_belief * bm_norm + w_window * ws + w_event * es
    score = raw * (1.0 - float(risk) * 0.5)
    return round(max(0.0, min(1.0, score)), 4)


def decide_action(
    score: float,
    risk: float,
    belief_sigma: float,
) -> str:
    """Map score + risk to action: buy | watch | avoid."""
    if risk > 0.6:
        return "avoid"
    if score > 0.65 and belief_sigma < 0.25:
        return "buy"
    if score > 0.45:
        return "watch"
    if score < 0.3:
        return "avoid"
    return "watch"


def decide_conviction(score: float, belief_sigma: float) -> str:
    """Map score + uncertainty to conviction: low | mid | high."""
    if belief_sigma < 0.15 and score > 0.7:
        return "high"
    if belief_sigma < 0.25 and score > 0.5:
        return "mid"
    return "low"


def rank_symbols(
    belief_states: list[dict[str, Any]],
    signals: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rank symbols by composite score.

    Args:
        belief_states: list of BeliefState dicts (from db.belief_state_list_date)
        signals: dict symbol → signal row (from db.signal_suggest or similar)

    Returns:
        Sorted list of enriched dicts for Recommendation generation.
    """
    ranked = []
    for bs in belief_states:
        symbol = bs.get("symbol", "")
        if not symbol or symbol == "_MARKET_":
            continue
        bv = bs.get("belief_vec") or {}
        # Use mu_5d (multi-horizon) as primary; fall back to legacy "mu"
        mu_5d = float(bv.get("mu_5d", bv.get("mu", 0.0)))
        mu_1d = float(bv.get("mu_1d", mu_5d * 0.3))
        mu_20d = float(bv.get("mu_20d", mu_5d * 0.7))
        sigma = float(bv.get("sigma_5d", bv.get("sigma", 0.3)))

        sig = signals.get(symbol, {})
        window_score = sig.get("window_score")
        event_kg_score = sig.get("event_kg_score")
        model_risk = float(sig.get("model_risk") or 0.0)

        score = compute_score(mu_5d, window_score, event_kg_score, model_risk)
        action = decide_action(score, model_risk, sigma)
        conviction = decide_conviction(score, sigma)

        # Horizon set: probability-scaled expected returns by horizon
        horizon_set = {
            "1d": round(mu_1d, 4),
            "5d": round(mu_5d, 4),
            "20d": round(mu_20d, 4),
        }
        # risk_5pct: approximate 5th-percentile return = mu_5d - 1.645*sigma
        risk_5pct = round(mu_5d - 1.645 * sigma, 4)

        ranked.append({
            "symbol": symbol,
            "score": score,
            "risk": round(model_risk, 4),
            "action": action,
            "conviction": conviction,
            "belief_mu": round(mu_5d, 4),
            "belief_sigma": round(sigma, 4),
            "window_score": window_score,
            "event_kg_score": event_kg_score,
            "expected_return_5d": round(mu_5d, 4),
            "risk_5pct": risk_5pct,
            "horizon_set": horizon_set,
        })

    return sorted(ranked, key=lambda x: x["score"], reverse=True)
