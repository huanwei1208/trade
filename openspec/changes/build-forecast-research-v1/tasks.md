## 1. Safety, review, and contract freeze

- [ ] 1.1 Create a dedicated implementation worktree and branch, record `git status -sb`, and keep local data, caches, and unrelated changes outside the branch.
- [ ] 1.2 Run the mandatory six-role `review-this` consensus review for reliability, performance, architecture, data quality, observability, and news sentiment; resolve all P0 findings before code changes.
- [ ] 1.3 Resolve and document the authoritative historical CSI 300 membership source, dated watchlist owner, benchmark, sector taxonomy, transaction-cost policy, and alert budgets.
- [ ] 1.4 Pre-register the V1 dataset and validation policy versions before inspecting candidate-model results.

## 2. M0 return-unit and anomaly investigation

- [ ] 2.1 Add focused fixtures reproducing decimal-versus-percent risk thresholds and extreme adjusted-return cases without reading or writing real data roots.
- [ ] 2.2 Trace `events/features.parquet` 5-day and 20-day extremes to raw price, adjustment, denominator, source-unit, and symbol/date evidence; write a read-only audit report.
- [ ] 2.3 Trace `event_propagations.actual_return_5d` extremes and reconcile the `-0.05` training threshold with the `-5.0` evaluation threshold.
- [ ] 2.4 Implement a typed decimal-return unit contract and explicit boundary adapters; add pytest coverage for exact-once conversion and unknown-unit rejection.
- [ ] 2.5 Implement anomaly quarantine records that retain raw evidence and prohibit silent clipping or training use; add focused quality-gate tests.
- [ ] 2.6 Run the focused unit/anomaly tests and `python -m compileall trade_py tests`, then commit the validated M0 unit as one logical change.

## 3. Additive research metadata storage

- [ ] 3.1 Define additive models for dataset versions, partition manifests, quality findings, validation runs, forecast snapshots, and forecast outcomes.
- [ ] 3.2 Implement owner-module repositories with immutable snapshot and idempotent append-only outcome semantics.
- [ ] 3.3 Add a migration dry-run, real-DB backup/snapshot hook, sample verification, active-version rollback, and migration tests using temporary databases.
- [ ] 3.4 Run focused repository/migration tests and compileall, record compatibility and rollback evidence, and commit the storage unit.

## 4. M1 point-in-time research dataset

- [ ] 4.1 Implement dated CSI 300 and watchlist universe adapters that fail closed when historical membership is unknown; add survivorship-bias contract tests.
- [ ] 4.2 Implement source adapters with as-of availability, source version, adjustment policy, and explicit units for prices, factors, and optional event evidence.
- [ ] 4.3 Implement separate feature and matured-label panels for 1-, 5-, and 20-day return, excess return, direction, and label-maturity state.
- [ ] 4.4 Implement manifest generation, content hashes, deterministic replay, partition reuse, and replay mismatch diagnostics.
- [ ] 4.5 Implement freshness, duplicates, missingness, calendar, adjustment, finite-value, unit, history-depth, and quarantine readiness gates.
- [ ] 4.6 Add fixture-based point-in-time leakage, label maturity, replay, and fail-closed tests, including a small end-to-end sample build.
- [ ] 4.7 Run focused dataset tests, compileall, and a bounded performance smoke proving status does not full-scan panels; commit the M1 dataset unit.

## 5. Compressed research CLI for data readiness

- [ ] 5.1 Add the `./trade research` facade while preserving all existing `trade` commands and help output.
- [ ] 5.2 Implement read-only `./trade research status` with readiness, freshness, coverage, label maturity, quarantine counts, active versions, and blocking reasons.
- [ ] 5.3 Add `status --detail` for the quality audit and `build --dry-run` for source, universe, date-range, partition, check, and mutation previews.
- [ ] 5.4 Add CLI contract tests proving read commands perform no collection, migration, training, activation, or outcome writes.
- [ ] 5.5 Run focused CLI tests and compileall, capture concise help/output examples, and commit the CLI-readiness unit.

## 6. M2 baselines and leakage-resistant validation

- [ ] 6.1 Implement versioned historical-prevalence, benchmark/sector-prevalence, momentum, regularized linear, and logistic baselines.
- [ ] 6.2 Implement expanding walk-forward splits with label-window purge, embargo, fold-local preprocessing, and effective-sample accounting.
- [ ] 6.3 Implement direction, ranking, calibration, interval, net-return, drawdown, sector, and regime metrics with uncertainty and sample counts.
- [ ] 6.4 Implement versioned costs, metric gates, and `candidate`, `monitoring`, `validated`, `rejected`, and `blocked` lifecycle transitions.
- [ ] 6.5 Add tests for temporal ordering, purge/embargo, preprocessing isolation, baseline parity, insufficient history, regime collapse, and offline-to-monitoring-only promotion.
- [ ] 6.6 Run focused validation tests and compileall, serialize one reproducible validation fixture, and commit the M2 validation unit.

## 7. M3 multi-horizon forecast service

- [ ] 7.1 Implement 1-, 5-, and 20-day direction probability, expected excess return, and ordered q10/q50/q90 forecast contracts.
- [ ] 7.2 Implement calibration metadata and fail-closed handling for stale data, failed quality, ineligible models, and unavailable calibration.
- [ ] 7.3 Add optional evidence adapters for event, KG, belief, causal, and recommendation inputs that preserve `calibrated=false` and never determine eligibility alone.
- [ ] 7.4 Add service tests for horizon independence, quantile ordering, version propagation, optional evidence, and every unavailable reason.
- [ ] 7.5 Run focused forecast tests and compileall, compare candidates with all baselines on the fixture dataset, and commit the M3 forecast unit.

## 8. M4 turning-zone and downside-risk forecasts

- [ ] 8.1 Freeze versioned local-low/local-high label definitions for neighborhood, horizon, tolerance, and minimum rebound or reversal.
- [ ] 8.2 Implement matured turning-zone labels with tests proving that future confirmation never enters point-in-time features.
- [ ] 8.3 Implement local-low/local-high probabilities, loss-threshold probability, maximum adverse excursion, and volatility-regime outputs.
- [ ] 8.4 Implement PR-AUC, Brier score, calibration error, alert-budget precision/recall, lead/lag, and rare-event availability metrics.
- [ ] 8.5 Add tests for rare no-event folds, exact-bottom semantic rejection, decimal risk thresholds, inconsistent quantiles, and unavailable calibration.
- [ ] 8.6 Run focused turning/risk tests and compileall, document event counts and alert-budget sensitivity, and commit the M4 risk unit.

## 9. M5 immutable forecasts and observation commands

- [ ] 9.1 Persist immutable forecast snapshots with exact as-of, dataset, universe, model, evidence, calibration, validation, and failure states.
- [ ] 9.2 Append idempotent outcomes only after label maturity and link them to the exact snapshot and label definition.
- [ ] 9.3 Implement read-only `forecast`, `rank`, `risk`, and `outcomes` commands with clear units, horizons, versions, and blocked reasons.
- [ ] 9.4 Implement `validate --dry-run` and explicit validation-run persistence without implicit model activation.
- [ ] 9.5 Add repository, service, and CLI tests for immutability, idempotency, maturity, ranking, read-only behavior, and reproducible validation.
- [ ] 9.6 Run focused observability/CLI tests, compileall, and a batch performance smoke for the bounded universe; commit the M5 observability unit.

## 10. Shadow rollout and promotion evidence

- [ ] 10.1 Back up metadata, dry-run the live dataset build, verify a small CSI 300 plus watchlist sample, then build and activate only a quality-ready version.
- [ ] 10.2 Train baselines and candidates from the active version and publish only `candidate`, `blocked`, or explicitly approved `monitoring` states.
- [ ] 10.3 Schedule daily shadow snapshots and matured-outcome appends with freshness, failure, latency, and drift observability.
- [ ] 10.4 Accumulate at least 60 matured live trading days and review calibration, net performance, sector/regime stability, and alert-budget behavior before any `validated` promotion.
- [ ] 10.5 Exercise rollback to the previous dataset/model active pointers and document residual data, compatibility, and calibration risks.

## 11. Final validation and branch closeout

- [ ] 11.1 Run all focused pytest suites, `python -m compileall trade_py trade_web tests`, strict OpenSpec validation, CLI compatibility smoke, and the documented performance smokes.
- [ ] 11.2 Run `git status -sb` and `git diff --check`, stage only intentional code/tests/docs, and confirm no generated research data or local DB is tracked.
- [ ] 11.3 Summarize exact validations, versions, rollback evidence, performance-smoke classification, and remaining risks in the final commit body.
- [ ] 11.4 Commit every validated logical unit, push after each 3-5 commits, then squash-merge the approved implementation branch to master and remove its branch/worktree per repository policy.
