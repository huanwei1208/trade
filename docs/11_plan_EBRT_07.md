# EBRT_07 — Premium TradeDB Decision Workspace

**Date**: 2026-03-20
**Status**: ✅ Complete

---

## 1. Why the current UI still fails

| Problem | Impact |
|---------|--------|
| `App.tsx` is a monolith | UI logic, data fetching, chart rendering, page state, and ops views are coupled and hard to evolve safely |
| Decision UX is weak | Today/Candidates do not answer "can I act, on what, and why" with enough hierarchy |
| Symbol is not first-class | Deep review is cramped and cannot act as the product centerpiece |
| Ops competes visually with trading pages | System runtime noise dilutes decision workflow confidence |
| Failure states are brittle | Candidates can degrade into a useless naked "Failed to fetch" path |
| Styling is console-grade | Layout, spacing, hierarchy, and visual semantics are not premium enough |

---

## 2. Target product structure

Top-level navigation:

1. `Today`
2. `Candidates`
3. `Symbol`
4. `Ops`

Primary workflow:

1. Read today's posture and blockers
2. Triage candidates with confidence/trust/invalidation context
3. Deep-dive one symbol with synchronized chart + explanation
4. Inspect ops only if execution quality or data quality must be verified

---

## 3. Implementation shape

### Frontend structure

```text
trade_web/frontend/src/
  App.tsx
  main.tsx
  components/
  pages/
  lib/
  styles/
```

Planned modules:

- `components/AppShell.tsx`
- `components/TopNav.tsx`
- `components/PanelCard.tsx`
- `components/DecisionHero.tsx`
- `components/CandidateTable.tsx`
- `components/CandidateQuickPanel.tsx`
- `components/SymbolDecisionHeader.tsx`
- `components/SymbolChart.tsx`
- `components/ExplanationRail.tsx`
- `components/StatusPill.tsx`
- `components/ActionChip.tsx`
- `components/TrustBadge.tsx`
- `components/MetricCard.tsx`
- `components/SectionHeader.tsx`
- `components/EmptyState.tsx`
- `components/ErrorState.tsx`
- `components/LoadingSkeleton.tsx`
- `components/RetryInline.tsx`
- `components/CollapseSection.tsx`
- `pages/TodayPage.tsx`
- `pages/CandidatesPage.tsx`
- `pages/SymbolPage.tsx`
- `pages/OpsPage.tsx`
- `lib/api.ts`
- `lib/chart.ts`
- `lib/format.ts`
- `lib/ui.ts`
- `styles/tokens.css`
- `styles/base.css`
- `styles/layout.css`
- `styles/components.css`
- `styles/pages.css`

### Backend alignment

Keep existing endpoints, but allow small payload enrichment where needed:

- `GET /api/today-page`
- `GET /api/signals-page`
- `GET /api/kline/{symbol}`
- `GET /api/explain/{symbol}`
- `GET /api/state/{symbol}`
- `GET /api/actions-page`
- `GET /api/trust/overview`
- `GET /api/events-page`
- `GET /api/dag/runtime`
- `GET /api/status`

Potential backend adjustments:

- tighten today-page blocker semantics
- expose candidate-friendly invalidator/evidence summary consistently
- expose richer kline payload semantics for chart overlays if current response is too thin

---

## 4. Design system tokens

Required palette:

- `--bg-0: #06111f`
- `--bg-1: #08182b`
- `--bg-2: #0d2138`
- `--bg-3: #102845`
- `--panel: rgba(10, 24, 44, 0.88)`
- `--panel-strong: rgba(12, 28, 50, 0.96)`
- `--panel-soft: rgba(11, 23, 40, 0.72)`
- `--line: rgba(112, 156, 214, 0.14)`
- `--line-strong: rgba(112, 156, 214, 0.24)`
- `--text-0: #eaf2ff`
- `--text-1: #c7d7f2`
- `--text-2: #96accd`
- `--text-3: #6f87a8`
- `--accent-blue: #2a9dff`
- `--accent-cyan: #3dd9d6`
- `--accent-indigo: #6c7cff`
- `--accent-violet: #8b74ff`
- `--ok: #28c864`
- `--warn: #ffb432`
- `--err: #ff5b6e`
- `--info: #39c0ff`

System decisions:

- dark-only shell
- desktop-first layout
- left sidebar + in-content utility bar
- premium glass-panel cards
- restrained motion only
- chart overlays must map directly to backend semantics

---

## 5. Delivery checklist

### Phase A — Plan and architecture

- [x] Inspect current frontend/backend state
- [x] Create `docs/11_plan_EBRT_07.md`
- [x] Finalize modular file structure

### Phase B — Frontend foundation

- [x] Create shared design tokens and CSS layers
- [x] Add reusable panel, pills, buttons, empty/error/loading components
- [x] Build shell with sidebar + top utility bar
- [x] Add shared fetch/retry helpers

### Phase C — Decision pages

- [x] Redesign Today page
- [x] Redesign Candidates page
- [x] Implement Symbol page as premium workspace
- [x] Persist selected symbol/candidate state if low-cost

### Phase D — Ops page

- [x] Rebuild Ops page with clear backstage hierarchy
- [x] Keep runtime/data health/trust/workflows readable but secondary

### Phase E — Backend alignment and verification

- [x] Apply minimal backend payload adjustments if needed
- [x] Build frontend successfully
- [x] Run targeted verification
- [x] Mark plan complete

---

## 6. Progress log

### 2026-03-20

- Confirmed current frontend is still centered on a large single-file `App.tsx`
- Confirmed backend already exposes decision-oriented endpoints sufficient for a real redesign
- Confirmed docs naming sequence should continue from `10_plan_EBRT_06.md`
- Started implementation plan in this document; progress updates will continue here
- Replaced the old frontend shell with a modular app structure: `components/`, `pages/`, `lib/`, `styles/`
- Implemented premium dark design tokens and split CSS layers: tokens/base/layout/components/pages
- Added reusable state components: loading skeletons, empty states, error states, retry inline, collapsible diagnostics
- Rebuilt Today as a decision-first page with hero, blocker-aware top setup strip, and compact diagnostics/activity sections
- Rebuilt Candidates as a triage workbench with sticky filters, selected row state, quick review rail, and stale-cache fallback
- Implemented Symbol as a first-class decision workspace with header, semantic SVG chart, explanation rail, and supporting context sections
- Rebuilt Ops as a backstage console with tabbed overview/pipeline/data health/trust/workflows sections
- Enriched backend payloads:
  - `GET /api/today-page` now returns `decision_posture`, `global_blocked`, `blocker_details`, `safe_to_view`, `recovery_condition`, plus `sparkline`/`event_tags` on `top_actions`
  - `GET /api/signals-page` now returns `sparkline` and `event_tags` for candidates
  - `GET /api/kline/{symbol}` now delegates core chart context building to `ExplanationService.build_kline_context()`
- Verification completed:
  - `npm run build` in `trade_web/frontend` ✅
  - `python -m compileall trade_web/backend/app.py trade_py/services/explanation_service.py trade_py/services/state_service.py` ✅
