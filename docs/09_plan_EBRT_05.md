# EBRT_05 — State-Centered Trading Decision Architecture

**Date**: 2026-03-19
**Status**: 🔄 In Progress

## Objective

Refactor from feature-model-trust system into a state-centered, explanation-first, no-action-first trading decision system with a coherent Web product structure.

## Architecture Target

```
factors/trust/freshness/belief/attention/signal
    ↓ StateService
WorldState          (market_regime, event_regime, sentiment_regime, ...)
    ↓ DecisionService
ScenarioSummary     (base/bull/bear case, confidence, triggers)
ActionDecision      (NO_ACTION|WATCH|PROBE|ADD|REDUCE|EXIT + reason)
    ↓ ExplanationService
DecisionExplanation (unified explanation contract)
    ↓ FastAPI endpoints
/api/state/{symbol}, /api/explain/{symbol}, /api/actions-page
/api/kline/{symbol}, /api/signals-page, /api/today-page (refactored)
```

## Modules

| Module | Role | Status |
|--------|------|--------|
| `trade_py/decision/world_state.py` | WorldState + regime sub-states | ✅ |
| `trade_py/decision/scenario.py` | ScenarioSummary + ScenarioCase | ✅ |
| `trade_py/decision/action.py` | DecisionAction enum + ActionDecision | ✅ |
| `trade_py/decision/explanation.py` | DecisionExplanation unified contract | ✅ |
| `trade_py/services/state_service.py` | Build WorldState from DB + factors | ✅ |
| `trade_py/services/decision_service.py` | Derive Scenario + Action | ✅ |
| `trade_py/services/explanation_service.py` | Build DecisionExplanation | ✅ |
| `trade_web/backend/app.py` | New endpoints + bug fix + thin handlers | ✅ |
| `README.md` | Fix startup instructions (./trade web) | ✅ |
| `tests/test_world_state.py` | WorldState builder tests | ✅ |
| `tests/test_decision_action.py` | ActionDecision tests | ✅ |
| `tests/test_explanation.py` | DecisionExplanation tests | ✅ |
| `tests/test_web_api_decision.py` | API endpoint tests | ⬜ (deferred — needs live DB) |

## Regime Inference Rules (rule-based, no ML)

### market_regime (from window_score)
- window_score > 70 → TRENDING_UP
- window_score < 30 → TRENDING_DOWN
- vol_ratio > 2.0 → VOLATILE
- else → SIDEWAYS

### event_regime (from kg_score, event_type, event markers)
- kg_score > 0.3 → POSITIVE_EVENT
- kg_score < -0.3 → NEGATIVE_EVENT
- no recent events → NO_EVENT
- else → NEUTRAL

### sentiment_regime (from belief_mu, net_sentiment)
- belief_mu > 0.1 AND net_sentiment > 0.1 → BULLISH
- belief_mu < -0.1 OR net_sentiment < -0.2 → BEARISH
- else → NEUTRAL

### technical_regime (from rsi_14)
- rsi < 35 → OVERSOLD
- rsi > 70 → OVERBOUGHT
- else → NEUTRAL

### uncertainty_level (from belief_sigma + trust_score)
- sigma > 0.4 OR trust_score < 0.4 → HIGH
- sigma < 0.2 AND trust_score > 0.7 → LOW
- else → MEDIUM

## ActionDecision Logic (no-action-first)

```
if uncertainty_level == HIGH → NO_ACTION (reason: "insufficient_evidence")
if data_quality_score < 0.5 → NO_ACTION (reason: "low_data_quality")
if trust_score < 0.4 → NO_ACTION (reason: "low_trust")
if market_regime == VOLATILE → WATCH (reason: "volatile_market")
if sentiment == BULLISH AND technical == OVERSOLD → PROBE
if sentiment == BULLISH AND technical != OVERBOUGHT → WATCH
if sentiment == BEARISH AND position → REDUCE
if score > 0.65 AND uncertainty == LOW → ADD
else → WATCH
```

## New API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/state/{symbol}` | Full WorldState |
| `GET /api/explain/{symbol}` | Full DecisionExplanation |
| `GET /api/actions-page` | Today's action candidates |
| `GET /api/trust/overview` | Portfolio-level trust summary |

## Bug Fixes

1. `/api/kline/{symbol}`: `_inference.predict(symbol)` → `_inference.predict([symbol])[symbol]`
2. README: `./trade ui` → `./trade web`
3. Move kline business logic to ExplanationService
4. Wire FreshnessReport into online explain path
