## Why

The existing BTC parquet is readable but cannot prove provider provenance,
final-candle status, UTC interval semantics, revision stability, or independent
source agreement. The research warehouse also treats heuristic counts as
validation, so Crypto results can look trustworthy without point-in-time-safe
inputs or sample-outcome evidence.

## What Changes

- Establish a BTC-only, UTC-daily market-data contract with immutable
  provider-native captures, OKX as primary, CoinGecko as a shadow close source,
  explicit finality, lineage, hashes, revisions, and common reason codes.
- Make cross-asset reads pure and route all fetch/repair/publish behavior through
  explicit CLI or job use cases using the canonical `market/cross_asset` path.
- Add D0-D5 data gates for acquisition stability, structural integrity,
  cross-source reconciliation, point-in-time correctness, deterministic replay,
  atomic publication, and rollback.
- Add a pre-registered BTC volatility-persistence study with point-in-time
  features, seven-day labels, purged walk-forward evaluation, bootstrap/FDR
  evidence, and explicit `insufficient_data`/failure states.
- Preserve the existing `trade data cross-asset btc` entry while adding
  sync/validate/status modes, dry-run, strict, and JSON output.
- Persist auditable readiness, reconciliation, validation-run, and hypothesis
  outputs without modifying or committing real raw market data.
- Add a dedicated BTC DAG row at the 09:00 local Crypto gate, leave the existing
  Gold/FX morning row intact, and cascade successful publication into research
  revalidation.
- Mark existing Crypto attention/support-score rows as non-statistical legacy
  scaffolding; do not remove compatible warehouse or Web surfaces.

Non-goals are ETH or multi-coin support, automatic trading, directional BTC
recommendations, Gold/news hypothesis implementation, C++ integration, and a
broad application-layer rewrite.

## Capabilities

### New Capabilities

- `crypto-market-data-assurance`: Provider-native BTC acquisition, pure reads,
  lineage, reconciliation, manifests, data readiness, atomic publication, and
  rollback.
- `crypto-volatility-validation`: Point-in-time BTC volatility features and
  labels, walk-forward statistical validation, evidence, status, and audit
  outputs.

### Modified Capabilities

None. There are no existing OpenSpec capability specs; compatibility changes
are additive to the current CLI and warehouse contracts.

## Impact

- Python data adapters, cross-asset access/service boundaries, and CLI parser.
- New manifest/run artifacts under ignored data roots and additive research ADS
  parquet outputs.
- Focused pytest coverage for paths, providers, schema/time invariants,
  reconciliation, publication/rollback, leakage prevention, and statistical
  status behavior.
- Existing `data/market/cross_asset/btc.parquet` remains read-only until a
  validated derived run is ready. First publication requires dry-run, sample
  comparison, hash verification, and a pointer-based rollback path.
- One reversible metadata-only DAG migration adds `crypto_btc_fetch` at
  `gate.crypto_daily` and its validation cascade while retaining the existing
  Gold/FX job; no market-data DB schema, Web contract, engine, or committed
  generated data is changed.
