# PIT Evidence Coverage Report (WP0 sample)

Generated read-only from the live data root on 2026-07-19 via
`generate_pit_coverage.py`. This is an observational snapshot; values change with
runs and MUST NOT be hardcoded into product logic.

## Summary

| Field | Value |
| --- | --- |
| asset_id | `crypto.BTC` |
| contract_version | `btc-data-v1` |
| run_count | 9 |
| earliest_proven_knowledge_time | `2026-07-12T16:25:33.309440+00:00` |
| has_precise_stage_times | `false` |
| publication_ledger_events | 2 |
| rollback_ledger_events | 0 |
| revision_ledger_present | `true` |

## Providers / data families

- primary: okx / BTC-USDT / 1Dutc
- shadow: binance / BTCUSDT / 1d
- data families: ohlcv, reconciliation, revisions, findings

## Intervals

| Interval | Coverage |
| --- | --- |
| proven | `>= 2026-07-12T16:25:33Z` (first immutable receipt) |
| partial | none (no precise stage receipts recorded) |
| unproven | `< 2026-07-12T16:25:33Z` for `installation_observed` |

## Supportable knowledge modes

- `market_available` (uses `available_at`; historical backfill allowed with
  `backfilled` provenance)
- `installation_observed` only from `earliest_proven_knowledge_time` forward

## Gap reason codes

- `LEGACY_TIME_UNPROVEN` — manifests lack `staged_at`/`assurance_completed_at`/
  `capture_completed_at`; the legacy adapter orders deterministically but cannot
  prove precise stage time.
- `PIT_NOT_PROVEN_BEFORE_EARLIEST_RECEIPT` — `installation_observed` queries before
  the first immutable receipt return `PIT_NOT_PROVEN`.

## Observed lifecycle state (informational)

- Formal current run `f2fd765097dcf21f16074fb3` at watermark 2026-07-11.
- Latest evaluated candidate `cdbbb5c608ba22b1c4aa06b0` at watermark 2026-07-18,
  `degraded` (D1 acquisition stability insufficient), 725 canonical rows.
- This is exactly the `observed_watermark > formal_watermark` gap the Observatory
  must surface. Tests use frozen fixtures; only real-data smoke records the actual
  runtime watermarks.

## Notes

`installation_observed` queries before `earliest_proven_knowledge_time` return
`PIT_NOT_PROVEN`; filesystem mtime is never used to fabricate history.
