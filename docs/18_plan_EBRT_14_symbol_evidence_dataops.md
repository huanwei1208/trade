# EBRT_14 — Symbol Page: Evidence + Data Ops Upgrade

**Date**: 2026-03-21
**Status**: ✅ Complete

---

## 1. Objective

Upgrade the Symbol page workspace tabs:
- Rename "Timeline" → **Evidence** (adds article/event evidence, sector context, peer table + belief timeline)
- Rename "Data/Trust" → **Data Ops** (symbol-level data coverage matrix + repair action bar)
- Keep "Decision" and "Belief" tabs unchanged
- Preserve existing Ops readiness/recovery flow (system-wide; untouched)

---

## 2. Tab Architecture (updated)

```
SymbolQuoteStrip      (unchanged)
SymbolFreshnessBanner (unchanged)
SymbolWorkspaceTabs   [Decision | Belief | Evidence | Data Ops]
TabBody:
  decision   → (unchanged from EBRT_13)
  belief     → (unchanged from EBRT_13)
  evidence   → SymbolEvidenceTab
                 ArticleEvidenceList  (market_events + Evidence rows)
                 SectorContextPanel   (sector name, heat, sentiment, peers)
                   PeerMiniTable      (symbol/name/1D/belief/trust)
                 BeliefCausalTimeline (existing — moved from old Timeline tab)
  data-ops   → SymbolDataOpsTab
                 SymbolDataCoverageMatrix  (multi-select domain rows)
                 SymbolRepairActionBar     (Re-pull/Replay/Preview/Mark-Verified/Open Full Ops)
```

Tab persistence key: `localStorage("trade-web:symbol-workspace-tab")`
Old "timeline" value → remapped to "evidence" on load.
Old "data-trust" value → remapped to "data-ops" on load.

---

## 3. Scope

### Backend (app.py)
- `GET /api/symbol-evidence/{symbol}` — article/event evidence + sentiment
- `GET /api/symbol-sector/{symbol}` — sector name + heat + peer comparison
- `GET /api/symbol-data-ops/{symbol}` — domain-level coverage matrix
- `POST /api/symbol-data-ops/repull` — trigger re-pull for selected domains
- `POST /api/symbol-data-ops/replay` — downstream replay
- `POST /api/symbol-data-ops/mark-verified` — mark domain verified

### Frontend
- Rename `WorkspaceTab` in api.ts: `"timeline" | "data-trust"` → `"evidence" | "data-ops"`
- Add new API types: `SymbolEvidenceResponse`, `SymbolSectorResponse`, `SymbolDataOpsResponse`
- Update `SymbolWorkspaceTabs.tsx`: rename tabs, add backward-compat remap
- New `SymbolEvidenceTab.tsx` — Evidence tab container
- New `ArticleEvidenceList.tsx` — event/article cards with sentiment/confidence
- New `SectorContextPanel.tsx` — sector name, heat, peer list container
- New `PeerMiniTable.tsx` — compact symbol/name/1D/belief/trust table
- New `SymbolDataOpsTab.tsx` — Data Ops tab container
- New `SymbolDataCoverageMatrix.tsx` — multi-select domain table
- New `SymbolRepairActionBar.tsx` — action buttons
- Update `SymbolPage.tsx` — swap Evidence/DataOps tab bodies, add 3 new API resources
- Update `i18n.tsx` — new keys for Evidence + Data Ops tabs
- Append `pages.css` — Evidence tab + Data Ops tab styles

---

## 4. Phases

### Phase 1 — Plan doc (this file) ✅
### Phase 2 — Backend: 3 GET + 3 POST endpoints ✅
### Phase 3 — Frontend: API types + tab rename ✅
### Phase 4 — Frontend: New components (Evidence tab) ✅
### Phase 5 — Frontend: New components (Data Ops tab) ✅
### Phase 6 — Frontend: SymbolPage wiring ✅
### Phase 7 — Frontend: i18n + CSS ✅
### Phase 8 — Build + verify ✅

---

## 5. Acceptance Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Plan doc created first | ✅ |
| 2 | "Timeline" tab renamed to "Evidence" | ✅ |
| 3 | "Data/Trust" tab renamed to "Data Ops" | ✅ |
| 4 | Old localStorage values remapped without error | ✅ |
| 5 | Evidence tab: article/event list renders (empty state if no data) | ✅ |
| 6 | Evidence tab: sector context + peer table renders | ✅ |
| 7 | Evidence tab: BeliefCausalTimeline still visible (moved) | ✅ |
| 8 | Data Ops: domain coverage matrix renders with rows | ✅ |
| 9 | Data Ops: multi-select + action bar (Re-pull/Replay/Mark-Verified) | ✅ |
| 10 | Data Ops: Open Full Ops navigates to system Ops page | ✅ |
| 11 | `/api/symbol-evidence/{symbol}` returns non-empty response | ✅ |
| 12 | `/api/symbol-sector/{symbol}` returns sector name + peers | ✅ |
| 13 | `/api/symbol-data-ops/{symbol}` returns domain rows | ✅ |
| 14 | POST repair endpoints accept payload + return job_id | ✅ |
| 15 | Build succeeds with no TypeScript errors | ✅ |

---

## 6. Implementation Progress

| File | Change | Status |
|------|--------|--------|
| `docs/18_plan_EBRT_14_symbol_evidence_dataops.md` | Plan doc | ✅ |
| `trade_web/backend/app.py` | 3 GET + 3 POST endpoints | ✅ |
| `trade_web/frontend/src/lib/api.ts` | New types + tab rename | ✅ |
| `trade_web/frontend/src/lib/i18n.tsx` | New i18n keys | ✅ |
| `trade_web/frontend/src/components/SymbolWorkspaceTabs.tsx` | Rename tabs + remap | ✅ |
| `trade_web/frontend/src/components/ArticleEvidenceList.tsx` | New | ✅ |
| `trade_web/frontend/src/components/SectorContextPanel.tsx` | New | ✅ |
| `trade_web/frontend/src/components/PeerMiniTable.tsx` | New | ✅ |
| `trade_web/frontend/src/components/SymbolEvidenceTab.tsx` | New | ✅ |
| `trade_web/frontend/src/components/SymbolDataCoverageMatrix.tsx` | New | ✅ |
| `trade_web/frontend/src/components/SymbolRepairActionBar.tsx` | New | ✅ |
| `trade_web/frontend/src/components/SymbolDataOpsTab.tsx` | New | ✅ |
| `trade_web/frontend/src/pages/SymbolPage.tsx` | Evidence/DataOps tab wiring | ✅ |
| `trade_web/frontend/src/styles/pages.css` | New sections | ✅ |

---

## 7. Key Design Decisions

### Evidence tab data sources
- `market_events` (sector-level): filtered by symbol's sector_code via sector_members
- `Evidence` table: 47 rows, `evidence_type="sentiment_gold"`, direction ±1.0
- Gold sentiment parquets: per-date per-sector files; symbol → sector via sector_members
- ArticleEvent table: 0 rows — show empty state gracefully
- Fallback chain: ArticleEvent → market_events → Evidence rows → empty state

### Sector context data sources
- sector_members: symbol → sector_code + industry_name
- signals table: peer symbols in same sector (score, action)
- BeliefState: peer mu values (latest)
- Recommendation: peer action/conviction

### Data Ops coverage matrix domains
```
Domain        Datasets
kline         kline parquet (daily OHLCV)
fund_flow     fund_flow parquet
fundamental   fundamental parquet
sentiment     sentiment gold parquet
events        market_events in DB (last 7 days)
belief        BeliefState in DB (latest)
recommend     Recommendation in DB (latest)
```
Status derived from: parquet file existence + modification date + DB row counts.

### Repair actions scope
- Re-pull: triggers `kline_update` / `fund_flow_update` etc. for this symbol only
  → For MVP: enqueue via EventBus or return a 202 "queued" response
- Replay: triggers downstream compute jobs for symbol
- Mark-Verified: sets `sync_state` record for domain+symbol to verified

### Open Full Ops
- Button in DataOps tab that calls `onOpenOpsFocus()` prop (already available)
- Jumps to Ops page → Readiness tab for this symbol's dataset
