"""Tests for trade_py/decision/explanation.py — DecisionExplanation contract."""
from __future__ import annotations

import pytest

from trade_py.decision.explanation import (
    EvidenceItem,
    DecisionExplanation,
    build_explanation,
)
from trade_py.decision.action import DecisionAction, ActionDecision
from trade_py.decision.world_state import (
    WorldState,
    MarketRegime,
    EventRegime,
    SentimentRegime,
    TechnicalRegime,
    UncertaintyLevel,
    build_world_state,
)
from trade_py.decision.scenario import build_scenario_summary


# ── EvidenceItem ──────────────────────────────────────────────────────────────

class TestEvidenceItem:
    def test_to_dict_keys(self):
        item = EvidenceItem(
            source="sentiment_gold",
            direction="bullish",
            strength=0.75,
            description="strong belief_mu",
        )
        d = item.to_dict()
        assert d["source"] == "sentiment_gold"
        assert d["direction"] == "bullish"
        assert d["strength"] == 0.75
        assert "weight" in d

    def test_rounding(self):
        item = EvidenceItem(
            source="x", direction="bearish", strength=0.123456789, description="test"
        )
        d = item.to_dict()
        assert len(str(d["strength"]).split(".")[-1]) <= 5


# ── DecisionExplanation ───────────────────────────────────────────────────────

class TestDecisionExplanation:
    def _make(self) -> DecisionExplanation:
        return DecisionExplanation(
            symbol="600000.SH",
            as_of="2026-03-19",
            action="WATCH",
            action_confidence="medium",
            thesis="test thesis",
            world_state_summary="sideways market",
        )

    def test_to_dict_all_layers(self):
        exp = self._make()
        d = exp.to_dict()
        # Layer 3
        assert "action" in d and "thesis" in d
        # Layer 2
        assert "world_state_summary" in d
        # Layer 1
        assert "trust" in d
        assert "data_quality_notes" in d
        # Layer 4
        assert "invalidators" in d
        assert "evidence_against" in d

    def test_to_summary_dict_compact(self):
        exp = self._make()
        exp.evidence_for = [
            EvidenceItem("tech", "bullish", 0.7, "oversold"),
            EvidenceItem("sent", "bullish", 0.6, "positive"),
            EvidenceItem("mkt",  "bullish", 0.5, "trending"),
        ]
        s = exp.to_summary_dict()
        assert len(s["top_evidence_for"]) <= 2

    def test_defaults_are_safe(self):
        exp = self._make()
        assert exp.evidence_for == []
        assert exp.evidence_against == []
        assert exp.warnings == []


# ── build_explanation ─────────────────────────────────────────────────────────

def _make_ws(bullish: bool = True) -> WorldState:
    return build_world_state(
        symbol="600000.SH",
        as_of_date="2026-03-19",
        window_score=75 if bullish else 20,
        vol_ratio=1.0,
        kg_score=0.4 if bullish else -0.4,
        belief_mu=0.2 if bullish else -0.2,
        net_sentiment=0.1 if bullish else -0.3,
        belief_sigma=0.15,
        rsi_14=38.0 if bullish else 72.0,
        trust_score=0.8,
        freshness_score=0.9,
    )


def _make_action(ws: WorldState) -> ActionDecision:
    from trade_py.decision.action import derive_action_decision
    return derive_action_decision(ws, composite_score=0.70)


class TestBuildExplanation:
    def test_returns_explanation_object(self):
        ws  = _make_ws(bullish=True)
        act = _make_action(ws)
        exp = build_explanation(ws, act)
        assert isinstance(exp, DecisionExplanation)

    def test_symbol_propagated(self):
        ws  = _make_ws()
        act = _make_action(ws)
        exp = build_explanation(ws, act)
        assert exp.symbol == "600000.SH"

    def test_thesis_non_empty(self):
        ws  = _make_ws()
        act = _make_action(ws)
        exp = build_explanation(ws, act)
        assert exp.thesis != ""

    def test_trust_from_breakdown(self):
        from trade_py.trust.breakdown import TrustBreakdown
        ws  = _make_ws()
        act = _make_action(ws)
        tb  = TrustBreakdown(
            trust_score=0.9, trust_level="HIGH",
            feature_coverage=1.0, data_freshness_score=1.0,
            warnings=["test_warning"],
        )
        exp = build_explanation(ws, act, trust_breakdown=tb)
        assert exp.trust_score == 0.9
        assert exp.trust_level == "HIGH"
        assert "test_warning" in exp.input_warnings

    def test_scenario_thesis_used(self):
        ws       = _make_ws(bullish=True)
        act      = _make_action(ws)
        scenario = build_scenario_summary(ws)
        exp      = build_explanation(ws, act, scenario=scenario)
        assert exp.thesis != ""
        assert exp.scenario_summary is not None

    def test_evidence_from_ws_signals(self):
        ws  = _make_ws(bullish=True)
        ws.supporting_signals = [
            {"source": "tech", "direction": "bullish", "strength": 0.7, "description": "oversold"}
        ]
        act = _make_action(ws)
        exp = build_explanation(ws, act)
        assert len(exp.evidence_for) >= 1

    def test_raw_reasons_merged(self):
        ws  = _make_ws()
        act = _make_action(ws)
        raw = [
            {"evidence_type": "rsi", "direction": 1.0, "weight": 0.6, "description": "oversold"},
            {"evidence_type": "vol", "direction": -1.0, "weight": 0.4, "description": "low vol"},
        ]
        exp = build_explanation(ws, act, raw_reasons=raw)
        assert len(exp.evidence_for) >= 1
        assert len(exp.evidence_against) >= 1

    def test_evidence_capped_at_5(self):
        ws  = _make_ws()
        ws.supporting_signals = [
            {"source": f"s{i}", "direction": "bullish", "strength": 0.5, "description": f"sig{i}"}
            for i in range(10)
        ]
        act = _make_action(ws)
        exp = build_explanation(ws, act)
        assert len(exp.evidence_for) <= 5

    def test_freshness_quality_notes(self):
        ws  = _make_ws()
        act = _make_action(ws)
        exp = build_explanation(
            ws, act,
            freshness_missing=["tushare_fundamental"],
            freshness_stale=["tushare_fund_flow"],
        )
        assert any("missing_data" in n for n in exp.data_quality_notes)
        assert any("stale_data" in n for n in exp.data_quality_notes)

    def test_high_uncertainty_warning(self):
        ws = build_world_state(
            symbol="000001.SZ",
            as_of_date="2026-03-19",
            belief_sigma=0.5,
            trust_score=0.8,
        )
        act = _make_action(ws)
        exp = build_explanation(ws, act)
        assert any("high_uncertainty" in w for w in exp.warnings)

    def test_to_dict_serialisable(self):
        import json
        ws  = _make_ws()
        act = _make_action(ws)
        exp = build_explanation(ws, act, scenario=build_scenario_summary(ws))
        d   = exp.to_dict()
        # Must be JSON-serialisable
        json.dumps(d)
