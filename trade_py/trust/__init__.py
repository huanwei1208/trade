"""trust — Trust layer for the EBRT pipeline.

Exposes:
    compute_trust_vector(db, eval_date, brier_score, drift_mmd) -> dict
    scalar_trust(trust_vec) -> float
    to_gain_eta(trust_scalar, base_eta) -> float
"""
from trade_py.evaluation.trust import compute_trust_vector, scalar_trust  # noqa: F401
from trade_py.trust.gate import to_gain_eta  # noqa: F401
