# 23 Plan - Crypto Research Data Quality and Signal Validation

## 1. Document Status and Parent Plan

- Status: active implementation plan
- Parent: `docs/22_plan_analysis_first_research_system.md`
- Priority domain: Crypto
- First asset: BTC only
- Change: `crypto-data-assurance-and-validation-v1`

This document is the authoritative child plan for the first Crypto research
slice. It narrows the analysis-first direction into a data-assurance and
falsifiable-validation loop. Older EBRT documents remain historical supporting
material and do not override the contracts defined here.

## 2. Goal and Success Criteria

Build a local-first BTC research path that can prove, with auditable evidence:

1. which provider and instrument produced every market row;
2. whether the daily data is complete, final, structurally valid, stable under
   replay, and consistent with an independent source;
3. whether a pre-registered BTC volatility hypothesis survives purged
   walk-forward validation; and
4. why a result is `validated`, `monitoring`, `rejected`, or unavailable.

Success does not require a positive signal. An honest `insufficient_data` or
`rejected` result is a valid outcome when the evidence supports it.

## 3. Current Baseline and Known Defects

The canonical sample at `data/market/cross_asset/btc.parquet` currently has 519
rows covering `2025-02-05 -> 2026-07-08`. The sample is daily and has no null
dates, duplicate dates, non-positive closes, or basic OHLC relationship
violations. That only proves that the file is readable; it does not prove
research-grade provenance or stability.

Known defects that must be closed before signal validation:

- The writer uses `data_root/market/cross_asset`, while `DataGateway` reads the
  legacy `data_root/cross_asset` path and may trigger an implicit network fetch.
- OKX `BTC-USDT` and CoinGecko `BTC-USD` can be silently merged into one file.
- OKX `confirm` is discarded, so an incomplete candle may be stored.
- Existing rows win overlap de-duplication, which can permanently preserve an
  incomplete or subsequently revised candle.
- The current file contains no provider, venue, quote currency, UTC interval,
  retrieval time, finality flag, payload hash, or revision metadata.
- `CrossAssetSignal` converts missing input into neutral numeric defaults and
  uses the maximum input watermark instead of a common watermark.
- Gold currently contains invalid OHLC rows and USD/CNH is stale; neither can
  support a current cross-asset conclusion yet.
- The warehouse Crypto classifier uses substring matching. Tokens such as
  `eth` and `defi` match unrelated words, and most currently labelled Crypto
  articles are false positives.
- Warehouse RSS rows were first ingested in July 2026 but are aggregated by old
  publication dates, creating point-in-time leakage.
- Existing `support_score=1.0` rows are deterministic count scaffolding, not
  statistical validation.

ETH, Nasdaq, US rates, automatic trading, allocation, and a general multi-asset
engine are explicitly outside BTC v1.

## 4. Research Questions

### H1 - BTC Volatility Persistence (Primary)

> When BTC 20-day realized volatility enters a high-volatility regime, is the
> following seven-complete-UTC-day realized volatility materially higher than
> on normal observation days?

H1 is non-directional. Signed returns are descriptive only and must not be
translated into buy/sell language.

### H2 - BTC / Gold Divergence (Gated Follow-up)

> Does an extreme divergence between BTC and a qualified gold proxy correspond
> to higher BTC volatility over the following seven complete UTC days?

H2 may run only after Gold and any FX normalizer independently pass the market
data gates in this document. The current SGE/CNH inputs are exploratory and
must not be presented as current XAU/USD truth.

### H3 - Crypto / Regulation News Burst (Deferred)

> Does a multi-source Crypto or regulation news burst correspond to higher BTC
> absolute return or realized volatility over the following seven UTC days?

H3 remains `insufficient_data` until continuous fetch coverage and semantic
precision gates are satisfied.

## 5. Point-in-Time and Provider Contracts

The single canonical root is:

```text
data/market/cross_asset/
```

Provider-native evidence is immutable and bundled by assurance run:

```text
data/market/cross_asset/runs/btc/<run_id>/
  raw/<provider>/<page>.json
  primary.parquet
  shadow.parquet
  canonical.parquet
  reconciliation.parquet
  revisions.parquet
  manifest.json
```

Canonical publication remains compatible with:

```text
data/market/cross_asset/btc.parquet
```

but is generated only from a validated run and accompanied by a versioned
manifest. A shadow provider never silently replaces the primary provider.

BTC v1 contracts:

- Primary: OKX spot `BTC-USDT`, UTC daily interval `1Dutc`.
- Shadow verifier: CoinGecko `bitcoin` in USD, daily close only.
- Calendar: UTC `[00:00, 24:00)` with one expected completed row per UTC day.
- Primary rows require `confirm=1`.
- CoinGecko is used for reconciliation, not as an OHLC fallback.
- Scheduling starts after `00:40 UTC`; the default local schedule is
  `09:00 Asia/Shanghai`.

OKX documents that `1D` is a UTC+8-opening candle, `1Dutc` is UTC-opening, and
`confirm=1` means completed. CoinGecko documents that its long-range OHLC
endpoint auto-coarsens to four-day candles, so the implementation must use a
daily market-chart close for shadow validation instead of treating long-range
OHLC as daily.

Every provider-native row must retain:

```text
provider, venue, instrument, base_asset, quote_asset, interval,
bar_open_at, bar_close_at, open, high, low, close, volume,
is_final, fetched_at, available_at, payload_hash, schema_version, run_id
```

For market bars, `available_at` is the source-time boundary at which the
completed bar can first be used (the UTC `bar_close_at` in BTC v1), while
`fetched_at` records when this installation first observed the row. Historical
backfills therefore remain usable for market research without hiding their
local first-observation time. No feature window may contain a row whose
`available_at` is later than its anchor close.

For news:

```text
available_at = max(published_at, first_seen_at)
```

An unobserved day is `unknown`. Only a successful fetch that returns zero
entries may record an observed zero.

## 6. Data Flow and Storage

```text
OKX raw capture -----------+
                           +-> reconciliation -> data gates -> canonical BTC run
CoinGecko shadow close ----+                          |
                                                      +-> rv20 / regime features
Immutable revision ledger ----------------------------+-> forward rv7 labels
                                                      +-> walk-forward ADS outputs
```

Each run writes to an immutable temporary/run directory. Degraded runs remain
auditable there, but the current pointer changes only after all required gates
pass. The manifest records:

- run ID and creation time;
- code revision and configuration hash;
- provider/instrument/quote/interval;
- input and output watermarks;
- row count, schema hash, file SHA-256, and payload hashes;
- every gate result and reason code; and
- the previous current run for rollback.

All completed run manifests are retained with no automatic pruning; this is
stronger than the minimum of ten. Generated market data and raw payloads remain
ignored runtime assets and are never committed.

## 7. Data Readiness Gates

Data state is independent of signal state:

```text
data_readiness = invalid | insufficient_data | ready | degraded
signal_validation = candidate | monitoring | validated | rejected
```

Only `data_readiness=ready` can publish a formal signal-validation result.

### D0 - Contract and Ownership

- One canonical root and one canonical BTC instrument contract.
- Reads are pure reads; fetch/repair/publish are explicit commands.
- BTC-USDT and BTC-USD stay provider-native and separate.
- Schema version, quote currency, timezone, finality, and provider are required.

Failure is `invalid`; no canonical publication occurs.

### D1 - Acquisition Stability

- Record expected, attempted, succeeded, empty, failed, latency, and retry count.
- Use bounded exponential retry, at most three attempts per provider.
- Over a rolling 30 days, at least 29 days must have both qualified sources.
- No consecutive completed-day gap longer than one day.
- Missing shadow credentials or an all-provider failure is explicit
  `degraded`, never a successful stale-cache result.

### D2 - Structural Integrity

- Required-field non-null rate: 100%.
- `(provider, instrument, interval, bar_open_at)` uniqueness: 100%.
- Strict UTC ordering and no future completed bars.
- `open/high/low/close > 0` and `high >= max(open, close)`,
  `low <= min(open, close)`, `high >= low`: 100%.
- Last 90 completed UTC days: 100% coverage.
- Full qualified history: at least 99.5% coverage and at least 365 days.

### D3 - Cross-Source and Temporal Correctness

After aligning UTC close dates:

- close basis `<= 0.5%`: pass;
- `> 0.5% and <= 1.0%`: warn and quarantine that date from research;
- `> 1.0%`: block publication.

A daily move above 20%, or above rolling `8 x MAD`, is `suspect`, not
automatically deleted. It passes only when the shadow source confirms it.

### D4 - Revision and Replay Stability

- Re-fetch the two latest completed days on every sync.
- Primary close revision `<= 0.2%`: accept and record.
- Revision `> 0.2% and <= 1.0%`: quarantine and warn.
- Revision `> 1.0%`: block publication.
- Incremental and full replay over the same provider captures must produce the
  same canonical rows and hashes.
- At least two overlapping completed dates are required in the revision
  comparison. A legacy parquet comparison is diagnostic migration evidence,
  not proof of repeated provider-native observation. The first new capture is
  staged/degraded; from the second capture onward the latest qualified staged
  provider-native run is the revision baseline.

### D5 - Publish, Drift, and Rollback Protocol

D5 is an audited storage protocol after D0-D4, not a pre-publication
`DataGateResult`.

- Publish only after D0-D4 pass.
- Stage immutable artifacts first, then replace the compatibility parquet and
  current pointer under an exclusive lock and predecessor compare-and-swap.
- Readers verify that the pointer hash matches the compatibility parquet and
  fail closed during any mismatch; they never serve a partially switched pair.
- A failed write or validation retains the previous current run.
- Rollback verifies archived hashes and original publication evidence, changes
  the pointer, and reruns D0-D4.
- A provider-native rollback target must have original `ready` evidence, D0-D4
  pass, and prior publication evidence; an arbitrary staged run is ineligible.
- The first migration can restore the exact legacy predecessor bytes. Because
  legacy data lacks provider lineage, that restored state is explicitly
  `insufficient_data`, never silently upgraded to ready.
- Target rollback completion: within five minutes.
- A schema change or source divergence above 1% blocks immediately.

Stable evidence means the same immutable inputs, code revision, and config
produce the same run ID, rows, metrics, and hashes.

## 8. H1 Feature and Label Contract

Let `r[t] = log(close[t] / close[t-1])`.

```text
rv20[t]      = sqrt(365) * std(r[t-19:t])
threshold[t] = expanding 80th percentile using observations strictly before t
high_vol[t]  = rv20[t] >= threshold[t]
future_rv7   = sqrt(365) * std(r[t+1:t+7])
abs_ret7     = abs(close[t+7] / close[t] - 1)
```

- At least 180 prior observations are required before defining a threshold.
- High-volatility events are separated by at least seven UTC days.
- `future_rv7` is the primary outcome; `abs_ret7` is secondary.
- Future or incomplete labels are `pending_horizon`, never zero.

## 9. Signal Validation Gates

### S0 - Pre-registration

Lock the feature, threshold, primary outcome, seven-day horizon, sample gates,
effect-size gate, and statistical method before reading outcome results.

### S1 - Point-in-Time Safety

- Features use only information available by the anchor close.
- Labels use only the following seven completed UTC days.
- No publication date is accepted before its first-seen/available time.
- A future-feature and shifted-label placebo must fail.

### S2 - Sample Sufficiency

- At least 365 ready BTC days.
- At least 30 non-overlapping high-volatility events.
- At least three valid test folds, three de-overlapped events per fold, and
  eight same-window normal comparators per fold.
- Insufficient samples produce `insufficient_data`, not a weak score.

### S3 - Purged Walk-Forward

- Expanding training window: initial 180 days.
- Test window: 60 days.
- Step: 60 days.
- Purge/embargo: seven days.
- Retain up to the five latest valid folds.

### S4 - Statistical and Practical Effect

Primary effect:

```text
median(future_rv7 | high_vol) / median(future_rv7 | normal)
```

`validated` requires all of:

- effect ratio at least `1.10`;
- fixed-seed block-bootstrap 95% CI lower bound above `1.0`;
- BH-adjusted `q <= 0.10` across the registered run family; and
- positive primary effect in at least two-thirds of valid folds.

A statistically significant opposite effect is `rejected`. A complete but
unstable result is `monitoring`. Signed return remains descriptive.

### S5 - Ongoing Revalidation

- Produce an audit result after each successful daily publication, but count a
  lifecycle recheck only when its watermark is at least 28 days after the
  previous active recheck.
- Two consecutive qualified rechecks whose primary CI crosses the null downgrade
  `validated -> monitoring`.
- Any data gate failure suppresses the signal status until data is ready again.

## 10. H2 and H3 Entry Gates

H2 cannot start until Gold and any FX normalizer have their own provider,
calendar, quote, finality, revision, and reconciliation contracts. Existing
SGE/CNH data is retained only as an exploratory seed; its result cannot exceed
`monitoring` while marked `provisional_proxy`.

H3 requires:

- at least 90 consecutive observed days;
- at least 80% daily source-attempt coverage;
- at least three independent Crypto-native sources;
- at least 30 non-overlapping events;
- token-boundary multi-label rules for `btc`, `eth`, `regulation`,
  `stablecoin`, `liquidity`, `risk_appetite`, and `volatility`; and
- a manually labelled, stratified gold set of at least 200 articles with
  precision at least 90% and recall at least 80%.

Tests must explicitly prove that `eth` does not match `method/whether` and
`defi` does not match `define/defining`.

## 11. CLI and Audit Interfaces

Existing syntax remains valid. Add modes without removing the compatibility
entry:

```text
./trade data cross-asset btc --mode sync|validate|status \
  [--dry-run] [--strict] [--json]

./trade data warehouse validate-research \
  --profile crypto-btc-v1 \
  --as-of latest-common \
  [--dry-run] [--strict] [--json]
```

Exit codes:

- `0`: run completed, including an honest `insufficient_data` conclusion;
- `2`: invalid arguments, schema, timestamps, or contract;
- `3`: acquisition, I/O, publish, or rollback failure; and
- `4`: cross-source reconciliation block.

Research-facing outputs:

- `ads_crypto_data_readiness_report`;
- `ads_crypto_provider_reconciliation`;
- `ads_crypto_volatility_validation`; and
- `ads_research_validation_run`.

The deterministic statistical `validation_run_id` is distinct from an ADS
`generation_id`. Replaying the same statistical result after a data rollback or
different lifecycle predecessor creates a new generation receipt, so an old
non-active receipt can never be promoted as if it represented the new context.
The four parquet tables are additive history, not independent "latest" files.
`_crypto_validation_current.json` is switched only after all four replacements
and the completion receipt succeed. Official readers must use
`read_crypto_validation_outputs()`, acquire the shared lock, follow that
pointer, and filter every table by the same `run_id`; reading each flat table's
last row directly is unsupported. During a crash window the pointer continues
to select the prior complete run. Receipt-backed recovery either restores an
unfinished transaction or finishes the pointer promotion before the next
lifecycle transition.

Every output includes evidence references, reason codes, input watermarks,
contract version, run ID, and `causal=false`.

## 12. Implementation Phases

1. C0 - Plan and OpenSpec artifacts.
2. C1 - Canonical path, pure-read gateway, provider-native captures, manifests.
3. C2 - Dual-source reconciliation, revision ledger, D0-D5 gates.
4. C3 - H1 features, labels, walk-forward validation, ADS reports.
5. C4 - Gold/FX assurance and H2.
6. C5 - Continuous Crypto news coverage, semantic gold set, and H3.
7. C6 - Read-only Web drill-down and position-risk integration.

C0-C3 form the first implementation change. C4-C6 require separate OpenSpec
changes after their entry gates are satisfied.

## 13. Test and Acceptance Matrix

All automated tests use `tmp_path` or frozen fixtures and never access real
data roots or the network.

Required coverage:

- a pure read cannot create a DB, file, or network call;
- `confirm=0` never enters canonical data;
- `1D` and `1Dutc` are not interchangeable;
- CoinGecko four-day OHLC cannot pass as a daily shadow series;
- duplicate/null/non-positive/OHLC/future/partial rows are rejected;
- quote/provider mixing is rejected;
- basis thresholds and revision thresholds hit pass/warn/block states;
- failed publication preserves the old current manifest;
- tampered staged artifacts and unpublished/non-ready rollback targets are
  rejected;
- replay is deterministic and rollback restores the prior run;
- synthetic positive, random, opposite, and insufficient samples produce
  `validated`, `monitoring`, `rejected`, and `insufficient_data` respectively;
- threshold calculation and walk-forward folds do not read future data; and
- placebos do not validate.
- ADS lifecycle updates serialize under one lock, reject stale ready-state
  writers, prioritize data-gate suppression, and expose only one cross-table
  run through the current pointer.

Validation commands:

```text
uv run --extra dev pytest tests/test_btc_provider_contract.py \
  tests/test_cross_asset_data_assurance.py \
  tests/test_crypto_data_cli.py \
  tests/test_crypto_research_validation.py \
  tests/test_data_gateway_cross_asset_read.py \
  tests/test_scheduler.py \
  tests/test_research_warehouse.py -q
python -m compileall trade_py trade_web tests
uv run --extra dev pytest -q
openspec validate crypto-data-assurance-and-validation-v1 --strict
```

## 14. Data Safety and Rollback

- Existing real market files are read-only inputs until a validated new run is
  ready to publish.
- Dry-run performs no writes.
- Raw captures, generated parquets, manifests, and temporary run data remain
  untracked.
- No old file or run is deleted during migration.
- A small-sample dry-run and hash comparison precede the first canonical
  pointer switch.
- Unrelated `.nvim/`, caches, local DBs, and generated data are never staged.

## 15. Implementation and Verification Record

Implementation status as of 2026-07-10: C0-C3 are complete in code and frozen
fixtures. No provider network request or real-data publication was performed as
part of automated verification.

- Focused Crypto/data/scheduler/warehouse suite: `108 passed`.
- Full Python suite: `299 passed`; eight existing `datetime.utcnow()` deprecation
  warnings remain outside this change.
- `python -m compileall -q trade_py trade_web tests`: passed.
- Strict OpenSpec validation: passed. The CLI emitted a non-blocking PostHog DNS
  flush warning after reporting the change valid.
- All new data tests use temporary roots and frozen provider payloads; no
  generated runtime data is part of the delivery.

The first live run is intentionally not expected to become `ready`. D1 needs
29 distinct qualified acquisition dates in a rolling 30-day ledger; a single
historical backfill cannot manufacture that evidence. D4 also needs repeated
overlap observations to prove revision stability. Until those observations
accumulate, runs are retained as immutable evidence but canonical publication
remains blocked.

Expected first-rollout sequence:

- Qualified days 1-28: immutable runs are staged, readiness remains degraded,
  the 09:00 job fails closed, and `data.crypto.synced` is not emitted.
- Capture 1 has no provider-native revision predecessor. Capture 2 can establish
  the first two-date overlap baseline, but D1 still blocks publication.
- Qualified day 29: first publication is permitted only if D0-D4 all pass and
  the 29 dates lie inside the rolling 30-day window.
- Immediately after the first pointer switch: run `validate` and `status`,
  compare pointer/artifact hashes, verify the ADS lineage, and rehearse both
  provider-native and legacy-predecessor rollback within five minutes.

Before enabling the 09:00 job, configure CoinGecko credentials and execute a
manual `--dry-run`. During initial operation, inspect provider attempts, raw
payload hashes, D0-D4 reason codes, reconciliation quarantine, and revision
records daily. A live publication should occur only after all gates naturally
reach `ready`.

The local pre-rollout snapshot inspected for this change remains a 519-row
legacy BTC OHLC parquet without a current pointer, raw captures, or assurance
manifest. The local metadata DB was still at migration v16, so the v17 Crypto
DAG rows also require an explicit live migration check. CoinGecko key tier,
daily-interval entitlement, rate limits, and response granularity were tested
only with frozen payloads, not against the live endpoint. The scheduler now
binds the Crypto gate explicitly to `09:00 Asia/Shanghai`.

The compatibility parquet and current pointer are two filesystem objects, so
the operating system cannot replace them as one cross-file transaction. The
implemented protocol bounds that risk: immutable staging, an exclusive lock,
predecessor compare-and-swap, exception rollback, and reader-side hash
verification. A process crash between the two replacements can cause temporary
`degraded` reads, but cannot cause mismatched data to be served as valid; an
operator must validate or restore the recorded predecessor before retrying.

Likewise, the ADS flat parquets are not a filesystem-wide transaction. Their
single current pointer is the visibility boundary. Code that bypasses the
official pointer-aware reader can observe additive rows from an in-progress
generation and must not be used for active research decisions.
