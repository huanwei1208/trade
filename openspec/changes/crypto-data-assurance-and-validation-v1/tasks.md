## 1. Documentation and Safety Baseline

- [x] 1.1 Add the detailed Crypto child plan and link it from the analysis-first parent plan
- [x] 1.2 Create proposal, design, capability specs, and implementation tasks for this change
- [x] 1.3 Recheck worktree safety and record that unrelated runtime data remains outside this branch

## 2. BTC Market Data Contract

- [x] 2.1 Make `DataGateway.get_cross_asset` a canonical-path pure reader with explicit degraded reports
- [x] 2.2 Add provider-native BTC schema/domain objects and OKX `1Dutc` final-candle normalization
- [x] 2.3 Add CoinGecko daily-close shadow normalization without OHLC fallback or provider mixing
- [x] 2.4 Add immutable run storage, manifests, deterministic run IDs, and revision records

## 3. Data Assurance and Publication

- [x] 3.1 Implement D0-D2 contract, acquisition, coverage, schema, OHLC, and anomaly gates
- [x] 3.2 Implement D3-D4 UTC reconciliation, basis thresholds, revision thresholds, and replay checks
- [x] 3.3 Implement locked predecessor-CAS publication, fail-closed pointer/hash reads, publication authorization, and predecessor rollback
- [x] 3.4 Extend the cross-asset CLI with compatible sync/validate/status modes, dry-run, strict, and JSON behavior
- [x] 3.5 Add a dedicated 09:00 BTC job, fail closed, retain Gold/FX scheduling, and cascade successful publication to validation

## 4. BTC Volatility Validation

- [x] 4.1 Implement point-in-time BTC returns, rv20 regimes, future-rv7 labels, and pending-horizon states
- [x] 4.2 Implement event de-overlap, purged expanding walk-forward folds, and deterministic placebo checks
- [x] 4.3 Implement block-bootstrap confidence intervals, BH adjustment, practical-effect gates, and signal statuses
- [x] 4.4 Persist additive readiness, reconciliation, validation, and run-audit warehouse outputs
- [x] 4.5 Add the `crypto-btc-v1` research-validation CLI profile with dry-run and JSON output
- [x] 4.6 Track one active validation row, suppress failed-data runs, and require two null-crossing rechecks before downgrade

## 5. Verification and Delivery

- [x] 5.1 Add focused provider, path, contract, reconciliation, publish, rollback, and CLI tests using temporary roots
- [x] 5.2 Add focused synthetic validation tests for leakage, statuses, determinism, and insufficient samples
- [x] 5.3 Run offline focused pytest, compileall, full Python pytest, and OpenSpec validation; document outcomes and residual risks
- [x] 5.4 Recheck staged scope, commit only intentional validated files, and leave generated data untracked

## 6. Live Pilot Before Enabling Automation

- [ ] 6.1 Verify CoinGecko credential tier, OKX/CoinGecko live response contracts, rate limits, and dry-run zero-write behavior
- [ ] 6.2 Apply and inspect migration v17, host timezone, 09:00 failure semantics, and successful event cascade in the live runtime
- [ ] 6.3 Accumulate 29 distinct qualified acquisition days and at least two provider-native revision-overlap observations
- [ ] 6.4 Verify the first pointer switch, validate/status hashes, ADS evidence references, and a five-minute rollback rehearsal
