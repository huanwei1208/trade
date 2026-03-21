# EBRT 15 - Latest Recommendation Chain Verification

## Goal

Close the latest-recommendation recovery loop with real data and verified APIs:

- repair freshness/status semantics against the real schema
- backfill latest upstream data needed for `2026-03-20`
- rerun the latest recommendation chain end to end
- verify every page/tab API against live payloads

## Progress

- [x] fix recovery job parameter mismatch for kline range repair
- [x] fix freshness/status semantics to read real sources instead of stale `sync_state` assumptions
- [x] fix symbol/event reads to use real `event_propagations + market_events`
- [x] fix `StateService` signals reads against the real `signals` schema
- [x] force payload snapshot invalidation when page payload semantics change
- [x] align `events-page` to latest effective market date instead of raw wall-clock day
- [x] backfill sentiment gold for `2026-03-19..2026-03-20`
- [x] rerun event extraction / propagation / signals / belief / recommendation / daily evaluation
- [x] execute formal readiness replay for `signals` and `fund_flow` on `2026-03-20`
- [x] verify Today / Candidates / Symbol / Ops APIs from a live local server
- [x] run targeted pytest and frontend build

## Data Recovery Notes

Live chain run completed for `2026-03-20`:

1. `sentiment_gold`
2. `event_extract`
3. `kg_propagate`
4. `window_score`
5. `belief_update`
6. `recommend`
7. `evaluate_daily`

Observed upstream limitations during fetch/backfill:

- BOE RSS feeds failed with DNS resolution errors
- EastMoney RSSHub feed timed out
- several symbol-level kline gap fills required fallback retries during `window_score`

Despite those upstream hiccups, the local store was repaired enough to produce current `2026-03-20`:

- sentiment bronze/silver/gold
- market events
- event propagations
- signals
- belief state
- recommendations
- daily quality gate

## Verified Outcomes

- `today-page` now rebuilds from fresh payloads and shows `TRENDING_UP`
- `signals-page` / `actions-page` now use current summaries instead of stale snapshot text
- `state/{symbol}` now reads actual signal columns and returns usable state
- `explain/{symbol}` and `kline/{symbol}` return usable symbol workspace data
- `events-page` now follows the latest market day and shows `2026-03-20` events
- readiness now shows `constrained: false` for `2026-03-20`
- recovery history for `signals` and `fund_flow` shows completed multi-step replay results

## Remaining Reality

- quality gate is still `partial`
- current reason is research maturity, not missing latest operational data:
  - `matured: labeled_propagation_ratio 0.0% < 5%`
- trust / quality gate still remain `partial` because research maturity is not yet sufficient; this is now a truthful model-quality constraint rather than a latest-data freshness failure
