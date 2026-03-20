"""Tests for trade_py/decision/world_state.py."""
from __future__ import annotations

import pytest

from trade_py.decision.world_state import (
    MarketRegime,
    EventRegime,
    SentimentRegime,
    TechnicalRegime,
    LiquidityRegime,
    UncertaintyLevel,
    build_world_state,
    infer_market_regime,
    infer_event_regime,
    infer_sentiment_regime,
    infer_technical_regime,
    infer_liquidity_regime,
    infer_uncertainty,
)


# ── infer_market_regime ────────────────────────────────────────────────────────

class TestInferMarketRegime:
    def test_trending_up(self):
        st = infer_market_regime(window_score=80, vol_ratio=1.0)
        assert st.regime == MarketRegime.TRENDING_UP

    def test_trending_down(self):
        st = infer_market_regime(window_score=20, vol_ratio=1.0)
        assert st.regime == MarketRegime.TRENDING_DOWN

    def test_volatile(self):
        st = infer_market_regime(window_score=60, vol_ratio=2.5)
        assert st.regime == MarketRegime.VOLATILE

    def test_sideways(self):
        st = infer_market_regime(window_score=50, vol_ratio=1.0)
        assert st.regime == MarketRegime.SIDEWAYS

    def test_no_data(self):
        st = infer_market_regime(window_score=None, vol_ratio=None)
        assert st.regime == MarketRegime.UNKNOWN


# ── infer_event_regime ─────────────────────────────────────────────────────────

class TestInferEventRegime:
    def test_positive_event(self):
        st = infer_event_regime(kg_score=0.5, event_count=2)
        assert st.regime == EventRegime.POSITIVE_EVENT

    def test_negative_event(self):
        st = infer_event_regime(kg_score=-0.4, event_count=1)
        assert st.regime == EventRegime.NEGATIVE_EVENT

    def test_neutral(self):
        st = infer_event_regime(kg_score=0.1, event_count=1)
        assert st.regime == EventRegime.NEUTRAL

    def test_no_event(self):
        st = infer_event_regime(kg_score=None, event_count=0)
        assert st.regime == EventRegime.NO_EVENT


# ── infer_sentiment_regime ────────────────────────────────────────────────────

class TestInferSentimentRegime:
    def test_bullish(self):
        st = infer_sentiment_regime(belief_mu=0.2, net_sentiment=0.1, belief_sigma=0.2)
        assert st.regime == SentimentRegime.BULLISH

    def test_bearish_mu(self):
        st = infer_sentiment_regime(belief_mu=-0.2, net_sentiment=0.0, belief_sigma=0.2)
        assert st.regime == SentimentRegime.BEARISH

    def test_bearish_sentiment(self):
        st = infer_sentiment_regime(belief_mu=0.0, net_sentiment=-0.3, belief_sigma=0.2)
        assert st.regime == SentimentRegime.BEARISH

    def test_neutral(self):
        st = infer_sentiment_regime(belief_mu=0.05, net_sentiment=0.0, belief_sigma=0.2)
        assert st.regime == SentimentRegime.NEUTRAL

    def test_no_data(self):
        st = infer_sentiment_regime(belief_mu=None, net_sentiment=None, belief_sigma=None)
        assert st.regime == SentimentRegime.UNKNOWN


# ── infer_technical_regime ────────────────────────────────────────────────────

class TestInferTechnicalRegime:
    def test_oversold(self):
        st = infer_technical_regime(rsi_14=30.0)
        assert st.regime == TechnicalRegime.OVERSOLD

    def test_overbought(self):
        st = infer_technical_regime(rsi_14=75.0)
        assert st.regime == TechnicalRegime.OVERBOUGHT

    def test_neutral(self):
        st = infer_technical_regime(rsi_14=50.0)
        assert st.regime == TechnicalRegime.NEUTRAL

    def test_no_data(self):
        st = infer_technical_regime(rsi_14=None)
        assert st.regime == TechnicalRegime.UNKNOWN


# ── infer_uncertainty ─────────────────────────────────────────────────────────

class TestInferUncertainty:
    def test_high_low_trust(self):
        st = infer_uncertainty(belief_sigma=0.2, trust_score=0.3)
        assert st.level == UncertaintyLevel.HIGH

    def test_high_high_sigma(self):
        st = infer_uncertainty(belief_sigma=0.5, trust_score=0.8)
        assert st.level == UncertaintyLevel.HIGH

    def test_low(self):
        st = infer_uncertainty(belief_sigma=0.1, trust_score=0.9)
        assert st.level == UncertaintyLevel.LOW

    def test_medium(self):
        st = infer_uncertainty(belief_sigma=0.3, trust_score=0.6)
        assert st.level == UncertaintyLevel.MEDIUM


# ── build_world_state ─────────────────────────────────────────────────────────

class TestBuildWorldState:
    def _full_ws(self):
        return build_world_state(
            symbol="600000.SH",
            as_of_date="2026-03-19",
            window_score=75,
            vol_ratio=1.2,
            kg_score=0.4,
            top_event_type="earnings",
            event_count=2,
            belief_mu=0.2,
            net_sentiment=0.15,
            belief_sigma=0.15,
            rsi_14=30.0,
            trust_score=0.8,
            freshness_score=0.9,
        )

    def test_basic_fields(self):
        ws = self._full_ws()
        assert ws.symbol == "600000.SH"
        assert ws.as_of_date == "2026-03-19"

    def test_market_regime_trending_up(self):
        ws = self._full_ws()
        assert ws.market_regime == MarketRegime.TRENDING_UP

    def test_sentiment_bullish(self):
        ws = self._full_ws()
        assert ws.sentiment_regime == SentimentRegime.BULLISH

    def test_event_positive(self):
        ws = self._full_ws()
        assert ws.event_regime == EventRegime.POSITIVE_EVENT

    def test_technical_oversold(self):
        ws = self._full_ws()
        assert ws.technical_regime == TechnicalRegime.OVERSOLD

    def test_uncertainty_low(self):
        ws = self._full_ws()
        assert ws.uncertainty_level == UncertaintyLevel.LOW

    def test_no_blockers_when_healthy(self):
        ws = self._full_ws()
        assert ws.blockers == []

    def test_blocker_low_trust(self):
        ws = build_world_state(
            symbol="000001.SZ",
            as_of_date="2026-03-19",
            trust_score=0.3,
            belief_sigma=0.2,
        )
        assert any("trust" in b for b in ws.blockers)

    def test_blocker_high_uncertainty(self):
        ws = build_world_state(
            symbol="000001.SZ",
            as_of_date="2026-03-19",
            belief_sigma=0.5,
            trust_score=0.8,
        )
        assert any("uncertainty" in b for b in ws.blockers)

    def test_blocker_low_data_quality(self):
        ws = build_world_state(
            symbol="000001.SZ",
            as_of_date="2026-03-19",
            freshness_score=0.3,
            trust_score=0.8,
        )
        assert any("data_quality" in b for b in ws.blockers)

    def test_state_summary_non_empty(self):
        ws = self._full_ws()
        assert ws.state_summary != ""
        assert "insufficient" not in ws.state_summary

    def test_to_dict_keys(self):
        ws = self._full_ws()
        d = ws.to_dict()
        for key in ("symbol", "as_of_date", "market_regime", "event_regime",
                    "sentiment_regime", "technical_regime", "uncertainty_level",
                    "trust_score", "data_quality_score", "state_summary", "blockers"):
            assert key in d, f"missing key: {key}"

    def test_sub_states_serialised(self):
        ws = self._full_ws()
        d = ws.to_dict()
        assert "market_state" in d
        assert "sentiment_state" in d
        assert "event_state" in d

    def test_data_quality_state_contains_missing_and_stale_datasets(self):
        ws = build_world_state(
            symbol="000001.SZ",
            as_of_date="2026-03-20",
            trust_score=0.8,
            freshness_score=0.5,
            freshness_missing=["tushare_kline", "tushare_fund_flow"],
            freshness_stale=["sentiment_gold"],
        )
        payload = ws.to_dict()
        data_quality = payload["data_quality_state"]
        assert data_quality["missing_datasets"] == ["tushare_kline", "tushare_fund_flow"]
        assert data_quality["stale_datasets"] == ["sentiment_gold"]
        assert any("missing_datasets" in blocker for blocker in payload["blockers"])
