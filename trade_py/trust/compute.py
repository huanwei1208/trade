"""Compute per-prediction trust from factor availability and data freshness.

Trust score formula
-------------------
  trust_score = (feature_coverage × 0.50
               + data_freshness_score × 0.30
               + 0.20)                          # fixed floor
              × (1 − default_fraction × 0.30)   # penalty for heavy defaults
  clamped to [0.0, 1.0]

trust_level thresholds:
  HIGH   trust_score > 0.70
  MEDIUM trust_score > 0.40
  LOW    trust_score ≤ 0.40

Freshness degradation (per day of lag):
  freshness_score = max(0.0,  1.0 − lag_days × 0.10)
  so data 3 days old → 0.70; 10 days old → 0.0
"""
from __future__ import annotations

import uuid
from typing import Any

from trade_py.trust.breakdown import TrustBreakdown


# Penalty coefficient for heavy default usage
_DEFAULT_PENALTY_COEF: float = 0.30
# Trust score thresholds
_HIGH_THRESHOLD: float = 0.70
_MEDIUM_THRESHOLD: float = 0.40
# Freshness degradation rate per day
_FRESHNESS_DECAY_PER_DAY: float = 0.10


def _freshness_score(lag_days: int | None) -> float:
    """Convert lag_days to freshness ∈ [0, 1]."""
    if lag_days is None:
        # Unknown freshness: assume moderately stale
        return 0.60
    return max(0.0, 1.0 - lag_days * _FRESHNESS_DECAY_PER_DAY)


def _trust_level(score: float) -> str:
    if score > _HIGH_THRESHOLD:
        return "HIGH"
    if score > _MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def compute_prediction_trust(
    factor_values: dict[str, Any],
    expected_cols: list[str],
    *,
    model_version: str = "",
    generation_method: str = "lightgbm",
    feature_schema_version: str = "v1",
    data_lag_days: int | None = None,
    default_value_sentinels: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> TrustBreakdown:
    """Compute trust for a single (symbol, date) inference output.

    Parameters
    ----------
    factor_values:
        Raw factor values as loaded from the factor store for this symbol.
        Keys are factor names; missing key or None value = missing feature.
    expected_cols:
        Ordered list of factor column names the model expects.
    model_version:
        Registry key or file stem of the model used.
    generation_method:
        "lightgbm", "xgboost", "onnx", etc.
    feature_schema_version:
        Contract version string; "v1" for the current 32-column schema.
    data_lag_days:
        How many days since the underlying data was last refreshed.
        None = unknown (uses a conservative 0.60 score).
    default_value_sentinels:
        Optional dict of {factor_name: default_value}.  A factor is counted
        as "used_defaults" if its stored value equals the sentinel exactly.
        If not provided, only strictly-missing (None / absent) counts.
    trace_id:
        Opaque ID for linking breakdown to a log entry.  Auto-generated if None.
    """
    if not expected_cols:
        return TrustBreakdown.unavailable("no_expected_cols")

    sentinels = default_value_sentinels or {}
    missing_features: list[str] = []
    used_defaults: list[str] = []

    for col in expected_cols:
        val = factor_values.get(col)
        if val is None:
            missing_features.append(col)
        elif col in sentinels and val == sentinels[col]:
            used_defaults.append(col)

    n_expected = len(expected_cols)
    n_missing = len(missing_features)
    n_default = len(used_defaults)

    feature_coverage = (n_expected - n_missing) / n_expected
    default_fraction = (n_missing + n_default) / n_expected
    freshness = _freshness_score(data_lag_days)

    raw_score = (
        feature_coverage * 0.50
        + freshness * 0.30
        + 0.20  # floor
    )
    trust_score = raw_score * (1.0 - default_fraction * _DEFAULT_PENALTY_COEF)
    trust_score = round(max(0.0, min(1.0, trust_score)), 4)

    warnings: list[str] = []
    if feature_coverage < 0.50:
        warnings.append(
            f"low_feature_coverage:{feature_coverage:.2f}"
            f" ({n_missing}/{n_expected} features missing)"
        )
    elif feature_coverage < 0.75:
        warnings.append(
            f"partial_feature_coverage:{feature_coverage:.2f}"
        )
    if n_default > 0:
        warnings.append(f"used_defaults:{n_default}_features")
    if data_lag_days is not None and data_lag_days > 3:
        warnings.append(f"stale_data:{data_lag_days}_days_old")
    if data_lag_days is None:
        warnings.append("data_freshness:unknown")

    return TrustBreakdown(
        trust_score=trust_score,
        trust_level=_trust_level(trust_score),
        feature_coverage=round(feature_coverage, 4),
        missing_features=missing_features,
        used_defaults=used_defaults,
        data_freshness_score=round(freshness, 4),
        model_version=model_version,
        feature_schema_version=feature_schema_version,
        trace_id=trace_id or str(uuid.uuid4())[:8],
        generation_method=generation_method,
        warnings=warnings,
    )


def compute_portfolio_trust(
    per_symbol_breakdowns: dict[str, TrustBreakdown],
) -> dict:
    """Aggregate per-symbol trust into a portfolio-level summary.

    Useful for the /api/today-page or batch predict endpoints.
    """
    if not per_symbol_breakdowns:
        return {"mean_trust_score": 0.0, "low_trust_symbols": [], "n_symbols": 0}

    scores = [b.trust_score for b in per_symbol_breakdowns.values()]
    mean_score = round(sum(scores) / len(scores), 4)
    low_trust = [sym for sym, b in per_symbol_breakdowns.items() if b.trust_level == "LOW"]

    return {
        "mean_trust_score": mean_score,
        "trust_level": _trust_level(mean_score),
        "low_trust_symbols": low_trust,
        "n_symbols": len(per_symbol_breakdowns),
        "n_low_trust": len(low_trust),
    }
