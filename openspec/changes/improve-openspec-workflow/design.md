## Context

The repository has a mature OpenSpec and design-quality process, but its operator
surface is fragmented. `openspec status` reports whether proposal artifacts are
complete, `openspec list` reports task counts, `openspec validate` reports schema
validity, and `./trade dev design-check` reports governance. These signals are useful
individually but do not answer the common question: what should happen next for this
change?

Current active changes demonstrate the ambiguity. A change can have
`isComplete = true` because proposal, design, specs, and tasks exist while still
having zero implemented tasks. Conversely, a change can have every task checked but
remain in `openspec/changes` with no archive prompt. Maintainers and implementation
agents need one read-only summary that keeps each source signal distinct.

The implementation must preserve `./trade` as the stable project command surface,
keep native OpenSpec responsible for writes, reuse the existing design-quality
evaluator, avoid importing runtime DB/data modules, and remain useful when one
underlying dependency fails. The stakeholders are contributors, reviewers, and
maintainers managing active changes.

## Goals / Non-Goals

**Goals:**

- Provide one deterministic text or JSON view of active OpenSpec lifecycle evidence.
- Show artifact progress, implementation task progress, native validation, governance
  state, lifecycle classification, and one recommended next action.
- Make partial, malformed, timed-out, or unavailable evidence explicit.
- Keep the public CLI facade thin and the workflow policy in a cohesive owner module.
- Preserve native OpenSpec as the only writer and source of artifact semantics.

**Non-Goals:**

- Create, apply, edit, archive, or otherwise mutate OpenSpec changes.
- Replace native OpenSpec status, validation, or archive behavior.
- Infer whether code is correct, merged, deployed, or safe to release.
- Change design-quality policy, historical OpenSpec artifacts, runtime data, API
  payloads, DB/parquet schemas, trading behavior, frontend behavior, or C++ code.
- Add a background daemon, cache, network service, or persistent status index.

## Design Quality Brief

### Requirements and acceptance

`./trade dev openspec` SHALL summarize every active change, while
`./trade dev openspec <change>` SHALL summarize exactly one active change. Each row
shall retain native task counts and validation, expose design governance, classify
the lifecycle as `authoring`, `review`, `implementation`, `archive-ready`, or
`blocked`, and provide one next-action command or remediation.

Acceptance requires deterministic text and versioned JSON, explicit distinction
between native artifact completion and implementation completion, stable exit codes,
lazy imports with no DB construction, bounded subprocess execution, unit tests for
the lifecycle matrix and failures, and CLI tests for list/single-change behavior.

### Ownership and boundaries

`trade_py/cli/dev.py` owns only argparse registration and lazy dispatch. A new
`trade_py/devtools/openspec_status/` package owns typed report models, native
OpenSpec command adaptation, design-quality evaluation, lifecycle derivation,
rendering, and exit-code calculation. It depends on the existing repository-root
discovery helper and `trade_py.devtools.design_quality.evaluate_change`; it must not
import CLI, DB, Web, market-data, decision, or engine runtime modules.

The native `openspec` executable remains authoritative for active change discovery,
artifact status, task counts, and native validation. The design-quality package
remains authoritative for governed evidence and approval state. The aggregator owns
only normalization and recommendation policy. Dependency direction is
`trade dev facade -> openspec_status service -> native OpenSpec adapter and
design-quality evaluator`.

### Data and state invariants

The command is repository read-only. It does not write OpenSpec artifacts, caches,
localStorage, databases, parquet, generated data, or Git state. Active change names
must satisfy the existing safe slug contract before being passed to either backend.
Results are sorted by change name, independent of native modification timestamps.

Native artifact completion and task completion remain separate fields. A native
`isComplete` value means only that the schema-required authoring artifacts are
complete; it must never imply that implementation tasks are checked. A change is
`archive-ready` only when native validation passes, all tasks are complete with at
least one tracked task, and governed changes have current strict approval. Missing,
invalid, timed-out, or contradictory evidence produces `blocked`, never success.

The report is computed per invocation and is not cached. Partial per-change evidence
may be included for diagnosis, but unavailable fields use explicit status and error
records rather than invented booleans or zero counts.

### Contracts and compatibility

The additive public command is:

```text
./trade dev openspec [change] [--format text|json]
```

Text output is optimized for scanning and includes change, lifecycle, task progress,
validation, governance, and next action. JSON uses schema
`trade.openspec.workflow.v1` and includes top-level `status`, `exit_code`, ordered
`changes`, ordered `errors`, and summary counts. Each change includes native status
evidence, task totals, validation state and issues, governance status/findings,
lifecycle, and next action.

Exit `0` means all requested summaries were collected and none is blocked. Exit `1`
means one or more valid active changes is blocked by change-owned authoring,
validation, governance, or task-state evidence. Exit `2` means invocation or
infrastructure failure, including an unknown requested change, missing executable,
timeout, non-JSON output, malformed required fields, or inability to enumerate
active changes. Existing commands and their arguments remain unchanged.

No migration is required. Rollback removes the additive parser route and owner
package; callers can continue using native `openspec` and `design-check`.

### Failure and recovery

Invalid CLI arguments are rejected by argparse. A missing `openspec` executable,
subprocess timeout, output limit breach, invalid JSON, unsupported required shape, or
repository discovery failure yields a stable infrastructure error with remediation.
Native validation failures and design findings remain change-owned blocked states.

For list mode, a failure isolated to one active change is recorded on that change and
does not hide successfully collected siblings, but the aggregate exits nonzero. A
failure to enumerate changes is fatal because there is no trustworthy scope. For
single-change mode, an unknown or inactive slug is an infrastructure/request error,
not an empty success.

The native subprocess receives a fixed timeout and captured-output byte limit. It is
not retried because native commands are local and retry could mask deterministic
artifact errors. Recovery is to install/fix OpenSpec, repair the named change, rerun
design review, complete tasks, or invoke native archive as recommended.

### Performance and capacity

Normal repository scale is tens of active changes and small Markdown/TOML artifacts.
List mode performs one native list call, one native all-change validation call, then
one artifact-status call and one in-process design evaluation per active change.
Single mode performs list discovery, targeted validation/status, and one design
evaluation. Work is sequential for deterministic diagnostics and because current
scale does not justify concurrent subprocess orchestration.

Each native invocation has a 10-second timeout and a 4 MiB combined output bound.
The existing design-quality evaluator supplies its own artifact count and byte
limits. Complexity is linear in active changes and bounded OpenSpec artifact size.
At 10x the current active-change count, the command remains a manual diagnostic; if
measured latency becomes material, a future native batch-status adapter can replace
per-change status calls without changing the public report.

### Observability and operations

Text output names blocked versus unavailable evidence and prints the exact next
command where one exists. JSON preserves native issues, governance findings, and
structured infrastructure errors without stack traces. Empty active scope is a
successful report with zero counts, while enumeration failure is exit `2`.

Operators can compare the aggregation with `openspec list --json`,
`openspec status --change <change> --json`,
`openspec validate <change> --json`, and
`./trade dev design-check <change> --format json`. No telemetry, log file, or
persistent audit record is added.

### Validation strategy

Unit tests will inject adapters rather than require real subprocesses for lifecycle
matrix coverage: incomplete authoring, review needed, implementation pending,
archive-ready, native validation failure, not-governed historical change, malformed
dependency response, timeout, and partial list-mode failure. Contract tests verify
deterministic ordering, versioned JSON, explicit errors, and exit precedence.

CLI tests cover parser shape, lazy imports/no DB, text and JSON output, unknown
change behavior, and current-repository smoke behavior. Completion also runs focused
pytest, `python -m compileall trade_py tests`, native OpenSpec validation,
`./trade dev check --show-plan`, `./trade dev check`, and `git diff --check`. Tests
use repository fixtures or temporary directories and never real trading data.

### Alternatives and trade-offs

1. **Documentation-only cleanup** would explain commands but cannot detect stale
   active changes or distinguish artifact and task completion at runtime.
2. **A wrapper that creates/applies/archives changes** would reduce keystrokes but
   duplicate native write semantics and increase accidental mutation risk.
3. **A read-only aggregate command** is selected because it resolves ambiguity while
   preserving native ownership and rollback simplicity.
4. **Parsing Markdown directly** could avoid subprocesses but would duplicate
   OpenSpec rules and drift from the installed implementation.
5. **Concurrent fan-out** could reduce latency but adds cancellation, ordering, and
   output aggregation complexity without evidence that current scale needs it.

The selected design accepts a dependency on native OpenSpec JSON shape. A narrow
adapter and explicit malformed/unavailable states contain that risk.

### Rollout and rollback

Land the typed owner module and focused tests first, then add the lazy CLI route and
help contract, then validate the real repository in text and JSON modes. The command
is additive and has no default workflow side effects, migration, feature flag, or
data restoration requirement.

Rollback is a source revert removing the command route, package, and tests. Native
OpenSpec changes and design-review artifacts remain untouched. Rollback triggers are
incorrect lifecycle recommendations, unbounded latency/output, or incompatible
native JSON that cannot be handled without weakening failure semantics.

## Decisions

### Decision 1: Aggregate evidence without owning writes

The command only observes and recommends. Native `openspec new`, apply workflows,
validation, and archive remain explicit operator actions. This prevents a status
inspection from changing repository state.

### Decision 2: Keep source statuses and derive one lifecycle

Native artifact status, task progress, validation, and governance remain visible
separate fields. The lifecycle is a small deterministic projection for navigation,
not a replacement state machine.

### Decision 3: Reuse the design-quality service in process

Calling `evaluate_change` avoids shelling out through the public facade and avoids
copying governance policy. The new module converts its typed report into the
workflow schema without changing design-quality behavior.

### Decision 4: Fail explicitly on unavailable evidence

The command may show partial evidence, but it cannot recommend implementation or
archive when required native or governance evidence is unavailable. Infrastructure
errors take exit precedence over change-owned blockers.

## Risks / Trade-offs

- [Native OpenSpec JSON shape changes] -> Validate required fields in one adapter and
  return explicit infrastructure errors rather than guessing.
- [The recommendation oversimplifies lifecycle] -> Preserve all source evidence and
  keep one conservative next action instead of automating writes.
- [List mode becomes slow as active changes grow] -> Bound calls and outputs, measure
  real latency, and retain a replaceable adapter boundary.
- [Historical ungoverned changes are mislabeled] -> Treat `NOT_GOVERNED` as visible
  evidence; require strict approval only where governance exists or is required.
- [Partial results appear successful] -> Carry per-change errors and make aggregate
  exit precedence deterministic.

## Migration Plan

No artifact or data migration is required. Add the command and tests, validate it
against current active changes, document the relationship to native commands, and
remove it by source revert if its recommendations prove misleading.

## Open Questions

None blocking. Automated archive cleanup and historical governance migration remain
separate future proposals because both require mutation or policy semantics.
