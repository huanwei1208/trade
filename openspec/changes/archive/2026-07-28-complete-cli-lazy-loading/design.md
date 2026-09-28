## Context

Nine CLI modules contain a recovered WIP that defers heavyweight imports into command handlers. Six-role review measured a roughly 6x startup improvement, but found the root dispatcher still imports every domain, evaluation/run help still loads runtime stacks, two annotations no longer resolve at runtime, and no test protects the import boundary. The main worktree also mixes these source edits with generated local state, so implementation and cleanup must remain isolated.

## Goals / Non-Goals

**Goals:**

- Parse root/domain help before importing unselected domain or runtime modules.
- Preserve canonical and deprecated command routing, arguments, exit codes, and direct module/script execution.
- Keep type annotations resolvable and fallback/error boundaries explicit.
- Prove import isolation, no-help-side-effects, and warning behavior with focused tests.
- Reduce recurring Git noise from known generated runtime files.

**Non-Goals:**

- Redesigning data, event, research, or trading workflows.
- Moving the entire job registry into a plugin framework.
- Introducing a static-type-checking gate or committing the current local Pyright configuration.
- Modifying real data, DB schemas, parquet formats, API contracts, or the C++ engine.

## Decisions

1. **Root dispatch uses string module names and `importlib.import_module`.** The root parser owns only domain metadata; it imports the selected canonical domain or legacy shim after parsing. This preserves direct script execution through absolute module names and removes cross-domain failure coupling. Keeping module objects in the metadata table was rejected because it necessarily imports every domain.

2. **Handler dependencies load after parser exit points.** `evaluate` parses before importing a selected evaluator, and `run` parses before loading bus/DB/job machinery. This makes `--help` read-only and available when runtime stacks are broken. A broad try/except around optional imports was rejected because it could hide real package failures.

3. **Canonical research invocation is explicit context.** Model/factor/evaluate mains accept a flag/prog context so `trade research ...` uses canonical help without a deprecation warning, while legacy top-level aliases retain the warning.

4. **Runtime type names remain defined.** Type-only imports are paired with runtime-safe aliases so `typing.get_type_hints` and tooling do not fail after dependencies become handler-local.

5. **Tests use fresh subprocesses for import boundaries.** Existing in-process CLI contract tests eagerly import all CLI modules and cannot prove isolation. New subprocess tests inspect loaded modules and filesystem snapshots, while focused unit tests cover routing and warnings.

6. **Generated-state ignore rules are narrow.** Ignore `.nvim/`, the repository-local generated DB directory, and legacy generated parquet files. Keep `pyrightconfig.json` local-only because the current configuration reports unresolved package roots and hundreds of errors; do not establish it as a project contract.

## Risks / Trade-offs

- **Monkeypatch paths move from CLI incidental globals to owner modules** → Tests and docs use owner-module patching; public CLI behavior remains unchanged.
- **Dynamic imports defer some failures until the selected command runs** → Preserve normal Python import errors for the selected command and test unrelated-command isolation.
- **Canonical/legacy context adds function parameters** → Defaults preserve direct callers and top-level aliases; canonical research explicitly opts out of warnings.
- **Startup benchmarks can be noisy** → Use a generous relative sanity threshold plus deterministic `sys.modules` assertions; performance-smoke classification is updated.

## Migration Plan

1. Recover only the coherent CLI WIP into a dedicated worktree.
2. Implement review findings and tests; run focused/full pytest, compileall, help/side-effect smokes, and OpenSpec strict validation.
3. Commit and push the feature branch.
4. Safely move duplicate dirty main-tree edits aside, squash-merge validated branches per repository policy, and push `master`.
5. Roll back by reverting the squash commit; no data rollback is required.

## Open Questions

None. Job-registry metadata/executor separation remains a P2 follow-up rather than a merge blocker.
