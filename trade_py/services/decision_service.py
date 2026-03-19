"""DecisionService — derives ScenarioSummary + ActionDecision from WorldState.

Thin delegation layer: all actual logic lives in scenario.py and action.py.
This service exists so the API handlers have a single, mockable entry-point.
"""
from __future__ import annotations

from trade_py.decision.world_state import WorldState
from trade_py.decision.scenario import ScenarioSummary, build_scenario_summary
from trade_py.decision.action import ActionDecision, derive_action_decision


class DecisionService:
    """Derive trading decision from WorldState.

    Parameters
    ----------
    inference
        Optional InferenceService instance.  When provided, composite_score
        and model_risk are pulled from its predictions instead of relying on
        the WorldState's raw window_score alone.
    """

    def __init__(self, inference=None) -> None:
        self._inference = inference

    # ── Public API ────────────────────────────────────────────────────────────

    def decide(
        self,
        ws: WorldState,
        *,
        has_position: bool = False,
    ) -> tuple[ScenarioSummary, ActionDecision]:
        """Return (ScenarioSummary, ActionDecision) for a WorldState.

        If an InferenceService is available, its composite_score and
        model_risk are passed through to derive_action_decision.
        """
        scenario = build_scenario_summary(ws)

        composite_score, model_risk = self._get_model_estimates(ws)

        action = derive_action_decision(
            ws,
            composite_score=composite_score,
            model_risk=model_risk,
            has_position=has_position,
        )
        return scenario, action

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_model_estimates(
        self, ws: WorldState
    ) -> tuple[float | None, float | None]:
        """Pull composite_score and model_risk from inference layer if possible."""
        if self._inference is None:
            return None, None
        try:
            preds = self._inference.predict([ws.symbol])
            p = preds.get(ws.symbol) or {}
            return p.get("model_score"), p.get("model_risk")
        except Exception:
            return None, None
