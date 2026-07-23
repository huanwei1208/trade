## Context

The current cross-asset module combines provider calls, merge policy, parquet
publication, local reads, and fallback behavior. Its writer and reader disagree
on the storage path; provider identity and quote currency are discarded; and a
read can create a DB and fetch from the network. The existing BTC file can seed
a migration audit but cannot establish finality or provider lineage.

This change is the C0-C3 implementation slice from the Crypto child plan. It
must work for a single local user, keep tests offline, preserve the existing CLI
entry, and avoid modifying real data until an explicitly invoked validated
publish run.

## Goals / Non-Goals

**Goals:**

- Separate pure reads, provider acquisition, validation, and publication.
- Capture OKX BTC-USDT UTC daily bars and CoinGecko BTC-USD daily shadow closes
  without mixing them.
- Produce deterministic readiness, reconciliation, manifest, revision, and
  rollback evidence.
- Implement the pre-registered BTC volatility-persistence study with explicit
  insufficient/invalid states and no directional recommendation.
- Keep the old CLI syntax and flat canonical BTC path compatible.

**Non-Goals:**

- ETH, Gold/FX repair, Crypto news validation, live Web work, automatic trading,
  portfolio optimization, DB migration, or C++ acceleration.
- Treating CoinGecko as a silent OHLC fallback or treating old untracked files
  as verified raw history.

## Decisions

### 1. Split readers from synchronization use cases

`DataGateway.get_cross_asset()` becomes a canonical-path pure reader. A new
Crypto market-data service owns provider calls, validation, run creation, and
publication. Existing callers keep the read method, but a missing file returns
an explicit degraded report instead of fetching.

Alternative rejected: retaining read-through with an `offline` option. The
default would remain unsafe and tests could still mutate caller data roots.

### 2. Store provider-native captures separately

OKX and CoinGecko adapters return normalized provider frames with lineage. Raw
captures remain separate by provider/instrument/run. The canonical series is
always based on completed OKX `BTC-USDT` `1Dutc` bars; CoinGecko contributes only
daily USD close reconciliation evidence.

Alternative rejected: merging both into one OHLC frame. Different instruments,
quotes, and OHLC granularities make such fallback semantically invalid.

### 3. Model validation as run artifacts

A deterministic `run_id` derives from contract version, input payload hashes,
config, effective as-of, and the implementation revision covering contracts,
gates, orchestration, and storage. A run directory contains normalized provider
data, reconciliation, readiness, revision, canonical candidate, and manifest.
The flat compatibility parquet changes only after successful validation. Under
an exclusive lock, publication verifies the predecessor, replaces the parquet,
and then switches the current pointer. Readers verify the pointer hash and fail
closed during any cross-file mismatch; the pointer records its predecessor for
rollback.

Alternative rejected: updating the parquet and manifest independently during
fetch. A partial failure would produce untraceable or mismatched state.

### 4. Separate data and signal states

Data readiness uses `invalid`, `insufficient_data`, `ready`, or `degraded`.
Signal validation uses `candidate`, `monitoring`, `validated`, or `rejected`.
Signal validation cannot claim `validated` unless data is ready. Reason codes
and evidence are preserved rather than collapsed into a scalar trust score.

### 5. Pre-register a non-directional volatility study

The validation module computes trailing 20-day annualized volatility, an
expanding past-only 80th-percentile regime threshold, and future seven-day
realized volatility/absolute return labels. It evaluates non-overlapping events
with expanding 180/60 walk-forward folds and a seven-day purge/embargo.

The primary effect is the median future-volatility ratio for high-volatility
versus normal days. `validated` additionally requires a ratio of at least 1.10,
a fixed-seed block-bootstrap lower bound above 1.0, BH q at most 0.10, and
positive effects in at least two-thirds of valid folds.

Alternative rejected: tuning thresholds on the same full sample or reporting
only an in-sample t-statistic. Both invite leakage and overstate evidence.

The four additive Crypto ADS tables use a single current-generation pointer as
their visibility boundary. Writers serialize lifecycle calculation and table
replacement, write a completion receipt, then switch the pointer. Readers hold
the shared lock and filter every table to that pointer's run ID. Flat-table
"last row" reads are not a supported current-state contract.

### 6. Preserve CLI compatibility through additive modes

`trade data cross-asset btc` remains a synchronization alias. Add
`--mode sync|validate|status`, `--dry-run`, `--strict`, and `--json`. The
warehouse command adds the `crypto-btc-v1` profile without requiring Web changes.

## Risks / Trade-offs

- [CoinGecko credentials or availability are missing] -> Store OKX raw evidence
  but return degraded and do not advance the validated current manifest.
- [USDT/USD basis legitimately widens] -> Preserve both prices and quarantine;
  never rewrite or average the providers.
- [Existing BTC history lacks lineage] -> Treat it as a migration seed only;
  readiness remains insufficient until qualified captures cover the required
  window or an explicitly audited import is recorded.
- [Atomic replacement is not multi-file transactional] -> Publish immutable run
  artifacts first, use predecessor compare-and-swap under an exclusive lock,
  replace the compatibility file, and move the small current pointer last.
  Readers verify the pair and return degraded instead of serving a mismatch;
  retain predecessor hashes for repair.
- [Bootstrap/FDR adds compute cost] -> The BTC-only daily sample is small; fixed
  iteration limits and deterministic seeds keep local runtime bounded.
- [Strict gates delay a validated result] -> `insufficient_data` is an intended
  outcome and preferable to a misleading score.

## Migration Plan

1. Add code and tests using only temporary roots and frozen provider fixtures.
2. Run `status`/`validate` read-only against a copied sample; do not publish.
3. Hash and snapshot the existing canonical BTC parquet before the first live
   run.
4. Execute dry-run and compare dates, rows, returns, and reconciliation output.
5. Publish only after D0-D4 pass; retain the prior file and manifest reference.
6. Roll back by verifying the predecessor hash, atomically restoring the prior
   compatibility file/pointer, and rerunning structural gates.
7. Apply the metadata-only DAG migration that adds `crypto_btc_fetch` to the
   daily 09:00 `gate.crypto_daily` while retaining Gold/FX on `gate.morning`;
   rollback disables the two new Crypto DAG rows.

## Open Questions

None for C0-C3. Gold/FX provider qualification and Crypto-native news sources
are deliberately deferred to separate changes.
