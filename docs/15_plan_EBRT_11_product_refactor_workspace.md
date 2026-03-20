# EBRT-11: Product Refactor — Workspace Quality Pass

**Date:** 2026-03-21
**Status:** In progress
**Scope:** TodayPage, CandidatesPage, SymbolPage, OpsPage, BackfillActionPanel

---

## 1. Critical Diagnosis

### OVERBUILT / REMOVE

| Area | Detail |
|------|--------|
| TodayPage "Recent Activity" section | `recentRuns`, `failedNodes`, `noteworthyEvents` panels are system engineering dashboards, not trader morning briefings. They mislead users into treating pipeline health as the primary concern when the primary concern is whether action is possible today. |
| OpsPage trust/workflows tabs prominence | Trust and Workflows tabs are not daily-use features. Their current tab position (5th and 6th of 6) is fine but the default tab (`overview`) is wrong — readiness is what operators check first. |

### FAKE USEFUL

| Area | Detail |
|------|--------|
| NoteworthyEvents panel | `eventsResource.today_events` rarely populates, so the panel is almost always empty. Showing an empty panel with a heading misleads users into thinking events are being monitored. |
| Pipeline health counts in TodayPage diagnostics | Counts like "3 healthy · 1 error" are not actionable from the Today view. The user cannot act on them without going to OpsPage, and TodayPage already has a link to readiness. |
| TrustAndFreshness CollapseSection open by default | Detailed freshness data should be secondary; opening it by default buries the more actionable top-setups section visually. |

### UNDERBUILT

| Area | Detail |
|------|--------|
| SymbolDecisionHeader | No price/return/volume data visible. Users open a symbol workspace but cannot see the latest close without reading the chart carefully. |
| CandidateTable | No quantitative comparison metrics. The `thesis` column is qualitative text that cannot be compared across rows. `belief_delta_mu` and `confidence` exist in the API but are not shown. |
| BackfillActionPanel | No operator chain visible. Users trigger "Replay downstream" but cannot see which jobs will be triggered. `plan.downstream_nodes` exists in the API. |
| Trust breakdown in CandidateQuickPanel | Trust exists as a badge only. The components breakdown (`explanation.trust.components`) is never surfaced outside ExplanationRail. |
| DataQuality panel in SymbolPage | Shows only note-cards (freeform strings). `WorldState.data_quality_state` has structured fields (`missing_datasets`, `stale_datasets`, `freshness_score`, `score`) that would make the panel actionable. |

### RIGHT DIRECTION BUT WEAK

| Area | Detail |
|------|--------|
| DataQuality panel (SymbolPage) | Has the right position in the layout but is unstructured. |
| CandidateQuickPanel | Good panel structure but missing trust breakdown and structured data quality section. |
| OperatingMode signal | DecisionHero shows a posture but it is not prominent enough. Users spend time reading the hero content when the primary signal should be "can I act today or not?" |

---

## 2. Page-by-Page Refactor Changes

### TodayPage

| Change | Rationale |
|--------|-----------|
| Add `OperatingModeBanner` as the topmost element (before DecisionHero) | Makes the "ACTIONABLE / REVIEW-ONLY / BLOCKED" determination immediately visible without reading narrative text. |
| Banner mode logic: `blocked` if `global_blocked`; `review` if `trust_gate.operational_status` includes "research" or "browse", or `trust_scalar < 0.4`; `actionable` otherwise | Deterministic derivation from existing API fields. |
| Keep DecisionHero unchanged | Still useful for narrative context below the banner. |
| Keep top setups section unchanged | Core decision content. |
| Set `trustAndFreshness` CollapseSection to `initialOpen=false` | Reduces visual noise; freshness detail is secondary. |
| **REMOVE** entire "Recent Activity" section (recentRuns + failedNodes + noteworthyEvents) | Engineering data that does not serve morning decision workflow. |
| Add `onOpenCandidates` prop wired through App.tsx | Banner's "View priority candidates" button needs a navigation handler. |
| ActionCard gains `belief_delta_mu` and `confidence` stats row | Adds quantitative context to action cards without cluttering the header. |

### CandidatesPage / CandidateTable

| Change | Rationale |
|--------|-----------|
| Replace "thesis" column with "belief change" column (`belief_delta_mu` + trust badge + event tags) | `thesis` text is not comparable across rows; quantitative delta is. |
| Move thesis summary to one-line subtitle in identity column | Context preserved but demoted to secondary. |
| Remove invalidator from table row | Too noisy in comparison context; available in QuickPanel. |
| Update column header from "Thesis" to "Belief Change" | Matches new column content. |

### CandidateQuickPanel

| Change | Rationale |
|--------|-----------|
| Add trust breakdown section (from `explanation.trust.components`) with bar visualization | Makes trust score interpretable without entering ExplanationRail. |
| Add data quality section (structured note-cards for `input_warnings` and `data_quality_notes`) | Surfaces quality issues in the comparison panel where they affect the review decision. |
| Improve blocked state display | Consistent with updated QuickPanel structure. |

### SymbolPage / SymbolDecisionHeader

| Change | Rationale |
|--------|-----------|
| Add price/return/volume stats strip to header (from `kline.ohlcv`) | Latest close, daily return, and volume are the first things a trader wants when reviewing a symbol. |
| DataQuality panel uses `WorldState.data_quality_state` structured fields | `missing_datasets`, `stale_datasets`, `freshness_score`, `score` are structured and actionable. |
| Fallback to old note-cards if `data_quality_state` unavailable | Backward compatibility. |
| WorldState panel moved to last position in supporting context | Most contextual, least immediately actionable. |

### OpsPage

| Change | Rationale |
|--------|-----------|
| Reorder tabs: readiness → recovery → overview → pipeline → trust → workflows | Readiness is what operators check first. Overview is useful but secondary. |
| Change default tab from `"overview"` to `"readiness"` | Operators arriving at Ops almost always want readiness, not overview. |

### BackfillActionPanel

| Change | Rationale |
|--------|-----------|
| Add operator chain display from `plan.downstream_nodes` | Users need to know which jobs will run before triggering replay. |
| Add confirmation caption text before action buttons | Warning text should appear before the submit buttons, not after. |
| Reorder: confirmation caption → action buttons → results | Logical flow: inform → act → see result. |

---

## 3. Phase-Based Implementation Plan

### Phase 1 — i18n and infrastructure (no visual impact)
1. Add i18n keys for new UI text (both zh-CN and en-US)
2. Verify no TypeScript breaks in existing components

### Phase 2 — TodayPage refactor
1. Write `OperatingModeBanner` component (inline in TodayPage)
2. Add `onOpenCandidates` prop and wire through App.tsx
3. Remove "Recent Activity" section
4. Set trustAndFreshness to `initialOpen=false`
5. Add `belief_delta_mu` stats row to ActionCard

### Phase 3 — CandidateTable and CandidateQuickPanel
1. Rewrite CandidateTable with quant band column
2. Add trust breakdown + data quality sections to CandidateQuickPanel

### Phase 4 — SymbolPage and SymbolDecisionHeader
1. Add price/return/volume stats strip to SymbolDecisionHeader
2. Rewrite DataQuality panel in SymbolPage using structured `data_quality_state`

### Phase 5 — OpsPage tab reorder and BackfillActionPanel
1. Reorder OpsPage tabs, change default tab
2. Add operator chain display to BackfillActionPanel
3. Add confirmation caption, reorder layout

### Phase 6 — CSS additions
1. Add all new component styles to pages.css
2. Verify responsive behavior at 1200px breakpoint

---

## 4. Acceptance Criteria

| ID | Criterion | Status |
|----|-----------|--------|
| AC-01 | OperatingModeBanner renders ACTIONABLE/REVIEW-ONLY/BLOCKED with correct color on TodayPage | TBD |
| AC-02 | OperatingModeBanner "View priority candidates" button navigates to CandidatesPage | TBD |
| AC-03 | OperatingModeBanner "Data recovery" button opens OpsPage recovery tab | TBD |
| AC-04 | TodayPage "Recent Activity" section is fully removed | TBD |
| AC-05 | TrustAndFreshness CollapseSection is collapsed by default | TBD |
| AC-06 | ActionCard shows belief_delta_mu with sign (+ green / - red) and confidence | TBD |
| AC-07 | CandidateTable "Belief Change" column shows trust badge + delta + event tags | TBD |
| AC-08 | CandidateTable identity column has thesis as one-line subtitle | TBD |
| AC-09 | CandidateQuickPanel shows trust breakdown bars when `explanation.trust.components` is populated | TBD |
| AC-10 | CandidateQuickPanel shows structured quality notes section | TBD |
| AC-11 | SymbolDecisionHeader shows latest close, daily return, and volume strip | TBD |
| AC-12 | Daily return is color-coded (green positive, red negative) | TBD |
| AC-13 | SymbolPage DataQuality panel shows structured table when `data_quality_state` is present | TBD |
| AC-14 | SymbolPage DataQuality panel falls back to note-cards when `data_quality_state` is absent | TBD |
| AC-15 | BackfillActionPanel shows operator chain from `plan.downstream_nodes` | TBD |
| AC-16 | BackfillActionPanel confirmation caption appears before action buttons | TBD |
| AC-17 | OpsPage default tab is "readiness" | TBD |
| AC-18 | OpsPage tab order is readiness → recovery → overview → pipeline → trust → workflows | TBD |
| AC-19 | All new UI strings appear in both zh-CN and en-US | TBD |
| AC-20 | No TypeScript compilation errors after all changes | TBD |
| AC-21 | Banner is responsive (column layout below 1200px) | TBD |
| AC-22 | No regression on existing CollapseSection, DecisionHero, ExplanationRail behavior | TBD |

---

## 5. Implementation Progress

| Task | File | Status |
|------|------|--------|
| Task 1 | docs/15_plan_EBRT_11_product_refactor_workspace.md | TBD |
| Task 2 | trade_web/frontend/src/lib/i18n.tsx | TBD |
| Task 3 | trade_web/frontend/src/pages/TodayPage.tsx | TBD |
| Task 4 | trade_web/frontend/src/components/CandidateTable.tsx | TBD |
| Task 5 | trade_web/frontend/src/components/CandidateQuickPanel.tsx | TBD |
| Task 6 | trade_web/frontend/src/components/SymbolDecisionHeader.tsx | TBD |
| Task 7 | trade_web/frontend/src/pages/SymbolPage.tsx | TBD |
| Task 8 | trade_web/frontend/src/components/BackfillActionPanel.tsx | TBD |
| Task 9 | trade_web/frontend/src/pages/OpsPage.tsx (tab reorder) | TBD |
| Task 10 | trade_web/frontend/src/App.tsx (onOpenCandidates) | TBD |
| Task 11 | trade_web/frontend/src/styles/pages.css (CSS additions) | TBD |
