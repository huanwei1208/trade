# Data Operations Workflow Plan

## Outcome

Reduce normal data operation to three commands while fixing the correctness defects that currently make a short facade unsafe:

```text
./trade data status
./trade data update [core|crypto|all]
./trade data check [--full]
```

Detailed dataset commands remain available as advanced compatibility paths.

## Current Evidence

- `trade data --help` exposes 21 first-level commands and dozens of examples.
- `trade status data --json` scanned about 9.46 million rows, took roughly 13 seconds in review measurement, and emitted more than 3,400 lines.
- Repeated `asset_batch_ingest` DAG rows currently share a handler identity and lose row-local configuration; commodity, FX, and crypto can therefore be skipped or run with the wrong class.
- BTC assurance and generic batch ingest can both write `market/crypto/btc.parquet` with different lock and publication contracts.
- Generic ingest can report `0/0` as success and can treat unreadable existing parquet as missing.

## Implementation Slices

1. P0 orchestration: row-unique DAG handlers, exact config propagation, additive metadata migration, BTC single-writer enforcement.
2. P0 durable semantics: fail-closed parquet/WAL reads, no-target and partial-failure handling, provider finality fix.
3. Concise facade: dedicated operations package, explicit profiles, dry-run, parent/child results, compatibility routing.
4. Read-only observability: metadata status, standard/full checks, compact JSON, stable exit codes.
5. Rollout: temporary-root tests, compileall/OpenSpec validation, real-root read-only status and dry-run, targeted incremental update, post-update check.

## Data Safety and Rollback

- Tests never point writers at the real root.
- The schema migration changes only DAG/asset metadata and is idempotent.
- `status`, `check`, and `update --dry-run` must produce zero filesystem/DB changes.
- SQLite metadata reads use WAL-aware `mode=ro`; `immutable=1` is forbidden because it can silently ignore uncheckpointed job and watermark records.
- Before a live crypto update, record the BTC current pointer, manifest path, and hashes; BTC assurance retains predecessor rollback.
- Failed updates never delete parquet or unreadable WAL. Rollback of the facade is a code/config revert, not a bulk data rewrite.
- A BTC candidate that passes structural, reconciliation, and revision gates but lacks 29 distinct successful acquisition dates is staged, not published. The profile reports warning code 1 and continues the independently owned non-BTC step; other BTC failures remain stop-on-failure errors.

## Validation Gates

- Unit tests for every new behavior and regression.
- Focused CLI, bus/DAG, ingest, migration, provider, and status pytest.
- `python -m compileall trade_py tests`.
- `openspec validate simplify-data-workflow --strict`.
- Help and dry-run smoke checks.
- Real-root read-only status/dry-run diff check.
- Targeted live update only after preflight; verify job results, watermarks, BTC pointer/hash, and `data check` result.
- A warning is an accepted terminal state only for an auditable time-based pilot gate; it is never used for provider, integrity, persistence, or partial-target failures.

## Deferred Risks

- News/sentiment is not in the initial structured-data profiles. Same-day overwrite and split-stage duplication must be fixed before it joins `all`.
- Dataset-specific direct legacy commands do not all share the new profile lock; they remain advanced paths until storage ownership is fully converged.
- Full value-quality audit is intentionally expensive and remains explicit.

## Delivery Evidence (2026-07-16)

- Baseline review worktree: `346 passed, 20 failed`; completed branch: `386 passed, 12 warnings` in 16.43 seconds. Focused operations/crypto coverage: `41 passed`.
- `python -m compileall trade_py trade_web tests`, `bash -n trade`, concise help smoke, and `openspec validate simplify-data-workflow --strict` passed. OpenSpec emitted only unreachable telemetry noise after reporting the change valid.
- Real-root status completed in 35–40 ms and observed the active WAL's latest job rows. DB, WAL, and SHM size/mtime snapshots were identical before and after the read.
- Real-root status plus `update crypto --dry-run` left all 17,678 observed filesystem entries unchanged.
- Live profile audit: parent job `2326` ended `warn`; BTC child `2327` staged candidate `0d49797bce89626cb8b1ee06` with `qualified_days=2/29`; non-BTC child `2328` completed `4/4` and added 20 rows.
- BTC current pointer hash `7ed8c5127ac02348ff9a9ce565900fd23ce4d55306d26a7d9ec3495c4df6b659` and canonical hash `46ad952d96e74317f3bc2cc4ac28d843334fbd747acfd12d6d8b69da1285d4e7` remained unchanged because the candidate was not publishable.
- ETH, SOL, BNB, and XRP each reached watermark `2026-07-15`, with 735 distinct non-null dates apiece. The full crypto check reported `10 pass, 2 warn, 0 fail, 0 unknown`; both warnings are the same explicit BTC pilot/freshness condition.
- Metadata migration version 22 is applied; repeated `asset_batch_ingest` rows retain commodity, FX, and crypto-specific config, and crypto excludes BTC.
- Performance-smoke classification: **updated**. Default status is metadata-only and was measured on the real root; full value checks remain opt-in.
