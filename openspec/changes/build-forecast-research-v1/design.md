## Context

The repository already has useful building blocks for factor storage, event features,
model registration, evaluation, causal evidence, recommendations, and research
workbenches. Those pieces are not yet a trustworthy forward-looking research loop.
The current local evidence shows why the next slice must start with data contracts:

- the regular factor panel ends on 2026-03-23 and event features end on 2026-03-12;
- the event feature file has only 53 dates, while the current model evaluations use
  five valid dates;
- 5-day and 20-day return labels contain extreme values above 100 in their current
  stored unit;
- event propagation outcomes contain many more extreme observations, with a maximum
  above one million;
- risk training uses `-0.05` while one evaluation path uses `-5.0`, so a decimal and
  percentage representation can be compared as if they were the same unit;
- current recommendation output is overwhelmingly `watch` and is not calibrated as
  a probability forecast.

This design therefore separates operational data availability from research
readiness. A successful sync does not imply that a dataset is safe for training, and
a model artifact does not imply that its forecast is validated.

The first production-shaped research universe is daily A-share data for CSI 300
constituents plus an explicit local watchlist. The broader A-share universe and
crypto research remain separate expansion tracks. The design reuses existing
factor, model-registry, evaluation, evidence, causal, and warehouse modules through
stable adapters; event, knowledge-graph, and belief features are optional evidence,
not mandatory inputs to the first daily baseline.

## Goals / Non-Goals

**Goals:**

- Build a reproducible point-in-time dataset with explicit universe, adjustment,
  availability, feature, label, and unit contracts.
- Produce calibrated 1-, 5-, and 20-trading-day direction, excess-return, interval,
  local-zone, and downside-risk forecasts.
- Compare every learned candidate with simple historical, momentum, sector, and
  linear/logistic baselines using purged walk-forward evaluation.
- Persist immutable forecast snapshots and append-only realized outcomes so every
  statement can be replayed and audited.
- Expose concise read-only CLI commands for dataset readiness, forecasts, ranking,
  risk, and validation state.
- Fail closed when data, label maturity, model validation, or calibration is
  insufficient, and expose the reason instead of emitting a confident decision.

**Non-Goals:**

- Automatic order generation, portfolio execution, or forced buy/sell advice.
- Claiming exact tops or bottoms; the product is a probability for a local zone in a
  future window.
- Deep-learning or model-zoo work before transparent baselines pass the same gates.
- A Web UI in the first implementation slice.
- Replacing the existing event, causal, recommendation, or crypto workflows.
- Promoting historical backtest performance directly to `validated` without a live
  shadow-observation period.

## Architecture

```text
market/factor/event sources
          |
          v
point-in-time adapters ---> quality audit/quarantine
          |                         |
          v                         v
versioned dataset manifest + partitioned feature/label panels
          |
          +--> baseline/model training --> purged walk-forward validation
          |                                  |
          |                                  v
          |                           model registry + gates
          |                                  |
          v                                  v
forecast service -----------------> immutable forecast snapshots
                                             |
realized prices --------------------> append-only outcomes
                                             |
                                             v
                            read-only CLI status/show/rank/risk
```

Python ownership remains layered:

- `trade_py/research/dataset/` owns point-in-time assembly, manifests, label
  maturity, quality gates, and replay hashes.
- `trade_py/research/forecast/` owns targets, baselines, training, calibration,
  validation, turning-zone definitions, and forecast orchestration.
- existing DB repository packages own additive dataset, model-validation, snapshot,
  and outcome persistence; services do not embed SQL.
- `trade_py/cli/research.py` is the stable facade and delegates to services.
- existing factor/event/evidence modules are consumed through adapters so their
  storage contracts are not silently redefined.

## Decisions

### 1. Canonical returns are decimal values

All internal returns, thresholds, quantiles, and realized outcomes use decimal
values: `0.05` means 5%. Human-facing commands may render a percent column, but
stored fields include `unit=decimal_return` and never infer a unit from magnitude.
The implementation first traces the extreme outcomes to adjustment, denominator,
or unit defects; it quarantines rather than clips unexplained values.

Alternative considered: keep existing percent-valued event outcomes and convert in
each consumer. This preserves local behavior but repeats the current ambiguity at
every boundary and is rejected.

### 2. Dataset versions are immutable and point-in-time

A dataset version records an `as_of` timestamp, trading calendar, universe version,
source versions, adjustment policy, feature availability times, label definitions,
quality report, row counts, partition hashes, and code version. Features at decision
time `t` can only use facts available by `t`; future data is permitted only in a
separate matured-label partition. Rebuilds create a new version and an optional
active pointer rather than modifying a prior version.

Alternative considered: train directly from the latest factor and event files. It
is simpler but cannot prove absence of survivorship, revision, or future leakage.

### 3. V1 uses CSI 300 plus an explicit watchlist

The bounded universe makes adjustment and point-in-time membership auditable and
keeps iteration fast. Universe membership is itself dated data; a current component
list must not be projected backward. Watchlist membership has the same effective
date contract.

Alternative considered: start with every local symbol. The present data contains
thousands of symbols but too little reliable temporal depth, so breadth would hide
quality failures and raise full-scan cost.

### 4. Targets are multi-horizon and benchmark-relative

For each of 1, 5, and 20 trading days, the research panel contains forward decimal
return, benchmark/sector excess return, direction, and matured-label state. Forecasts
contain up probability, expected excess return, q10/q50/q90 return intervals, and
target-specific calibration metadata. Labels use adjusted prices and a versioned
benchmark definition.

Alternative considered: a single binary up/down label. It is easy to explain but
does not express magnitude, uncertainty, or relative opportunity.

### 5. Local optima are modeled as future zones

The system predicts the probability that a configured local-low or local-high event
occurs inside a future horizon. A versioned label definition specifies the local
neighborhood, minimum reversal/rebound, tolerance, and horizon. Only the label
builder sees the future neighborhood after it matures. Output names use `zone`, not
`top` or `bottom`, and always include probability, horizon, tolerance, and status.

Alternative considered: predict the exact turning date and price. That target is
unstable, encourages leakage, and overstates precision.

### 6. Baselines precede model complexity

The first candidates are historical prevalence, benchmark/sector prevalence,
momentum rules, regularized linear/logistic models, and one tree baseline such as
LightGBM when already available. Every candidate is evaluated through the same
dataset and cost assumptions. A complex model can advance only if it beats the best
eligible baseline across enough out-of-sample days and is not dependent on one
sector or regime.

Alternative considered: reuse active KG models as the primary forecast. They remain
eligible optional evidence, but their stale five-day evaluation does not establish a
general daily forecast baseline.

### 7. Validation uses purged expanding walk-forward splits

Splits preserve time order, purge overlapping labels, embargo adjacent samples, and
fit preprocessing inside each training fold. Initial research eligibility requires
at least 500 trading sessions in the dataset, at least six folds, and at least 120
distinct out-of-sample trading days. Metrics include rank IC, direction ROC-AUC and
PR-AUC where appropriate, Brier/log loss, calibration error, interval coverage,
top-decile excess return after configured costs, drawdown, and sector/regime slices.

Model states are `candidate`, `monitoring`, `validated`, `rejected`, or `blocked`.
Offline gates can advance a candidate only to `monitoring`; `validated` requires at
least 60 matured live trading days, stable calibration, and explicit approval.

Alternative considered: random cross-validation. It inflates performance when time
and labels overlap and is rejected for all forecast promotion decisions.

### 8. Forecasts and outcomes are separate audit records

`ForecastSnapshot` is immutable and contains forecast time, symbol, horizon,
universe/dataset/model versions, probabilities and intervals, evidence references,
calibration state, and failure/unknown reasons. `ForecastOutcome` is append-only and
is written only after a label matures. A validation run references both sets and its
configuration. No outcome update mutates what was known when the forecast was made.

Alternative considered: recalculate forecasts on demand. It saves storage but makes
live calibration, regression comparison, and audit impossible.

### 9. CLI commands are concise and safe by default

The everyday surface stays flat; operational detail is exposed through flags rather
than another level of subcommands:

```text
./trade research status
./trade research forecast [SYMBOL]
./trade research rank
./trade research risk [SYMBOL]
./trade research build --dry-run
./trade research validate
./trade research outcomes
```

`status` includes research-dataset readiness and accepts `--detail` for its quality
audit. Read commands never trigger collection, training, migrations, or outcome
writes. Write commands support `--dry-run`, declare the selected
universe/as-of/version, and print their mutation plan. Existing command surfaces
remain compatible.

### 10. Storage changes are additive and reversible

Metadata is stored through additive DB migrations. Large feature and label panels
remain versioned columnar partitions, with DB records pointing to manifests. Before
touching a real DB or active pointer, the workflow creates a backup/snapshot,
supports dry-run, verifies a small sample and hashes, and documents rollback to the
previous active version. Tests use temporary roots only.

## Performance and Observability

- Dataset builds partition by date and universe version, scan only required columns,
  and reuse unchanged partitions by content hash.
- Status commands query manifests and aggregate quality records rather than scanning
  the full panel.
- Forecast generation is batch-oriented per as-of date; model loading and feature
  reads are shared across symbols.
- Every stage emits counts, elapsed time, source freshness, quarantine rates,
  missingness, label maturity, and version identifiers.
- Structured failure codes distinguish `stale_data`, `insufficient_history`,
  `label_not_mature`, `unit_violation`, `quality_gate_failed`,
  `model_not_eligible`, and `calibration_unavailable`.

## Risks / Trade-offs

- **Historical constituent data is incomplete** -> Treat unknown membership as a
  blocking quality state; do not backfill current CSI 300 membership into history.
- **Corporate actions create false extreme returns** -> Require adjustment-policy
  provenance and cross-check suspicious rows against raw prices before training.
- **Fixed metric thresholds encourage overfitting** -> Version gates and require
  baseline, regime, calibration, and live-shadow evidence together.
- **Rare turning/risk events yield unstable accuracy** -> Use PR-AUC, calibration,
  precision at a fixed alert budget, confidence intervals, and explicit unavailable
  states instead of headline accuracy.
- **A bounded universe misses opportunities** -> Expand only after the same dataset
  and validation gates pass; universe is a versioned input, not a code rewrite.
- **Sixty live days delays a `validated` label** -> Allow `monitoring` forecasts for
  inspection while clearly preventing promotion claims.
- **Existing evidence modules have mixed units or freshness** -> Consume them only
  through adapters that validate units, as-of availability, and optionality.

## Migration Plan

1. Run the mandatory six-role review against this change before implementation and
   resolve all P0 findings.
2. Add unit contracts, anomaly reports, and fixture-based tests; audit existing
   extreme labels without mutating real data.
3. Add additive metadata schema and repositories with migration dry-run, backup,
   sample verification, and rollback coverage.
4. Build one small point-in-time sample, replay it, and compare hashes before creating
   a full CSI 300 plus watchlist dataset version.
5. Train/evaluate baselines and candidates; publish only `candidate` or `blocked`
   states until offline gates pass.
6. Generate immutable daily snapshots in shadow mode and append outcomes as labels
   mature.
7. After at least 60 live trading days, review calibration and stability before any
   explicit promotion to `validated`.

Rollback never rewrites an old dataset, snapshot, or outcome. It repoints the active
dataset/model to the prior verified version, disables scheduled shadow generation,
and leaves additive tables available for audit.

## Open Questions

- Which authoritative source will provide historical CSI 300 membership dates? The
  implementation must block historical builds until this is resolved.
- Which local watchlist file/table is the stable owner, and how are effective dates
  represented?
- Which benchmark and sector taxonomy are complete enough for the first excess-return
  contract?
- What initial transaction-cost assumptions and alert budgets should be versioned in
  the first validation policy? Defaults must be conservative and visible.
- Are existing active KG model records safe to relabel after unit audit, or should
  they remain legacy-only and be retrained under the new contracts?
