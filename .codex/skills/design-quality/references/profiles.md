# Impact profiles

Declare every impact in `design-quality.toml`. `applies = false` still requires a
specific reason grounded in the proposed change.

For every selected profile, populate each policy-named field under
`[evidence.<profile>]`. Markdown keywords and generic prose do not satisfy these
fields. Impact-signal regexes only surface contradictions when an impact is declared
false; they are never approval evidence.

## Public contract

Use `public_contract` for CLI/API/payload/schema/engine interfaces. Document consumers,
compatibility, migration/default/fallback behavior, versioning, and rollback.

## Persistent write and schema migration

Use `persistent_write` and/or `schema_migration` for DB, parquet, cache, manifest, or
durable file writes. Cover the authoritative writer, idempotency key, locking/CAS,
staging and validation, atomic visibility, crash windows, partial results, reader
consistency, backup/hash verification, rollback, and audit evidence.

For migrations, use the policy's typed transition structure: preserve the old version,
declare backward and forward compatibility, dual-read/write, non-destructive
checkpointed backfill, readiness-gated cutover, restorable rollback, and a bounded
legacy-retirement window.

## Point-in-time and predictive work

Use `point_in_time` and/or `predictive_model` for forecasts, recommendations, ranks,
labels, backtests, or time-sensitive features. Cover decision/event/publication/
first-seen/available/revision clocks, timezone, knowledge and universe policy,
coverage, label maturity, leakage tests, evidence identity, out-of-sample population
and window, horizon, metrics, sample count, uncertainty, regimes, baseline,
calibration lifecycle, promotion criteria, and explicit unavailable behavior.

Pending, stale, unavailable, or uncalibrated evidence must not become an ordinary
numeric prediction, neutral score, or success state.

Use the exact typed values declared by the active policy. Each forecast clock table
has its own source enum, sample count is positive, state fields are enums, and
`no_numeric_fallback` is the boolean `true`.

## External-event data

Use `external_event_data` for news, social, macro, on-chain, and third-party event
feeds. Cover all temporal clocks, provenance/licensing, empty/partial/unavailable/
rate-limited/invalid/stale states, quota/cost, retry classification, circuit breaking,
bounded queues/backpressure, poison/DLQ/replay, corrections/tombstones/finality, and
degraded-mode semantics.

These are typed policy contracts: distinct clock-source enums, a known stable source
ID/kind, approved provenance state bound to the same source and a non-placeholder
reference, licensing, complete state sets, finite positive bounds, enabled
idempotency with source/event keys and bounded deduplication, approved enums,
mandatory DLQ/replay/backpressure/tombstone booleans, and clock tables with explicit
fallback/timezone/confidence. Do not substitute prose strings.

## Runtime concurrency

Use `runtime_concurrency` for parallel workers, shared state, queues, or batch
orchestration. Define bounded concurrency, ownership, ordering, atomicity, timeout,
cancellation, backpressure, partial failure aggregation, and capacity tests.
