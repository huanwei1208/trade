## ADDED Requirements

### Requirement: Multi-horizon probabilistic forecasts
The system SHALL produce separate 1-, 5-, and 20-trading-day outputs containing up
probability, expected benchmark-relative return, q10/q50/q90 decimal-return
quantiles, calibration state, and model/dataset/universe versions. It SHALL NOT
collapse the horizons into one recommendation label.

#### Scenario: Generate an eligible daily forecast
- **WHEN** the dataset is ready and an eligible model exists for a symbol and horizon
- **THEN** the system emits the probability, expected excess return, ordered quantiles, versions, and evidence timestamp for that horizon

#### Scenario: One horizon is not eligible
- **WHEN** the 20-day model is blocked but the 1-day and 5-day models are eligible
- **THEN** the system emits explicit `model_not_eligible` status for 20 days without hiding the eligible shorter-horizon outputs

### Requirement: Transparent baselines
The system SHALL evaluate historical prevalence, benchmark or sector prevalence,
momentum, and regularized linear or logistic baselines through the same dataset,
splits, costs, and metrics as learned candidates. A more complex model SHALL NOT be
eligible unless it improves on the best eligible baseline under the versioned
validation policy.

#### Scenario: Complex model fails to beat a baseline
- **WHEN** a candidate's out-of-sample results do not satisfy the configured improvement gates over the best baseline
- **THEN** the model remains `candidate` or becomes `rejected` and is not used as a validated forecast

### Requirement: Leakage-resistant walk-forward validation
The system SHALL use time-ordered expanding walk-forward splits, purge samples with
overlapping label windows, embargo adjacent observations, and fit preprocessing only
on each training fold. Research eligibility SHALL require at least six folds and 120
distinct out-of-sample trading days.

#### Scenario: Requested folds overlap outcome windows
- **WHEN** a validation configuration would place overlapping label windows across a train-test boundary
- **THEN** the validator purges or embargoes the overlapping samples and records the resulting effective sample size

#### Scenario: Too few effective test days remain
- **WHEN** purging leaves fewer than 120 distinct out-of-sample trading days
- **THEN** the validation state is `blocked` with reason `insufficient_history`

### Requirement: Forecast quality is multi-dimensional
The system SHALL report rank IC, direction ROC-AUC, Brier score or log loss,
calibration error, interval coverage, net top-decile excess return under versioned
costs, drawdown, and sector/regime slices. Metric uncertainty and effective sample
counts SHALL accompany the point estimates.

#### Scenario: Aggregate metric passes but one regime collapses
- **WHEN** an aggregate gate passes while a required sector or market-regime slice breaches its stability gate
- **THEN** the model cannot advance beyond `monitoring` and the failing slice is included in the validation evidence

### Requirement: Explicit model lifecycle
The system SHALL use `candidate`, `monitoring`, `validated`, `rejected`, and `blocked`
states. Offline validation MAY advance a model to `monitoring` but SHALL NOT advance
it to `validated`. Validation SHALL require at least 60 matured live trading days,
stable calibration, and explicit approval.

#### Scenario: Offline evaluation passes
- **WHEN** a candidate passes all configured offline gates
- **THEN** the system permits promotion to `monitoring` and records that live evidence is still pending

#### Scenario: Live shadow period is incomplete
- **WHEN** a monitoring model has fewer than 60 matured live trading days
- **THEN** the system refuses `validated` promotion and reports the remaining evidence requirement

### Requirement: Forecasts fail closed
The system SHALL emit an unavailable state rather than a numeric forecast when data
freshness, quality, model eligibility, calibration, or required evidence is missing.

#### Scenario: Factors are stale
- **WHEN** required inputs are older than the versioned freshness threshold
- **THEN** the forecast returns `stale_data` with the latest input date and does not reuse an older probability as current
