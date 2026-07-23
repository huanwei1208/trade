## Why

The main worktree contains a partially completed CLI import-deferral change: command modules load much less code, but the root dispatcher still imports every domain and several help paths still initialize runtime subsystems. This leaves unrelated commands vulnerable to optional dependency failures, preserves avoidable startup cost, and has already left unresolved runtime annotations and untested compatibility edges.

## What Changes

- Complete selected-domain lazy dispatch at `trade_py.cli.main` while preserving canonical and legacy command routing.
- Move evaluation and run-time dependencies behind argument parsing so help remains lightweight and read-only.
- Preserve runtime-resolvable type annotations and narrow the K-line settings fallback boundary.
- Stop canonical `trade research ...` commands from printing legacy deprecation warnings while retaining warnings for old top-level aliases.
- Add isolated regression tests for import boundaries, help behavior, side effects, aliases, and direct module/script entrypoints.
- Ignore repository-local generated DB/parquet/editor state without committing those runtime files.

Non-goals: redesigning business commands, changing data/trading semantics, migrating databases, adding dependencies, or making the existing local Pyright configuration a project quality gate.

## Capabilities

### New Capabilities

- `cli-startup-isolation`: Selected CLI domains and command handlers load on demand; help and unrelated commands remain available when optional runtime stacks are absent.

### Modified Capabilities

None.

## Impact

- Affected code: root CLI dispatch, legacy research shims, selected command-local imports, CLI regression tests, and generated-state ignore rules.
- User-visible contracts: command names, arguments, exit codes, help content, and deprecation routing remain compatible; canonical research commands no longer emit false deprecation warnings.
- No API, DB schema, parquet layout, C++ engine, or real-data migration is involved.
- Compatibility risk is concentrated in import timing and monkeypatch seams; subprocess and focused/full pytest coverage are required before merge.
