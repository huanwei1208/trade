## Context

The current `trade data` parser mixes orchestration, status, source CRUD, data browsing, and more than a dozen dataset-specific commands in one file. The apparent unified sync covers only registry-backed crypto/FX/commodity assets, while scheduled ingestion is driven by repeated `pipeline_dag` rows that share a job name but have different configurations. Because handler identity and config lookup are job-name based, repeated nodes can be deduplicated or execute an unrelated first configuration. The BTC assurance service and generic batch engine also publish to the same canonical path with different locks.

Operationally, `trade status data` performs a multi-million-row value scan by default, emits thousands of JSON lines, and several read-looking paths construct `TradeDB` or directory helpers that migrate/create state. The user needs a short, reliable route that says what will run, updates the intended datasets, and verifies the result without hiding unknown or partial states.

The change must preserve real local data, keep existing detailed commands usable, use temporary roots for tests, and avoid coupling data refresh to model training or trading decisions.

## Goals / Non-Goals

**Goals:**

- Make `trade data`, `trade data status`, `trade data update`, and `trade data check` the primary workflow.
- Make status genuinely read-only and metadata-based, with a compact machine-readable schema.
- Define explicit, ordered data profiles with per-step configuration and deterministic failure behavior.
- Repair DAG row identity/config propagation and establish one canonical writer for BTC.
- Fail closed on unreadable durable inputs, invalid provider finality, zero targets, partial persistence failures, and unexpected empty acquisitions.
- Preserve legacy commands and their detailed options as an advanced compatibility surface.

**Non-Goals:**

- Changing trading-decision, recommendation, model-training, or backtest semantics.
- Repartitioning or bulk-rewriting existing parquet.
- Treating news/LLM pipelines as implicit dependencies of structured market-data refresh.
- Completing every historical data-storage performance improvement in one slice; remaining dataset-specific storage risks stay explicit and do not become hidden success.

## Decisions

### 1. Put the concise workflow in a dedicated operations package

Create focused contracts, profiles, read-only status, and update services below `trade_py/data/operations/`. `trade_py/cli/data.py` only detects the primary commands and delegates; its existing parser/handlers remain the legacy implementation.

Alternative rejected: adding three more branches and orchestration logic to the existing 2,000+ line CLI module. That would preserve the catch-all boundary that caused command and failure-policy drift.

### 2. Keep `sync` compatible and introduce `update` as the unambiguous operation

The current `trade data sync` retains its registry-ingest meaning for compatibility. The new `trade data update [core|crypto|all]` owns the business workflow, while bare `trade data` and `trade data status` are fast read-only status. Primary help shows only `status/update/check`; `--help-all` points to legacy commands.

Alternative rejected: silently changing bare `sync` from seven registry assets to a long multi-dataset run. That would be a surprising and potentially expensive write expansion.

### 3. Use version-controlled ordered profiles, not tag discovery

Profiles are immutable tuples of step IDs, job names, and explicit configuration:

- `core`: Kline, market/sector index, fund flow, and northbound.
- `crypto`: BTC assurance, then generic non-BTC crypto assets.
- `all`: `core + crypto + fundamental + macro`.

News/sentiment remains an explicit advanced workflow until its same-day writes and stage boundaries satisfy the no-data-loss contract. No profile triggers model, belief, recommendation, or evaluation jobs. `--dry-run` renders the exact plan without constructing a DB or writing files.

Alternative rejected: selecting all registry jobs with `stage=fetch` or daily tags. The registry contains legacy, split, NLP, calendar, and optional jobs whose ordering and cost are not interchangeable.

### 4. Bind DAG execution to row identity

`bootstrap_from_dag` parses each row's `config_json`, passes it directly to `run_job`, and includes the DAG row ID in handler identity. This prevents subscription de-duplication and unordered `LIMIT 1` config resolution. The job-name lookup remains only as a backward-compatible fallback for direct single-job callers.

### 5. Enforce BTC canonical ownership at the generic-ingest boundary

Generic batch selection excludes `crypto.BTC` and reports the specialized owner. The crypto profile always runs BTC assurance separately. An additive migration updates the crypto batch DAG metadata to exclude BTC and documents the ownership boundary. This is defense in depth: even an old or manually edited DAG cannot make the generic engine overwrite assurance output.

Alternative rejected: sharing a lock between two semantically different writers. A common lock would serialize writes but would not preserve the assurance pointer/hash contract.

### 6. Make durable ingest failures explicit

Existing parquet and WAL reads fail closed: an unreadable artifact is preserved and the asset fails with evidence instead of being treated as missing. Final flush errors are reflected back into per-asset results. Zero selected targets and any partial batch failure are non-success. Provider-empty frames are only successful when an existing watermark proves the requested interval is already current; otherwise they are degraded/failure.

Provider finality derives from candle close time relative to fetch time, never from a provider field with different semantics such as Binance trade count.

### 7. Separate status, check, and full audit cost

`status` reads only existing manifests and SQLite through URI `mode=ro`; it never creates a directory or applies migrations. Missing evidence is `unknown`, not pass. Target latency is under two seconds for the current local dataset.

`check` runs the existing consolidated validation without value-row scanning. `check --full` adds value-quality scans and emits a compact summary by default; `--detail` exposes the full evidence tree. Both remain read-only by replacing inspector uses of creating path helpers with pure path construction.

Exit codes are centralized: `0=pass`, `1=warn`, `2=quality/update failure`, `3=execution error`, `130=interrupted`.

### 8. Use an update-level lock and parent/child audit result

An update profile takes a non-blocking profile lock below `.db/locks/` before running. Each step records job audit through existing DB methods, and the command prints a parent run ID plus ordered step results. Dry-run does not acquire the lock or open the DB. A failed step stops the profile by default; `--keep-going` is an explicit diagnostic option and the final result remains failure.

## Risks / Trade-offs

- [Existing direct legacy commands can still bypass the profile lock] -> Keep them advanced/deprecated, add storage-level locks where canonical ownership matters, and report this residual risk.
- [Full audit remains expensive] -> Make it explicit, compact by default, and measure it separately from status SLO.
- [A metadata migration runs when an explicit update opens TradeDB] -> Keep it idempotent, SQL-only, and non-destructive; validate it on a temporary DB before live use.
- [Generic BTC exclusion changes legacy `sync --symbols BTC`] -> Return an actionable non-success pointing to `trade data update crypto` or `trade data btc`; never silently do nothing.
- [Current production quality gate is already degraded] -> An update is successful only when its own steps persist correctly; global check status remains separate and auditable rather than being rewritten to green.

## Migration Plan

1. Add temporary-root regression tests for DAG row identity/config, BTC writer exclusion, provider finality, unreadable parquet/WAL, zero targets, partial flush, read-only status, profiles, and exit codes.
2. Apply the additive DAG/asset metadata migration to a temporary DB and inspect the exact changed rows.
3. Run focused pytest, CLI help/dry-run, compileall, and OpenSpec validation in the implementation worktree.
4. Run `trade data status` and `trade data update <profile> --dry-run` against the real root; verify zero filesystem/DB changes from both.
5. Snapshot relevant DB/DAG metadata and BTC pointer/hash before the first live crypto update.
6. Run a targeted incremental profile, then `trade data check`; inspect step audits, watermarks, BTC pointer/hash, and exit codes.
7. Roll back by reverting facade routing and the additive metadata rows/config. No parquet rollback is needed for dry-run; a live BTC publish uses its existing predecessor rollback contract.

## Open Questions

None for the initial structured-market-data profiles. Bringing general news/sentiment into `all` is a follow-up gate, not an implicit assumption.
