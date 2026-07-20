## Why

The existing BTC assurance pipeline already produces immutable runs, manifests,
D0-D5 gates, cross-source reconciliation, revisions, atomic publication, and an
H1 volatility-persistence study. But the read side collapses all of that into a
single mutable `current` pointer and a flat `btc.parquet`, so users cannot tell
whether the data they see is the latest market observation, the latest evaluated
candidate, or the formally published baseline. Concretely, on 2026-07-19 the
formal current run is seven full UTC days behind the latest evaluated candidate,
yet a normal reader only sees the stale current. The Web layer also joins a
registry symbol into an uppercase `BTC.parquet` path while the real canonical
file is lowercase `btc.parquet`, and it reads the flat parquet directly, bypassing
the current pointer, artifact hashes, and shared lock.

This change builds a read-only BTC Observatory and Research Lab that consumes one
shared snapshot-resolution kernel from both Web and Jupyter, exposes orthogonal
lifecycle/quality/freshness/compatibility states instead of a single readiness,
supports point-in-time reconstruction under two knowledge modes, and renders H1
research evidence bound to immutable snapshots.

## What Changes

- Add a rebuildable Snapshot Catalog projected from existing immutable manifests,
  `btc_current.json`, and publish/rollback audits. The Catalog is a projection,
  not a second source of truth, and must be reconstructable from immutable facts.
- Add a Snapshot Resolver and read-only Python SDK that resolve semantic channels
  (`latest_observed`, `evaluated_candidate`, `formal`) plus exact run/release,
  under an explicit `knowledge_as_of` + `knowledge_mode` + `revision_policy`
  contract, freezing `latest` aliases at request start.
- Add orthogonal read-side state axes (acquisition/quality/lifecycle/research)
  plus freshness/compatibility and purpose fitness, all versioned projections
  that never write back to `data_readiness` or the publish authority.
- Add a versioned legacy timestamp adapter so selectors order deterministically
  even though existing manifests lack `staged_at`/`assurance_completed_at`/
  `capture_completed_at`, without ever reading filesystem mtime.
- Add layered composite comparison that returns independent formal / candidate /
  observed layers (never a merged single truth) and refuses to be used as a
  research dataset.
- Add point-in-time resolution under `market_available` and `installation_observed`
  knowledge modes, with an evidence coverage report and explicit `PIT_NOT_PROVEN`
  when legacy data cannot prove what the installation knew at time T.
- Add FastAPI observatory routes (`context`/`series`/`dates`/`trust`/`runs`/`runs
  diff`/`hypotheses`/`research-runs`) with OpenAPI golden fixtures, ETag/304,
  stable cursor pagination, and a frozen error/reason-code contract.
- Add Web Observatory surfaces (Overview Truth Bar, three-layer composite,
  Trust/Lineage, Date Evidence, run diff, H1 research evidence) and a thin
  reproducible notebook template, all consuming the same snapshot/metric contract.
- Add a Crypto research workflow adapter that maps H1 onto the existing
  `validation_run_id`/`generation_id`/`_crypto_validation_current.json` authority
  with explicit `run`/`import`/`promote` CLI commands and immutable receipts; it
  never creates a competing current-selection authority.
- Fix the uppercase/lowercase BTC path defect at the resolver boundary, without
  new code depending on case-guessing.

## Supersession

This change records the following supersessions of
`crypto-data-assurance-and-validation-v1` and its plan (docs/23). The D0-D5 gates,
immutable runs, hashes, locks, CAS, atomic publish/rollback, and the H1 method,
gating, and lifecycle remain in force and are NOT superseded.

| Topic | Prior narrative | V1 current fact |
| --- | --- | --- |
| Shadow source | CoinGecko / BTC-USD daily close | Binance, instrument `BTCUSDT`, quote `USDT`, interval `1d` |
| Owner path | `market/cross_asset` as new owner | `trade_py/data/market/crypto` is the owner; `market/cross_asset` is a compatibility shim only |
| Credentials | CoinGecko credential/tier live-pilot blocker | No longer a V1 blocker; the CoinGecko live-pilot/credential tasks are closed/rewritten |
| Read model | single `current` pointer represents all truth | orthogonal channels + versioned read-side projections |
| Web read path | direct flat parquet join with uppercase symbol | resolver-mediated, hash-verified, lowercase-correct |

The CoinGecko live-pilot tasks (6.1) in the prior change are marked closed by this
supersession. D1 acquisition stability can still block a new automatic Formal
publish, but never blocks Latest Observed, Candidate, Trust, or historical Formal
display.

## Non-goals

- Automatic trading, order placement, position sizing, or directional buy/sell
  recommendations.
- Minute-level, tick, or order-book real-time monitoring; inferring depth or
  slippage from daily volume.
- RSI/MACD/KDJ indicator walls, a single news-sentiment score, or unevidenced
  causal narratives.
- Hiding a blocker behind a single trust score, or computing formal research
  metrics ad hoc in the browser.
- Promoting notebook conclusions to formal product conclusions automatically.
- Building an empty all-asset platform before BTC semantics are stable.
- Deleting Today, Candidates, old Data, old Research, or Ops in round one.

## Affected contracts

- **New read-only Python API**: `trade_py/observatory/*` domain, catalog, service,
  query SDK.
- **New CLI**: `trade observatory catalog {rebuild,update,verify,status,rollback}`
  and `trade research btc {run,import,promote}` (all with `--dry-run`, JSON, atomic
  receipts). `catalog rollback` (Phase B) is a pointer-only CAS with
  `--to-generation`/`--expected-current`; there is no HTTP write endpoint. No
  existing CLI removed.
- **New Web API**: `/api/v1/observatory/*` (additive). Existing
  `/api/data/kline/crypto.BTC` retained and marked deprecated.
- **DB/schema**: no migration. The Catalog is an additive rebuildable SQLite
  projection outside `trade.db`; research receipts reuse the existing warehouse
  ADS pointer authority. Phase B (2026-07-20) freezes this projection as immutable,
  install-once, scope-bound generations
  (`observatory/generations/catalog-<generation_id>.{sqlite,manifest.json}`) under a
  typed CAS pointer `observatory/catalog-current.json`, adds the frozen integrity
  reason codes (`CATALOG_CORRUPT`/`CATALOG_CAS_CONFLICT`/`CATALOG_ROLLBACK_REJECTED`/
  `CATALOG_LOCK_TIMEOUT`), and a pointer-only `catalog rollback` CLI; the legacy
  `catalog.sqlite` + `generation.json` pair is retained read-only. See
  `frozen_contracts.md` §"Phase B generation contracts" and `design.md` §"Phase B
  immutable-generation layout".
- **Data layout**: no change to immutable runs/manifests/audits; `btc.parquet`
  and `btc_current.json` become a Formal materialized compatibility view and an
  acceleration pointer respectively.

## Compatibility, data safety, and rollout

- All browsing paths are read-only: no provider network, no sync, no publish, no
  rollback, no DB migration, no research outcome writes.
- Integrity mismatches fail closed; the resolver never silently falls back to
  another artifact to keep drawing.
- The only new write sides are the three explicitly approved ones (additive
  attempt receipts if approved, Operations/CLI Catalog rebuild, Research CLI run
  register/promote), each with its own schema version, dry-run, temporary target,
  audit receipt, and no-half-state-on-failure tests.
- Catalog introduction is schema-versioned, additive, and reversible via a
  dual-read report, generation CAS, and feature-flagged Web routes. Rollback
  restores the prior Catalog generation and Web adapter without touching provider
  artifacts or the Formal Baseline.

## Validation

Focused pytest under `tests/observatory/` plus `test_btc_observatory_*`,
`python -m compileall`, frontend build/typecheck and Vitest/Playwright/axe
targets, and `openspec validate btc-observatory-research-lab-v1 --strict`. All
tests use `tmp_path`/frozen fixtures and never touch real providers or mutate
real `data/`.
