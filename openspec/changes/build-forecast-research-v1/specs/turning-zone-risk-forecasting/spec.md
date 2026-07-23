## ADDED Requirements

### Requirement: Local extrema are forecast as zones
The system SHALL forecast the probability that a versioned local-low or local-high
event occurs within a future horizon. The output SHALL state the horizon,
neighborhood, reversal or rebound threshold, tolerance, probability, calibration
state, and model version, and SHALL NOT claim an exact turning date or price.

#### Scenario: Local-low zone forecast is available
- **WHEN** an eligible local-low model receives a ready point-in-time feature row
- **THEN** the system emits a future-window probability and the complete versioned zone definition

#### Scenario: Consumer requests an exact bottom
- **WHEN** a caller asks the forecast service for an exact bottom date or price
- **THEN** the service rejects the unsupported semantic and directs the caller to the probabilistic zone output

### Requirement: Turning labels use future data only after maturity
The system SHALL build turning-zone labels only after the complete future horizon
and local neighborhood have matured. Forecast features SHALL remain limited to the
decision-time information set.

#### Scenario: Reversal confirmation is incomplete
- **WHEN** the configured future rebound or decline window is not complete
- **THEN** the turning-zone label is `label_not_mature` and is excluded from fitting and validation

### Requirement: Downside risk is probabilistic and unit-safe
For each supported horizon, the system SHALL expose decimal-return q10/q50/q90,
probability of loss beyond the configured decimal threshold, expected maximum
adverse excursion, and volatility-regime state. Risk thresholds SHALL carry explicit
decimal units.

#### Scenario: Five-percent loss risk is requested
- **WHEN** the configured threshold is a 5% loss
- **THEN** the model and evaluator both use `-0.05` decimal return and persist the threshold unit with the result

#### Scenario: Quantiles are inconsistent
- **WHEN** generated quantiles do not satisfy q10 less than or equal to q50 less than or equal to q90
- **THEN** the system marks the forecast invalid and emits no risk summary from those values

### Requirement: Rare-event evaluation uses alert-aware metrics
The system SHALL evaluate local-zone and tail-risk targets with PR-AUC, Brier score,
calibration error, precision and recall at a versioned alert budget, lead/lag within
the tolerance window, and event counts. It SHALL NOT use accuracy alone as an
eligibility gate.

#### Scenario: Accuracy is high because events are rare
- **WHEN** a model predicts no events and achieves high overall accuracy
- **THEN** the validator reports failed event recall and prevents promotion

### Requirement: Risk uncertainty is visible
The system SHALL expose insufficient-event, calibration-unavailable, and
out-of-regime states, together with sample counts and evidence windows, rather than
substituting a neutral probability.

#### Scenario: Too few tail events exist in a fold
- **WHEN** a validation fold has fewer events than the policy requires for calibration
- **THEN** the risk result is `calibration_unavailable` for that fold and cannot satisfy the promotion gate
