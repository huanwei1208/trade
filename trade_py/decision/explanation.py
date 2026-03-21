"""DecisionExplanation — unified explainability contract.

All API endpoints and page payloads must consume a DecisionExplanation
instead of building ad hoc reason strings.  This ensures explainability
is consistent, structured, and machine-readable.

Four explainability layers (per spec):
  1. Input quality    — missing features, stale data, defaults
  2. State            — why the current world state is labelled this way
  3. Decision         — why action is NO_ACTION / WATCH / PROBE / ADD ...
  4. Counter-argument — what evidence opposes the thesis / would invalidate it
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from trade_py.decision.world_state import WorldState
    from trade_py.decision.scenario import ScenarioSummary
    from trade_py.decision.action import ActionDecision
    from trade_py.trust.breakdown import TrustBreakdown


@dataclass
class EvidenceItem:
    """A single piece of supporting or opposing evidence."""

    source: str          # "sentiment_gold", "market_event", "technical", "model", ...
    direction: str       # "bullish" | "bearish" | "neutral"
    strength: float      # 0–1
    description: str     # one-line English
    weight: float = 1.0  # relative importance

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "direction": self.direction,
            "strength": round(self.strength, 4),
            "description": self.description,
            "weight": round(self.weight, 4),
        }


@dataclass
class ReasonItem:
    """A structured, factual reason item for grouped display on the Symbol page.

    Groups:
        price_trend      — price change, MA relation
        technical        — RSI, MACD, KDJ state
        volume_liquidity — volume vs average
        event_sentiment  — event/sentiment signals
        belief_uncertainty — trust/uncertainty context
        counter_argument — opposing signals
        invalidation     — invalidation conditions
    """

    id: str
    group: str           # one of the 7 groups above
    polarity: str        # "support" | "oppose" | "neutral" | "warning"
    title: str           # short title, e.g. "MA5 cross above MA20"
    description: str     # concrete detail, e.g. "MA5 (10.72) crossed above MA20 (10.41) on 2026-03-18"
    source: str = "technical"
    metric_name: str | None = None   # e.g. "rsi14"
    metric_value: float | None = None  # e.g. 28.1
    metric_unit: str | None = None   # e.g. "%"
    lookback: str | None = None      # e.g. "5d"
    strength: float = 0.5
    sort_key: int = 0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "group": self.group,
            "polarity": self.polarity,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "strength": round(self.strength, 4),
            "sort_key": self.sort_key,
        }
        if self.metric_name is not None:
            d["metric_name"] = self.metric_name
        if self.metric_value is not None:
            d["metric_value"] = round(self.metric_value, 4)
        if self.metric_unit is not None:
            d["metric_unit"] = self.metric_unit
        if self.lookback is not None:
            d["lookback"] = self.lookback
        return d


@dataclass
class DecisionExplanation:
    """Unified explanation for a symbol's decision on a given date.

    This is the single authoritative explanation object consumed by
    all API endpoints.  Do not generate ad hoc reason strings in handlers.

    Layer 1 — Input quality:
        trust, data_quality_notes, input_warnings

    Layer 2 — State explanation:
        world_state_summary, state_rationale

    Layer 3 — Decision explanation:
        action, action_confidence, thesis, reason

    Layer 4 — Counter-argument:
        evidence_against, invalidators
    """

    symbol: str
    as_of: str

    # Layer 3: decision
    action: str                           # DecisionAction.value
    action_confidence: str                # "high" | "medium" | "low"
    thesis: str                           # one-line forward thesis

    # Layer 2: state
    world_state_summary: str              # from WorldState.state_summary
    state_rationale: str = ""             # why regimes were assigned

    # Layer 1: trust + quality
    trust_score: float = 0.5
    trust_level: str = "MEDIUM"
    trust_components: dict[str, float] = field(default_factory=dict)
    data_quality_notes: list[str] = field(default_factory=list)  # stale/missing datasets
    input_warnings: list[str] = field(default_factory=list)       # from TrustBreakdown.warnings

    # Layer 3: evidence
    evidence_for: list[EvidenceItem] = field(default_factory=list)

    # Layer 4: counter-argument
    evidence_against: list[EvidenceItem] = field(default_factory=list)
    invalidators: list[str] = field(default_factory=list)
    next_triggers: list[str] = field(default_factory=list)

    # Optional full sub-objects (for rich endpoints)
    scenario_summary: dict | None = None  # ScenarioSummary.to_dict()
    world_state: dict | None = None       # WorldState.to_dict()

    # Structural warnings (e.g. conflicting signals, high uncertainty)
    warnings: list[str] = field(default_factory=list)

    # Grouped factual reasons for Symbol workspace (populated by ExplanationService)
    reason_groups: dict[str, list["ReasonItem"]] = field(default_factory=dict)

    # Explicit causal-chain payload for auditability / future UI use
    causal_chain: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of,
            # Layer 3
            "action": self.action,
            "action_confidence": self.action_confidence,
            "thesis": self.thesis,
            # Layer 2
            "world_state_summary": self.world_state_summary,
            "state_rationale": self.state_rationale,
            # Layer 1
            "trust": {
                "trust_score": round(self.trust_score, 4),
                "trust_level": self.trust_level,
                "components": {k: round(v, 4) for k, v in self.trust_components.items()},
            },
            "data_quality_notes": list(self.data_quality_notes),
            "input_warnings": list(self.input_warnings),
            # Evidence
            "evidence_for": [e.to_dict() for e in self.evidence_for],
            "evidence_against": [e.to_dict() for e in self.evidence_against],
            # Layer 4
            "invalidators": list(self.invalidators),
            "next_triggers": list(self.next_triggers),
            # Rich objects
            "scenario_summary": self.scenario_summary,
            "world_state": self.world_state,
            # Structural
            "warnings": list(self.warnings),
            # Grouped factual reasons for Symbol workspace
            "reason_groups": {
                group: [item.to_dict() for item in items]
                for group, items in self.reason_groups.items()
            },
            "causal_chain": self.causal_chain,
        }

    def to_summary_dict(self) -> dict[str, Any]:
        """Compact form for list pages (signals-page, actions-page)."""
        return {
            "symbol": self.symbol,
            "as_of": self.as_of,
            "action": self.action,
            "action_confidence": self.action_confidence,
            "thesis": self.thesis,
            "trust_score": round(self.trust_score, 4),
            "trust_level": self.trust_level,
            "state_summary": self.world_state_summary,
            "top_evidence_for": [e.to_dict() for e in self.evidence_for[:2]],
            "top_evidence_against": [e.to_dict() for e in self.evidence_against[:2]],
            "invalidators": self.invalidators[:3],
            "warnings": self.warnings[:3],
        }


def build_explanation(
    ws: "WorldState",
    action_decision: "ActionDecision",
    *,
    trust_breakdown: "TrustBreakdown | None" = None,
    scenario: "ScenarioSummary | None" = None,
    raw_reasons: list[dict] | None = None,
    freshness_missing: list[str] | None = None,
    freshness_stale: list[str] | None = None,
) -> DecisionExplanation:
    """Assemble a DecisionExplanation from the architecture components.

    Parameters
    ----------
    ws : WorldState
        Current state for the symbol.
    action_decision : ActionDecision
        Decision derived from the world state.
    trust_breakdown : TrustBreakdown | None
        Per-prediction trust from the inference layer.
    scenario : ScenarioSummary | None
        Scenario summary (adds bull/bear cases to explanation).
    raw_reasons : list[dict] | None
        Existing reason dicts from decision/explain.py `build_reasons()`.
        These are merged into evidence_for / evidence_against.
    freshness_missing : list[str] | None
        Datasets absent from the data store.
    freshness_stale : list[str] | None
        Datasets present but stale.
    """
    # ── Layer 1: trust + quality ──────────────────────────────────────────────
    trust_score = float(ws.trust_score)
    trust_level = (
        "HIGH" if trust_score > 0.70 else
        "MEDIUM" if trust_score > 0.40 else "LOW"
    )
    trust_components: dict[str, float] = {}
    input_warnings: list[str] = []
    if trust_breakdown is not None:
        trust_score = trust_breakdown.trust_score
        trust_level = trust_breakdown.trust_level
        input_warnings = list(trust_breakdown.warnings)
        trust_components = {
            "feature_coverage": trust_breakdown.feature_coverage,
            "data_freshness": trust_breakdown.data_freshness_score,
        }

    data_quality_notes: list[str] = []
    if freshness_missing:
        data_quality_notes.append(f"missing_data:{','.join(freshness_missing)}")
    if freshness_stale:
        data_quality_notes.append(f"stale_data:{','.join(freshness_stale)}")

    # ── Layer 2: state rationale ──────────────────────────────────────────────
    state_rationale_parts = []
    if ws.market_state:
        state_rationale_parts.append(f"market:{ws.market_state.rationale}")
    if ws.sentiment_state:
        state_rationale_parts.append(f"sentiment:{ws.sentiment_state.rationale}")
    if ws.technical_state:
        state_rationale_parts.append(f"technical:{ws.technical_state.rationale}")
    state_rationale = "; ".join(state_rationale_parts)

    # ── Layer 3: thesis ───────────────────────────────────────────────────────
    action_val = action_decision.action.value if hasattr(action_decision.action, "value") else str(action_decision.action)
    if scenario and scenario.dominant_scenario == "bull":
        thesis = scenario.bull_case.thesis
    elif scenario and scenario.dominant_scenario == "bear":
        thesis = scenario.bear_case.thesis
    else:
        thesis = ws.state_summary or "Insufficient information to form a thesis."

    # ── Evidence from WorldState + raw_reasons ────────────────────────────────
    evidence_for: list[EvidenceItem] = []
    evidence_against: list[EvidenceItem] = []

    # Map WorldState supporting/opposing to EvidenceItems
    for sig in ws.supporting_signals:
        evidence_for.append(EvidenceItem(
            source=str(sig.get("source", "signal")),
            direction="bullish",
            strength=float(sig.get("strength", 0.5)),
            description=str(sig.get("description", "")),
            weight=float(sig.get("weight", 1.0)),
        ))
    for sig in ws.opposing_signals:
        evidence_against.append(EvidenceItem(
            source=str(sig.get("source", "signal")),
            direction="bearish",
            strength=float(sig.get("strength", 0.5)),
            description=str(sig.get("description", "")),
            weight=float(sig.get("weight", 1.0)),
        ))

    # Enrich from raw_reasons (legacy decision/explain.py output)
    if raw_reasons:
        for r in raw_reasons:
            direction = float(r.get("direction", 0.0))
            item = EvidenceItem(
                source=str(r.get("evidence_type", "unknown")),
                direction="bullish" if direction >= 0 else "bearish",
                strength=min(1.0, abs(float(r.get("weight", 0.5)))),
                description=str(r.get("description", "")),
                weight=float(r.get("weight", 1.0)),
            )
            if direction >= 0:
                evidence_for.append(item)
            else:
                evidence_against.append(item)

    # Fallback: derive evidence from regime labels
    if not evidence_for and not evidence_against:
        for factor in action_decision.supporting_factors:
            evidence_for.append(EvidenceItem(
                source=factor.split(":")[0],
                direction="bullish",
                strength=0.5,
                description=factor,
                weight=1.0,
            ))
        for factor in action_decision.opposing_factors:
            evidence_against.append(EvidenceItem(
                source=factor.split(":")[0],
                direction="bearish",
                strength=0.5,
                description=factor,
                weight=1.0,
            ))

    # ── Layer 4: invalidators ─────────────────────────────────────────────────
    invalidators = list(action_decision.invalidators)
    if scenario:
        dominant = scenario.dominant_scenario
        if dominant == "bull":
            invalidators = list(scenario.bull_case.invalidators) + invalidators
        elif dominant == "bear":
            invalidators = list(scenario.bear_case.invalidators) + invalidators

    # De-duplicate
    seen: set[str] = set()
    invalidators = [x for x in invalidators if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]

    # ── Structural warnings ───────────────────────────────────────────────────
    warnings: list[str] = []
    if ws.uncertainty_level == "HIGH":
        warnings.append("high_uncertainty: interpret with caution")
    if len(evidence_for) > 0 and len(evidence_against) > 0:
        if len(evidence_against) >= len(evidence_for):
            warnings.append("conflicting_signals: evidence_against >= evidence_for")
    if ws.data_quality_score < 0.50:
        warnings.append("low_data_quality: decision based on stale or missing data")

    return DecisionExplanation(
        symbol=ws.symbol,
        as_of=ws.as_of_date,
        action=action_val,
        action_confidence=action_decision.confidence,
        thesis=thesis,
        world_state_summary=ws.state_summary,
        state_rationale=state_rationale,
        trust_score=trust_score,
        trust_level=trust_level,
        trust_components=trust_components,
        data_quality_notes=data_quality_notes,
        input_warnings=input_warnings,
        evidence_for=evidence_for[:5],
        evidence_against=evidence_against[:5],
        invalidators=invalidators[:6],
        next_triggers=list(action_decision.next_triggers)[:4],
        scenario_summary=scenario.to_dict() if scenario else None,
        world_state=ws.to_dict(),
        warnings=warnings,
    )
