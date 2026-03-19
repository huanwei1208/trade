"""ScenarioSummary — derive bull/base/bear cases from WorldState.

A ScenarioSummary answers: "given the current world state, what are the
plausible forward outcomes and what must be true for each?"

All derivation is rule-based from WorldState regime labels.
No ML model is required here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from trade_py.decision.world_state import (
    WorldState,
    MarketRegime,
    EventRegime,
    SentimentRegime,
    TechnicalRegime,
    UncertaintyLevel,
)


@dataclass
class ScenarioCase:
    """A single bull/base/bear scenario."""

    label: str                            # "bull" | "base" | "bear"
    probability: float                    # rough prior, 0–1, sums to ≤1
    thesis: str                           # one-line forward thesis
    required_confirmations: list[str] = field(default_factory=list)
    invalidators: list[str] = field(default_factory=list)
    next_triggers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "probability": round(self.probability, 3),
            "thesis": self.thesis,
            "required_confirmations": list(self.required_confirmations),
            "invalidators": list(self.invalidators),
            "next_triggers": list(self.next_triggers),
        }


@dataclass
class ScenarioSummary:
    """Three-case scenario derived from WorldState.

    Consumers use this to explain *why* an action was chosen and what
    conditions would invalidate the thesis.
    """

    symbol: str
    as_of_date: str
    base_case: ScenarioCase
    bull_case: ScenarioCase
    bear_case: ScenarioCase
    scenario_confidence: float     # 0–1; high = regimes are clear, not conflicted
    dominant_scenario: str         # "bull" | "base" | "bear"
    world_state_summary: str       # mirrored from WorldState.state_summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of_date": self.as_of_date,
            "base_case": self.base_case.to_dict(),
            "bull_case": self.bull_case.to_dict(),
            "bear_case": self.bear_case.to_dict(),
            "scenario_confidence": round(self.scenario_confidence, 3),
            "dominant_scenario": self.dominant_scenario,
            "world_state_summary": self.world_state_summary,
        }


def _count_bullish(ws: WorldState) -> int:
    """Count bullish signals across regimes."""
    count = 0
    if ws.market_regime == MarketRegime.TRENDING_UP:
        count += 1
    if ws.event_regime == EventRegime.POSITIVE_EVENT:
        count += 1
    if ws.sentiment_regime == SentimentRegime.BULLISH:
        count += 1
    if ws.technical_regime == TechnicalRegime.OVERSOLD:
        count += 1  # contrarian bullish
    return count


def _count_bearish(ws: WorldState) -> int:
    """Count bearish signals across regimes."""
    count = 0
    if ws.market_regime == MarketRegime.TRENDING_DOWN:
        count += 1
    if ws.event_regime == EventRegime.NEGATIVE_EVENT:
        count += 1
    if ws.sentiment_regime == SentimentRegime.BEARISH:
        count += 1
    if ws.technical_regime == TechnicalRegime.OVERBOUGHT:
        count += 1  # reversal risk
    return count


def build_scenario_summary(ws: WorldState) -> ScenarioSummary:
    """Derive ScenarioSummary from WorldState using regime rules.

    The scenario_confidence is higher when:
    - regimes are consistent (all bullish or all bearish)
    - uncertainty is LOW
    - data quality is high
    It is lower when:
    - regimes conflict
    - uncertainty is HIGH
    - data is stale
    """
    n_bull = _count_bullish(ws)
    n_bear = _count_bearish(ws)
    n_total = n_bull + n_bear

    # Confidence: consistency of signals, modulated by data quality + uncertainty
    if n_total == 0:
        raw_conf = 0.30
    else:
        consistency = max(n_bull, n_bear) / n_total
        raw_conf = consistency * 0.70 + ws.data_quality_score * 0.15 + (
            0.15 if ws.uncertainty_level == UncertaintyLevel.LOW else
            0.05 if ws.uncertainty_level == UncertaintyLevel.MEDIUM else 0.0
        )
    scenario_confidence = round(min(1.0, raw_conf), 3)

    # Dominant scenario
    if ws.uncertainty_level == UncertaintyLevel.HIGH or ws.data_quality_score < 0.40:
        dominant = "base"
    elif n_bull > n_bear:
        dominant = "bull"
    elif n_bear > n_bull:
        dominant = "bear"
    else:
        dominant = "base"

    # Probabilities (soft, not calibrated)
    if dominant == "bull":
        pb, pbase, pbear = 0.55, 0.30, 0.15
    elif dominant == "bear":
        pb, pbase, pbear = 0.15, 0.30, 0.55
    else:
        pb, pbase, pbear = 0.25, 0.50, 0.25

    # Scale by confidence
    conf_adj = scenario_confidence
    pb    = round(pb * conf_adj + (1 - conf_adj) * 0.25, 3)
    pbase = round(pbase * conf_adj + (1 - conf_adj) * 0.50, 3)
    pbear = round(pbear * conf_adj + (1 - conf_adj) * 0.25, 3)

    # Construct cases
    sent_label = ws.sentiment_regime.lower()
    mkt_label  = ws.market_regime.replace("_", " ").lower()

    bull_case = ScenarioCase(
        label="bull",
        probability=pb,
        thesis=f"Sentiment turns bullish, market {mkt_label} continues; upside in 5d horizon.",
        required_confirmations=[
            "belief_mu > 0.15",
            "window_score > 65",
            "no new negative events",
        ],
        invalidators=[
            "belief_sigma increases above 0.35",
            "negative macro event",
            "market transitions to TRENDING_DOWN",
        ],
        next_triggers=[
            "volume_breakout",
            "positive_event_confirmed",
        ],
    )

    bear_case = ScenarioCase(
        label="bear",
        probability=pbear,
        thesis=f"Negative event or bearish sentiment {sent_label} leads to 5d downside.",
        required_confirmations=[
            "belief_mu < -0.10",
            "window_score < 35",
        ],
        invalidators=[
            "positive macro catalyst",
            "strong volume recovery",
            "belief_mu recovers above 0",
        ],
        next_triggers=[
            "negative_event_confirmed",
            "heavy_selling_volume",
        ],
    )

    base_case = ScenarioCase(
        label="base",
        probability=pbase,
        thesis=f"Sideways / range-bound; mixed {sent_label} sentiment and {mkt_label} market.",
        required_confirmations=[
            "no strong directional catalyst",
            "belief_sigma remains < 0.35",
        ],
        invalidators=[
            "strong directional event",
            "trust_score drops below 0.40",
        ],
        next_triggers=[
            "regime_change",
            "significant_news_event",
        ],
    )

    # Add event-specific context
    if ws.event_regime == EventRegime.POSITIVE_EVENT:
        bull_case.required_confirmations.insert(0, f"positive_event_confirmed:{ws.event_state.top_event_type if ws.event_state else ''}")
        bull_case.thesis = f"Positive event ({ws.event_state.top_event_type if ws.event_state else ''}) drives short-term upside."
    elif ws.event_regime == EventRegime.NEGATIVE_EVENT:
        bear_case.required_confirmations.insert(0, f"negative_event_persists:{ws.event_state.top_event_type if ws.event_state else ''}")
        bear_case.thesis = f"Negative event ({ws.event_state.top_event_type if ws.event_state else ''}) creates headwind."

    return ScenarioSummary(
        symbol=ws.symbol,
        as_of_date=ws.as_of_date,
        base_case=base_case,
        bull_case=bull_case,
        bear_case=bear_case,
        scenario_confidence=scenario_confidence,
        dominant_scenario=dominant,
        world_state_summary=ws.state_summary,
    )
