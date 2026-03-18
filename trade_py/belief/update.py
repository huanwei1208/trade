"""Residual belief update (decay + gain + conflict).

Formula:
    b_{t+1,s} = (1-λ)·b_{t,s} + η_{t,s}·Σ w_{t,s,i}·Δ(e_{t,s,i})
    η_{t,s}   = clip(η₀ · TrustGate_t · (1−Drift_t) · r̄, 0, 1)
    Δ(e)      = strength · direction
"""
from __future__ import annotations

from typing import Any

# Default hyper-parameters
DECAY_LAMBDA = 0.1   # daily belief decay rate
GAIN_ETA_0   = 0.4   # base learning rate
BELIEF_VERSION = "v1"


def compute_delta(evidence: dict[str, Any]) -> float:
    """Scalar contribution of a single evidence item."""
    return float(evidence.get("strength", 0.0)) * float(evidence.get("direction", 0.0))


def compute_gain_eta(
    base_eta: float = GAIN_ETA_0,
    *,
    trust_gate: float = 1.0,
    drift: float = 0.0,
    mean_reliability: float = 1.0,
) -> float:
    """Adaptive learning rate: η = clip(η₀ · TrustGate · (1-Drift) · r̄, 0, 1)."""
    eta = base_eta * trust_gate * (1.0 - drift) * mean_reliability
    return max(0.0, min(1.0, eta))


def residual_update(
    b_prev: dict[str, float],
    weighted_evidence: list[dict[str, Any]],
    *,
    decay_lambda: float = DECAY_LAMBDA,
    gain_eta: float = GAIN_ETA_0,
) -> dict[str, float]:
    """Apply decay + weighted residual update to belief vector.

    b_new = (1-λ)·b_prev + η·Σ(w_i · Δ_i)

    Args:
        b_prev: dict with at least {"mu": float}
        weighted_evidence: list of evidence dicts with "weight" and "strength"/"direction"
        decay_lambda: belief decay rate (0 = no decay, 1 = full reset)
        gain_eta: effective learning rate (from compute_gain_eta)

    Returns:
        New belief dict.
    """
    # Weighted sum of deltas
    delta_sum = sum(
        ev.get("weight", 0.0) * compute_delta(ev)
        for ev in weighted_evidence
    )

    b_new = dict(b_prev)

    # Update mu dimension
    mu_prev = float(b_prev.get("mu", 0.0))
    mu_new = (1.0 - decay_lambda) * mu_prev + gain_eta * delta_sum
    # Clip to reasonable range [-1, 1]
    b_new["mu"] = max(-1.0, min(1.0, round(mu_new, 6)))

    # Uncertainty: reduce when evidence is consistent, increase when conflicted
    if weighted_evidence:
        weights = [float(e.get("weight", 0.0)) for e in weighted_evidence]
        # Entropy of weight distribution → lower entropy = more focused attention
        import math
        entropy = -sum(w * math.log(w + 1e-9) for w in weights if w > 0)
        max_entropy = math.log(len(weights) + 1e-9)
        attention_focus = 1.0 - (entropy / (max_entropy + 1e-9))
        sigma_prev = float(b_prev.get("sigma", 0.3))
        sigma_new = sigma_prev * (1.0 - 0.1 * attention_focus) + 0.02
        b_new["sigma"] = max(0.05, min(0.5, round(sigma_new, 6)))
    else:
        # No evidence — uncertainty grows slightly
        sigma_prev = float(b_prev.get("sigma", 0.3))
        b_new["sigma"] = min(0.5, round(sigma_prev + 0.01, 6))

    # Preserve / decay policy and momentum dims if present
    for dim in ["policy_dim", "momentum_dim"]:
        if dim in b_prev:
            b_new[dim] = round((1.0 - decay_lambda) * float(b_prev[dim]), 6)

    return b_new


def cold_start_belief() -> dict[str, float]:
    """Initial belief for a symbol with no history."""
    return {"mu": 0.0, "sigma": 0.3}
