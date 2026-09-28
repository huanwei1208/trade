## ADDED Requirements

### Requirement: Unified developer quality interface
The system SHALL expose `./trade dev check` and `./trade dev fix` without changing
the behavior of existing developer, runtime, data, build, or test commands.

#### Scenario: Run the default quality gate
- **WHEN** an operator runs `./trade dev check`
- **THEN** the system selects changed repository files, runs every applicable required check, prints one combined summary, and returns a deterministic exit code

#### Scenario: Existing quality history is requested
- **WHEN** an operator runs `./trade dev quality`
- **THEN** the system preserves the existing QualityReport history behavior

### Requirement: Changed-file selection is branch-aware
The default gate SHALL include committed changes since the merge base, staged and
unstaged changes, and untracked non-ignored files. It SHALL ignore deleted files and
SHALL NOT inspect paths outside the repository. Base selection SHALL be explicit and
observable.

#### Scenario: Branch contains a committed Python change and an untracked Shell file
- **WHEN** the default quality gate resolves both files against its selected base
- **THEN** it routes both files and prints the base reference used

#### Scenario: No applicable files changed
- **WHEN** the selected scope contains no supported files
- **THEN** the system returns success with a clear no-applicable-files result and runs no language tool

#### Scenario: Unsafe filename or external symlink is selected
- **WHEN** a changed path contains option-like or newline characters or resolves through a symlink outside the repository
- **THEN** the system uses NUL-safe parsing and option terminators, rejects external mutation targets, and returns an infrastructure error rather than invoking a tool unsafely

### Requirement: Check mode is source-tree read-only
Check mode SHALL NOT pass formatter write flags, install dependencies, stage files,
commit files, modify tracked source/configuration, or mutate protected data, DB,
model, vendor, or generated-source artifacts. It MAY write declared ignored
tool-cache/build paths for explicit build steps, and the plan SHALL identify those
paths. Fix mode SHALL be explicit and SHALL restrict formatter writes to selected
owned source files.

#### Scenario: Python formatting is invalid in check mode
- **WHEN** Ruff reports a changed Python file would be reformatted
- **THEN** check mode fails and leaves the file byte-for-byte unchanged

#### Scenario: Explicit fix is requested
- **WHEN** an operator runs `./trade dev fix` for selected Python and frontend files
- **THEN** the system invokes only approved formatter fixes for those files and does not stage or commit them

### Requirement: Language-specific checks are deterministic
The gate SHALL route Python to syntax/Ruff/BasedPyright, Shell to syntax/ShellCheck,
C/C++ to clang-format and configured build validation, frontend TypeScript/
JavaScript to Prettier/ESLint/TypeScript/build validation, Java to offline Maven formatter/test
validation, and supported configuration files to parse/hygiene checks. A provider
registry SHALL own language routing, execution policy, and native result mapping.
The selected plan SHALL be printable without execution.

#### Scenario: Mixed Python and frontend change
- **WHEN** changed scope contains both Python and TypeScript files
- **THEN** both language plans run and their results are aggregated without one language hiding the other

#### Scenario: Full validation is requested
- **WHEN** an operator runs `./trade dev check --all`
- **THEN** the system selects all tracked eligible files plus supported untracked files, adds repository-wide test/build checks, and returns nonzero for every required violation or infrastructure failure

#### Scenario: Source-like file has no registered provider
- **WHEN** a changed first-party source-like file is not recognized by any provider
- **THEN** the gate fails visibly as uncovered instead of returning a no-applicable-files success

### Requirement: Ownership and protected state are explicit
The gate SHALL use versioned repository configuration to classify owned source,
vendored/generated content, fixtures, lock/config files, and protected runtime/data/
model paths. Vendored/generated source and protected state SHALL be mutation-
ineligible, and exclusions SHALL appear in text and JSON reports.

#### Scenario: Fix all encounters SQLite amalgamation
- **WHEN** full fix scope includes tracked `engine/vendor` generated or vendored source
- **THEN** the system excludes it from mutation, reports the ownership reason, and never passes it to a formatter write command

### Requirement: Relevant missing tools fail visibly
When a required tool is absent for a selected language, the gate SHALL fail that
language with the missing executable, affected files, and an exact setup hint. It
SHALL NOT silently skip the check or download the tool.

#### Scenario: C++ changes exist without clang-format
- **WHEN** selected C/C++ files require formatting validation and no supported clang-format executable exists
- **THEN** the gate classifies the C/C++ formatter check as infrastructure failure, exits with aggregate code 2, and prints the configured installation hint

#### Scenario: No C++ files changed
- **WHEN** clang-format is absent but the selected scope has no C/C++ files
- **THEN** the gate does not fail because of the unrelated missing tool

### Requirement: Results and exit codes are stable
Every result SHALL contain status, language/group, check name, duration, and concise
remediation. Text output SHALL be concise. JSON output SHALL use a versioned schema,
deterministic ordering, stable check IDs, base/head provenance, scope fingerprint,
tool versions, exclusions, failure kinds, bounded diagnostics, and remediation
codes. Runtime logs SHALL use stderr so JSON stdout remains valid. The gate SHALL
aggregate failures. Exit 0 SHALL mean required checks passed, exit 1 SHALL mean
diagnostic/test quality violations, and exit 2 SHALL mean invocation, missing-tool,
Git/I/O/spawn, timeout, signal, or runner failure; aggregate precedence SHALL be
`2 > 1 > 0`.

#### Scenario: Two language checks fail
- **WHEN** Python lint and ShellCheck both fail
- **THEN** the summary displays both failures and the process exits 1 after all independent checks complete

#### Scenario: Quality and infrastructure failures occur together
- **WHEN** one check finds a lint violation and another required tool times out
- **THEN** both appear in deterministic text/JSON reports and the aggregate exit code is 2

### Requirement: Execution dependencies and resources are bounded
Every planned step SHALL declare prerequisites, timeout, output limit, resource
class, mutation capability, and offline/network policy. Default checks SHALL be
offline. Independent lightweight steps MAY run with bounded concurrency; heavy build
steps SHALL be serialized, and failed prerequisites SHALL cause dependent steps to
report `SKIP` with a cause.

#### Scenario: CMake build prerequisite fails
- **WHEN** the configured CMake step fails before ctest
- **THEN** ctest is reported as `SKIP` caused by that step while independent language checks continue

### Requirement: Quality CLI is isolated from runtime data services
The shell and Python CLI SHALL dispatch check/fix before importing settings/DB owner
modules or constructing TradeDB. The shell SHALL use frozen no-sync execution so a
check cannot update or download the Python environment.

#### Scenario: Check runs with an absent data root
- **WHEN** an operator runs the quality gate and the default data root does not exist
- **THEN** the command neither imports nor constructs TradeDB, leaves the data root absent, and performs no migration or seed operation

### Requirement: Developer setup is explicit
The canonical Python developer setup SHALL install the pinned quality development
dependencies. Frontend, Maven, ShellCheck, and clang-format probes SHALL report
compatible versions and exact explicit setup commands; checks SHALL NOT install them.

#### Scenario: Fresh environment lacks a development tool
- **WHEN** the corresponding language is selected before its explicit setup step
- **THEN** the gate exits 2 with the required setup command and performs no download

### Requirement: Suppressions are narrow and auditable
Quality configuration SHALL prohibit blanket project-wide suppressions added solely
to make the gate green. A necessary suppression MUST use the narrowest file/rule
scope and include a reason in code or configuration.

#### Scenario: Existing dynamic module needs a type exception
- **WHEN** a BasedPyright diagnostic is demonstrably invalid for one adapter
- **THEN** the exception is limited to that diagnostic and location with an explanatory reason rather than disabling type checking globally

#### Scenario: New blanket suppression is introduced
- **WHEN** a change widens a global Ruff, BasedPyright, Prettier, ESLint, NOLINT, or formatter exclusion without structured approval metadata
- **THEN** the suppression audit fails and reports the exact added rule and scope

### Requirement: Quality runner behavior is covered without live data
The system SHALL cover routing, command planning, missing tools, no-change behavior,
failure aggregation, read-only check behavior, explicit fix behavior, and exit codes
with focused tests using temporary repositories or injected executors. Those tests
SHALL NOT access real data roots or databases.

#### Scenario: Unit test simulates missing tools and failures
- **WHEN** the quality runner test uses a fake executor and temporary file scope
- **THEN** it verifies the complete summary and exit code without installing tools, invoking real builds, or accessing production data
