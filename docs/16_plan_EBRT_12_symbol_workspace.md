# EBRT_12 — Symbol Page: Holding Decision Workspace

**Date**: 2026-03-21
**Status**: ✅ Complete

---

## 1. Objective

Refactor the Symbol page from a "generic explanation page" into a true **Holding Decision Workspace** that directly answers: *"Given the current data, can I hold this stock?"*

---

## 2. Problem Statement

Current Symbol page problems:
- Trust/belief score are visually dominant — they are quality gates, not primary facts
- Daily return computed from last 2 OHLCV bars (fragile, ignores prev_close column)
- No MA lines, no RSI/MACD/KDJ subpanel on chart
- No quote block (prev_close, change_pct, open, high, low)
- Evidence items are vague ("technical bullish") without concrete metric facts
- Chart has belief overlay enabled by default (misleading)
- Layout: chart-left + rail-right — doesn't support 4-layer workspace hierarchy
- Kline API returns indicator metadata only, not per-bar MA/RSI/MACD/KDJ arrays

---

## 3. Scope

### Backend
- Upgrade `/api/kline/{symbol}` to add `adjust` and `timeframe` params
- Add per-bar indicator columns to OHLCV rows: ma5/10/20/60, rsi14, macd_hist/cross, kdj_k/d/j/cross
- Add `quote` block: latest_price, prev_close, change, change_pct, open, high, low, volume, amount, turnover
- Add `price_basis` block: adjust mode, timeframe, latest_trade_date
- Add `ReasonItem` dataclass to `explanation.py`
- Add `reason_groups: dict` field to `DecisionExplanation`
- Generate factual grouped reasons from indicator data in `ExplanationService`

### Frontend
- New `SymbolQuoteStrip.tsx` — dominant price display, change, secondary stats
- New `SymbolChartToolbar.tsx` — timeframe selector, adjust mode, indicator toggle
- New `SymbolDecisionPanel.tsx` — recommendation, trust, blockers, actionability
- New `SymbolReasonBoard.tsx` — grouped reasons (7 groups)
- Refactor `SymbolChart.tsx` — add MA lines, proper volume colors, RSI/MACD/KDJ subpanel, no default belief overlay
- Refactor `SymbolPage.tsx` — 4-layer layout
- Simplify `SymbolDecisionHeader.tsx` — identity + back only (quote strip replaces price stats)
- Update `api.ts` — new types
- Update `i18n.tsx` — new keys
- Rebuild `pages.css` — new sections

---

## 4. Phases

### Phase 1 — Plan doc (this file) ✅
### Phase 2 — Backend: kline API upgrade + indicators + quote ✅
### Phase 3 — Backend: grouped reasons (ReasonItem + reason_groups) ✅
### Phase 4 — Frontend: API types ✅
### Phase 5 — Frontend: new components (QuoteStrip, Toolbar, DecisionPanel, ReasonBoard) ✅
### Phase 6 — Frontend: SymbolChart refactor (MA, volume, indicator subpanel) ✅
### Phase 7 — Frontend: SymbolPage layout refactor ✅
### Phase 8 — Frontend: CSS rebuild ✅
### Phase 9 — Build + verify ✅

---

## 5. Acceptance Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Plan doc created first | ✅ |
| 2 | `/api/kline/{symbol}` includes per-bar ma5/ma20/rsi14/macd_hist/kdj_k values | ✅ |
| 3 | `/api/kline/{symbol}` includes `quote` block with prev_close, change, change_pct | ✅ |
| 4 | `/api/kline/{symbol}` includes `price_basis` block | ✅ |
| 5 | `reason_groups` field present in explanation, contains factual reasons | ✅ |
| 6 | Quote strip visible with dominant price + change | ✅ |
| 7 | Chart shows MA lines (MA5, MA20 minimum) | ✅ |
| 8 | Chart shows volume bars with up/down coloring | ✅ |
| 9 | Chart has RSI or MACD subpanel switchable | ✅ |
| 10 | Decision panel shows recommendation + trust as qualifier (not hero) | ✅ |
| 11 | Reason board shows grouped concrete reasons | ✅ |
| 12 | Belief overlay not shown by default on main chart | ✅ |
| 13 | Freshness banner demoted below quote strip | ✅ |
| 14 | Advanced/model context in collapsible section | ✅ |
| 15 | Daily return uses backend-provided prev_close (not fragile last-2-bars) | ✅ |
| 16 | Build succeeds with no TypeScript errors | ✅ |

---

## 6. Implementation Progress

| File | Change | Status |
|------|--------|--------|
| `docs/16_plan_EBRT_12_symbol_workspace.md` | Plan doc | ✅ |
| `trade_py/decision/explanation.py` | Add ReasonItem + reason_groups | ✅ |
| `trade_py/services/explanation_service.py` | Upgrade _read_ohlcv, add reason gen | ✅ |
| `trade_web/backend/app.py` | Add adjust/timeframe params | ✅ |
| `trade_web/frontend/src/lib/api.ts` | New types | ✅ |
| `trade_web/frontend/src/components/SymbolQuoteStrip.tsx` | New | ✅ |
| `trade_web/frontend/src/components/SymbolChartToolbar.tsx` | New | ✅ |
| `trade_web/frontend/src/components/SymbolDecisionPanel.tsx` | New | ✅ |
| `trade_web/frontend/src/components/SymbolReasonBoard.tsx` | New | ✅ |
| `trade_web/frontend/src/components/SymbolChart.tsx` | Add MA/RSI/MACD, no default belief | ✅ |
| `trade_web/frontend/src/pages/SymbolPage.tsx` | 4-layer layout | ✅ |
| `trade_web/frontend/src/components/SymbolDecisionHeader.tsx` | Simplify to identity | ✅ |
| `trade_web/frontend/src/lib/i18n.tsx` | New keys | ✅ |
| `trade_web/frontend/src/styles/pages.css` | New sections | ✅ |

---

## 7. Key Design Decisions

### Quote Block Source of Truth
- Use `prev_close` column from parquet (stored by akshare fetcher) rather than last-2-bars calculation
- Quote block included in `/api/kline/{symbol}` response
- Frontend derives price stats from `kline.quote.*`, NOT from `kline.ohlcv[-1] - ohlcv[-2]`

### Price Basis
- akshare KlineFetcher stores front-adjusted (qfq) data by default
- `price_basis.adjust = "qfq"` annotates this in the response
- UI shows "前复权" label next to chart, tooltip explains basis

### Indicator Strategy
- Per-bar indicators computed in ExplanationService._read_ohlcv using rolling calculations
- Included inline in each bar dict (ma5, ma10, ma20, ma60, rsi14, etc.)
- Frontend uses these for SVG path rendering

### Reason Groups
Generated from indicator values on latest N bars:
- price_trend: 1d/5d/20d return, price vs MA20
- technical: RSI state, MACD direction, KDJ cross
- volume_liquidity: volume ratio vs 20d average
- event_sentiment: from evidence_for/against where source includes event/sentiment
- belief_uncertainty: trust score state, uncertainty level
- counter_argument: from evidence_against (non-event/sentiment)
- invalidation: from invalidators list

### Chart Subpanel
- Default: RSI14 subpanel visible
- Can switch to: MACD / KDJ / none
- Belief overlay moved to optional advanced mode (off by default)
