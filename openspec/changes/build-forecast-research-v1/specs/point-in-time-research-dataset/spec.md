## ADDED Requirements

### Requirement: Point-in-time dataset versions
The system SHALL build immutable research dataset versions whose manifests record
the as-of time, trading calendar, dated universe membership, source versions,
adjustment policy, feature availability policy, label definitions, code version,
partition hashes, and quality result. A feature row at decision time SHALL contain
only values available by that time.

#### Scenario: Replay an existing version
- **WHEN** an operator replays a dataset version with the same sources, policies, and code version
- **THEN** the system produces the same manifest and partition hashes or reports the exact mismatched inputs

#### Scenario: Future observation appears in a feature
- **WHEN** a source value became available after the feature row's decision time
- **THEN** the system excludes the value and records a point-in-time availability violation if it was requested

### Requirement: Dated universe membership
The system SHALL represent CSI 300 and watchlist membership with effective dates and
SHALL NOT project current membership backward into historical samples. Unknown
historical membership SHALL block the affected build range.

#### Scenario: Historical constituent membership is unavailable
- **WHEN** a build requests a date for which constituent membership cannot be established
- **THEN** the system marks that range `quality_gate_failed` and emits no training-ready rows for it

### Requirement: Canonical return units
The system SHALL store research returns and return thresholds as decimal returns,
where `0.05` means 5%, and SHALL carry an explicit unit identifier across source,
label, model, forecast, and outcome boundaries.

#### Scenario: Percent-valued source enters a decimal boundary
- **WHEN** a source declares percent units such as `5.0` for 5%
- **THEN** the adapter converts it exactly once to `0.05`, records the source unit, and exposes decimal units downstream

#### Scenario: Unit metadata is absent
- **WHEN** a return-bearing source does not declare a recognized unit
- **THEN** the system quarantines the rows and blocks their use in labels or training

### Requirement: Mature labels are isolated from features
The system SHALL store forward labels separately from point-in-time features and
SHALL mark each 1-, 5-, and 20-trading-day label as immature until its full outcome
window is available. Immature labels SHALL NOT enter training or validation.

#### Scenario: Twenty-day label has not matured
- **WHEN** fewer than 20 subsequent trading sessions are available for a feature row
- **THEN** the system records the label as `label_not_mature` and excludes it from training and scoring metrics

### Requirement: Quality audit and anomaly quarantine
The system SHALL audit freshness, duplicates, missing critical fields, calendar
alignment, price adjustment continuity, non-finite values, unit consistency, and
return anomalies before declaring a dataset ready. Unexplained anomalies SHALL be
quarantined with source evidence and SHALL NOT be silently clipped or imputed.

#### Scenario: Extreme adjusted return is detected
- **WHEN** a return breaches the configured anomaly policy
- **THEN** the system retains the raw evidence in a quarantine report, excludes it from eligible labels, and reports whether adjustment, denominator, or unit checks resolved it

#### Scenario: Dataset does not meet minimum history
- **WHEN** a training dataset contains fewer than 500 distinct trading sessions
- **THEN** the dataset remains available for inspection but its research state is `insufficient_history`

### Requirement: Data mutations are reversible
The system SHALL provide a dry-run for dataset builds and metadata migrations, use a
backup or reversible snapshot before changing real metadata or an active pointer,
verify a small sample after mutation, and support rollback to the prior active
version.

#### Scenario: Dry-run a full dataset build
- **WHEN** an operator invokes a build with `--dry-run`
- **THEN** the system reports sources, date range, universe, expected partitions, quality checks, and intended metadata mutations without writing data or DB state

#### Scenario: Post-build verification fails
- **WHEN** sample row, count, schema, or hash verification fails after a build
- **THEN** the system does not activate the new version and reports the rollback procedure

### Requirement: Dataset status is manifest-based and read-only
The system SHALL expose readiness, freshness, coverage, quarantine counts, label
maturity, and version identifiers without scanning full feature partitions or
triggering collection, transformation, or writes.

#### Scenario: Inspect current dataset status
- **WHEN** an operator runs the dataset status command
- **THEN** the system reads manifests and quality aggregates only and returns a non-ready reason whenever a gate is unmet
