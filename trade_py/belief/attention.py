"""Attention logit computation for the BeliefEngine.

Formula (from EBRT.pdf §Algorithms):
    ℓ_{t,s,i} = α·σ_i           # compatibility (direction similarity)
               + β·log(1 + m_i)  # magnitude
               + γ·log(ε + r_i)  # reliability
               + δ·log(ε + n_i)  # novelty
               − κ·log(ε + ν_i)  # noise penalty
               + ξ·log(ε + u_i)  # influence boost
               − ρ·conflict(i,b) # conflict with current belief

    w_{t,s,i} = softmax(ℓ / τ)   # τ controls sharpness
"""
from __future__ import annotations

import math
from typing import Any

_EPS = 1e-6

# Default hyper-parameters
ALPHA = 1.0   # compatibility weight
BETA  = 0.8   # magnitude weight
GAMMA = 0.6   # reliability weight
DELTA = 0.5   # novelty weight
KAPPA = 0.4   # noise penalty
XI    = 0.3   # influence weight
RHO   = 0.7   # conflict penalty
TAU   = 1.0   # softmax temperature


def _conflict(direction_i: float, belief_mu: float) -> float:
    """Conflict score: penalise when evidence direction opposes current belief."""
    sign_b = 1.0 if belief_mu >= 0 else -1.0
    sign_i = 1.0 if direction_i >= 0 else -1.0
    if sign_i == sign_b:
        return 0.0
    return abs(belief_mu) * abs(direction_i)


def compute_logits(
    evidence_list: list[dict[str, Any]],
    prior_belief: dict[str, float],
    *,
    alpha: float = ALPHA,
    beta: float = BETA,
    gamma: float = GAMMA,
    delta: float = DELTA,
    kappa: float = KAPPA,
    xi: float = XI,
    rho: float = RHO,
    tau: float = TAU,
) -> list[dict[str, Any]]:
    """Compute attention logits and softmax weights for each evidence item.

    Args:
        evidence_list: list of Evidence dicts with fields:
            evidence_id, strength, direction, reliability, novelty,
            noise_penalty, influence_boost
        prior_belief: dict with at least {"mu": float}

    Returns:
        List of dicts with evidence_id, logit, weight, factors_json added.
    """
    if not evidence_list:
        return []

    b_mu = float(prior_belief.get("mu", 0.0))
    logits: list[float] = []
    factors_list: list[dict] = []

    for ev in evidence_list:
        m_i   = float(ev.get("strength", 0.0))
        d_i   = float(ev.get("direction", 0.0))
        r_i   = float(ev.get("reliability", 0.5))
        n_i   = float(ev.get("novelty", 0.5))
        nu_i  = float(ev.get("noise_penalty", 0.0))
        u_i   = float(ev.get("influence_boost", 0.0))

        # σ_i: compatibility — cosine-like between direction and current belief
        sigma_i = float(d_i * (1.0 if b_mu >= 0 else -1.0))

        conflict_penalty = _conflict(d_i, b_mu)

        ell = (
            alpha * sigma_i
            + beta  * math.log1p(abs(m_i))
            + gamma * math.log(_EPS + r_i)
            + delta * math.log(_EPS + n_i)
            - kappa * math.log(_EPS + nu_i if nu_i > 0 else _EPS)
            + xi    * math.log(_EPS + u_i if u_i > 0 else _EPS)
            - rho   * conflict_penalty
        )
        logits.append(ell / tau)
        factors_list.append({
            "compatibility": round(alpha * sigma_i, 4),
            "magnitude":     round(beta  * math.log1p(abs(m_i)), 4),
            "reliability":   round(gamma * math.log(_EPS + r_i), 4),
            "novelty":       round(delta * math.log(_EPS + n_i), 4),
            "noise":         round(-kappa * math.log(_EPS + (nu_i if nu_i > 0 else _EPS)), 4),
            "influence":     round(xi    * math.log(_EPS + (u_i if u_i > 0 else _EPS)), 4),
            "conflict":      round(-rho  * conflict_penalty, 4),
        })

    # Softmax
    max_l = max(logits)
    exps = [math.exp(l - max_l) for l in logits]
    s = sum(exps)
    weights = [e / s for e in exps] if s > 0 else [1.0 / len(logits)] * len(logits)

    result = []
    for ev, ell, w, factors in zip(evidence_list, logits, weights, factors_list):
        item = dict(ev)
        item["logit"] = round(ell * tau, 4)  # un-scaled for readability
        item["weight"] = round(w, 6)
        item["factors"] = factors
        result.append(item)

    return result
