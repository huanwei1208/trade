# EBRT_13 — Symbol Page: Internal Workspace Tabs

**Date**: 2026-03-21
**Status**: ✅ Complete

---

## 1. Objective

Surgical upgrade adding 4 second-level tabs **inside** the Symbol page.
No top-level navigation changes. All existing behavior (QuoteStrip, FreshnessBanner,
readiness/recovery hooks, 3 data fetches) is preserved.

---

## 2. Tab Architecture

```
SymbolQuoteStrip      (unchanged — always visible)
SymbolFreshnessBanner (unchanged — always visible)
SymbolWorkspaceTabs   [Decision | Belief | Timeline | Data/Trust]
TabBody (conditional):
  decision  → ChartWorkspace + DecisionPanel + ReasonBoard + slim ExplanationRail + DecisionChangeStrip
  belief    → BeliefWorkspace (Funnel/Waterfall/Compare) + BeliefNodeInspector
  timeline  → BeliefCausalTimeline (trend line + causal event cards)
  data-trust → DataTrustPanel (DQS, trust breakdown, provenance, warnings)
```

Tab persistence: `localStorage("trade-web:symbol-workspace-tab")`
Default tab: `decision`

---

## 3. Scope

### Backend
- `GET /api/belief-graph/{symbol}` — returns layered belief structure

### Frontend
- New `SymbolWorkspaceTabs.tsx` — segmented tab bar (4 tabs)
- New `DecisionChangeStrip.tsx` — compact what-changed signals
- New `BeliefWorkspace.tsx` — container with Funnel/Waterfall/Compare mode toggle
- New `BeliefCausalTimeline.tsx` — belief trend + causal event cards
- New `DataTrustPanel.tsx` — DQS + trust + provenance + warnings
- Modify `ExplanationRail.tsx` — add `slim` prop
- Modify `SymbolPage.tsx` — add tab state + beliefGraphResource + tab body rendering
- Update `api.ts` — `BeliefGraphResponse` + related types
- Update `i18n.tsx` — new keys for all 4 tabs
- Append `pages.css` — new CSS sections

---

## 4. Phases

### Phase 1 — Plan doc (this file) ✅
### Phase 2 — Backend: /api/belief-graph endpoint ✅
### Phase 3 — Frontend: API types ✅
### Phase 4 — Frontend: SymbolWorkspaceTabs + DecisionChangeStrip ✅
### Phase 5 — Frontend: BeliefWorkspace + BeliefCausalTimeline + DataTrustPanel ✅
### Phase 6 — Frontend: ExplanationRail slim prop + SymbolPage tab wiring ✅
### Phase 7 — Frontend: i18n keys + CSS ✅
### Phase 8 — Build + verify ✅

---

## 5. Acceptance Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Plan doc created first | ✅ |
| 2 | Tab bar visible below FreshnessBanner | ✅ |
| 3 | Active tab persisted in localStorage | ✅ |
| 4 | Decision tab: chart + decision panel + reasons + rail visible | ✅ |
| 5 | Belief tab: funnel/waterfall/compare view modes switchable | ✅ |
| 6 | Timeline tab: belief trend line + causal event cards | ✅ |
| 7 | Data/Trust tab: DQS + trust breakdown + warnings | ✅ |
| 8 | `/api/belief-graph/{symbol}` returns non-empty response | ✅ |
| 9 | Graceful degradation when belief-graph returns empty | ✅ |
| 10 | No fabricated causal relationships | ✅ |
| 11 | SymbolQuoteStrip always visible regardless of tab | ✅ |
| 12 | SymbolFreshnessBanner always visible regardless of tab | ✅ |
| 13 | Build succeeds with no TypeScript errors | ✅ |

---

## 6. Implementation Progress

| File | Change | Status |
|------|--------|--------|
| `docs/17_plan_EBRT_13_symbol_workspace_tabs.md` | Plan doc | ✅ |
| `trade_web/backend/app.py` | Add /api/belief-graph endpoint | ✅ |
| `trade_web/frontend/src/lib/api.ts` | BeliefGraphResponse types | ✅ |
| `trade_web/frontend/src/lib/i18n.tsx` | New i18n keys | ✅ |
| `trade_web/frontend/src/components/SymbolWorkspaceTabs.tsx` | New | ✅ |
| `trade_web/frontend/src/components/DecisionChangeStrip.tsx` | New | ✅ |
| `trade_web/frontend/src/components/BeliefWorkspace.tsx` | New | ✅ |
| `trade_web/frontend/src/components/BeliefCausalTimeline.tsx` | New | ✅ |
| `trade_web/frontend/src/components/DataTrustPanel.tsx` | New | ✅ |
| `trade_web/frontend/src/components/ExplanationRail.tsx` | Add slim prop | ✅ |
| `trade_web/frontend/src/pages/SymbolPage.tsx` | Tab state + wiring | ✅ |
| `trade_web/frontend/src/styles/pages.css` | New sections | ✅ |

---

## 7. Key Design Decisions

### Tab Persistence
- Store active tab in `localStorage("trade-web:symbol-workspace-tab")`
- Read on mount, write on change
- Invalid/unknown values fall back to `"decision"`

### Belief Graph Backend
- Composes data from existing belief history, recommendation, trust components
- Sub-beliefs derived from trust.components (data_quality, kline, sentiment, events)
- Factors derived from top_attention scores
- Provenance edges: factor → sub_belief connections (only if attention weight > threshold)
- No fabricated causal reasoning — only express what the data actually provides

### ExplanationRail Slim Mode
- `slim` prop hides: scenario_summary, trust_components bars, data_quality_notes
- These sections move to DataTrustPanel in the data-trust tab
- Evidence + invalidators + next_triggers remain in slim mode

### Graceful Degradation
- Belief tab shows empty/placeholder state if `/api/belief-graph` returns no sub_beliefs
- Timeline tab shows belief overlay from kline data if belief history is empty
- DataTrustPanel falls back to DQS + warnings from kline/explain resources if belief-graph unavailable
