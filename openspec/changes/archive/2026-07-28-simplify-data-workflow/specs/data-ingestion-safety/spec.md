## ADDED Requirements

### Requirement: DAG node identity and configuration are preserved
The system SHALL execute every enabled DAG row exactly once per event using that row's own configuration and a handler identity unique to the DAG row.

#### Scenario: Repeated job type on one source
- **WHEN** two enabled DAG rows share a source and job name but have different configurations
- **THEN** both handlers execute exactly once with their respective configurations

#### Scenario: Repeated job type on another source
- **WHEN** a crypto DAG row shares a job name with commodity and FX rows
- **THEN** the crypto event cannot resolve or execute either non-crypto configuration

### Requirement: BTC canonical data has one writer
The system SHALL reserve canonical `market/crypto/btc.parquet` publication for the BTC assurance service and MUST prevent generic batch ingest from writing that asset.

#### Scenario: Generic crypto batch
- **WHEN** generic ingest selects all enabled crypto assets
- **THEN** BTC is excluded with an actionable specialized-owner reason and all eligible non-BTC assets remain selectable

#### Scenario: BTC-only generic request
- **WHEN** a legacy generic sync requests only BTC
- **THEN** it returns non-success and directs the caller to the assurance-backed crypto update without modifying the canonical file or pointer

### Requirement: Durable input corruption fails closed
The system SHALL preserve and report unreadable existing parquet or WAL artifacts and MUST NOT replace them as if they were absent.

#### Scenario: Existing parquet cannot be read
- **WHEN** incremental ingest encounters an unreadable canonical parquet
- **THEN** the asset fails, the existing file remains unchanged, and the result identifies the path and read error

#### Scenario: WAL cannot be read
- **WHEN** ingest append or recovery encounters an unreadable WAL
- **THEN** the WAL remains available for repair and the asset/profile cannot be reported successful

### Requirement: Update success requires targets and durable completion
The system SHALL distinguish no-target, already-current, updated, partial, and failed outcomes. Zero matched targets, unexpected empty provider responses, partial asset failures, and flush failures MUST NOT be reported as success.

#### Scenario: No matching targets
- **WHEN** a requested class or symbol matches no eligible assets
- **THEN** the update returns a nonzero result with the requested selector and an actionable reason

#### Scenario: Partial batch failure
- **WHEN** some assets persist and others fail acquisition or flush
- **THEN** the batch and parent profile are non-success and preserve per-asset results

#### Scenario: Proven already current
- **WHEN** a provider returns no new rows and existing evidence proves the requested interval is already complete
- **THEN** the asset is reported already-current and may complete successfully without pretending rows were updated

### Requirement: Daily-candle finality uses time semantics
The system SHALL mark a provider daily candle final only when its close time is not later than the effective fetch time.

#### Scenario: Open Binance UTC candle
- **WHEN** a Binance response includes the currently open UTC daily candle with nonzero trade count
- **THEN** normalization marks it non-final and assurance/generic persistence excludes it from completed history
