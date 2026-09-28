## Why

The repository has tests and language-specific build commands, but it has no single
changed-files quality gate and no dedicated agent workflow that prevents malformed,
over-complex, misplaced, or unvalidated code from being declared complete. Python
currently has pytest only, frontend code has TypeScript build checks but no formatter
or linter, and Shell/C++ checks depend on developers remembering separate commands.

## What Changes

- Add a repository-local `code-quality` skill that triggers for implementation,
  refactoring, review, and bug-fix work across Python, Shell, C/C++, Java/Maven,
  TypeScript/JavaScript, configuration, and documentation files.
- Add a flat developer interface: `./trade dev check` for changed files,
  `./trade dev check --all` for repository-wide/pre-merge validation, and
  `./trade dev fix` for explicitly safe formatter fixes.
- Route files to language-specific checks while preserving one summary, deterministic
  exit codes, missing-tool diagnostics, a versioned JSON report, and protected-state
  read-only behavior for check mode.
- Add Python Ruff formatting/linting and gradual BasedPyright checks, frontend Prettier/ESLint
  formatting/linting plus existing strict TypeScript checks, Shell syntax/ShellCheck,
  C/C++ clang-format plus existing CMake/ctest validation, and Java/Maven test and
  formatting policy for `engine/tradedb-driver`.
- Add a declarative ownership/tool registry that excludes vendored/generated/runtime
  artifacts from mutation, detects uncovered source-like files, and defines typed
  step dependencies, timeouts, network policy, and setup hints.
- Add shared structural rules for module ownership, public contracts, error handling,
  test isolation, generated/local data safety, and financial unknown/failure states.
- Default to branch/working-tree changed files so existing debt does not block every
  edit. Keep `--all` as a hard, non-green repository debt audit until a follow-up
  makes the whole baseline pass; keep suppressions narrow, documented, and auditable.
- Add focused unit and CLI contract tests for routing, command construction, failure
  aggregation, no-change behavior, missing tools, fix/check separation, and exit
  codes.

Non-goals are auto-rewriting business logic, making subjective size limits hard
failures, downloading tools implicitly during a read-only check, mutating real data,
or replacing focused unit, integration, engine, or frontend tests.

## Capabilities

### New Capabilities

- `cross-language-quality-gate`: Changed/all file selection, ownership and language
  provider routing, check/fix semantics, versioned diagnostics, tool execution
  policy, protected-state safety, and stable CLI behavior.
- `code-quality-agent-workflow`: Repository-local skill behavior for pre-edit design
  checks, language-specific constraints, validation integrity, and completion
  reporting.

### Modified Capabilities

None.

## Impact

- Affected code: `trade_py/cli/dev.py`, a focused developer-quality package,
  `pyproject.toml`, `uv.lock`, frontend package/config files, repository formatter
  and quality-registry configuration, the Java/Maven module, tests, `AGENTS.md`, and
  `.codex/skills/code-quality/`.
- CLI compatibility: additive `trade dev check` and `trade dev fix`; existing
  `trade dev quality` and all other commands retain their behavior.
- Dependencies: development-only Ruff and BasedPyright; frontend development-only
  Prettier/ESLint; a pinned Maven formatting plugin. ShellCheck and clang-format remain system
  tools with explicit diagnostics. Quality checks never install or download them.
- Data/API/DB/engine contracts: no data, API, DB schema, parquet layout, or engine
  runtime behavior changes. Check mode is read-only; fix mode is explicit and limited
  to formatter-supported source files.
- Compatibility risk: repository-wide strictness can expose existing debt. The
  default changed-file scope, gradual type checking, and explicit all-mode report
  prevent a surprise flag day while still making touched code accountable.
