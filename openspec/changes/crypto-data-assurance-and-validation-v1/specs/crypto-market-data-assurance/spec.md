## ADDED Requirements

### Requirement: Cross-asset reads are pure and canonical
The system SHALL read BTC data only from the canonical
`market/cross_asset` path and SHALL NOT fetch, create a database, or write files
while servicing a read.

#### Scenario: Missing local BTC data
- **WHEN** a caller reads BTC from a data root without a canonical file
- **THEN** the system returns an empty frame and an explicit degraded report without changing the data root

### Requirement: Provider-native BTC captures preserve lineage
The system SHALL store OKX BTC-USDT UTC-daily bars and CoinGecko BTC-USD daily
shadow closes separately with provider, instrument, quote, interval, finality,
availability time, payload hash, schema version, and run ID.

#### Scenario: Incomplete OKX candle
- **WHEN** OKX returns a candle whose `confirm` field is not `1`
- **THEN** the system retains it only as raw evidence and excludes it from the canonical candidate

#### Scenario: Shadow source cannot provide daily data
- **WHEN** CoinGecko returns a non-daily series or required credentials are unavailable
- **THEN** the system records a degraded shadow result and does not reinterpret coarse data as daily closes

### Requirement: BTC data gates are explicit and auditable
The system SHALL evaluate contract, acquisition, structural, temporal,
cross-source, revision, and replay gates and SHALL preserve every outcome,
threshold, reason code, and evidence reference.

#### Scenario: Provider close divergence blocks publication
- **WHEN** aligned OKX and CoinGecko daily closes differ by more than one percent
- **THEN** the run is blocked with source-divergence evidence and the current canonical artifact remains unchanged

#### Scenario: Suspicious move is independently confirmed
- **WHEN** a BTC move exceeds the anomaly threshold and the shadow source confirms the move within the reconciliation threshold
- **THEN** the row remains eligible and the anomaly plus confirmation evidence are recorded

### Requirement: Publication is versioned and reversible
The system SHALL publish only a validated immutable run, switch the
compatibility artifact and current pointer under an exclusive lock with
predecessor compare-and-swap, retain at least ten run manifests, require readers
to verify the pointer/artifact hash pair, and support restoring the verified
predecessor.

#### Scenario: Publish fails before pointer switch
- **WHEN** run artifact or compatibility-file publication fails
- **THEN** the prior current pair is restored on handled failure, while any crash-window mismatch fails closed and is never served as valid data

#### Scenario: Rollback succeeds
- **WHEN** a user restores the predecessor run and its recorded hashes match
- **THEN** the system restores the prior compatibility artifact and pointer under the publication lock and records an append-only rollback audit

### Requirement: Cross-asset CLI reports trustworthy outcomes
The system SHALL preserve `trade data cross-asset btc` and support explicit
sync, validate, and status modes with dry-run, strict, JSON, and non-zero failure
semantics.

#### Scenario: Dry-run synchronization
- **WHEN** a user invokes BTC sync with `--dry-run`
- **THEN** the command reports planned provider and gate activity without writing raw, canonical, manifest, or database artifacts

#### Scenario: Reconciliation block exit code
- **WHEN** strict validation encounters a blocking provider divergence
- **THEN** the command returns exit code 4 and emits the reason and evidence in JSON when requested

### Requirement: Scheduled BTC acquisition is post-UTC-close and failure-aware
The system SHALL run Crypto daily acquisition after 00:40 UTC, SHALL cascade
research validation only after a successful canonical publication, and SHALL
surface degraded or unpublished BTC outcomes as job failures.

#### Scenario: Shadow credentials are unavailable
- **WHEN** the scheduled BTC run cannot acquire its qualified CoinGecko shadow
- **THEN** the job fails explicitly, keeps the prior canonical current, and does not emit a successful Crypto-synced event
