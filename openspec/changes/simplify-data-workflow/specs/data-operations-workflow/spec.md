## ADDED Requirements

### Requirement: Concise primary data command surface
The system SHALL expose `status`, `update`, and `check` as the primary `trade data` operations, and SHALL keep existing detailed commands executable as an advanced compatibility surface.

#### Scenario: Primary help is concise
- **WHEN** a user runs `trade data --help`
- **THEN** the first-level workflow shows only status, update, and check with short examples and a pointer to advanced help

#### Scenario: Legacy command remains callable
- **WHEN** a user invokes an existing detailed data command with its previous arguments
- **THEN** the system dispatches the compatible implementation without silently changing its write scope

### Requirement: Status is fast and read-only
The system SHALL build default data status from existing metadata, manifests, and read-only database connections without creating directories, databases, migrations, job state, or parquet files.

#### Scenario: Empty root status
- **WHEN** status runs against a nonexistent or empty data root
- **THEN** it returns observed=false or unknown components and leaves the root unchanged

#### Scenario: Populated root status
- **WHEN** status runs against an existing data root
- **THEN** it returns a compact profile-oriented summary with WAL-current watermarks and job evidence without scanning value rows or mutating database files

### Requirement: Update uses explicit ordered profiles
The system SHALL provide version-controlled `core`, `crypto`, and `all` profiles with ordered steps and explicit per-step configuration. Profiles MUST NOT trigger model training, belief, recommendation, evaluation, or other trading-decision work.

#### Scenario: Dry-run plan
- **WHEN** a user runs `trade data update PROFILE --dry-run`
- **THEN** the command prints every ordered step and configuration, performs zero writes, and exits successfully if the profile is valid

#### Scenario: Step failure
- **WHEN** an update step fails or only partially persists its requested targets
- **THEN** the profile stops by default, records the failure, and returns a nonzero update-failure exit code

#### Scenario: Auditable pilot gate remains pending
- **WHEN** a step stages valid evidence and only a time-based pilot gate remains pending
- **THEN** the profile records a warning, continues independent later steps, and exits with warning code 1 without publishing the gated candidate

#### Scenario: Crypto profile ownership
- **WHEN** the crypto profile runs
- **THEN** BTC is attempted by assurance, a pilot-pending candidate remains unpublished and visible as a warning, and the generic batch step targets only non-BTC crypto assets

### Requirement: Check has standard and full tiers
The system SHALL provide a read-only standard check and an explicit full audit tier. Missing or zero evidence MUST be reported as unknown rather than pass.

#### Scenario: Standard check
- **WHEN** a user runs `trade data check`
- **THEN** the system validates metadata, freshness, schemas, provider readiness, and reconciliation without scanning all value rows

#### Scenario: Full audit
- **WHEN** a user runs `trade data check --full`
- **THEN** the system additionally performs value-quality scans and reports the audit scope and elapsed evidence

### Requirement: Stable exit-code contract
The system SHALL use `0` for pass, `1` for warning, `2` for quality or update failure, `3` for execution error, and `130` for interruption across the concise data workflow.

#### Scenario: Quality failure
- **WHEN** a strict check completes and its aggregate gate is fail
- **THEN** the command exits with code 2 while preserving the structured evidence
