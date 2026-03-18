"""Conflict detection using AGM conservatism.

Conflict score: measures how much the evidence set contradicts the current belief.
High conflict → lower gain_eta (belief updates more cautiously).
"""
from __future__ import annotations

import json
from typing import Any


def detect_conflict(
    weighted_evidence: list[dict[str, Any]],
    prior_belief: dict[str, float],
) -> tuple[float, dict]:
    """Detect directional conflict between evidence and prior belief.

    Returns:
        (conflict_score, conflict_details_dict)
        conflict_score in [0, 1]
    """
    if not weighted_evidence:
        return 0.0, {"reason": "no_evidence"}

    b_mu = float(prior_belief.get("mu", 0.0))
    b_sigma = float(prior_belief.get("sigma", 0.3))

    # Weighted directional mass for each sign
    positive_mass = 0.0
    negative_mass = 0.0

    for ev in weighted_evidence:
        w = float(ev.get("weight", 0.0))
        d = float(ev.get("direction", 0.0))
        if d > 0:
            positive_mass += w * d
        elif d < 0:
            negative_mass += w * abs(d)

    total = positive_mass + negative_mass
    if total < 1e-9:
        return 0.0, {"reason": "zero_mass"}

    # Directional disagreement: how much evidence opposes belief direction
    dominant = positive_mass if b_mu >= 0 else negative_mass
    opposing = negative_mass if b_mu >= 0 else positive_mass

    # AGM conservatism: conflict = fraction of opposing mass
    conflict_score = float(opposing / total) if total > 0 else 0.0

    # Amplify if belief is already strong (high |mu|, low sigma)
    belief_strength = abs(b_mu) / (b_sigma + 1e-6)
    conflict_score = min(1.0, conflict_score * (1.0 + 0.2 * belief_strength))

    details = {
        "positive_mass": round(positive_mass, 4),
        "negative_mass": round(negative_mass, 4),
        "conflict_fraction": round(opposing / total, 4) if total > 0 else 0.0,
        "belief_strength_amplifier": round(1.0 + 0.2 * belief_strength, 4),
        "final_score": round(conflict_score, 4),
    }

    return round(conflict_score, 4), details
