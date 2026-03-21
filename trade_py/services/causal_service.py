"""CausalService — explicit causal chain builder and validation scaffold.

This service extends the current:

    WorldState -> ScenarioSummary -> ActionDecision -> DecisionExplanation

flow with explicit, machine-readable causal objects:

    ObservedFacts -> CausalFactors -> ConvictionVector -> HorizonExpectations
    -> ActionDecision -> ValidationOutcome -> RewardPunishmentRecord

The current implementation is intentionally conservative:
- fact/factor/link derivation is heuristic and marked as such
- sector conviction remains unavailable without a formal sector factor layer
- validation focuses on observability and auditability before online learning
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from datetime import date
from typing import Any

import pandas as pd

from trade_py.decision.action import ActionDecision, DecisionAction
from trade_py.decision.causal import (
    CausalDecisionChain,
    CausalFactor,
    CausalLink,
    ConvictionVector,
    HorizonExpectation,
    ObservedFact,
    RewardPunishmentRecord,
    ValidationOutcome,
)
from trade_py.decision.scenario import ScenarioSummary
from trade_py.decision.world_state import (
    EventRegime,
    LiquidityRegime,
    MarketRegime,
    TechnicalRegime,
    UncertaintyLevel,
    WorldState,
)
from trade_py.trust.breakdown import TrustBreakdown


def _clamp(value: float | None, lo: float = 0.0, hi: float = 1.0) -> float | None:
    if value is None:
        return None
    return max(lo, min(hi, float(value)))


def _confidence_bucket(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= 0.70:
        return "HIGH"
    if value >= 0.45:
        return "MEDIUM"
    return "LOW"


def _action_confidence_score(label: str) -> float:
    norm = str(label or "").lower()
    if norm == "high":
        return 0.80
    if norm == "medium":
        return 0.60
    if norm == "low":
        return 0.35
    return 0.50


class CausalService:
    """Build and validate machine-readable causal chains."""

    def __init__(self, state_svc, decision_svc, inference=None, data_root: str = "data") -> None:
        self._state_svc = state_svc
        self._decision_svc = decision_svc
        self._inference = inference
        self._data_root = data_root

    # ── Public API ────────────────────────────────────────────────────────

    def build_for_symbol(
        self,
        symbol: str,
        *,
        as_of_date: str | None = None,
        has_position: bool = False,
        db=None,
        persist: bool = False,
        include_validation: bool = False,
        validation_horizons: tuple[int, ...] = (1, 5, 20),
    ) -> CausalDecisionChain:
        local_db = db or self._state_svc._db or self._state_svc._open_db()
        as_of = as_of_date or local_db.get_latest_market_asof() or date.today().isoformat()
        trust_score, trust_breakdown = self._get_trust(symbol)
        ws = self._state_svc.build(symbol, as_of_date=as_of, trust_score=trust_score)
        scenario, action = self._decision_svc.decide(ws, has_position=has_position)
        return self.build_from_components(
            symbol=symbol,
            as_of_date=as_of,
            ws=ws,
            scenario=scenario,
            action=action,
            trust_breakdown=trust_breakdown,
            db=local_db,
            persist=persist,
            include_validation=include_validation,
            validation_horizons=validation_horizons,
        )

    def build_from_components(
        self,
        *,
        symbol: str,
        as_of_date: str,
        ws: WorldState,
        scenario: ScenarioSummary,
        action: ActionDecision,
        trust_breakdown: TrustBreakdown | None = None,
        db=None,
        persist: bool = False,
        include_validation: bool = False,
        validation_horizons: tuple[int, ...] = (1, 5, 20),
    ) -> CausalDecisionChain:
        facts = self._build_observed_facts(symbol, as_of_date, ws, action, trust_breakdown)
        factors = self._derive_causal_factors(symbol, as_of_date, ws, action, facts, trust_breakdown)
        conviction = self._compute_conviction_vector(ws, scenario, action, factors, trust_breakdown)
        expectations = self._derive_horizon_expectations(ws, scenario, action, conviction, factors)
        links = self._build_causal_links(facts, factors, conviction, expectations, action)
        warnings = self._build_warnings(ws, trust_breakdown, conviction)

        inferred_state = {
            "world_state": ws.to_dict(),
            "state_labels": {
                "market_regime": ws.market_regime,
                "event_regime": ws.event_regime,
                "sentiment_regime": ws.sentiment_regime,
                "technical_regime": ws.technical_regime,
                "liquidity_regime": ws.liquidity_regime,
                "uncertainty_level": ws.uncertainty_level,
            },
            "scenario_summary": scenario.to_dict(),
            "trust_breakdown": trust_breakdown.to_dict() if trust_breakdown is not None else None,
        }

        chain = CausalDecisionChain(
            symbol=symbol,
            as_of_date=as_of_date,
            observed_facts=facts,
            inferred_state=inferred_state,
            causal_factors=factors,
            conviction_vector=conviction,
            horizon_expectations=expectations,
            action_decision=action.to_dict(),
            causal_links=links,
            warnings=warnings,
        )

        if persist:
            local_db = db or self._state_svc._db or self._state_svc._open_db()
            chain.snapshot_id = self.persist_chain(local_db, chain)

        if include_validation:
            local_db = db or self._state_svc._db or self._state_svc._open_db()
            if chain.snapshot_id is None:
                chain.snapshot_id = self.persist_chain(local_db, chain)
            outcomes, rewards = self.validate_chain(
                local_db,
                chain,
                horizons=validation_horizons,
                persist=True,
            )
            chain.validation_outcomes = outcomes
            chain.reward_punishment = rewards

        return chain

    def persist_chain(self, db, chain: CausalDecisionChain) -> str:
        snapshot_id = chain.snapshot_id or self._snapshot_id(chain.symbol, chain.as_of_date)
        chain.snapshot_id = snapshot_id
        db.causal_snapshot_upsert(
            snapshot_id=snapshot_id,
            symbol=chain.symbol,
            as_of_date=chain.as_of_date,
            action=chain.action_decision.get("action"),
            decision_confidence=chain.conviction_vector.final_decision_confidence,
            data_model_trust=chain.conviction_vector.data_model_trust,
            inferred_state=chain.inferred_state,
            chain=chain.to_dict(),
        )
        return snapshot_id

    def validate_chain(
        self,
        db,
        chain: CausalDecisionChain,
        *,
        horizons: tuple[int, ...] = (1, 5, 20),
        persist: bool = False,
    ) -> tuple[list[ValidationOutcome], list[RewardPunishmentRecord]]:
        if chain.snapshot_id is None:
            chain.snapshot_id = self.persist_chain(db, chain)
        outcomes = self._evaluate_expectations(chain, horizons=horizons)
        rewards = self._assign_reward_punishment(chain, outcomes)
        if persist:
            db.causal_validation_replace(chain.snapshot_id, [item.to_dict() for item in outcomes])
            db.causal_reward_records_replace(chain.snapshot_id, [item.to_dict() for item in rewards])
        return outcomes, rewards

    def validate_snapshot(
        self,
        db,
        *,
        snapshot_id: str | None = None,
        symbol: str | None = None,
        as_of_date: str | None = None,
        horizons: tuple[int, ...] = (1, 5, 20),
        persist: bool = True,
    ) -> dict[str, Any]:
        row = None
        if snapshot_id:
            row = db.causal_snapshot_get(snapshot_id)
        elif symbol:
            row = db.causal_snapshot_get_latest(symbol, as_of_date=as_of_date)
        if not row:
            raise ValueError("causal snapshot not found")

        chain_payload = row.get("chain") or {}
        chain = self._chain_from_dict(chain_payload)
        if chain.snapshot_id is None:
            chain.snapshot_id = row.get("snapshot_id")
        outcomes, rewards = self.validate_chain(db, chain, horizons=horizons, persist=persist)
        return {
            "snapshot_id": chain.snapshot_id,
            "symbol": chain.symbol,
            "as_of_date": chain.as_of_date,
            "validation_outcomes": [item.to_dict() for item in outcomes],
            "reward_punishment": [item.to_dict() for item in rewards],
        }

    # ── Builders ──────────────────────────────────────────────────────────

    def _build_observed_facts(
        self,
        symbol: str,
        as_of_date: str,
        ws: WorldState,
        action: ActionDecision,
        trust_breakdown: TrustBreakdown | None,
    ) -> list[ObservedFact]:
        facts: list[ObservedFact] = []

        def _add(
            *,
            source: str,
            fact_type: str,
            metric_name: str,
            metric_value: Any | None,
            metric_unit: str | None = None,
            horizon_hint: str | None = None,
            provenance: str = "observed",
            confidence: float | None = None,
            raw_payload_ref: str | None = None,
        ) -> None:
            if metric_value is None and raw_payload_ref is None:
                return
            fact_id = f"{symbol}:{as_of_date}:{metric_name}"
            facts.append(
                ObservedFact(
                    id=fact_id,
                    symbol=symbol,
                    as_of_date=as_of_date,
                    source=source,
                    fact_type=fact_type,
                    metric_name=metric_name,
                    metric_value=metric_value,
                    metric_unit=metric_unit,
                    horizon_hint=horizon_hint,
                    provenance=provenance,
                    confidence=confidence,
                    raw_payload_ref=raw_payload_ref,
                )
            )

        market = ws.market_state
        event = ws.event_state
        sentiment = ws.sentiment_state
        technical = ws.technical_state
        liquidity = ws.liquidity_state
        uncertainty = ws.uncertainty_state
        dq = ws.data_quality_state

        if market is not None:
            _add(source="signals", fact_type="market", metric_name="window_score", metric_value=market.window_score, metric_unit="score")
            _add(source="signals", fact_type="market", metric_name="market_vol_ratio", metric_value=market.vol_ratio, metric_unit="ratio")
        if event is not None:
            _add(source="events", fact_type="event", metric_name="event_kg_score", metric_value=event.kg_score, metric_unit="score", horizon_hint="event_window")
            _add(source="events", fact_type="event", metric_name="event_count_recent", metric_value=event.event_count_recent, metric_unit="count", horizon_hint="event_window")
            _add(source="events", fact_type="event", metric_name="top_event_type", metric_value=event.top_event_type or None, provenance="observed", raw_payload_ref="event_state.top_event_type")
        if sentiment is not None:
            _add(source="belief", fact_type="sentiment", metric_name="belief_mu", metric_value=sentiment.belief_mu, metric_unit="score", horizon_hint="5d")
            _add(source="belief", fact_type="sentiment", metric_name="belief_sigma", metric_value=sentiment.belief_sigma, metric_unit="score", horizon_hint="5d")
            _add(source="signals", fact_type="sentiment", metric_name="net_sentiment", metric_value=sentiment.net_sentiment, metric_unit="score", horizon_hint="5d")
        if technical is not None:
            _add(source="factors", fact_type="technical", metric_name="rsi_14", metric_value=technical.rsi_14, metric_unit="rsi", horizon_hint="1d")
            _add(source="factors", fact_type="technical", metric_name="macd_signal", metric_value=technical.macd_signal, metric_unit="signal", horizon_hint="5d")
        if liquidity is not None:
            _add(source="factors", fact_type="liquidity", metric_name="vol_ratio", metric_value=liquidity.vol_ratio, metric_unit="ratio", horizon_hint="1d")
            _add(source="factors", fact_type="liquidity", metric_name="fund_flow_score", metric_value=liquidity.fund_flow_score, metric_unit="score", horizon_hint="5d")
        if uncertainty is not None:
            _add(source="trust", fact_type="uncertainty", metric_name="uncertainty_sigma", metric_value=uncertainty.belief_sigma, metric_unit="score")
        if dq is not None:
            _add(source="freshness", fact_type="data_quality", metric_name="freshness_score", metric_value=dq.freshness_score, metric_unit="score")
            _add(source="freshness", fact_type="data_quality", metric_name="missing_dataset_count", metric_value=len(dq.missing_datasets), metric_unit="count")
            _add(source="freshness", fact_type="data_quality", metric_name="stale_dataset_count", metric_value=len(dq.stale_datasets), metric_unit="count")
        _add(source="decision_model", fact_type="model", metric_name="model_score", metric_value=action.score, metric_unit="score", horizon_hint="5d", provenance="decision_input")
        _add(source="decision_model", fact_type="model", metric_name="model_risk", metric_value=action.risk, metric_unit="risk", horizon_hint="5d", provenance="decision_input")
        if trust_breakdown is not None:
            _add(source="trust", fact_type="trust", metric_name="feature_coverage", metric_value=trust_breakdown.feature_coverage, metric_unit="score")
            _add(source="trust", fact_type="trust", metric_name="data_freshness_score", metric_value=trust_breakdown.data_freshness_score, metric_unit="score")
            _add(source="trust", fact_type="trust", metric_name="trust_score", metric_value=trust_breakdown.trust_score, metric_unit="score")
        else:
            _add(source="trust", fact_type="trust", metric_name="trust_score", metric_value=ws.trust_score, metric_unit="score")
        return facts

    def _derive_causal_factors(
        self,
        symbol: str,
        as_of_date: str,
        ws: WorldState,
        action: ActionDecision,
        facts: list[ObservedFact],
        trust_breakdown: TrustBreakdown | None,
    ) -> list[CausalFactor]:
        by_metric = {fact.metric_name: fact.id for fact in facts}
        factors: list[CausalFactor] = []

        def _make(
            factor_type: str,
            direction: str,
            strength: float | None,
            weight: float | None,
            rationale: str,
            contributing: list[str],
            horizon_scope: list[str],
            trust_dependency: str | None = None,
        ) -> None:
            factors.append(
                CausalFactor(
                    id=f"{symbol}:{as_of_date}:{factor_type}",
                    symbol=symbol,
                    as_of_date=as_of_date,
                    factor_type=factor_type,
                    direction=direction,
                    strength=_clamp(strength),
                    weight=_clamp(weight),
                    contributing_facts=[item for item in contributing if item],
                    rationale=rationale,
                    trust_dependency=trust_dependency,
                    horizon_scope=horizon_scope,
                    inference_type="heuristic",
                )
            )

        market = ws.market_state
        if market is not None:
            direction = {
                MarketRegime.TRENDING_UP: "positive",
                MarketRegime.TRENDING_DOWN: "negative",
                MarketRegime.VOLATILE: "mixed",
                MarketRegime.SIDEWAYS: "neutral",
            }.get(ws.market_regime, "unknown")
            strength = None if market.window_score is None else abs(float(market.window_score) - 50.0) / 50.0
            _make(
                "trend_factor",
                direction,
                strength,
                0.90,
                market.rationale,
                [by_metric.get("window_score", ""), by_metric.get("market_vol_ratio", "")],
                ["5d", "20d"],
                trust_dependency="data_model_trust",
            )

        event = ws.event_state
        if event is not None:
            direction = {
                EventRegime.POSITIVE_EVENT: "positive",
                EventRegime.NEGATIVE_EVENT: "negative",
                EventRegime.NEUTRAL: "neutral",
                EventRegime.NO_EVENT: "neutral",
            }.get(ws.event_regime, "unknown")
            strength = abs(float(event.kg_score or 0.0)) if event.kg_score is not None else None
            _make(
                "event_factor",
                direction,
                strength,
                0.80,
                event.rationale,
                [by_metric.get("event_kg_score", ""), by_metric.get("event_count_recent", ""), by_metric.get("top_event_type", "")],
                ["1d", "5d", "event_window"],
            )

        sentiment = ws.sentiment_state
        if sentiment is not None:
            if ws.sentiment_regime == "BULLISH":
                direction = "positive"
            elif ws.sentiment_regime == "BEARISH":
                direction = "negative"
            elif ws.sentiment_regime == "NEUTRAL":
                direction = "neutral"
            else:
                direction = "unknown"
            strength = None
            if sentiment.belief_mu is not None or sentiment.net_sentiment is not None:
                strength = max(abs(float(sentiment.belief_mu or 0.0)), abs(float(sentiment.net_sentiment or 0.0)))
            _make(
                "sentiment_factor",
                direction,
                strength,
                0.75,
                sentiment.rationale,
                [by_metric.get("belief_mu", ""), by_metric.get("belief_sigma", ""), by_metric.get("net_sentiment", "")],
                ["1d", "5d"],
            )

        technical = ws.technical_state
        if technical is not None:
            direction = {
                TechnicalRegime.OVERSOLD: "positive",
                TechnicalRegime.OVERBOUGHT: "negative",
                TechnicalRegime.NEUTRAL: "neutral",
            }.get(ws.technical_regime, "unknown")
            strength = None if technical.rsi_14 is None else abs(float(technical.rsi_14) - 50.0) / 50.0
            _make(
                "momentum_factor",
                direction,
                strength,
                0.70,
                technical.rationale,
                [by_metric.get("rsi_14", ""), by_metric.get("macd_signal", "")],
                ["1d", "5d"],
            )

        liquidity = ws.liquidity_state
        if liquidity is not None:
            direction = {
                LiquidityRegime.HIGH: "positive",
                LiquidityRegime.LOW: "negative",
                LiquidityRegime.NORMAL: "neutral",
            }.get(ws.liquidity_regime, "unknown")
            strength = None if liquidity.vol_ratio is None else min(1.0, abs(float(liquidity.vol_ratio) - 1.0))
            _make(
                "liquidity_factor",
                direction,
                strength,
                0.65,
                liquidity.rationale,
                [by_metric.get("vol_ratio", ""), by_metric.get("fund_flow_score", "")],
                ["1d", "5d"],
            )

        dq = ws.data_quality_state
        if dq is not None:
            direction = "negative" if dq.missing_datasets or dq.stale_datasets or dq.freshness_score < 0.8 else "positive"
            strength = 1.0 - float(dq.freshness_score or dq.score or 0.5)
            _make(
                "data_quality_factor",
                direction,
                strength,
                0.95,
                dq.rationale,
                [by_metric.get("freshness_score", ""), by_metric.get("missing_dataset_count", ""), by_metric.get("stale_dataset_count", "")],
                ["all"],
                trust_dependency="data_model_trust",
            )

        uncertainty = ws.uncertainty_state
        if uncertainty is not None:
            direction = {
                UncertaintyLevel.HIGH: "negative",
                UncertaintyLevel.MEDIUM: "mixed",
                UncertaintyLevel.LOW: "positive",
            }.get(ws.uncertainty_level, "unknown")
            sigma = float(uncertainty.belief_sigma or 0.0)
            trust_penalty = 1.0 - float((trust_breakdown.trust_score if trust_breakdown else ws.trust_score) or 0.5)
            strength = _clamp(max(sigma, trust_penalty))
            _make(
                "uncertainty_factor",
                direction,
                strength,
                0.85,
                uncertainty.rationale,
                [by_metric.get("uncertainty_sigma", ""), by_metric.get("trust_score", "")],
                ["all"],
                trust_dependency="data_model_trust",
            )

        if action.reason:
            _make(
                "decision_rule_factor",
                "positive" if action.action in {DecisionAction.PROBE, DecisionAction.ADD} else "neutral",
                _action_confidence_score(action.confidence),
                0.55,
                f"action_reason={action.reason}",
                [by_metric.get("model_score", ""), by_metric.get("model_risk", "")],
                ["5d"],
                trust_dependency="final_decision_confidence",
            )

        return factors

    def _compute_conviction_vector(
        self,
        ws: WorldState,
        scenario: ScenarioSummary,
        action: ActionDecision,
        factors: list[CausalFactor],
        trust_breakdown: TrustBreakdown | None,
    ) -> ConvictionVector:
        directional = [item for item in factors if item.direction in {"positive", "negative", "mixed", "neutral"}]
        positive = sum((item.weight or 0.0) * (item.strength or 0.0) for item in directional if item.direction == "positive")
        negative = sum((item.weight or 0.0) * (item.strength or 0.0) for item in directional if item.direction == "negative")
        mixed = sum((item.weight or 0.0) * (item.strength or 0.0) for item in directional if item.direction == "mixed")
        conflict = min(1.0, negative if positive > 0 else positive)
        trust = float(trust_breakdown.trust_score if trust_breakdown is not None else ws.trust_score)

        market_strength = next((item.strength for item in factors if item.factor_type == "trend_factor"), None)
        market_conviction = None if market_strength is None else _clamp((market_strength * 0.7 + scenario.scenario_confidence * 0.3) * trust)

        symbol_signal_mass = positive + negative + mixed
        if symbol_signal_mass <= 0:
            symbol_conviction = _clamp(0.35 * trust)
        else:
            clarity = max(positive, negative, mixed) / max(symbol_signal_mass, 1e-6)
            symbol_conviction = _clamp((0.5 * clarity + 0.5 * scenario.scenario_confidence) * trust)

        short_conv = _clamp((scenario.scenario_confidence * 0.4 + (positive + mixed * 0.5) * 0.35 + trust * 0.25) - conflict * 0.20)
        medium_conv = _clamp((scenario.scenario_confidence * 0.55 + (positive * 0.30) + trust * 0.15) - conflict * 0.15)
        final_conf = _clamp((_action_confidence_score(action.confidence) * 0.6 + trust * 0.25 + scenario.scenario_confidence * 0.15))

        notes = {
            "sector_conviction": "unavailable_without_explicit_sector_factor_layer",
            "confidence_semantics": "data_model_trust is separated from market/symbol conviction",
        }
        labels = {
            "market_conviction": _confidence_bucket(market_conviction),
            "sector_conviction": _confidence_bucket(None),
            "symbol_conviction": _confidence_bucket(symbol_conviction),
            "horizon_conviction_short": _confidence_bucket(short_conv),
            "horizon_conviction_medium": _confidence_bucket(medium_conv),
            "data_model_trust": _confidence_bucket(trust),
            "final_decision_confidence": _confidence_bucket(final_conf),
        }
        return ConvictionVector(
            market_conviction=market_conviction,
            sector_conviction=None,
            symbol_conviction=symbol_conviction,
            horizon_conviction_short=short_conv,
            horizon_conviction_medium=medium_conv,
            data_model_trust=trust,
            final_decision_confidence=final_conf,
            labels=labels,
            notes=notes,
        )

    def _derive_horizon_expectations(
        self,
        ws: WorldState,
        scenario: ScenarioSummary,
        action: ActionDecision,
        conviction: ConvictionVector,
        factors: list[CausalFactor],
    ) -> list[HorizonExpectation]:
        base_signal = float(action.score or 0.5) - 0.5
        if action.action in {DecisionAction.REDUCE, DecisionAction.EXIT}:
            base_signal = -abs(base_signal or 0.08)
        elif action.action == DecisionAction.NO_ACTION and ws.blockers:
            base_signal = 0.0
        elif action.action == DecisionAction.WATCH and scenario.dominant_scenario == "bear":
            base_signal = min(base_signal, -0.03)
        elif action.action in {DecisionAction.PROBE, DecisionAction.ADD} and base_signal <= 0:
            base_signal = max(base_signal, 0.04)

        if base_signal > 0.015:
            direction = "positive"
        elif base_signal < -0.015:
            direction = "negative"
        else:
            direction = "flat"

        invalidators = list(action.invalidators[:4])
        supportive_ids = [item.id for item in factors if item.direction == "positive"][:4]
        expectations: list[HorizonExpectation] = []

        for horizon, multiplier, confidence in (
            ("1d", 0.035, conviction.horizon_conviction_short),
            ("5d", 0.080, max(filter(None, [conviction.horizon_conviction_short, conviction.horizon_conviction_medium]), default=conviction.horizon_conviction_short)),
            ("20d", 0.140, conviction.horizon_conviction_medium),
        ):
            expected_return = None if direction == "flat" and abs(base_signal) < 0.01 else round(base_signal * multiplier, 4)
            expected_volatility = None
            if ws.uncertainty_score is not None:
                horizon_days = int(horizon.rstrip("d"))
                expected_volatility = round(0.015 * math.sqrt(horizon_days) * (0.7 + float(ws.uncertainty_score)), 4)
            expectations.append(
                HorizonExpectation(
                    horizon=horizon,
                    expected_return=expected_return,
                    expected_volatility=expected_volatility,
                    expected_direction=direction,
                    confidence=confidence,
                    supporting_factors=supportive_ids,
                    invalidators=invalidators,
                    derivation_method="heuristic_from_world_state_and_action",
                    calibrated=False,
                )
            )

        event_factor = next((item for item in factors if item.factor_type == "event_factor"), None)
        if event_factor is not None and ws.event_regime not in {EventRegime.NO_EVENT, EventRegime.UNKNOWN}:
            expectations.append(
                HorizonExpectation(
                    horizon="event_window",
                    expected_return=round((base_signal or 0.0) * 0.09, 4) if direction != "flat" else None,
                    expected_volatility=None,
                    expected_direction="positive" if ws.event_regime == EventRegime.POSITIVE_EVENT else "negative" if ws.event_regime == EventRegime.NEGATIVE_EVENT else "flat",
                    confidence=conviction.horizon_conviction_short,
                    supporting_factors=[event_factor.id],
                    invalidators=invalidators,
                    derivation_method="heuristic_event_window",
                    calibrated=False,
                )
            )
        return expectations

    def _build_causal_links(
        self,
        facts: list[ObservedFact],
        factors: list[CausalFactor],
        conviction: ConvictionVector,
        expectations: list[HorizonExpectation],
        action: ActionDecision,
    ) -> list[CausalLink]:
        links: list[CausalLink] = []

        for factor in factors:
            for fact_id in factor.contributing_facts:
                links.append(
                    CausalLink(
                        id=f"{fact_id}->{factor.id}",
                        from_node_type="observed_fact",
                        from_node_id=fact_id,
                        to_node_type="causal_factor",
                        to_node_id=factor.id,
                        link_type="fact_supports_factor",
                        weight=factor.weight,
                        evidence=[fact_id],
                        status="heuristic",
                        explanation=f"{fact_id} contributes to {factor.factor_type}",
                    )
                )

        conviction_nodes = {
            "trend_factor": "market_conviction",
            "event_factor": "horizon_conviction_short",
            "sentiment_factor": "symbol_conviction",
            "momentum_factor": "horizon_conviction_short",
            "liquidity_factor": "symbol_conviction",
            "data_quality_factor": "data_model_trust",
            "uncertainty_factor": "final_decision_confidence",
            "decision_rule_factor": "final_decision_confidence",
        }
        conviction_values = asdict(conviction)

        for factor in factors:
            target = conviction_nodes.get(factor.factor_type)
            if not target:
                continue
            links.append(
                CausalLink(
                    id=f"{factor.id}->{target}",
                    from_node_type="causal_factor",
                    from_node_id=factor.id,
                    to_node_type="conviction",
                    to_node_id=target,
                    link_type="factor_updates_conviction",
                    weight=conviction_values.get(target),
                    evidence=list(factor.contributing_facts),
                    status="heuristic",
                    explanation=f"{factor.factor_type} informs {target}",
                )
            )

        for expectation in expectations:
            source_node = "horizon_conviction_medium" if expectation.horizon in {"20d"} else "horizon_conviction_short"
            source_value = conviction_values.get(source_node)
            links.append(
                CausalLink(
                    id=f"{source_node}->{expectation.horizon}",
                    from_node_type="conviction",
                    from_node_id=source_node,
                    to_node_type="expectation",
                    to_node_id=expectation.horizon,
                    link_type="conviction_supports_expectation",
                    weight=source_value,
                    evidence=list(expectation.supporting_factors),
                    status="heuristic",
                    explanation=f"{source_node} shapes the {expectation.horizon} expectation",
                )
            )
            links.append(
                CausalLink(
                    id=f"{expectation.horizon}->{action.action.value}",
                    from_node_type="expectation",
                    from_node_id=expectation.horizon,
                    to_node_type="action",
                    to_node_id=action.action.value,
                    link_type="expectation_drives_action",
                    weight=expectation.confidence,
                    evidence=list(expectation.supporting_factors),
                    status="heuristic",
                    explanation=f"{expectation.horizon} expectation contributes to {action.action.value}",
                )
            )
        return links

    def _build_warnings(
        self,
        ws: WorldState,
        trust_breakdown: TrustBreakdown | None,
        conviction: ConvictionVector,
    ) -> list[str]:
        warnings: list[str] = []
        if ws.blockers:
            warnings.extend(f"blocker:{item}" for item in ws.blockers)
        if trust_breakdown is not None:
            warnings.extend(f"trust:{item}" for item in trust_breakdown.warnings)
            if trust_breakdown.missing_features:
                warnings.append(f"missing_features:{len(trust_breakdown.missing_features)}")
        if conviction.sector_conviction is None:
            warnings.append("sector_conviction_unavailable")
        return warnings

    # ── Validation ────────────────────────────────────────────────────────

    def _evaluate_expectations(
        self,
        chain: CausalDecisionChain,
        *,
        horizons: tuple[int, ...] = (1, 5, 20),
    ) -> list[ValidationOutcome]:
        from trade_py.data.access import DataGateway

        gateway = DataGateway(self._data_root)
        df = gateway._load_kline_local(chain.symbol)  # intentional: validation should stay read-only
        if df.empty or "date" not in df.columns or "close" not in df.columns:
            return [
                ValidationOutcome(
                    symbol=chain.symbol,
                    decision_as_of=chain.as_of_date,
                    evaluation_date=None,
                    horizon=f"{h}d",
                    predicted_direction=next((item.expected_direction for item in chain.horizon_expectations if item.horizon == f"{h}d"), "unknown"),
                    realized_return=None,
                    realized_volatility=None,
                    invalidator_hit=None,
                    calibration_error=None,
                    decision_correctness="pending",
                    notes="kline history unavailable for validation",
                    snapshot_id=chain.snapshot_id,
                )
                for h in horizons
            ]

        local = df.copy()
        local["date"] = pd.to_datetime(local["date"]).dt.date
        local = local.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        try:
            decision_date = date.fromisoformat(chain.as_of_date)
        except ValueError:
            decision_date = local["date"].iloc[-1]

        candidates = local.index[local["date"] >= decision_date].tolist()
        if not candidates:
            return [
                ValidationOutcome(
                    symbol=chain.symbol,
                    decision_as_of=chain.as_of_date,
                    evaluation_date=None,
                    horizon=f"{h}d",
                    predicted_direction=next((item.expected_direction for item in chain.horizon_expectations if item.horizon == f"{h}d"), "unknown"),
                    realized_return=None,
                    realized_volatility=None,
                    invalidator_hit=None,
                    calibration_error=None,
                    decision_correctness="pending",
                    notes="decision date not yet present in local kline history",
                    snapshot_id=chain.snapshot_id,
                )
                for h in horizons
            ]
        start_idx = candidates[0]
        start_close = float(local.iloc[start_idx]["close"])

        expectation_map = {item.horizon: item for item in chain.horizon_expectations}
        outcomes: list[ValidationOutcome] = []
        closes = local["close"].astype(float).tolist()
        for horizon in horizons:
            key = f"{horizon}d"
            expectation = expectation_map.get(key)
            predicted_direction = expectation.expected_direction if expectation is not None else "unknown"
            target_idx = start_idx + horizon
            if target_idx >= len(local):
                outcomes.append(
                    ValidationOutcome(
                        symbol=chain.symbol,
                        decision_as_of=chain.as_of_date,
                        evaluation_date=None,
                        horizon=key,
                        predicted_direction=predicted_direction,
                        realized_return=None,
                        realized_volatility=None,
                        invalidator_hit=None,
                        calibration_error=None,
                        decision_correctness="pending",
                        notes="insufficient future bars for validation",
                        snapshot_id=chain.snapshot_id,
                    )
                )
                continue

            end_close = float(local.iloc[target_idx]["close"])
            realized_return = (end_close - start_close) / start_close if start_close else None
            window_closes = closes[start_idx: target_idx + 1]
            returns = []
            for i in range(1, len(window_closes)):
                prev = float(window_closes[i - 1] or 0.0)
                if prev:
                    returns.append((float(window_closes[i]) - prev) / prev)
            realized_vol = float(pd.Series(returns).std()) if returns else 0.0
            min_path = min((price - start_close) / start_close for price in window_closes) if start_close else None
            max_path = max((price - start_close) / start_close for price in window_closes) if start_close else None
            invalidator_hit = None
            if predicted_direction == "positive" and min_path is not None:
                invalidator_hit = bool(min_path <= -0.05)
            elif predicted_direction == "negative" and max_path is not None:
                invalidator_hit = bool(max_path >= 0.05)

            correctness = self._classify_expectation(predicted_direction, realized_return)
            calibration_error = None
            if expectation is not None and expectation.expected_return is not None and realized_return is not None:
                calibration_error = abs(float(expectation.expected_return) - float(realized_return))

            outcomes.append(
                ValidationOutcome(
                    symbol=chain.symbol,
                    decision_as_of=chain.as_of_date,
                    evaluation_date=local.iloc[target_idx]["date"].isoformat(),
                    horizon=key,
                    predicted_direction=predicted_direction,
                    realized_return=realized_return,
                    realized_volatility=realized_vol,
                    invalidator_hit=invalidator_hit,
                    calibration_error=calibration_error,
                    decision_correctness=correctness,
                    notes="heuristic_price_path_validation",
                    snapshot_id=chain.snapshot_id,
                )
            )
        return outcomes

    def _assign_reward_punishment(
        self,
        chain: CausalDecisionChain,
        outcomes: list[ValidationOutcome],
    ) -> list[RewardPunishmentRecord]:
        records: list[RewardPunishmentRecord] = []
        for outcome in outcomes:
            if outcome.realized_return is None:
                continue
            realized_sign = 1 if outcome.realized_return > 0 else -1 if outcome.realized_return < 0 else 0
            expected_sign = 1 if outcome.predicted_direction == "positive" else -1 if outcome.predicted_direction == "negative" else 0
            magnitude = min(1.0, abs(float(outcome.realized_return)) * 10.0)

            expectation_reward = magnitude if realized_sign == expected_sign and expected_sign != 0 else 0.0
            expectation_punish = magnitude if realized_sign != expected_sign and expected_sign != 0 else 0.0
            records.append(
                RewardPunishmentRecord(
                    target_type="expectation",
                    target_id=f"{chain.symbol}:{chain.as_of_date}:{outcome.horizon}",
                    reward_score=expectation_reward,
                    punishment_score=expectation_punish,
                    rationale=f"{outcome.horizon} expectation evaluated as {outcome.decision_correctness}",
                    evaluation_horizon=outcome.horizon,
                    derived_from_validation_id=f"{chain.snapshot_id}:{outcome.horizon}",
                    snapshot_id=chain.snapshot_id,
                )
            )

            for factor in chain.causal_factors:
                if factor.direction not in {"positive", "negative"}:
                    continue
                factor_sign = 1 if factor.direction == "positive" else -1
                reward = (factor.weight or 0.0) * (factor.strength or 0.0) * magnitude if factor_sign == realized_sign else 0.0
                punish = (factor.weight or 0.0) * (factor.strength or 0.0) * magnitude if factor_sign != realized_sign else 0.0
                if reward == 0.0 and punish == 0.0:
                    continue
                records.append(
                    RewardPunishmentRecord(
                        target_type="factor",
                        target_id=factor.id,
                        reward_score=reward or 0.0,
                        punishment_score=punish or 0.0,
                        rationale=f"{factor.factor_type} compared with realized {outcome.horizon} return",
                        evaluation_horizon=outcome.horizon,
                        derived_from_validation_id=f"{chain.snapshot_id}:{outcome.horizon}",
                        snapshot_id=chain.snapshot_id,
                    )
                )

            records.append(
                RewardPunishmentRecord(
                    target_type="action_rule",
                    target_id=chain.action_decision.get("reason") or chain.action_decision.get("action") or "unknown_action_rule",
                    reward_score=expectation_reward,
                    punishment_score=expectation_punish,
                    rationale=f"decision rule {chain.action_decision.get('reason') or chain.action_decision.get('action')} evaluated over {outcome.horizon}",
                    evaluation_horizon=outcome.horizon,
                    derived_from_validation_id=f"{chain.snapshot_id}:{outcome.horizon}",
                    snapshot_id=chain.snapshot_id,
                )
            )
        return records

    # ── Helpers ────────────────────────────────────────────────────────────

    def _get_trust(self, symbol: str) -> tuple[float | None, TrustBreakdown | None]:
        if self._inference is None:
            return None, None
        try:
            pred_map = self._inference.predict([symbol])
            payload = pred_map.get(symbol) or {}
            trust = payload.get("trust") or {}
            if not trust:
                return payload.get("trust_score"), None
            return trust.get("trust_score"), TrustBreakdown(
                trust_score=float(trust.get("trust_score", 0.5)),
                trust_level=str(trust.get("trust_level", "MEDIUM")),
                feature_coverage=float(trust.get("feature_coverage", 0.5)),
                missing_features=list(trust.get("missing_features", [])),
                used_defaults=list(trust.get("used_defaults", [])),
                data_freshness_score=float(trust.get("data_freshness_score", 1.0)),
                model_version=str(trust.get("model_version", "")),
                feature_schema_version=str(trust.get("feature_schema_version", "v1")),
                trace_id=str(trust.get("trace_id", "")),
                generation_method=str(trust.get("generation_method", "inference")),
                warnings=list(trust.get("warnings", [])),
            )
        except Exception:
            return None, None

    def _snapshot_id(self, symbol: str, as_of_date: str) -> str:
        digest = hashlib.md5(f"{symbol}:{as_of_date}".encode("utf-8")).hexdigest()[:16]
        return f"causal:{symbol}:{as_of_date}:{digest}"

    def _classify_expectation(self, predicted_direction: str, realized_return: float | None) -> str:
        if realized_return is None:
            return "pending"
        if predicted_direction == "flat":
            return "correct" if abs(realized_return) < 0.015 else "partial"
        if predicted_direction == "positive":
            if realized_return > 0.01:
                return "correct"
            if realized_return >= -0.01:
                return "partial"
            return "incorrect"
        if predicted_direction == "negative":
            if realized_return < -0.01:
                return "correct"
            if realized_return <= 0.01:
                return "partial"
            return "incorrect"
        return "unknown"

    def _chain_from_dict(self, payload: dict[str, Any]) -> CausalDecisionChain:
        facts = [ObservedFact(**item) for item in payload.get("observed_facts", [])]
        factors = [CausalFactor(**item) for item in payload.get("causal_factors", [])]
        conviction = ConvictionVector(**(payload.get("conviction_vector") or {}))
        expectations = [HorizonExpectation(**item) for item in payload.get("horizon_expectations", [])]
        links = [CausalLink(**item) for item in payload.get("causal_links", [])]
        outcomes = [ValidationOutcome(**item) for item in payload.get("validation_outcomes", [])]
        rewards = [RewardPunishmentRecord(**item) for item in payload.get("reward_punishment", [])]
        return CausalDecisionChain(
            symbol=str(payload.get("symbol") or ""),
            as_of_date=str(payload.get("as_of_date") or ""),
            observed_facts=facts,
            inferred_state=dict(payload.get("inferred_state") or {}),
            causal_factors=factors,
            conviction_vector=conviction,
            horizon_expectations=expectations,
            action_decision=dict(payload.get("action_decision") or {}),
            causal_links=links,
            validation_outcomes=outcomes,
            reward_punishment=rewards,
            warnings=list(payload.get("warnings") or []),
            snapshot_id=payload.get("snapshot_id"),
            provenance=str(payload.get("provenance") or "causal-chain-v1"),
        )
