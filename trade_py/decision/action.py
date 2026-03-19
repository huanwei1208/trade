"""ActionDecision — no-action-first decision engine.

The system is explicitly no-action-first:
- Every symbol starts at NO_ACTION.
- Evidence must actively override toward WATCH / PROBE / ADD.
- Blockers from WorldState immediately enforce NO_ACTION.

Action ordering (increasing aggression):
    NO_ACTION < WATCH < PROBE < ADD < REDUCE < EXIT

REDUCE and EXIT require position context (not available in offline mode)
so they are only generated when position data is explicitly passed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from trade_py.decision.world_state import (
    WorldState,
    MarketRegime,
    EventRegime,
    SentimentRegime,
    TechnicalRegime,
    LiquidityRegime,
    UncertaintyLevel,
)


class DecisionAction(str, Enum):
    NO_ACTION = "NO_ACTION"
    WATCH     = "WATCH"
    PROBE     = "PROBE"
    ADD       = "ADD"
    REDUCE    = "REDUCE"
    EXIT      = "EXIT"


@dataclass
class ActionDecision:
    """A fully structured, explainable action decision.

    Attributes
    ----------
    action : DecisionAction
        The recommended action.
    confidence : str
        "high" | "medium" | "low"
    score : float
        Composite opportunity score in [0, 1].
    risk : float
        Downside risk estimate in [0, 1].
    position_hint : str
        Suggested position sizing hint; empty if not applicable.
    reason : str
        Primary machine-readable reason code for this action.
    no_action_reason : str
        If action is NO_ACTION, the specific blocker reason.
    invalidators : list[str]
        Events that would flip this decision.
    next_triggers : list[str]
        Signals that would escalate to a more aggressive action.
    supporting_factors : list[str]
        Regime labels / signals that support this decision.
    opposing_factors : list[str]
        Regime labels / signals that argue against this decision.
    """

    action: DecisionAction
    confidence: str                       # "high" | "medium" | "low"
    score: float                          # 0–1
    risk: float                           # 0–1
    position_hint: str = ""
    reason: str = ""
    no_action_reason: str = ""
    invalidators: list[str] = field(default_factory=list)
    next_triggers: list[str] = field(default_factory=list)
    supporting_factors: list[str] = field(default_factory=list)
    opposing_factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "confidence": self.confidence,
            "score": round(self.score, 4),
            "risk": round(self.risk, 4),
            "position_hint": self.position_hint,
            "reason": self.reason,
            "no_action_reason": self.no_action_reason,
            "invalidators": list(self.invalidators),
            "next_triggers": list(self.next_triggers),
            "supporting_factors": list(self.supporting_factors),
            "opposing_factors": list(self.opposing_factors),
        }


def _confidence_label(score: float, uncertainty: str) -> str:
    if uncertainty == UncertaintyLevel.HIGH:
        return "low"
    if score > 0.65 and uncertainty == UncertaintyLevel.LOW:
        return "high"
    if score > 0.50:
        return "medium"
    return "low"


def derive_action_decision(
    ws: WorldState,
    *,
    composite_score: float | None = None,
    model_risk: float | None = None,
    has_position: bool = False,
) -> ActionDecision:
    """Derive ActionDecision from WorldState using explicit no-action-first logic.

    Parameters
    ----------
    ws : WorldState
        Current world state for the symbol.
    composite_score : float | None
        Pre-computed opportunity score [0,1] from EBRT/rank layer.
        If None, computed from regime signals.
    model_risk : float | None
        Model risk estimate [0,1].
    has_position : bool
        Whether the portfolio currently holds this symbol.
        Enables REDUCE / EXIT decisions.
    """
    score = float(composite_score or 0.50)
    risk  = float(model_risk or 0.0)

    supporting: list[str] = []
    opposing: list[str] = []
    invalidators: list[str] = []
    next_triggers: list[str] = []

    # ── Stage 1: Blocker gates (NO_ACTION) ────────────────────────────────────
    if ws.blockers:
        primary_blocker = ws.blockers[0]
        return ActionDecision(
            action=DecisionAction.NO_ACTION,
            confidence="low",
            score=score,
            risk=risk,
            reason="blocker_gate",
            no_action_reason=primary_blocker,
            invalidators=[f"resolve:{b}" for b in ws.blockers],
            next_triggers=["data_refreshed", "trust_recovered"],
        )

    # ── Stage 2: Collect signals ───────────────────────────────────────────────
    if ws.market_regime == MarketRegime.TRENDING_UP:
        supporting.append("market:TRENDING_UP")
    elif ws.market_regime == MarketRegime.TRENDING_DOWN:
        opposing.append("market:TRENDING_DOWN")
        invalidators.append("market_regime_changes_to_UP")
    elif ws.market_regime == MarketRegime.VOLATILE:
        opposing.append("market:VOLATILE")

    if ws.event_regime == EventRegime.POSITIVE_EVENT:
        supporting.append("event:POSITIVE_EVENT")
        next_triggers.append("event_kg_score_confirms")
    elif ws.event_regime == EventRegime.NEGATIVE_EVENT:
        opposing.append("event:NEGATIVE_EVENT")
        invalidators.append("negative_event_reverses")

    if ws.sentiment_regime == SentimentRegime.BULLISH:
        supporting.append("sentiment:BULLISH")
    elif ws.sentiment_regime == SentimentRegime.BEARISH:
        opposing.append("sentiment:BEARISH")
        invalidators.append("belief_mu_recovers_above_0")

    if ws.technical_regime == TechnicalRegime.OVERSOLD:
        supporting.append("technical:OVERSOLD")  # contrarian signal
        next_triggers.append("rsi_crosses_40")
    elif ws.technical_regime == TechnicalRegime.OVERBOUGHT:
        opposing.append("technical:OVERBOUGHT")
        invalidators.append("rsi_cools_below_65")

    if ws.liquidity_regime == LiquidityRegime.HIGH:
        supporting.append("liquidity:HIGH")
    elif ws.liquidity_regime == LiquidityRegime.LOW:
        opposing.append("liquidity:LOW")

    n_support = len(supporting)
    n_oppose  = len(opposing)

    # ── Stage 3: Risk gate ────────────────────────────────────────────────────
    if risk > 0.60:
        if has_position:
            return ActionDecision(
                action=DecisionAction.REDUCE,
                confidence="medium",
                score=score,
                risk=risk,
                position_hint="reduce_to_half",
                reason="high_risk",
                invalidators=["model_risk_drops_below_0.40"],
                supporting_factors=supporting,
                opposing_factors=opposing + [f"model_risk={risk:.2f}"],
            )
        return ActionDecision(
            action=DecisionAction.WATCH,
            confidence="low",
            score=score,
            risk=risk,
            reason="high_risk_no_position",
            invalidators=["model_risk_drops_below_0.40"],
            supporting_factors=supporting,
            opposing_factors=opposing + [f"model_risk={risk:.2f}"],
        )

    # ── Stage 4: Volatile market — never ADD ─────────────────────────────────
    if ws.market_regime == MarketRegime.VOLATILE:
        return ActionDecision(
            action=DecisionAction.WATCH,
            confidence="low",
            score=score,
            risk=risk,
            reason="volatile_market",
            invalidators=["volatility_regime_resolves"],
            next_triggers=["vol_ratio_drops_below_1.5"],
            supporting_factors=supporting,
            opposing_factors=opposing,
        )

    # ── Stage 5: Signal counting → action level ───────────────────────────────
    if n_oppose > n_support:
        # Bearish dominant
        if has_position:
            return ActionDecision(
                action=DecisionAction.REDUCE,
                confidence="medium",
                score=score,
                risk=risk,
                position_hint="reduce",
                reason="bearish_dominant",
                invalidators=[f"resolve:{o}" for o in opposing[:2]],
                supporting_factors=supporting,
                opposing_factors=opposing,
            )
        return ActionDecision(
            action=DecisionAction.NO_ACTION,
            confidence="low",
            score=score,
            risk=risk,
            reason="bearish_dominant",
            no_action_reason=f"bearish:{n_oppose}_signals_vs_{n_support}_bullish",
            invalidators=[f"resolve:{o}" for o in opposing[:2]],
            supporting_factors=supporting,
            opposing_factors=opposing,
        )

    if n_support == 0 and n_oppose == 0:
        # No clear signal
        return ActionDecision(
            action=DecisionAction.WATCH,
            confidence="low",
            score=score,
            risk=risk,
            reason="no_clear_signal",
            next_triggers=["regime_signal_emerges"],
            supporting_factors=supporting,
            opposing_factors=opposing,
        )

    # Bullish domain
    uncertainty = ws.uncertainty_level
    confidence = _confidence_label(score, uncertainty)

    if score > 0.65 and uncertainty == UncertaintyLevel.LOW and n_support >= 3:
        action = DecisionAction.ADD
        reason = "high_conviction_bullish"
        position_hint = "standard"
        next_triggers.append("hold_until_regime_changes")
    elif score > 0.55 and n_support >= 2:
        action = DecisionAction.PROBE
        reason = "moderate_bullish"
        position_hint = "half_standard"
        next_triggers.append("add_if_confirms")
    else:
        action = DecisionAction.WATCH
        reason = "weak_bullish"
        position_hint = ""
        next_triggers.append("probe_if_score_crosses_0.55")

    return ActionDecision(
        action=action,
        confidence=confidence,
        score=score,
        risk=risk,
        position_hint=position_hint,
        reason=reason,
        invalidators=invalidators,
        next_triggers=next_triggers,
        supporting_factors=supporting,
        opposing_factors=opposing,
    )
