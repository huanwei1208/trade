## Why

The data surface currently exposes more than twenty top-level subcommands, while the apparently unified sync only covers registry-backed crypto/FX/commodity assets and the default status scan is slow, verbose, and not reliably read-only. More importantly, the current DAG can collapse distinct ingest nodes onto one handler/config and generic BTC ingestion can bypass the assurance-owned canonical file, so shortening the command without fixing orchestration would make wrong-data execution easier.

## What Changes

- Add a concise data facade with three primary operations: fast read-only `status`, profile-driven incremental `update`, and strict `check` with an explicit `--full` audit tier.
- Define versioned `core`, `crypto`, and `all` update profiles that reuse existing jobs with explicit per-step configuration and never include model training, belief, recommendation, or other downstream decision work.
- Bind each EventBus DAG handler to its row identity and exact `config_json`, so repeated job types execute once per configured node instead of being deduplicated or resolving an arbitrary first row.
- Make BTC assurance the sole writer of canonical `market/crypto/btc.parquet`; generic batch ingest must not publish BTC.
- Fail closed for unreadable existing parquet/WAL, no-target updates, partial ingest failures, and unexpected empty acquisition instead of reporting successful `0/0` or overwriting history.
- Correct provider finality handling so an open UTC daily candle cannot be treated as final.
- Keep existing detailed commands executable as compatibility/advanced paths, but remove them from the primary help page and route recovery guidance to the concise facade.
- Preserve real data in place. The change includes an additive metadata migration and dry-run/read-only verification; it does not rewrite existing parquet as part of migration.

Non-goals: redesigning trading decisions, training models, changing API payloads, migrating parquet layouts, or silently running news/LLM cascades from the default core profile. News/sentiment joins `all` only when its update path satisfies the same no-data-loss and failure contracts.

## Capabilities

### New Capabilities

- `data-operations-workflow`: Concise status/update/check commands, explicit profiles, compatibility routing, read-only status behavior, audit tiers, and stable exit codes.
- `data-ingestion-safety`: DAG node identity/config propagation, single-writer ownership, fail-closed durable ingestion, provider finality, and non-success semantics for empty/partial runs.

### Modified Capabilities

None. The active Crypto assurance change remains the owner of BTC evidence semantics; this change enforces its existing canonical-writer boundary from generic orchestration.

## Impact

- CLI: `trade`, `trade_py/cli/data.py`, and a new focused orchestration module.
- Data orchestration: `trade_py/bus`, `trade_py/jobs`, asset batch ingestion, provider normalization, and an additive SQLite migration.
- Data contracts: no parquet layout change; canonical BTC ownership becomes explicit and generic sync no longer writes BTC.
- Compatibility: legacy detailed data commands remain callable. New primary exit codes are `0=pass`, `1=warn`, `2=quality/update failure`, `3=execution error`, with `130` retained for interruption.
- Safety and rollout: tests use temporary roots; migration is idempotent and metadata-only; `update --dry-run` performs zero writes; real-data rollout starts with read-only status and dry-run profile inspection, followed by a targeted incremental run and strict verification. Rollback disables the new facade/profile routing and restores the prior DAG metadata without deleting data.
