# 17 Plan - Recommendation Recovery Closeout

## Goal

Close the latest recommendation recovery chain end to end and verify the real tab APIs against live data.

## Progress

- Fixed recovery job argument mismatches for `kline`, sentiment, and `fund_flow`.
- Fixed latest-as-of resolution so Today / Candidates / Symbol / Readiness default to the latest effective market date instead of calendar `today`.
- Expanded `BeliefEngine` to include the current `signals` universe, allowing `belief_state` and `recommendation` to be rebuilt for `2026-03-20`.
- Prevented `window_score` from stalling the whole chain on symbols with zero local `fund_flow` coverage by falling back to a neutral large-order score.
- Corrected `StateService` freshness so `fund_flow` / `fundamental` can use snapshot coverage instead of being falsely reported as missing.
- Filtered `Recommendation` output to active tradable symbols only and cleared stale per-day recommendation rows before rewriting.
- Corrected `trust/overview` parsing and fixed Symbol kline loading to use local parquet data instead of a nonexistent helper import.

## Verified

- `2026-03-20` recommendations rebuilt to `5310` active symbols.
- `evaluate_daily('2026-03-20')` completed with gate `partial` because research maturity is still limited, not because the latest recommendation chain is missing.
- Real API checks were rerun for Today / Candidates / Symbol / Ops related endpoints after the rebuild.

## Remaining Product Reality

- The latest day is still decision-constrained by research maturity (`labeled_propagation_ratio 0.0% < 5%`), so the system remains in a constrained review mode rather than fully actionable mode.
- Recovery history currently records the interrupted batched attempts as errors because the final completion pass was executed directly to avoid a long-running per-symbol recovery loop. Data state is repaired, but the historical action log is intentionally honest about that operational shortcut.
