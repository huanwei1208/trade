## 1. Specification and Baseline

- [x] 1.1 Validate the proposal, design, capability specs, and detailed docs plan against the six-role consensus findings
- [x] 1.2 Record baseline focused test failures and confirm the implementation worktree contains no unrelated runtime data

## 2. DAG and Canonical Ownership P0

- [x] 2.1 Bind EventBus DAG handlers to row-unique identities and pass the exact parsed row config into `run_job`
- [x] 2.2 Add an idempotent metadata migration that records BTC assurance ownership and excludes BTC from generic Crypto DAG ingest
- [x] 2.3 Enforce specialized BTC ownership in generic batch selection and update recovery guidance
- [x] 2.4 Add focused temporary-DB and pointer-invariant tests for repeated DAG jobs and BTC exclusion

## 3. Durable Ingestion P0

- [x] 3.1 Make existing parquet and WAL read errors fail closed without replacing the unreadable artifact
- [x] 3.2 Propagate final flush failures into per-asset results and make zero-target or partial batches non-success
- [x] 3.3 Correct Binance daily-candle finality to use close-time semantics
- [x] 3.4 Add fault-injection tests for corrupt parquet/WAL, zero targets, partial flush, and open UTC candles

## 4. Concise Data Operations Facade

- [x] 4.1 Add focused operation contracts and versioned `core`, `crypto`, and `all` profiles with no decision/model cascades
- [x] 4.2 Implement dry-run and locked profile execution with ordered step audit and stop-on-failure behavior
- [x] 4.3 Implement compact read-only status using pure filesystem paths, manifests, and SQLite URI read-only connections
- [x] 4.4 Implement standard and full read-only checks with compact/detail JSON and centralized exit codes
- [x] 4.5 Route `trade data`, `status`, `update`, and `check` to the facade; preserve detailed legacy commands and shorten root help
- [x] 4.6 Add CLI behavior tests for help, profiles, dry-run zero-write, empty-root status, check tiers, compatibility routing, and exit codes

## 5. Validation and Delivery

- [x] 5.1 Run focused pytest for CLI, DAG, ingest, migration, provider, crypto assurance, and status behavior
- [x] 5.2 Run shared Python pytest/compileall and document any pre-existing or unrelated failures
- [x] 5.3 Run OpenSpec strict validation plus help, dry-run, and performance smoke checks
- [x] 5.4 Verify real-root status and profile dry-run are read-only, then run the smallest authorized live incremental profile and strict post-check
- [x] 5.5 Recheck staged scope, commit each validated implementation unit, record compatibility/data risks, and classify performance smoke coverage
