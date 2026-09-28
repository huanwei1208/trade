## Why

OpenSpec authoring, validation, design governance, implementation progress, and
archive readiness are currently exposed through separate commands with different
status meanings. In particular, native artifact completion can be mistaken for
implementation completion, while changes with all tasks finished can remain active
without a clear next action.

## What Changes

- Add a read-only `./trade dev openspec [change] [--format text|json]` command that
  aggregates active change progress, native validation, design-governance state, and
  one deterministic recommended next action.
- Distinguish artifact authoring, design review, implementation, archive-ready, and
  blocked states without replacing native OpenSpec create, apply, validate, or
  archive operations.
- Preserve native status and validation evidence in a versioned machine-readable
  report instead of treating `isComplete` as proof that implementation tasks are
  complete.
- Collect native evidence from one bounded temporary snapshot, bind governance
  requirements to Git-base provenance, and reject evidence drift before publishing a
  lifecycle recommendation.
- Report unavailable or malformed dependency results explicitly and return stable
  nonzero exit codes instead of presenting partial evidence as success.
- Route native status fan-out through bounded concurrency and process-group cleanup so
  the command has a command-wide deadline and deterministic output ordering.
- Add focused CLI and service tests plus concise command guidance.

Design-quality governance applies with the `core`, `contract`, and `concurrency`
profiles because this is an additive public developer CLI contract with bounded
parallel status collection. It does not change trading, market-data, DB, parquet,
API, frontend, or C++ engine behavior.

## Capabilities

### New Capabilities

- `openspec-workflow-status`: Read-only lifecycle, governance, validation, progress,
  and next-action reporting for active OpenSpec changes.

### Modified Capabilities

None.

## Impact

- **Public CLI:** Adds `./trade dev openspec [change] [--format text|json]`; existing
  `trade dev`, native `openspec`, and design-check commands remain compatible.
- **Python ownership:** `trade_py/cli/dev.py` remains a thin argument/dispatch facade.
  A dedicated `trade_py/devtools/openspec_status/` package owns collection,
  normalization, lifecycle derivation, rendering, and exit semantics.
- **Dependencies:** Reuses the installed native `openspec` CLI and the existing
  design-quality batch evaluator. No new package or network dependency is added.
- **Data safety:** Reads repository OpenSpec artifacts and governance evidence only.
  Trading data, databases, parquet, caches, and generated runtime assets are outside
  its access scope, and no schema migration is involved.
- **Compatibility risk:** Native OpenSpec JSON may evolve. The adapter validates
  required fields, preserves explicit unavailable/error states, and never mutates
  native OpenSpec content.
- **Schema support:** Workflow schema v1 supports the repository's task-bearing
  `spec-driven` OpenSpec schema. Other native schemas fail explicitly as unsupported
  until a reviewed lifecycle strategy is added.
