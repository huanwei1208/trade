## Context

`trade` is a mixed repository: Python owns most domain/service/data behavior,
`trade` and migration scripts use Shell, `engine/` is C++20 with CMake/ctest,
`engine/tradedb-driver/` is Java/Maven, and `trade_web/frontend/` is strict
TypeScript/React. The current quality surface is fragmented:

- Python dev dependencies contain pytest but no formatter, linter, or type checker.
- The frontend runs `tsc -b && vite build` but has no formatter/linter contract.
- ShellCheck is available on the current host, while shfmt is not.
- clang++ and CMake are available, while clang-format/clang-tidy are not currently
  installed.
- The repository has a broad `review-this` skill, but no language-aware skill for
  the implementation loop and no single machine-readable developer gate.

This is a developer-workflow change, not a runtime or trading-semantics change. The
primary stakeholder is anyone or any agent editing the repository; the secondary
stakeholder is a reviewer who needs concise, reproducible evidence instead of a list
of commands the author may or may not have run.

## Goals / Non-Goals

**Goals:**

- Make one short command select and run the applicable language checks.
- Make the default gate accountable to all files changed on the current branch,
  including staged, unstaged, and untracked files.
- Keep tracked source and protected runtime/data state read-only in check mode, while
  declaring permitted ignored caches/build outputs; make source rewriting explicit
  through a separate fix command.
- Fail deterministically on code defects or missing required tools for relevant
  files, while distinguishing warnings and intentional skips.
- Add a concise repository-local skill that guides agents before editing and blocks
  unsupported completion claims after editing.
- Introduce stricter tooling incrementally without a repository-wide formatting
  rewrite or an unreviewable baseline suppression file.

**Non-Goals:**

- Replacing focused tests, CMake/ctest, frontend builds, or six-role reviews.
- Automatically installing system or npm tools during a check.
- Performing any network access from the default check path.
- Automatically fixing subjective architecture, function decomposition, or business
  semantics.
- Making raw line count or complexity heuristics hard failures without context.
- Reformatting untouched legacy files.
- Touching real data, databases, generated parquet, model artifacts, or runtime APIs.

## Architecture

```text
./trade dev check|fix
          |
          v
trade_py.cli.dev (thin parser/delegation)
          |
          v
trade_py.devtools.quality (package)
  |-- scope + ownership manifest
  |-- typed step/result/report models
  |-- provider registry
  |-- dependency-aware planner
  |-- bounded subprocess executor
  `-- text/JSON renderer + stable exit code
          |
          +-- Python: Ruff, BasedPyright, syntax compile
          +-- Shell: bash -n, ShellCheck
          +-- C/C++: clang-format; CMake/ctest in full validation
          +-- Java: Maven offline format/test validation
          +-- Web: Prettier, ESLint, TypeScript; build in full validation
          `-- Shared: diff whitespace, JSON/TOML parse, file hygiene
```

The agent-side skill is independent of the runner implementation:

```text
.codex/skills/code-quality/SKILL.md
  |-- core workflow and completion contract
  `-- references/{python,shell,cpp,java,web,shared}.md
```

## Decisions

### 1. One cross-language skill and one command family

Use `code-quality`, `./trade dev check`, and `./trade dev fix`. A single router avoids
duplicated Python/C++/frontend commands and ensures mixed changes receive a combined
result. Existing `trade dev quality` remains the QualityReport history command.

Alternative considered: separate `py-check`, `cpp-check`, and `web-check`. This is
explicit but recreates the command sprawl the user wants to avoid and makes it easy
to miss one language in a cross-module change.

### 2. Changed branch scope is the default hard gate

Resolve a base from `--base`, then `QUALITY_BASE_REF`, `origin/master`, or `master`.
Use the merge base to include committed branch changes plus staged/unstaged changes,
and add untracked non-ignored files. Ignore deleted files. A path supplied through
`--path` narrows, but never expands outside the repository.

`--all` selects all tracked eligible source files plus supported untracked,
non-ignored files and adds full validation commands. It is a hard debt/readiness
audit: violations always return nonzero. The changed-file gate is the mandatory
no-regression blocker immediately; `--all` becomes a mandatory pre-merge gate only
after a focused follow-up makes its baseline green. Running a failing `--all` never
counts as successful validation.

Alternative considered: format/lint the whole repository in this feature. That would
mix hundreds of unrelated edits with the quality infrastructure and violate the
reviewability goal.

### 3. Check and fix have separate mutation contracts

`check` invokes only check/type/build/test modes and never passes a write flag to a
formatter. It must not modify tracked source, configuration, or protected runtime
data/DB/model paths. It may write declared ignored caches/build outputs such as
`.venv`, `node_modules`, `build`, or frontend build metadata only when the selected
full step explicitly declares that capability; those paths are printed in the plan.
`fix` can run Ruff/Prettier/ESLint/clang-format/Maven fixes only for selected owned
source files, then reports remaining non-fixable violations. It does not stage,
commit, install, or rewrite vendored/generated/runtime data.

Alternative considered: `check --fix`. A separate verb makes accidental source
mutation less likely and is easier to test as a public contract.

### 4. Python uses Ruff plus gradual BasedPyright

Ruff owns formatting, import order, and high-signal correctness/modernization rules.
BasedPyright runs in `standard` mode on changed Python paths, focusing on public
boundaries without turning dynamic pandas/data adapters into a false-positive flood.
The development dependencies are version-bounded through `uv.lock`. Subjective
complexity and size thresholds remain skill warnings that require refactoring or a
written justification.

Alternative considered: Black + isort + Flake8 + Pylint + mypy. Their responsibilities
overlap, increase latency/configuration drift, and add noisy diagnostics without a
clear ownership boundary.

### 5. The frontend uses portable Node tooling plus existing TypeScript

Prettier owns TypeScript/JavaScript/JSON formatting, ESLint owns high-signal linting,
and existing strict TypeScript remains the type contract. Changed mode sends only
selected frontend files to Prettier/ESLint and runs TypeScript when source/config
files changed; all mode also runs the existing production build. Node dependencies
are pinned in package-lock.

Alternative considered: Biome. Its Linux native binaries through the tested 1.7–2.2
lines require glibc newer than this repository's Debian 10/glibc 2.28 host. A gate
that cannot run on the supported checkout host is not acceptable; pure Node tooling
keeps formatter, linter, and type responsibilities separate without that native ABI
dependency.

### 6. Shell, C++, and Java prefer installed ecosystem tools

Shell changes run `bash -n` per file and one ShellCheck invocation. C/C++ changes run
clang-format in check mode (or `-i` only in fix mode). Java/Maven changes run a
pinned formatter check and tests in offline mode; an explicit setup step primes Maven
dependencies. Missing tools for relevant files are infrastructure failures with exact
install hints, not silent skips. Full mode additionally uses existing CMake
build/ctest and frontend build paths; expensive checks and permitted ignored outputs
remain visible in the plan and summary.

Alternative considered: write local formatters or silently downgrade missing tools
to warnings. Home-grown formatting is unreliable, and silent skips create a false
green result.

### 7. Providers and typed steps make the runner extensible

Each `QualityProvider` owns path predicates, supported modes, tool/version probes,
plan construction, native exit mapping, and remediation. `CheckStep` carries a stable
ID, argv, cwd, selected files, prerequisites, mutation capability, timeout, output
limit, resource class, and offline/network policy. The planner rejects uncovered
source-like files instead of returning a false green.

Use NUL-delimited Git output, insert `--` before paths, reject unsafe symlink targets,
and byte-bound path batches below platform argument limits. Run lightweight
independent steps with bounded concurrency, serialize heavy build/test steps, mark
blocked dependents `SKIP(caused_by=...)`, and terminate timed-out process groups.

Separate selection, planning, execution, and rendering. Unit tests inject a fake
executor and temporary git repositories so aggregation and mutation contracts are
covered without network, installation, real builds, or production data.

### 8. Results have stable text and JSON semantics

Support `--format text|json` and a non-executing `--show-plan`. The versioned JSON
`GateReport` contains schema/runner version, base and head SHAs, scope fingerprint,
ordered stable check IDs, provider/tool versions, files/exclusions, prerequisites,
status, failure kind, durations, bounded diagnostics, and remediation codes. Logs go
to stderr so JSON stdout stays parseable.

Each check reports `PASS`, `FAIL`, `WARN`, or `SKIP`. Exit `0` means every required
check passed; exit `1` means a diagnostic/test quality violation; exit `2` means
invalid invocation, missing tools, Git/I/O/spawn errors, timeout, signal, or runner
failure. Aggregate precedence is `2 > 1 > 0`. Multiple independent failures are
aggregated instead of stopping at the first tool.

### 9. The skill contains process, references contain language detail

Keep SKILL.md concise: inspect scope, read only relevant language references, define
hard versus judgment rules, run the machine gate, preserve unrelated changes, and
report evidence. Detailed rules live one level below in language reference files.
Generate `agents/openai.yaml` with the official skill-creator script and validate the
folder with `quick_validate.py`.

### 10. Ownership, suppressions, and setup are explicit

A versioned `quality.toml` classifies first-party source, vendored/generated content,
fixtures, lockfiles/config, and protected runtime/model/data paths. Vendor/generated
files are mutation-ineligible; uncovered source-like changed files fail visibly.
Suppressions require an exact scope, rule, reason, owner, and expiry and are included
in reports.

`./trade setup-python` installs the dev extra explicitly. The shell wrapper dispatches
quality commands through frozen/no-sync execution so a check never updates `.venv`.
Frontend, Maven, ShellCheck, and clang-format setup remain explicit and are diagnosed
before execution. `check` and `fix` dispatch before settings, DB imports, or TradeDB
construction. The existing review command also uses a tested repository locator and
validates reused worktrees.

## Risks / Trade-offs

- **Touched legacy files may contain old violations** -> Limit initial rules to
  high-signal sets, fix the touched file intentionally, and prohibit blanket ignores.
- **Full-tree mode may not initially be green** -> Mark it as an explicit readiness
  audit that still exits nonzero, publish counts, and promote it to a required
  pre-merge gate only after focused cleanup commits make it green.
- **BasedPyright can be noisy on dynamic data code** -> Use standard mode and changed
  paths, keep Ruff responsible for lint, and require narrow typed adapters rather
  than global disablement.
- **Missing clang-format or node_modules blocks relevant changes** -> Emit exact setup
  commands; do not download during check. Unrelated language changes are unaffected.
- **Unsafe filenames or symlinks escape the checkout** -> Use NUL Git protocols,
  option terminators, resolved containment checks, and mutation-time revalidation.
- **Full C++/frontend checks can be slow** -> Default to changed static checks; reserve
  build/ctest/production build for `--all` and the skill's risk-based validation.
- **Formatter fixes can create broad diffs** -> Restrict fix to selected files and
  show the resulting git diff; never stage automatically.
- **A skill can be ignored by an agent** -> Add its trigger to AGENTS.md and make the
  executable gate the objective completion evidence.

## Migration Plan

1. Land the OpenSpec and six-role review; resolve all P0 findings.
2. Add the skill skeleton/references and validate its metadata.
3. Add the provider registry, typed planner/executor/report, DB-isolated CLI, and
   fixture-based path/exit/dependency tests.
4. Add Python, frontend, and Java development configs/locks, plus Shell/C++ formatter
   configuration, ownership manifest, and setup diagnostics.
5. Run changed mode on this feature, inspect the hard-failing all-mode debt, and tune
   only high-signal rules without blanket suppression.
6. Update AGENTS.md and user-facing help, forward-test the skill on realistic Python,
   Shell, C++, and frontend tasks, and fix routing/wording gaps.
7. Roll back by removing the additive CLI commands/config/skill and restoring lock
   files; no runtime data or schema rollback is required.

## Open Questions

- Whether clang-format should be installed system-wide or through a future repository
  bootstrap command remains an operator choice; this change provides a diagnostic and
  documented version expectation without mutating the host automatically.
- The exact point when `--all` becomes mandatory-passing depends on the measured
  legacy violation count. That transition must be a small follow-up with a green
  baseline, not a permanent exemption.
