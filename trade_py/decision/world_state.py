"""WorldState — explicit market state model for a symbol on a given date.

The WorldState aggregates all observable regime signals into a single
structured object.  Downstream consumers (DecisionService, ExplanationService,
API endpoints) read from WorldState instead of computing heuristics locally.

Design principles:
- Rule-based, deterministic — no hidden ML inside state inference
- Every field has an explicit derivation rationale
- No-information is represented explicitly (UNKNOWN / None), not silently elided
- Serialisable to dict for API responses
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Regime constants ──────────────────────────────────────────────────────────

class MarketRegime:
    TRENDING_UP   = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    SIDEWAYS      = "SIDEWAYS"
    VOLATILE      = "VOLATILE"
    UNKNOWN       = "UNKNOWN"


class EventRegime:
    POSITIVE_EVENT = "POSITIVE_EVENT"
    NEGATIVE_EVENT = "NEGATIVE_EVENT"
    NEUTRAL        = "NEUTRAL"
    NO_EVENT       = "NO_EVENT"
    UNKNOWN        = "UNKNOWN"


class SentimentRegime:
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class TechnicalRegime:
    OVERSOLD   = "OVERSOLD"
    OVERBOUGHT = "OVERBOUGHT"
    NEUTRAL    = "NEUTRAL"
    UNKNOWN    = "UNKNOWN"


class LiquidityRegime:
    HIGH    = "HIGH"
    NORMAL  = "NORMAL"
    LOW     = "LOW"
    UNKNOWN = "UNKNOWN"


class UncertaintyLevel:
    LOW     = "LOW"
    MEDIUM  = "MEDIUM"
    HIGH    = "HIGH"
    UNKNOWN = "UNKNOWN"


# ── Sub-state dataclasses ─────────────────────────────────────────────────────

@dataclass
class MarketRegimeState:
    regime: str = MarketRegime.UNKNOWN
    window_score: float | None = None
    vol_ratio: float | None = None
    rationale: str = ""


@dataclass
class EventRegimeState:
    regime: str = EventRegime.UNKNOWN
    kg_score: float | None = None
    top_event_type: str = ""
    event_count_recent: int = 0
    rationale: str = ""


@dataclass
class SentimentState:
    regime: str = SentimentRegime.UNKNOWN
    belief_mu: float | None = None
    net_sentiment: float | None = None
    belief_sigma: float | None = None
    rationale: str = ""


@dataclass
class TechnicalState:
    regime: str = TechnicalRegime.UNKNOWN
    rsi_14: float | None = None
    macd_signal: float | None = None   # +1 bullish cross, -1 bearish, 0 neutral
    kdj_cross: float | None = None
    rationale: str = ""


@dataclass
class LiquidityState:
    regime: str = LiquidityRegime.UNKNOWN
    vol_ratio: float | None = None
    fund_flow_score: float | None = None
    rationale: str = ""


@dataclass
class UncertaintyState:
    level: str = UncertaintyLevel.UNKNOWN
    belief_sigma: float | None = None
    trust_score: float | None = None
    rationale: str = ""


@dataclass
class DataQualityState:
    score: float = 0.5          # 0–1; from FreshnessReport.overall_freshness_score
    freshness_score: float = 0.5
    missing_datasets: list[str] = field(default_factory=list)
    stale_datasets: list[str] = field(default_factory=list)
    rationale: str = ""


# ── Master WorldState ─────────────────────────────────────────────────────────

@dataclass
class WorldState:
    """Complete state picture for a symbol on a given date.

    All fields are derived deterministically from DB / factor / trust inputs.
    Consumers must not compute additional heuristics — read from here.

    Serialisation:  call `.to_dict()` for API response.
    """

    symbol: str
    as_of_date: str

    # Regime labels (string constants from the *Regime classes above)
    market_regime: str = MarketRegime.UNKNOWN
    event_regime: str = EventRegime.UNKNOWN
    sentiment_regime: str = SentimentRegime.UNKNOWN
    technical_regime: str = TechnicalRegime.UNKNOWN
    liquidity_regime: str = LiquidityRegime.UNKNOWN
    uncertainty_level: str = UncertaintyLevel.UNKNOWN

    # Scalar quality scores
    uncertainty_score: float = 0.5    # 0 = certain, 1 = highly uncertain
    data_quality_score: float = 0.5   # 0 = bad, 1 = perfect freshness
    trust_score: float = 0.5

    # One-line human-readable summary (English, no emoji)
    state_summary: str = ""

    # Blockers: reasons that prevent any positive action
    blockers: list[str] = field(default_factory=list)

    # Evidence lists
    supporting_signals: list[dict[str, Any]] = field(default_factory=list)
    opposing_signals: list[dict[str, Any]] = field(default_factory=list)

    # Sub-states (optional detail; serialised in to_dict)
    market_state: MarketRegimeState | None = None
    event_state: EventRegimeState | None = None
    sentiment_state: SentimentState | None = None
    technical_state: TechnicalState | None = None
    liquidity_state: LiquidityState | None = None
    uncertainty_state: UncertaintyState | None = None
    data_quality_state: DataQualityState | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "symbol": self.symbol,
            "as_of_date": self.as_of_date,
            "market_regime": self.market_regime,
            "event_regime": self.event_regime,
            "sentiment_regime": self.sentiment_regime,
            "technical_regime": self.technical_regime,
            "liquidity_regime": self.liquidity_regime,
            "uncertainty_level": self.uncertainty_level,
            "uncertainty_score": round(self.uncertainty_score, 4),
            "data_quality_score": round(self.data_quality_score, 4),
            "trust_score": round(self.trust_score, 4),
            "state_summary": self.state_summary,
            "blockers": list(self.blockers),
            "supporting_signals": list(self.supporting_signals),
            "opposing_signals": list(self.opposing_signals),
        }
        if self.market_state is not None:
            d["market_state"] = {
                "regime": self.market_state.regime,
                "window_score": self.market_state.window_score,
                "vol_ratio": self.market_state.vol_ratio,
                "rationale": self.market_state.rationale,
            }
        if self.event_state is not None:
            d["event_state"] = {
                "regime": self.event_state.regime,
                "kg_score": self.event_state.kg_score,
                "top_event_type": self.event_state.top_event_type,
                "event_count_recent": self.event_state.event_count_recent,
                "rationale": self.event_state.rationale,
            }
        if self.sentiment_state is not None:
            d["sentiment_state"] = {
                "regime": self.sentiment_state.regime,
                "belief_mu": self.sentiment_state.belief_mu,
                "net_sentiment": self.sentiment_state.net_sentiment,
                "belief_sigma": self.sentiment_state.belief_sigma,
                "rationale": self.sentiment_state.rationale,
            }
        if self.technical_state is not None:
            d["technical_state"] = {
                "regime": self.technical_state.regime,
                "rsi_14": self.technical_state.rsi_14,
                "macd_signal": self.technical_state.macd_signal,
                "rationale": self.technical_state.rationale,
            }
        if self.liquidity_state is not None:
            d["liquidity_state"] = {
                "regime": self.liquidity_state.regime,
                "vol_ratio": self.liquidity_state.vol_ratio,
                "rationale": self.liquidity_state.rationale,
            }
        if self.uncertainty_state is not None:
            d["uncertainty_state"] = {
                "level": self.uncertainty_state.level,
                "belief_sigma": self.uncertainty_state.belief_sigma,
                "trust_score": self.uncertainty_state.trust_score,
                "rationale": self.uncertainty_state.rationale,
            }
        if self.data_quality_state is not None:
            d["data_quality_state"] = {
                "score": round(self.data_quality_state.score, 4),
                "freshness_score": round(self.data_quality_state.freshness_score, 4),
                "missing_datasets": list(self.data_quality_state.missing_datasets),
                "stale_datasets": list(self.data_quality_state.stale_datasets),
                "rationale": self.data_quality_state.rationale,
            }
        return d


# ── Rule-based regime inference ───────────────────────────────────────────────

def infer_market_regime(
    window_score: float | None,
    vol_ratio: float | None,
) -> MarketRegimeState:
    if window_score is None and vol_ratio is None:
        return MarketRegimeState(regime=MarketRegime.UNKNOWN, rationale="no_data")

    ws = float(window_score or 50.0)
    vr = float(vol_ratio or 1.0)

    if vr > 2.0:
        return MarketRegimeState(
            regime=MarketRegime.VOLATILE, window_score=ws, vol_ratio=vr,
            rationale=f"vol_ratio={vr:.2f}>2.0",
        )
    if ws > 70:
        return MarketRegimeState(
            regime=MarketRegime.TRENDING_UP, window_score=ws, vol_ratio=vr,
            rationale=f"window_score={ws:.0f}>70",
        )
    if ws < 30:
        return MarketRegimeState(
            regime=MarketRegime.TRENDING_DOWN, window_score=ws, vol_ratio=vr,
            rationale=f"window_score={ws:.0f}<30",
        )
    return MarketRegimeState(
        regime=MarketRegime.SIDEWAYS, window_score=ws, vol_ratio=vr,
        rationale=f"window_score={ws:.0f} in [30,70]",
    )


def infer_event_regime(
    kg_score: float | None,
    top_event_type: str = "",
    event_count: int = 0,
) -> EventRegimeState:
    if kg_score is None and event_count == 0:
        return EventRegimeState(
            regime=EventRegime.NO_EVENT, event_count_recent=0,
            rationale="no_recent_events",
        )
    ks = float(kg_score or 0.0)
    if ks > 0.30:
        return EventRegimeState(
            regime=EventRegime.POSITIVE_EVENT, kg_score=ks,
            top_event_type=top_event_type, event_count_recent=event_count,
            rationale=f"kg_score={ks:.3f}>0.30",
        )
    if ks < -0.30:
        return EventRegimeState(
            regime=EventRegime.NEGATIVE_EVENT, kg_score=ks,
            top_event_type=top_event_type, event_count_recent=event_count,
            rationale=f"kg_score={ks:.3f}<-0.30",
        )
    return EventRegimeState(
        regime=EventRegime.NEUTRAL, kg_score=ks,
        top_event_type=top_event_type, event_count_recent=event_count,
        rationale=f"kg_score={ks:.3f} in (-0.30, 0.30)",
    )


def infer_sentiment_regime(
    belief_mu: float | None,
    net_sentiment: float | None,
    belief_sigma: float | None,
) -> SentimentState:
    if belief_mu is None and net_sentiment is None:
        return SentimentState(regime=SentimentRegime.UNKNOWN, rationale="no_data")

    mu = float(belief_mu or 0.0)
    ns = float(net_sentiment or 0.0)
    sigma = float(belief_sigma or 0.3)

    if mu > 0.10 and ns > 0.05:
        return SentimentState(
            regime=SentimentRegime.BULLISH, belief_mu=mu, net_sentiment=ns,
            belief_sigma=sigma, rationale=f"mu={mu:.3f}>0.10 ns={ns:.3f}>0.05",
        )
    if mu < -0.10 or ns < -0.20:
        return SentimentState(
            regime=SentimentRegime.BEARISH, belief_mu=mu, net_sentiment=ns,
            belief_sigma=sigma, rationale=f"mu={mu:.3f} or ns={ns:.3f}<-0.20",
        )
    return SentimentState(
        regime=SentimentRegime.NEUTRAL, belief_mu=mu, net_sentiment=ns,
        belief_sigma=sigma, rationale=f"mu={mu:.3f} ns={ns:.3f} neutral",
    )


def infer_technical_regime(
    rsi_14: float | None,
    macd_signal: float | None = None,
) -> TechnicalState:
    if rsi_14 is None:
        return TechnicalState(regime=TechnicalRegime.UNKNOWN, rationale="no_data")

    rsi = float(rsi_14)
    macd = float(macd_signal or 0.0)

    if rsi < 35:
        return TechnicalState(
            regime=TechnicalRegime.OVERSOLD, rsi_14=rsi, macd_signal=macd,
            rationale=f"rsi={rsi:.1f}<35",
        )
    if rsi > 70:
        return TechnicalState(
            regime=TechnicalRegime.OVERBOUGHT, rsi_14=rsi, macd_signal=macd,
            rationale=f"rsi={rsi:.1f}>70",
        )
    return TechnicalState(
        regime=TechnicalRegime.NEUTRAL, rsi_14=rsi, macd_signal=macd,
        rationale=f"rsi={rsi:.1f} in [35,70]",
    )


def infer_liquidity_regime(
    vol_ratio: float | None,
    fund_flow_score: float | None = None,
) -> LiquidityState:
    if vol_ratio is None:
        return LiquidityState(regime=LiquidityRegime.UNKNOWN, rationale="no_vol_data")

    vr = float(vol_ratio)
    if vr > 1.5:
        return LiquidityState(
            regime=LiquidityRegime.HIGH, vol_ratio=vr,
            fund_flow_score=fund_flow_score,
            rationale=f"vol_ratio={vr:.2f}>1.5",
        )
    if vr < 0.7:
        return LiquidityState(
            regime=LiquidityRegime.LOW, vol_ratio=vr,
            fund_flow_score=fund_flow_score,
            rationale=f"vol_ratio={vr:.2f}<0.7",
        )
    return LiquidityState(
        regime=LiquidityRegime.NORMAL, vol_ratio=vr,
        fund_flow_score=fund_flow_score,
        rationale=f"vol_ratio={vr:.2f} in [0.7,1.5]",
    )


def infer_uncertainty(
    belief_sigma: float | None,
    trust_score: float | None,
) -> UncertaintyState:
    sigma = float(belief_sigma or 0.3)
    trust = float(trust_score or 0.5)
    score = round(min(1.0, sigma * 1.5 + (1.0 - trust) * 0.5) / 1.5, 4)

    if sigma > 0.40 or trust < 0.40:
        level = UncertaintyLevel.HIGH
        rationale = f"sigma={sigma:.3f}>0.40 or trust={trust:.3f}<0.40"
    elif sigma < 0.20 and trust > 0.70:
        level = UncertaintyLevel.LOW
        rationale = f"sigma={sigma:.3f}<0.20 and trust={trust:.3f}>0.70"
    else:
        level = UncertaintyLevel.MEDIUM
        rationale = f"sigma={sigma:.3f} trust={trust:.3f}"

    return UncertaintyState(
        level=level, belief_sigma=sigma, trust_score=trust,
        rationale=rationale,
    )


def _build_state_summary(ws: WorldState) -> str:
    """One-line English state description."""
    parts = []
    if ws.market_regime != MarketRegime.UNKNOWN:
        parts.append(ws.market_regime.replace("_", " ").lower())
    if ws.sentiment_regime not in (SentimentRegime.NEUTRAL, SentimentRegime.UNKNOWN):
        parts.append(ws.sentiment_regime.lower() + " sentiment")
    if ws.technical_regime not in (TechnicalRegime.NEUTRAL, TechnicalRegime.UNKNOWN):
        parts.append(ws.technical_regime.lower())
    if ws.event_regime not in (EventRegime.NEUTRAL, EventRegime.NO_EVENT, EventRegime.UNKNOWN):
        parts.append(ws.event_regime.replace("_", " ").lower())
    if ws.uncertainty_level == UncertaintyLevel.HIGH:
        parts.append("high uncertainty")
    if not parts:
        return "insufficient data"
    return ", ".join(parts)


def build_world_state(
    symbol: str,
    as_of_date: str,
    *,
    window_score: float | None = None,
    vol_ratio: float | None = None,
    kg_score: float | None = None,
    top_event_type: str = "",
    event_count: int = 0,
    belief_mu: float | None = None,
    net_sentiment: float | None = None,
    belief_sigma: float | None = None,
    rsi_14: float | None = None,
    macd_signal: float | None = None,
    trust_score: float | None = None,
    data_quality_score: float | None = None,
    freshness_missing: list[str] | None = None,
    freshness_stale: list[str] | None = None,
    freshness_score: float | None = None,
    supporting_signals: list[dict] | None = None,
    opposing_signals: list[dict] | None = None,
) -> WorldState:
    """Construct a WorldState from individual observable inputs.

    All inputs are optional — missing inputs produce UNKNOWN regimes
    and increase uncertainty.  Callers should pass as much as available.
    """
    market_st = infer_market_regime(window_score, vol_ratio)
    event_st  = infer_event_regime(kg_score, top_event_type, event_count)
    sent_st   = infer_sentiment_regime(belief_mu, net_sentiment, belief_sigma)
    tech_st   = infer_technical_regime(rsi_14, macd_signal)
    liq_st    = infer_liquidity_regime(vol_ratio)
    unc_st    = infer_uncertainty(belief_sigma, trust_score)

    dq_score  = float(data_quality_score or freshness_score or 0.5)
    dq_st = DataQualityState(
        score=dq_score,
        freshness_score=float(freshness_score or dq_score),
        missing_datasets=list(freshness_missing or []),
        stale_datasets=list(freshness_stale or []),
        rationale=f"freshness={dq_score:.3f}",
    )

    # Blockers: explicit reasons preventing any positive action
    blockers: list[str] = []
    if unc_st.level == UncertaintyLevel.HIGH:
        blockers.append("high_uncertainty")
    if dq_score < 0.50:
        blockers.append("low_data_quality")
    if float(trust_score or 0.5) < 0.40:
        blockers.append("low_trust")
    if freshness_missing:
        blockers.append(f"missing_datasets:{','.join(freshness_missing[:3])}")

    ws = WorldState(
        symbol=symbol,
        as_of_date=as_of_date,
        market_regime=market_st.regime,
        event_regime=event_st.regime,
        sentiment_regime=sent_st.regime,
        technical_regime=tech_st.regime,
        liquidity_regime=liq_st.regime,
        uncertainty_level=unc_st.level,
        uncertainty_score=float(
            min(1.0, float(belief_sigma or 0.3) + (1.0 - float(trust_score or 0.5)) * 0.5)
        ),
        data_quality_score=dq_score,
        trust_score=float(trust_score or 0.5),
        blockers=blockers,
        supporting_signals=list(supporting_signals or []),
        opposing_signals=list(opposing_signals or []),
        market_state=market_st,
        event_state=event_st,
        sentiment_state=sent_st,
        technical_state=tech_st,
        liquidity_state=liq_st,
        uncertainty_state=unc_st,
        data_quality_state=dq_st,
    )
    ws.state_summary = _build_state_summary(ws)
    return ws
