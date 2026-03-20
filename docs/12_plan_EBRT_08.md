# EBRT_08 — Readiness, Recovery, and Auditability Upgrade

**Date**: 2026-03-20
**Status**: ✅ Completed

---

## 1. Objective

This pass upgrades TradeDB from a strong-looking decision workspace into an auditable operating surface that can answer:

1. Can I trust today's conclusion?
2. Which dataset/day is missing, partial, changed, or replaying?
3. What outputs are affected?
4. Can I backfill and replay directly from the UI?
5. Did changed data actually trigger downstream recomputation?

---

## 2. Core gaps being fixed

| Gap | Current issue | Target |
|-----|---------------|--------|
| Status semantics | Raw `UNKNOWN`, `partial`, `ok`, `DEGRADED` leak to users | Product-language status layer in zh-CN + en |
| Readiness history | Only "current snapshot" exists in Ops | Day-level dataset readiness heatmap |
| Recovery UX | No integrated repair path from UI | Inspect → backfill → replay → audit timeline |
| Deep links | Product pages do not send users into recovery context | Today / Candidates / Symbol jump into focused readiness view |
| Auditability | Missing distinction between missing / repaired / changed | Changed-data detection + replay state |
| Layout resilience | Dense cards still overflow on long text | Safe wrapping, truncation, shrink behavior, scroll discipline |

---

## 3. Implementation phases

### Phase 1 — status semantics + i18n cleanup + overflow/layout fixes

- [x] Add shared i18n provider/dictionary for current UI surfaces
- [x] Add status semantics helper layer for decision/readiness/trust/gate language
- [x] Remove raw `UNKNOWN` / `partial` / `ok` from primary decision-facing copy
- [x] Update Today / Candidates / Symbol / Ops to use semantic labels
- [x] Fix current overflow issues and layout brittleness
- [ ] Verify app builds and commit Phase 1

### Phase 2 — Ops readiness tab + heatmap + inspector

- [x] Add new Ops tab structure with `readiness` and `recovery`
- [x] Add backend `GET /api/readiness-grid`
- [x] Implement readiness summary strip
- [x] Implement day-level dataset heatmap
- [x] Implement inspector panel with dataset/day detail and impact scope
- [ ] Verify app builds and commit Phase 2

### Phase 3 — backfill / replay actions + backend endpoints

- [x] Add backend `POST /api/readiness/backfill`
- [x] Add backend `GET /api/readiness/replay-plan`
- [x] Add backend readiness history / recovery timeline support
- [x] Implement recovery action panel in UI
- [x] Wire real backfill + downstream replay execution paths
- [ ] Verify app builds and commit Phase 3

### Phase 4 — changed-data detection + deep-link integration

- [x] Add backend changed-data detection endpoint / derived state
- [x] Surface `changed`, `replaying`, `replayed` in readiness model
- [x] Add deep links from Today / Candidates / Symbol into Ops readiness/recovery
- [x] Preserve focused date/dataset/tab state through query string and local storage
- [x] Final verification and commit Phase 4

---

## 4. Backend strategy

Use existing assets wherever possible:

- `dataset_snapshots` for daily evaluation history and metadata fingerprints
- `daily_quality_gate` for daily gate results
- `data_gaps` for gap state
- `data_repair_runs` for repair/backfill audit trail
- `pipeline_dag` + `job_runs` + `event_log` for replay orchestration and runtime audit

Planned additions:

- readiness grid payload builder
- dataset/day semantic state derivation
- replay plan builder from dataset → downstream jobs / impact areas
- background backfill + replay trigger endpoint
- changed-data / replay-pending resolution

---

## 5. Frontend strategy

Planned additions:

- `src/lib/i18n.tsx`
- `src/lib/statusText.ts`
- readiness/recovery components
- improved semantic banners and CTA paths on Today / Candidates / Symbol
- robust text containment and shrink rules

---

## 6. Progress log

### 2026-03-20

- Confirmed the current modular frontend is the correct base for the next pass
- Confirmed existing backend already has useful primitives:
  - `dataset_snapshots`
  - `daily_quality_gate`
  - `data_gaps`
  - `data_repair_runs`
  - `pipeline_dag`
  - `job_runs`
  - `event_log`
- Confirmed real DAG nodes already exist for `kline_update`, `fund_flow_update`, `fundamental`, `sentiment_*`, `event_extract`, `kg_propagate`, `belief_update`, `recommend`
- Started Phase 1
- Added shared frontend i18n provider and bilingual dictionary in `trade_web/frontend/src/lib/i18n.tsx`
- Added semantic status mapping helpers in `trade_web/frontend/src/lib/statusText.ts`
- Integrated semantic labels into App shell, Today, Candidates, Symbol, and Ops surfaces
- Replaced primary decision-facing raw statuses with product-language copy
- Added layout resilience rules for dense cards, lists, rail panels, and failure summaries
- Verified `cd trade_web/frontend && npm run build`
- Started Phase 2
- Added backend readiness aggregation in `trade_web/backend/readiness.py`
- Added `GET /api/readiness-grid` and hooked it into FastAPI snapshot caching
- Reworked Ops tabs into `overview / readiness / recovery / pipeline / trust / workflows`
- Implemented readiness summary cards, dataset heatmap, tooltip, and sticky inspector
- Verified `python -m compileall trade_web/backend/app.py trade_web/backend/readiness.py`
- Started Phase 3
- Added recovery audit table `readiness_recovery_actions`
- Added backend recovery endpoints for replay plan, history, backfill, and replay execution
- Extended jobs so `fund_flow`, `fundamental`, `window_score`, `belief_update`, `recommend`, and `evaluate_daily` can consume date ranges
- Added recovery action panel with dry-run / backfill / replay controls in the Ops inspector
- Verified `cd trade_web/frontend && npm run build`
- Verified `python -m compileall trade_web/backend/app.py trade_web/backend/readiness.py trade_py/jobs/__init__.py trade_py/db/trade_db.py`
- Started Phase 4
- Added fingerprint-based changed-data detection endpoint and action fingerprints before/after recovery execution
- Surfaced `changed`, `replaying`, and `replayed` in readiness cell resolution
- Added App-level deep-link state for `opsTab/date/dataset`
- Added Today / Candidates / Symbol CTAs that jump directly into focused Ops readiness or recovery context
- Preserved focused Ops tab + selected dataset/day in local storage and query string
- Re-verified `cd trade_web/frontend && npm run build`
- Re-verified `python -m compileall trade_web/backend/app.py trade_web/backend/readiness.py trade_py/jobs/__init__.py trade_py/db/trade_db.py`
