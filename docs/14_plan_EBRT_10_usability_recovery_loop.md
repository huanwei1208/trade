# EBRT_10 — Usability Recovery Loop: Make It Actually Usable

**Date**: 2026-03-20
**Status**: ✅ Complete

---

## 1. Objective

Turn the current "high-quality product shell" into a genuinely usable, auditable, operational decision workspace. The user must be able to complete the full loop: discover constrained conclusions → inspect data readiness → backfill / replay → see recovery timeline → return to refreshed front-stage outputs.

---

## 2. Problem Statement

Despite strong architecture (DAG-driven readiness, EventBus, recovery hooks, i18n layer), the product still has critical usability gaps:

| Area | Problem |
|------|---------|
| SymbolChart | Empty state shows raw English: "No chart context" / "Historical OHLCV is not available" — not actionable |
| SymbolChart | Toolbar labels ("volume", "events", "belief", "zones"), legend ("Decision overlay", "Last close"), footer ("Market context", "Latest bar", "Vol"), SVG strip ("UNKNOWN", "Trust") — all raw English |
| SymbolPage | World state grid labels ("Market", "Event", "Sentiment", "Technical", "Liquidity", "Uncertainty") — hardcoded English |
| OpsPage | Trust tab has "Trust" / "Coverage" hardcoded; stage summary has "err" / "running" raw strings |
| TodayPage | Diagnostic section uses hardcoded "Pipeline" label |
| CandidatesPage | Trust filter buttons show raw "HIGH" / "MEDIUM" / "LOW" |
| statusText.ts | `getGateStatusText` does not handle "error" or "running" → falls through to "未知/Unknown" for failed nodes |
| ExplanationRail | Scenario labels use `humanizeEnum` → "Bull Case" / "Base Case" — not i18n |
| Symbol empty state | Cannot tell if empty chart is due to missing OHLCV, constrained readiness, or no history |
| Recovery loop | Already implemented but empty state of SymbolChart lacks CTA to readiness/recovery |

---

## 3. Scope

This pass is a **semantic + i18n + empty-state + failure-path** pass. All back-stage readiness/recovery infrastructure was already built (EBRT_05–09). This pass wires it into the front-stage decision surfaces and fixes leakage.

Out of scope (already done):
- Readiness heatmap structure
- BackfillActionPanel wiring
- RecoveryTimeline component
- Backend /api/readiness-grid and /api/readiness/backfill endpoints

In scope:
- Fix all raw English in user-facing decision surfaces
- Fix getGateStatusText for "error" / "running"
- Improve SymbolChart empty state to be context-aware and actionable
- Pass onOpenReadiness / onOpenRecovery callbacks into SymbolChart
- Add missing i18n keys (25+ new entries per locale)
- Fix world state labels in SymbolPage
- Fix trust filter labels in CandidatesPage
- Fix hardcoded "Pipeline" in TodayPage diagnostics
- Fix Trust/Coverage/err/running in OpsPage trust tab + stage summary
- Translate scenario labels in ExplanationRail

---

## 4. Phases

### Phase 1 — Plan doc + semantics + i18n foundation (this phase)
- Create this doc ✅
- Add new i18n keys (symbol chart layers, legends, footers, world state labels, scenario labels, status labels)
- Fix `getGateStatusText` to handle "error" and "running"

### Phase 2 — SymbolChart failure path + English cleanup
- Fix empty state: context-aware (no OHLCV vs readiness constrained vs explanation available)
- Add `onOpenReadiness` / `onOpenRecovery` callbacks to SymbolChart
- Fix all raw English in chart toolbar, SVG legend/strip, footer
- Pass callbacks from SymbolPage to SymbolChart

### Phase 3 — SymbolPage, OpsPage, TodayPage, CandidatesPage cleanup
- Fix SymbolPage world state labels
- Fix OpsPage trust/coverage strings + stage summary
- Fix TodayPage "Pipeline" label
- Fix CandidatesPage trust filter labels
- Fix ExplanationRail scenario labels

### Phase 4 — Progress doc finalization
- Update this table with final status

---

## 5. Acceptance Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Plan doc created before code | ✅ |
| 2 | getGateStatusText handles "error" and "running" (no more "未知" for failed nodes) | ✅ |
| 3 | SymbolChart empty state is context-aware and shows CTA | ✅ |
| 4 | SymbolChart toolbar, legend, strip, footer are fully i18n'd | ✅ |
| 5 | SymbolPage world state grid uses translated labels | ✅ |
| 6 | OpsPage trust tab uses i18n for Trust/Coverage | ✅ |
| 7 | OpsPage stage summary uses i18n for err/running counts | ✅ |
| 8 | TodayPage diagnostic section uses t("ops.tabs.pipeline") | ✅ |
| 9 | CandidatesPage trust filter uses i18n labels | ✅ |
| 10 | ExplanationRail scenario labels use i18n | ✅ |
| 11 | No raw English visible on Symbol page in zh-CN mode | ✅ |
| 12 | Repo remains runnable after changes | ✅ |

---

## 6. Implementation Progress

| File | Change | Status |
|------|--------|--------|
| `docs/14_plan_EBRT_10_usability_recovery_loop.md` | New plan doc | ✅ |
| `trade_web/frontend/src/lib/i18n.tsx` | Added 36 new keys (chart layers, world state, scenario, trust filter, ops trust, status) | ✅ |
| `trade_web/frontend/src/lib/statusText.ts` | Added "error" / "running" cases to getGateStatusText | ✅ |
| `trade_web/frontend/src/components/SymbolChart.tsx` | Context-aware ChartEmptyState with CTA; i18n toolbar/legend/strip/footer; removed unused areaPath import | ✅ |
| `trade_web/frontend/src/pages/SymbolPage.tsx` | World state labels → t(); pass onOpenReadiness/onOpenRecovery to SymbolChart | ✅ |
| `trade_web/frontend/src/pages/OpsPage.tsx` | Trust tab i18n (Trust/Coverage); stage summary i18n (err/running); workflows "No root cause" i18n | ✅ |
| `trade_web/frontend/src/pages/TodayPage.tsx` | "Pipeline" → t("ops.tabs.pipeline"); pipeline error count uses t("status.error"); labelizeDataset → getDatasetText | ✅ |
| `trade_web/frontend/src/pages/CandidatesPage.tsx` | Trust filter labels HIGH/MEDIUM/LOW → i18n | ✅ |
| `trade_web/frontend/src/components/ExplanationRail.tsx` | Scenario labels use t(`scenario.{key}`) with humanizeEnum fallback | ✅ |
| `trade_web/frontend/src/components/DecisionHero.tsx` | labelizeDataset → getDatasetText for dataset blocker items | ✅ |

---

## 7. Risks / Assumptions

- **SVG text nodes**: Cannot use JSX components inside SVG `<text>` elements; must call `t()` directly to get string values. ✅ Compatible — `useI18n()` returns `t` function that returns strings.
- **Backend enum values**: `state.market_regime`, `state.technical_regime` come from backend as raw strings like "TRENDING_UP". We translate via existing `getWorldStateLabel()`. ✅ Already implemented.
- **Scenario labels**: `explanation.scenario_summary[key].label` is backend-controlled text. We add i18n keys using the known schema keys ("bull_case", "base_case", "bear_case") and fall back to humanizeEnum for unknown values.
- **SymbolChart callbacks**: Adding `onOpenReadiness?` / `onOpenRecovery?` props to SymbolChart is additive — no existing consumers break since they are optional.
- **Trust filter i18n**: CandidatesPage uses TrustFilter type = "ALL" | "HIGH" | "MEDIUM" | "LOW"; i18n is display-only, filter logic stays on English enum.

---

## 8. Architecture / Workflow Notes

### Empty state hierarchy for SymbolChart

```
bars.length === 0 and:
  explanation != null AND explanation.trust?.trust_score > 0
    → "解释结果可用，但价格历史暂缺" + CTA to readiness
  kline != null (loaded) AND kline.ohlcv is empty
    → "OHLCV 数据暂未就绪" + CTA to readiness + CTA to recovery
  kline == null
    → "标的数据未加载" (but this is handled by ErrorState before reaching SymbolChart)
  otherwise
    → Generic empty state + CTA to readiness
```

### Status semantics for error / running

`getGateStatusText` currently handles: ok, partial, blocked, degraded, missing + default (unknown).
Missing: "error" → should map to "异常/Error" with "err" tone.
Missing: "running" → should map to "运行中/Running" with "info" tone.
This prevents failed job nodes from displaying "未知" as primary failure label.

### i18n key additions (new keys, both locales)

Chart layers: `symbol.chartLayer.{volume,events,belief,zones}`
Chart legend: `symbol.chartLegend.{decisionOverlay,lastClose,vol}`
Chart footer: `symbol.chartFooter.{marketContext,latestBar}`
Chart empty: `symbol.chartEmpty`, `symbol.chartEmptyCopy`, `symbol.chartEmptyExplanationAvailable`, `symbol.chartEmptyReadinessCause`
World state: `symbol.worldStateLabel.{market,event,sentiment,technical,liquidity,uncertainty}`
Ops: `ops.trust.scalar`, `ops.trust.coverageLabel`, `ops.stage.error`, `ops.stage.running`
Status: `status.error`, `status.running`
Scenarios: `scenario.bull_case`, `scenario.base_case`, `scenario.bear_case`
Trust filter: `candidates.trust.all`, `candidates.trust.high`, `candidates.trust.medium`, `candidates.trust.low`
