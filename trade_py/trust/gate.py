"""TrustGate — converts trust_scalar to gain_eta for BeliefEngine.

Formula:
    gain_eta = base_eta × (0.33 + 1.33 × trust_scalar)
    trust=0.0 → eta=0.05, trust=0.5 → eta=0.15, trust=1.0 → eta=0.25
"""
from __future__ import annotations


def to_gain_eta(trust_scalar: float, base_eta: float = 0.15) -> float:
    """Scale BeliefEngine learning rate by trust scalar.

    Args:
        trust_scalar: composite trust score in [0, 1]. Default 0.5 = neutral.
        base_eta: base learning rate (default 0.15 matches GAIN_ETA_0 × ~0.375).

    Returns:
        Effective gain_eta in [base_eta × 0.33, base_eta × 1.66].
    """
    ts = max(0.0, min(1.0, float(trust_scalar)))
    return round(base_eta * (0.33 + 1.33 * ts), 6)
