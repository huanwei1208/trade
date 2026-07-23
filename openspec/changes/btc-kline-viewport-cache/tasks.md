# Implementation Tasks

## 1. Specification and baseline

- [x] 1.1 Inspect current worktree state, chart component behavior, existing tests,
  and lightweight-charts visible range APIs without mutating real data.
- [x] 1.2 Record the viewport-cache proposal, design brief, governance marker,
  and acceptance criteria for the browser-local viewport behavior.

## 2. Frontend implementation

- [x] 2.1 Add focused, typed panel-owned viewport helpers for recent-window calculation, cache validation, restore, logical-date conversion, and persistence. `[validates:btc-kline.viewport-state] [validation:test]`
- [x] 2.2 Wire `ExchangeKlineChart` to apply a cached viewport or recent-month default after data load, while preserving full loaded history and existing mouse/touch interactions. `[validates:btc-kline.viewport-state] [validation:test]`
- [x] 2.3 Update Fit and Newest controls so Fit shows all loaded history and Newest restores the recent-window view ending at the newest candle. `[validates:btc-kline.viewport-state] [validation:test]`

## 3. Validation and delivery

- [x] 3.1 Add focused unit tests for recent default, cache restore/fallback, persistence, chart visible-range application, and owner callback wiring. `[validates:btc-kline.viewport-state] [validation:test]`
- [ ] 3.2 Run focused frontend unit tests, typecheck, build, repository checks, and `git diff --check`. `[validates:btc-kline.viewport-state] [validation:test]`
- [ ] 3.3 Inspect final diff/status and commit only intentional files.
