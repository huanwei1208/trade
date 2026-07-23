## ADDED Requirements

### Requirement: BTC volatility features are point-in-time safe
The system SHALL compute 20-day annualized realized volatility and the
high-volatility threshold using only completed observations available at or
before each anchor date.

#### Scenario: Expanding threshold excludes future observations
- **WHEN** a later extreme-volatility observation is added to the dataset
- **THEN** thresholds and regimes for earlier anchor dates remain unchanged

### Requirement: Forward labels are explicit and non-overlapping
The system SHALL compute seven-complete-UTC-day future realized volatility and
absolute return labels, mark incomplete horizons as pending, and separate
eligible high-volatility events by at least seven days.

#### Scenario: Latest anchor has no complete horizon
- **WHEN** fewer than seven completed UTC days follow an anchor
- **THEN** its label status is `pending_horizon` and no numeric zero is substituted

### Requirement: Validation uses purged walk-forward evidence
The system SHALL use an expanding 180-day training window, 60-day tests,
60-day steps, seven-day purge/embargo, at least three valid folds, at least
30 non-overlapping events, at least three events per valid fold, and at least
eight same-window normal comparators per valid fold.

#### Scenario: Sample is insufficient
- **WHEN** any required history, event, or fold gate is not met
- **THEN** the completed run reports `insufficient_data` and does not emit a support score implying validation

### Requirement: Statistical status includes practical effect
The system SHALL mark H1 `validated` only when the median future-volatility
ratio is at least 1.10, the fixed-seed block-bootstrap 95% lower bound exceeds
1.0, the BH-adjusted q-value is at most 0.10, and at least two-thirds of valid
folds have positive effects.

#### Scenario: Stable positive synthetic effect
- **WHEN** a leakage-free synthetic dataset satisfies every data, sample, statistical, and effect gate
- **THEN** the H1 result is `validated` with metrics, fold evidence, confidence interval, q-value, and `causal=false`

#### Scenario: Complete but unstable evidence
- **WHEN** data and sample gates pass but the statistical or fold-stability gates do not
- **THEN** the result is `monitoring` rather than `validated`

#### Scenario: Significant opposite effect
- **WHEN** sufficient evidence significantly supports the opposite pre-registered effect
- **THEN** the result is `rejected` with explicit evidence and no trade recommendation

### Requirement: Validation runs are deterministic and auditable
The system SHALL derive a deterministic run ID from inputs, configuration, and
contract version and SHALL persist readiness, fold, aggregate, reason, evidence,
watermark, and hash metadata in additive research outputs.

The system SHALL keep that deterministic validation run ID separate from the
ADS generation ID. A new lifecycle predecessor, activation decision, or data
rollback SHALL produce a new generation receipt even when the statistical
validation result itself is unchanged.

#### Scenario: Identical replay
- **WHEN** the same immutable inputs, code version, and configuration are replayed
- **THEN** the run ID, features, labels, metrics, status, and output hashes are identical

#### Scenario: Data is not ready
- **WHEN** the input BTC data readiness is not `ready`
- **THEN** signal validation is suppressed and the output identifies the blocking data gates

### Requirement: Cross-table ADS visibility uses one generation pointer
The system SHALL serialize lifecycle transition and ADS persistence, write a
completion receipt for all four additive tables, and switch one current pointer
only after the complete run is durable. Readers SHALL select every table by the
pointer run ID rather than infer current state from flat-table row order.

#### Scenario: Writer stops after a partial table replacement
- **WHEN** only a subset of the new run's flat tables has been replaced
- **THEN** the current pointer still selects the previous complete run and the official reader returns no mixed-run snapshot

### Requirement: Placebo checks prevent false validation
The system SHALL execute deterministic time-shifted and randomized-placebo
checks and SHALL block a validated status if a placebo passes the registered
significance gates.

#### Scenario: Future-information placebo passes
- **WHEN** a future-feature or shifted-label placebo appears statistically valid
- **THEN** the run is invalidated with leakage evidence

### Requirement: Active validation state is conservatively revalidated
The system SHALL suppress active evidence whenever data readiness is not ready
and SHALL require two consecutive confidence intervals crossing the null before
downgrading a previously validated H1 state to monitoring. Counted lifecycle
rechecks SHALL have watermarks at least 28 days apart; intervening daily runs
remain auditable but do not advance the crossing counter.

#### Scenario: First unstable revalidation after a validated run
- **WHEN** one ready-data revalidation is monitoring because its confidence interval crosses the null
- **THEN** the active state remains validated with a pending-recheck marker

#### Scenario: Second consecutive unstable revalidation
- **WHEN** the next ready-data run also crosses the null
- **THEN** the active state is downgraded to monitoring and both run IDs remain auditable

#### Scenario: Daily duplicate evidence does not advance lifecycle
- **WHEN** a null-crossing run arrives fewer than 28 days after the previous active recheck
- **THEN** the run is retained as audit evidence but does not replace the active state or increment the crossing counter
