# EBRT_06 — Decision Workspace UI Redesign

**Date**: 2026-03-20
**Status**: ✅ Complete

---

## 1. Diagnosis (current problems)

| Problem | Evidence |
|---------|---------|
| Ops dominates front stage | "Today / Picks / Pipeline" — 3 equal tabs, pipeline is a DAG console |
| Candidates = score table | model_score / window_score / kg_score / net_sentiment — doesn't answer "what should I do?" |
| No Symbol page | Symbol detail is a 420px side panel inside Picks — too cramped for real explainability |
| Explainability fragmented | trust gate bar, kline-side reasons, belief overlay, endpoint-local heuristics — not unified |
| Chart semantics weak | No event marker overlays, no belief strip, no regime strip, no decision zone — just bars |
| TypeScript types lag backend | KlineData still has `predicted_return_5d` (old); no WorldState / DecisionExplanation types |
| kline endpoint fat | Inline recommendation heuristics (rsi/vol/sentiment scoring) in route handler — not using services |
| Fake certainty risk | `prediction.predicted_return_5d` shown in UI without calibration warning |

---

## 2. New Information Architecture

```
TODAY         CANDIDATES      SYMBOL          OPS
─────────     ──────────      ──────────────  ───────────
thesis        action table    decision header  DAG
market state  + side panel    chart + overlays workflow history
trust gate    (explain on     explanation      data health
action cards  click)          panel            job runs
blockers      → Symbol →      world state
[runs]                        scenario
```

Navigation order reflects user task priority:
- Decision first → Exploration second → Operations backstage

---

## 3. Modules

| File | Change | Status |
|------|--------|--------|
| `docs/10_plan_EBRT_06.md` | New plan | ✅ |
| `trade_web/backend/app.py` | Enrich today-page, signals-page; kline + explain; thin kline handler | ✅ |
| `trade_web/frontend/src/App.tsx` | Full restructure: 4 pages, new types, chart overlays | ✅ |
| `trade_web/frontend/src/styles.css` | New layout classes for decision workspace | ✅ |

---

## 4. Backend Changes

### 4.1 `/api/today-page` payload enrichment
Add to `_today_page_payload()`:
- `today_thesis`: string — from top ADD/PROBE candidate's thesis
- `market_regime`: string — from StateService.build() on a representative symbol
- `blockers`: list[str] — from trust gate + missing data
- `top_actions`: enriched picks with `action`, `confidence`, `thesis`, `trust_score`

### 4.2 `/api/signals-page` enrichment
For top 20 picks, add:
- `action`, `confidence`: from DecisionService.decide(ws)
- `thesis`: from ScenarioSummary or WorldState.state_summary
- `trust_score`, `trust_level`: from StateService freshness
- `world_state_summary`: from WorldState.state_summary
- `top_invalidators`: list[str] (max 2) for table display

### 4.3 `/api/kline/{symbol}` — add explanation
Append `explanation: _explain_svc.explain(symbol).to_summary_dict()` to the existing response.
Remove inline recommendation heuristics (rsi/vol/net_sent scoring). The explanation service covers it.

---

## 5. Frontend Changes

### 5.1 New TypeScript types (aligned with backend)
```ts
type WorldState = { market_regime, event_regime, sentiment_regime, technical_regime,
                    uncertainty_level, blockers, state_summary, trust_score, data_quality_score }
type ActionDecision = { action, confidence, score, risk, reason, invalidators, next_triggers,
                        supporting_factors, opposing_factors }
type EvidenceItem = { source, direction, strength, description, weight }
type DecisionExplanation = { symbol, as_of, action, action_confidence, thesis,
                             world_state_summary, state_rationale, trust,
                             evidence_for, evidence_against, invalidators,
                             next_triggers, scenario_summary, warnings,
                             data_quality_notes, input_warnings }
type CandidateRow = { symbol, name, action, confidence, score, risk, thesis,
                      trust_score, trust_level, world_state_summary, top_invalidators }
```

### 5.2 Navigation: 4 pages
```ts
type PageKey = "today" | "candidates" | "symbol" | "ops"
```
Symbol page is navigated to by clicking a symbol anywhere (today cards, candidates table).
Back button returns to previous page.

### 5.3 Today page layout
```
[market regime pill] [trust badge] [date]
[thesis text — 1-2 lines]
[blocker strip — conditional]
[action cards × 5 — flex row]
  card: symbol / action / confidence / one-line thesis / [→]
[▶ recent runs — collapsed <details>]
```

### 5.4 Candidates page layout
```
[action filter pills: ALL / ADD / PROBE / WATCH]
[table: SYMBOL | ACTION | CONF | TRUST | THESIS | INVALIDATORS]
→ row click: side panel slides in
  panel: full DecisionExplanation summary
  [Open Full Detail →] → navigates to Symbol page
```

### 5.5 Symbol page layout (main new feature)
```
[← Back] SYMBOL NAME [ACTION] [CONF] [TRUST] [date]
[Thesis line]
[Invalidators inline: • item1 • item2]
─────────────────────────────────────────────────────
chart (left ~60%)      │ explanation panel (right ~40%)
  regime strip          │  Evidence For
  OHLCV candlesticks    │  Evidence Against
  event markers         │  World State
  decision zone         │  Scenario Summary
  belief overlay        │  Next Triggers
  trust indicator       │  Data Quality
  volume               │  Blockers
```

### 5.6 Chart overlay semantics (SVG)
| Overlay | Backend source | Semantics |
|---------|---------------|-----------|
| Candlesticks | `kline.ohlcv` | Price action |
| Event markers | `kline.event_markers` | △ pos / ▽ neg / ○ neutral |
| Decision zone | `explanation.action` | Tinted area (green=ADD, yellow=PROBE/WATCH) |
| Belief line | `kline.belief_overlay` | mu line + ±sigma band |
| Trust indicator | `explanation.trust.trust_level` | Corner badge, not a fake strip |
| Regime labels | `kline.world_state.*_regime` | Text labels in chart header |
| Volume | `kline.ohlcv[].volume` | Bar chart sub-panel |

**Explicitly NOT rendered:**
- Predicted future K-line paths
- Deterministic price targets
- Any overlay without a direct backend object

---

## 6. Interaction Flows

### Flow A: Today → Symbol
```
Today page loads → shows top action cards
User clicks card → navigates to Symbol page (symbol + back=today)
Symbol page loads kline + explain in parallel
Chart renders with semantic overlays
Explanation panel shows evidence_for/against/blockers
```

### Flow B: Candidates → Symbol
```
Candidates page loads signals-page (enriched)
User selects row → side panel shows explain summary
User clicks [Full Detail] → navigates to Symbol page
```

### Flow C: Ops (backstage)
```
Ops page = existing Pipeline functionality
DAG visualization + workflow history + job runs
SSE streaming kept
```

---

## 7. Temporary Simplifications

1. Trust strip over time: only show today's trust as a badge (no historical strip — no data)
2. Invalidation price line: not rendered (backend returns text, not price levels)
3. Regime over time: only show current regime as labels (no historical regime strip)
4. Scenario band: show bull/base/bear probability table, not a chart band
5. Hover-sync chart↔explanation: not implemented in Phase 1 (too complex, deferred)

---

## 8. Build + Verify

```bash
cd trade_web/frontend
npm install
npm run build

# Serve
./trade web  # or: uv run python -m trade_py.cli.main web

# Verify endpoints
curl -s http://localhost:8080/api/today-page | python3 -m json.tool | grep -E "today_thesis|top_actions|blockers"
curl -s http://localhost:8080/api/signals-page | python3 -m json.tool | grep -E '"action"' | head -5
curl -s http://localhost:8080/api/explain/600000.SH | python3 -m json.tool | grep -E "action|thesis|trust"
```
