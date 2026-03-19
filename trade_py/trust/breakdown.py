"""TrustBreakdown — machine-readable trust metadata for a single prediction."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrustBreakdown:
    """Per-prediction trust metadata.

    Consumers should treat trust_score as a quality weight, not a filter.
    trust_level is a convenience bucketing for UI / logging.

    Fields
    ------
    trust_score : float
        Composite trust in [0, 1].  Higher = more reliable prediction.
    trust_level : str
        "HIGH" (>0.70), "MEDIUM" (0.40–0.70), "LOW" (<0.40).
    feature_coverage : float
        Fraction of expected feature columns that had real (non-default) values.
    missing_features : list[str]
        Feature names absent from the factor store for this (date, symbol).
    used_defaults : list[str]
        Feature names present in factor store but stored as neutral defaults.
    data_freshness_score : float
        Freshness of underlying data in [0, 1].  Decreases with staleness lag.
    model_version : str
        Model identifier (file stem or registry key).
    feature_schema_version : str
        Version string for the feature column contract (e.g. "v1").
    trace_id : str
        Opaque identifier tying this breakdown to a specific inference call.
    generation_method : str
        Inference method used (e.g. "lightgbm", "xgboost", "onnx").
    warnings : list[str]
        Structured warning strings — machine-readable, not prose.
    """

    trust_score: float
    trust_level: str                          # "LOW" | "MEDIUM" | "HIGH"
    feature_coverage: float
    missing_features: list[str] = field(default_factory=list)
    used_defaults: list[str] = field(default_factory=list)
    data_freshness_score: float = 1.0
    model_version: str = ""
    feature_schema_version: str = "v1"
    trace_id: str = ""
    generation_method: str = "lightgbm"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "trust_score": round(self.trust_score, 4),
            "trust_level": self.trust_level,
            "feature_coverage": round(self.feature_coverage, 4),
            "missing_features": list(self.missing_features),
            "used_defaults": list(self.used_defaults),
            "data_freshness_score": round(self.data_freshness_score, 4),
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
            "trace_id": self.trace_id,
            "generation_method": self.generation_method,
            "warnings": list(self.warnings),
        }

    @classmethod
    def unavailable(cls, reason: str = "model_not_loaded") -> "TrustBreakdown":
        """Sentinel for when inference is not possible."""
        return cls(
            trust_score=0.0,
            trust_level="LOW",
            feature_coverage=0.0,
            warnings=[f"inference_unavailable:{reason}"],
        )
