"""Tests for trade_py/decision/action.py — no-action-first logic."""
from __future__ import annotations

import pytest

from trade_py.decision.action import (
    DecisionAction,
    ActionDecision,
    derive_action_decision,
)
from trade_py.decision.world_state import (
    WorldState,
    MarketRegime,
    EventRegime,
    SentimentRegime,
    TechnicalRegime,
    LiquidityRegime,
    UncertaintyLevel,
    build_world_state,
)


def _ws(
    *,
    symbol: str = "600000.SH",
    as_of: str = "2026-03-19",
    market=MarketRegime.SIDEWAYS,
    event=EventRegime.NEUTRAL,
    sentiment=SentimentRegime.NEUTRAL,
    technical=TechnicalRegime.NEUTRAL,
    liquidity=LiquidityRegime.NORMAL,
    uncertainty=UncertaintyLevel.MEDIUM,
    data_quality: float = 0.8,
    trust: float = 0.7,
    blockers: list[str] | None = None,
) -> WorldState:
    """Helper: construct a minimal WorldState for action tests."""
    ws = WorldState(
        symbol=symbol,
        as_of_date=as_of,
        market_regime=market,
        event_regime=event,
        sentiment_regime=sentiment,
        technical_regime=technical,
        liquidity_regime=liquidity,
        uncertainty_level=uncertainty,
        data_quality_score=data_quality,
        trust_score=trust,
        blockers=blockers or [],
    )
    ws.state_summary = "test"
    return ws


# ── Blocker gate ──────────────────────────────────────────────────────────────

class TestBlockerGate:
    def test_blocker_gives_no_action(self):
        ws = _ws(blockers=["low_trust"])
        act = derive_action_decision(ws)
        assert act.action == DecisionAction.NO_ACTION
        assert act.reason == "blocker_gate"
        assert act.no_action_reason == "low_trust"

    def test_blocker_confidence_low(self):
        ws = _ws(blockers=["high_uncertainty"])
        act = derive_action_decision(ws)
        assert act.confidence == "low"

    def test_no_blocker_can_progress(self):
        ws = _ws()
        act = derive_action_decision(ws)
        assert act.action != DecisionAction.NO_ACTION or act.reason != "blocker_gate"


# ── Risk gate ─────────────────────────────────────────────────────────────────

class TestRiskGate:
    def test_high_risk_no_position_gives_watch(self):
        ws = _ws()
        act = derive_action_decision(ws, model_risk=0.7, has_position=False)
        assert act.action == DecisionAction.WATCH
        assert act.reason == "high_risk_no_position"

    def test_high_risk_with_position_gives_reduce(self):
        ws = _ws()
        act = derive_action_decision(ws, model_risk=0.7, has_position=True)
        assert act.action == DecisionAction.REDUCE

    def test_low_risk_passes_through(self):
        ws = _ws(sentiment=SentimentRegime.BULLISH, market=MarketRegime.TRENDING_UP)
        act = derive_action_decision(ws, model_risk=0.1)
        assert act.reason != "high_risk_no_position"


# ── Volatile market ───────────────────────────────────────────────────────────

class TestVolatileMarket:
    def test_volatile_gives_watch(self):
        ws = _ws(market=MarketRegime.VOLATILE)
        act = derive_action_decision(ws)
        assert act.action == DecisionAction.WATCH
        assert act.reason == "volatile_market"


# ── Bearish dominant ──────────────────────────────────────────────────────────

class TestBearishDominant:
    def test_bearish_no_position_gives_no_action(self):
        ws = _ws(
            sentiment=SentimentRegime.BEARISH,
            event=EventRegime.NEGATIVE_EVENT,
            market=MarketRegime.TRENDING_DOWN,
        )
        act = derive_action_decision(ws, has_position=False)
        assert act.action == DecisionAction.NO_ACTION
        assert act.reason == "bearish_dominant"

    def test_bearish_with_position_gives_reduce(self):
        ws = _ws(
            sentiment=SentimentRegime.BEARISH,
            event=EventRegime.NEGATIVE_EVENT,
            market=MarketRegime.TRENDING_DOWN,
        )
        act = derive_action_decision(ws, has_position=True)
        assert act.action == DecisionAction.REDUCE


# ── No signal ─────────────────────────────────────────────────────────────────

class TestNoSignal:
    def test_no_signal_gives_watch(self):
        ws = _ws()  # all NEUTRAL/SIDEWAYS
        act = derive_action_decision(ws)
        assert act.action in (DecisionAction.WATCH, DecisionAction.NO_ACTION)


# ── Bullish progression ───────────────────────────────────────────────────────

class TestBullishProgression:
    def test_high_conviction_gives_add(self):
        ws = _ws(
            market=MarketRegime.TRENDING_UP,
            sentiment=SentimentRegime.BULLISH,
            event=EventRegime.POSITIVE_EVENT,
            technical=TechnicalRegime.OVERSOLD,
            uncertainty=UncertaintyLevel.LOW,
        )
        act = derive_action_decision(ws, composite_score=0.75)
        assert act.action == DecisionAction.ADD
        assert act.reason == "high_conviction_bullish"

    def test_moderate_bullish_gives_probe(self):
        ws = _ws(
            market=MarketRegime.TRENDING_UP,
            sentiment=SentimentRegime.BULLISH,
            uncertainty=UncertaintyLevel.MEDIUM,
        )
        act = derive_action_decision(ws, composite_score=0.60)
        assert act.action == DecisionAction.PROBE

    def test_weak_bullish_gives_watch(self):
        ws = _ws(
            market=MarketRegime.TRENDING_UP,
            uncertainty=UncertaintyLevel.MEDIUM,
        )
        act = derive_action_decision(ws, composite_score=0.40)
        assert act.action == DecisionAction.WATCH


# ── ActionDecision serialisation ─────────────────────────────────────────────

class TestActionDecisionSerialisation:
    def test_to_dict_keys(self):
        ws = _ws()
        act = derive_action_decision(ws)
        d = act.to_dict()
        for key in ("action", "confidence", "score", "risk", "reason",
                    "invalidators", "next_triggers",
                    "supporting_factors", "opposing_factors"):
            assert key in d, f"missing key: {key}"

    def test_action_value_is_string(self):
        ws = _ws()
        act = derive_action_decision(ws)
        d = act.to_dict()
        assert isinstance(d["action"], str)
