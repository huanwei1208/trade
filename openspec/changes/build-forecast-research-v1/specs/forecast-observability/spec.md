## ADDED Requirements

### Requirement: Forecast snapshots are immutable
The system SHALL persist an immutable `ForecastSnapshot` for every emitted forecast,
including as-of time, symbol, horizon, dataset/universe/model versions,
probabilities, expected return, intervals, evidence references, calibration and
validation states, and unknown or failure reasons.

#### Scenario: Model is retrained after a forecast
- **WHEN** a new model version becomes active after a forecast was emitted
- **THEN** the original snapshot remains linked to the original model and is not recalculated or overwritten

### Requirement: Realized outcomes are append-only
The system SHALL append a `ForecastOutcome` only after the corresponding label
matures and SHALL link it to the exact snapshot and label definition. Outcome
ingestion SHALL NOT mutate the original forecast payload.

#### Scenario: Five-day outcome matures
- **WHEN** the full five-trading-day outcome window becomes available
- **THEN** the system appends one idempotent outcome record with source and unit provenance for the matching snapshot

#### Scenario: Outcome is not mature
- **WHEN** an outcome job encounters a snapshot whose horizon is incomplete
- **THEN** it records no realized value and reports `label_not_mature`

### Requirement: Validation runs are reproducible
The system SHALL persist every validation run's dataset, model, split, metric,
cost-policy, regime-policy, code-version, and result identifiers so the result can be
replayed or its dependency mismatch explained.

#### Scenario: Reproduce a validation report
- **WHEN** an operator requests replay of a stored validation run
- **THEN** the system uses the recorded versions and either reproduces the metrics or reports every unavailable or changed dependency

### Requirement: Research CLI is concise and read-safe
The system SHALL expose a flat everyday command surface through `./trade research
status`, `forecast`, `rank`, `risk`, `build`, `validate`, and `outcomes`. `status`
SHALL summarize dataset and model readiness and accept `--detail` for the quality
audit. Status, forecast, rank, risk, and outcome inspection SHALL be read-only and
SHALL NOT implicitly collect, migrate, train, activate, or write outcomes.

#### Scenario: Rank current opportunities
- **WHEN** an operator runs the read-only rank command for an as-of date and horizon
- **THEN** the command returns eligible snapshots ordered by the selected declared metric plus their versions and validation states without writing local data

#### Scenario: Build requires mutation
- **WHEN** an operator invokes a dataset build
- **THEN** the command supports `--dry-run` and prints the universe, date range, sources, versions, checks, and intended writes before mutation

### Requirement: Readiness reasons are observable
The system SHALL distinguish at least `stale_data`, `insufficient_history`,
`label_not_mature`, `unit_violation`, `quality_gate_failed`,
`model_not_eligible`, and `calibration_unavailable`. CLI and stored snapshot surfaces
SHALL preserve these reasons instead of mapping them to zero, neutral, or `watch`.

#### Scenario: Model is blocked by unit audit
- **WHEN** the source data fails the return-unit contract
- **THEN** forecast status reports `unit_violation`, affected source/version evidence, and no numeric forecast

### Requirement: Heuristic evidence remains labeled
Existing recommendation, causal, knowledge-graph, belief, or event outputs SHALL be
accepted only as versioned optional evidence unless they independently satisfy the
new point-in-time and calibration gates. Their heuristic or uncalibrated state SHALL
remain visible in every combined explanation.

#### Scenario: Uncalibrated causal signal supports a forecast
- **WHEN** a forecast explanation references an uncalibrated causal signal
- **THEN** the evidence is labeled `calibrated=false` and cannot by itself make the forecast eligible or validated
