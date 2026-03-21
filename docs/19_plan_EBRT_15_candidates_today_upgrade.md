# EBRT_15 — Candidates & Today Page Upgrade

## Objective

Focused product/UX upgrade across Today + Candidates pages on top of the existing
workspace-first architecture. No broad redesign — additive enrichment only.

---

## Scope

### Candidates Page

- **Richer columns**: confidence, trust (symbol-level), belief μ, Δbelief, risk, factor summary chips
- **Sorting**: extended sort keys (belief, belief_delta, risk, risk_adjusted, latest); header click toggles asc/desc; risk defaults to asc
- **Factor placement rule**: Candidates = summary chips only (1 pos + 1 neg per row); full decomposition lives on Symbol page
- **CandidateQuickPanel**: adds quant row (belief μ / Δbelief / risk), recommendation_state badge, factor_summary section (multi-chip), data risk flag

### Today Page

- **Always show recommendations** — never hide even when system is blocked/constrained
- Split into two labeled groups: **Actionable** and **Constrained**
- When globally blocked: all actionable cards downgrade to constrained group
- Shows constraint hints (dataset + lag) in constrained group header
- ActionCard gets `constrained` / `constraintReason` props + badge label

### Backend Payload Extensions

`signals-page` and `today-page` payloads enriched with:
- `factor_summary: { positive: string[]; negative: string[] }` — from `ActionDecision.supporting_factors/opposing_factors`
- `data_risk_flag: string | null` — first world-state blocker text
- `recommendation_state: "ACTIONABLE" | "CONSTRAINED" | "BROWSE_ONLY"`

---

## Files Changed

| File | Change |
|------|--------|
| `trade_web/backend/app.py` | `_today_page_payload` + `_signals_page_payload` enrichment with factor_summary, data_risk_flag, recommendation_state; global_blocked downgrades ACTIONABLE→CONSTRAINED |
| `trade_web/frontend/src/lib/api.ts` | Added `RecommendationState`, `FactorSummary`; extended `CandidateRow` |
| `trade_web/frontend/src/lib/ui.ts` | Extended `CandidateSortKey`; `sortCandidates(rows, key, dir)` with direction param |
| `trade_web/frontend/src/components/CandidateTable.tsx` | Full rewrite: 9-column grid, column header buttons with sort indicators, FactorChips, rec-state badges |
| `trade_web/frontend/src/pages/CandidatesPage.tsx` | Added `sortDir` state + `handleSort()`; passes to CandidateTable |
| `trade_web/frontend/src/components/CandidateQuickPanel.tsx` | Added quant-row, rec-state badge, factor-summary section, data risk, confidence |
| `trade_web/frontend/src/pages/TodayPage.tsx` | Removed canRenderCards gate; displayActionable/displayConstrained split; labeled groups; constraint hints |
| `trade_web/frontend/src/lib/i18n.tsx` | New i18n keys for sort options, table columns, factor labels, rec-state labels, today groups |
| `trade_web/frontend/src/styles/components.css` | Updated candidate-table grid: 4-col → 9-col |
| `trade_web/frontend/src/styles/pages.css` | New CSS: sort indicators, factor chips, rec-state badges, belief-mu, risk-badge, qp-metric, today-rec-groups, action-card--constrained |

---

## New i18n Keys

```
candidates.sort.belief, .beliefDelta, .risk, .riskAdjusted
candidates.table.confidence, .trust, .belief, .delta, .risk, .factors, .pulse, .noName, .noInvalidator
candidates.constrained, .browseOnlyLabel
candidate.factorSummary, .factorPos, .factorNeg, .trustComponents, .constrainedNoAction
today.recGroupActionable, .recGroupConstrained, .recGroupBlockedAll
today.cardConstrained, .cardBrowseOnly, .cardWaitingRecovery
today.topSetupsActionable, .topSetupsConstrained
today.operatingModeActionable, .operatingModeReviewOnly, .operatingModeBlocked
today.mainConstraint
```

---

## Acceptance Criteria

- [x] Candidates table shows 9 columns: symbol | decision | confidence | trust | belief μ | Δbelief | risk | factors | pulse
- [x] Column headers are clickable; repeated click toggles asc/desc; risk defaults to asc
- [x] Factor chips: max 1 positive + 1 negative per row; compact labels (e.g., "trend↑")
- [x] Row shows ⚠ badge for CONSTRAINED, ○ badge for BROWSE_ONLY
- [x] Quick panel shows belief μ / Δbelief / risk metrics row
- [x] Quick panel shows rec-state badge when not ACTIONABLE
- [x] Quick panel shows factor summary chips (multi)
- [x] Quick panel shows data risk flag prominently
- [x] Today page always renders recommendation groups (no canRenderCards gate)
- [x] Actionable group label: green dot + label
- [x] Constrained group label: amber dot + label; shows blocker hint when globally blocked
- [x] ActionCard has constraint badge label based on recommendation_state
- [x] Backend: factor_summary/data_risk_flag/recommendation_state on both payloads
- [x] `npm run build` passes (0 TypeScript errors, 83 modules)

---

## Factor Placement Rule

> **Candidates page** = factor summary chips only (1 pos + 1 neg in table; up to all in quick panel)
> **Symbol page** = full factor decomposition (BeliefCausalTimeline, evidence tabs)

This is enforced in code comments and prop/class naming.

---

## Trust Distinction

> **Symbol-level trust** → shown on Candidates table, CandidateQuickPanel, Symbol header
> **System/portfolio trust** → shown in Today diagnostics (`today.trust_gate`)

Labelled clearly in UI to avoid confusion.
