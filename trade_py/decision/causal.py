"""Explicit causal-chain domain objects for auditable trading decisions.

The existing architecture already exposes:

    WorldState -> ScenarioSummary -> ActionDecision -> DecisionExplanation

This module adds machine-readable causal objects on top of that flow so the
system can record:

    ObservedFacts -> InferredState -> CausalFactors -> ConvictionVector
    -> HorizonExpectations -> ActionDecision -> ValidationOutcome
    -> RewardPunishmentRecord

The objects intentionally distinguish observed inputs from inferred factors and
future expectations. Missing information should remain explicit as ``None`` or
``unknown`` instead of being silently collapsed to zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any


def _round(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, digits)
    return value


@dataclass
class ObservedFact:
    id: str
    symbol: str
    as_of_date: str
    source: str
    fact_type: str
    metric_name: str
    metric_value: Any | None
    metric_unit: str | None = None
    horizon_hint: str | None = None
    provenance: str = "observed"
    confidence: float | None = None
    raw_payload_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "as_of_date": self.as_of_date,
            "source": self.source,
            "fact_type": self.fact_type,
            "metric_name": self.metric_name,
            "metric_value": _round(self.metric_value),
            "metric_unit": self.metric_unit,
            "horizon_hint": self.horizon_hint,
            "provenance": self.provenance,
            "confidence": _round(self.confidence),
            "raw_payload_ref": self.raw_payload_ref,
        }


@dataclass
class CausalFactor:
    id: str
    symbol: str
    as_of_date: str
    factor_type: str
    direction: str
    strength: float | None
    weight: float | None
    contributing_facts: list[str] = field(default_factory=list)
    rationale: str = ""
    trust_dependency: str | None = None
    horizon_scope: list[str] = field(default_factory=list)
    inference_type: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "as_of_date": self.as_of_date,
            "factor_type": self.factor_type,
            "direction": self.direction,
            "strength": _round(self.strength),
            "weight": _round(self.weight),
            "contributing_facts": list(self.contributing_facts),
            "rationale": self.rationale,
            "trust_dependency": self.trust_dependency,
            "horizon_scope": list(self.horizon_scope),
            "inference_type": self.inference_type,
        }


@dataclass
class ConvictionVector:
    market_conviction: float | None = None
    sector_conviction: float | None = None
    symbol_conviction: float | None = None
    horizon_conviction_short: float | None = None
    horizon_conviction_medium: float | None = None
    data_model_trust: float | None = None
    final_decision_confidence: float | None = None
    labels: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_conviction": _round(self.market_conviction),
            "sector_conviction": _round(self.sector_conviction),
            "symbol_conviction": _round(self.symbol_conviction),
            "horizon_conviction_short": _round(self.horizon_conviction_short),
            "horizon_conviction_medium": _round(self.horizon_conviction_medium),
            "data_model_trust": _round(self.data_model_trust),
            "final_decision_confidence": _round(self.final_decision_confidence),
            "labels": dict(self.labels),
            "notes": dict(self.notes),
        }


@dataclass
class HorizonExpectation:
    horizon: str
    expected_return: float | None
    expected_volatility: float | None
    expected_direction: str
    confidence: float | None
    supporting_factors: list[str] = field(default_factory=list)
    invalidators: list[str] = field(default_factory=list)
    derivation_method: str = "heuristic"
    calibrated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "expected_return": _round(self.expected_return),
            "expected_volatility": _round(self.expected_volatility),
            "expected_direction": self.expected_direction,
            "confidence": _round(self.confidence),
            "supporting_factors": list(self.supporting_factors),
            "invalidators": list(self.invalidators),
            "derivation_method": self.derivation_method,
            "calibrated": self.calibrated,
        }


@dataclass
class CausalLink:
    id: str
    from_node_type: str
    from_node_id: str
    to_node_type: str
    to_node_id: str
    link_type: str
    weight: float | None
    evidence: list[str] = field(default_factory=list)
    status: str = "heuristic"
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from_node_type": self.from_node_type,
            "from_node_id": self.from_node_id,
            "to_node_type": self.to_node_type,
            "to_node_id": self.to_node_id,
            "link_type": self.link_type,
            "weight": _round(self.weight),
            "evidence": list(self.evidence),
            "status": self.status,
            "explanation": self.explanation,
        }


@dataclass
class ValidationOutcome:
    symbol: str
    decision_as_of: str
    evaluation_date: str | None
    horizon: str
    predicted_direction: str
    realized_return: float | None
    realized_volatility: float | None
    invalidator_hit: bool | None
    calibration_error: float | None
    decision_correctness: str
    notes: str = ""
    snapshot_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "decision_as_of": self.decision_as_of,
            "evaluation_date": self.evaluation_date,
            "horizon": self.horizon,
            "predicted_direction": self.predicted_direction,
            "realized_return": _round(self.realized_return),
            "realized_volatility": _round(self.realized_volatility),
            "invalidator_hit": self.invalidator_hit,
            "calibration_error": _round(self.calibration_error),
            "decision_correctness": self.decision_correctness,
            "notes": self.notes,
            "snapshot_id": self.snapshot_id,
        }


@dataclass
class RewardPunishmentRecord:
    target_type: str
    target_id: str
    reward_score: float | None
    punishment_score: float | None
    rationale: str
    evaluation_horizon: str
    derived_from_validation_id: str | None = None
    snapshot_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "reward_score": _round(self.reward_score),
            "punishment_score": _round(self.punishment_score),
            "rationale": self.rationale,
            "evaluation_horizon": self.evaluation_horizon,
            "derived_from_validation_id": self.derived_from_validation_id,
            "snapshot_id": self.snapshot_id,
        }


@dataclass
class CausalDecisionChain:
    symbol: str
    as_of_date: str
    observed_facts: list[ObservedFact] = field(default_factory=list)
    inferred_state: dict[str, Any] = field(default_factory=dict)
    causal_factors: list[CausalFactor] = field(default_factory=list)
    conviction_vector: ConvictionVector = field(default_factory=ConvictionVector)
    horizon_expectations: list[HorizonExpectation] = field(default_factory=list)
    action_decision: dict[str, Any] = field(default_factory=dict)
    causal_links: list[CausalLink] = field(default_factory=list)
    validation_outcomes: list[ValidationOutcome] = field(default_factory=list)
    reward_punishment: list[RewardPunishmentRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    snapshot_id: str | None = None
    provenance: str = "causal-chain-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of_date": self.as_of_date,
            "observed_facts": [item.to_dict() for item in self.observed_facts],
            "inferred_state": self.inferred_state,
            "causal_factors": [item.to_dict() for item in self.causal_factors],
            "conviction_vector": self.conviction_vector.to_dict(),
            "horizon_expectations": [item.to_dict() for item in self.horizon_expectations],
            "action_decision": self.action_decision,
            "causal_links": [item.to_dict() for item in self.causal_links],
            "validation_outcomes": [item.to_dict() for item in self.validation_outcomes],
            "reward_punishment": [item.to_dict() for item in self.reward_punishment],
            "warnings": list(self.warnings),
            "snapshot_id": self.snapshot_id,
            "provenance": self.provenance,
        }
