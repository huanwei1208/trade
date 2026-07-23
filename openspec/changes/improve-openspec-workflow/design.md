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
shall retain native task counts and validation, expose full design-governance
evidence, classify the lifecycle as `authoring`, `review`, `implementation`,
`archive-ready`, or `blocked`, and provide one typed next action.

Acceptance requires deterministic text and versioned JSON, explicit distinction
between native artifact completion and implementation completion, Git-bound
governance applicability, one immutable evidence generation, stable exit codes, lazy
imports with no runtime construction, bounded process-tree execution, the complete
lifecycle matrix, and list/single-change contract tests. Workflow v1 supports the
repository's task-bearing `spec-driven` schema and fails closed on other schemas.

### Ownership and boundaries

`trade_py/cli/dev.py` owns only argparse registration and lazy dispatch. A new
`trade_py/devtools/openspec_status/` package owns typed report models, native
OpenSpec command adaptation, design-quality evaluation, lifecycle derivation,
rendering, bounded process execution, and exit-code calculation. A small
`trade_py/devtools/design_quality/governance.py` helper owns the shared conversion
from Git scope provenance to required-governance names; the existing quality
contributor and the new aggregator both call it. The status package may import only
developer-tool modules and standard-library adapters; import-boundary tests reject
coupling to `trade_py.data`, `trade_py.db`, `trade_py.event`,
`trade_py.intelligence`, engine runtime modules, and `trade_web`.

The native `openspec` executable remains authoritative for active change discovery,
artifact status, task counts, and native validation. The design-quality package
remains authoritative for governed evidence and approval state. The aggregator owns
only normalization and recommendation policy. Dependency direction is
`trade dev facade -> openspec_status service -> native OpenSpec adapter and
design-quality batch evaluator`. Neither backend imports the status package.

### Data and state invariants

The source repository is read-only. The service loads an allowlisted, bounded
OpenSpec snapshot with no-follow pre/post-stat checks, records its per-change
artifact digest and source Git `HEAD`, and materializes only that snapshot in a
temporary directory. All native OpenSpec commands run against the temporary
generation. The temporary directory is deleted at exit and is never a source of
runtime state.

Design-quality strict evaluation runs once in batch against the source worktree. Each
returned artifact digest must equal the corresponding preloaded snapshot digest, and
the source snapshot is verified again before report publication. A digest mismatch,
file-generation drift, Git provenance failure, or mixed evaluation date makes the
affected collection `unavailable`; no lifecycle is derived from mixed evidence.
Active change names satisfy the existing safe slug contract. Results are sorted by
change name, independent of worker completion order or native modification time.

Native artifact completion and task completion remain separate fields. A native
`isComplete` value means only that the schema-required authoring artifacts are
complete; it never implies implementation tasks are checked. Workflow v1 accepts
only native `schemaName = "spec-driven"` with `tasks` in `applyRequires` and a tasks
artifact. Unsupported schemas are `unavailable`, not guessed. A change is
`archive-ready` only when native validation passes, at least one tracked task exists,
all tasks are complete, and governed or governance-required changes have current
strict approval.

The report is computed per invocation and is not cached. Partial per-change evidence
may be included for diagnosis, but unavailable fields use `null`, explicit
`collection_status`, and error records rather than invented booleans or zero counts.
One UTC `evaluation_date` is captured for the run and must match every embedded
governance report.

### Contracts and compatibility

The additive public command is:

```text
./trade dev openspec [change] [--format text|json]
```

Text output is optimized for scanning and includes change, lifecycle, task progress,
validation, governance, and next action. JSON uses schema
`trade.openspec.workflow.v1`. All listed fields are required unless explicitly
nullable; unknown additive fields are allowed within v1, but removing a field,
changing its type, enum, nullability, or meaning requires a new schema version.

The top level contains:

- `schema_version: "trade.openspec.workflow.v1"`;
- `status: "PASS"|"BLOCKED"|"ERROR"`, where `ERROR` has precedence over
  `BLOCKED`, including partial infrastructure failure;
- `exit_code: 0|1|2`, consistent with `status`;
- `evaluation_date: YYYY-MM-DD`, captured once in UTC;
- `source: {git_head, base_ref, base_sha, snapshot_digest}`;
- `changes: Change[]`, sorted by `name`;
- `errors: Error[]`, sorted by `(change|null, source, code, message)`;
- `summary`, with integer `changes`, `authoring`, `review`, `implementation`,
  `archive_ready`, `blocked`, `unavailable`, and `errors` counts;
- `limits`, with integer `max_changes`, `status_workers`,
  `subprocess_timeout_seconds`, `command_deadline_seconds`,
  `native_output_bytes`, and `report_output_bytes`.

Each `Change` contains required `name`, `collection_status:
"complete"|"unavailable"`, nullable `lifecycle`, nullable integer
`completed_tasks`/`total_tasks`, `native`, nullable `governance`, `next_action`, and
`errors`. `native` preserves `schema_name`, `apply_requires`, ordered artifact
records, validation state/issues, and parsed payload digests. `governance` embeds the
complete `trade.design.report.v1` object from `DesignReport.to_dict()` and adds
`required: bool` plus `requirement_source:
"new_change"|"marker_deleted"|"existing_governed"|"historical_exempt"`. The
embedded report schema is validated before `approval_eligible` is trusted.

`next_action` is always `{kind, command, reason}`. `kind` is
`author|review|apply|archive|repair|none`; `command` is a string or `null`; and
`reason` is nonempty. Each `Error` is `{code, source, change, message,
remediation}`, with `source` in `request|git|openspec|design_quality|snapshot`,
nullable `change`, and all other fields nonempty strings. Native validation issues
remain structured native objects and are not flattened into strings.

Exit `0` means all requested summaries were collected and none is blocked. Exit `1`
means one or more valid active changes is blocked by change-owned authoring,
validation, governance, or task-state evidence. Exit `2` means invocation or
infrastructure failure, including an unknown requested change, missing executable,
timeout, non-JSON output, malformed required fields, or inability to enumerate
active changes. Existing commands and their arguments remain unchanged.

Lifecycle is derived by the first matching row:

| Priority | Condition | Collection / lifecycle | Next action |
| --- | --- | --- | --- |
| 1 | request, Git provenance, snapshot, deadline, native shape, or required backend evidence fails | `unavailable` / `null` | `repair`, exact remediation, exit `2` |
| 2 | schema is not task-bearing `spec-driven` | `unavailable` / `null` | `repair`, no executable command, exit `2` |
| 3 | native validation fails | `complete` / `blocked` | `repair`, `openspec validate <change> --strict` |
| 4 | required artifact is not done | `complete` / `authoring` | `author`, `openspec instructions <artifact> --change <change>` |
| 5 | governance is required but missing/invalid, or strict report is `FAIL` | `complete` / `blocked` | `repair`, `./trade dev design-check <change>` |
| 6 | governed design lacks current strict approval but diagnostic evidence is otherwise valid | `complete` / `review` | `review`, `./trade dev design-check <change> --strict` |
| 7 | no tracked tasks, or any task is incomplete | `complete` / `implementation` | `apply`, `openspec instructions apply --change <change>` |
| 8 | all tracked tasks complete and required strict approval passes | `complete` / `archive-ready` | `archive`, `openspec archive <change>` |

New changes absent from the merge-base OpenSpec tree and changes whose existing
governance marker was deleted are governance-required. Existing governed changes
remain required. Only changes present at the merge base without a marker are
`historical_exempt`. Unavailable Git provenance fails at priority 1. The service runs
one strict `evaluate_changes` batch with the exact required-name set; its complete
versioned reports are the sole source for governance rows 5-8.

No migration is required. Rollback removes the additive parser route and owner
package; callers can continue using native `openspec` and `design-check`.

### Failure and recovery

Invalid CLI arguments are rejected by argparse. A missing `openspec` executable,
subprocess timeout, aggregate deadline, output limit breach, invalid JSON,
unsupported required shape, or repository discovery failure yields a stable
infrastructure error with remediation. Native validation failures and design
findings remain change-owned blocked states.

For list mode, a failure isolated to one active change is recorded on that change and
does not hide successfully collected siblings, but the aggregate exits nonzero. A
failure to enumerate changes is fatal because there is no trustworthy scope. For
single-change mode, an unknown or inactive slug is an infrastructure/request error,
not an empty success. An affected change has `collection_status = "unavailable"` and
`lifecycle = null`; infrastructure failure is never rendered as change-owned
`blocked`.

One bounded executor owns every Git/OpenSpec child it starts. It uses a new process
session, nonblocking incremental reads from stdout and stderr, a shared byte budget,
immediate process-group termination on timeout or overflow, TERM followed by KILL,
unconditional reap, and bounded stderr tails. `KeyboardInterrupt` and the command
deadline cancel and reap every active child before exit. Native commands are not
retried because retry could hide deterministic artifact errors. Recovery is to
install/fix OpenSpec, repair the named change, rerun design review, complete tasks,
or invoke the literal next action.

### Performance and capacity

Normal repository scale is tens of active changes and small Markdown/TOML artifacts.
List mode performs one native list call, one native all-change validation call, then
one artifact-status call per active change and one strict design batch. The status
fan-out uses at most four workers and re-sorts results by change. Single mode still
uses list discovery to reject inactive names, then targeted validation/status and the
same strict design batch path.

The command accepts at most 100 active changes, matching design-policy v1. Each
native invocation has a 10-second timeout and 1 MiB combined stdout/stderr limit; the
entire command has a 60-second deadline and a 16 MiB serialized report limit. Native
issues and governance findings are capped at 50 entries per change with explicit
`omitted_count`; native parsed payloads and embedded design reports are validated
before retention. The design evaluator loads policy once and evaluates all names in
one batch, preserving its 16 MiB artifact envelope.

Review measurements on the initial design found roughly 2 seconds for list,
1.9 seconds for validate-all, and 2.3 seconds per status process. Four workers make
the current 11-change native path approximately 11 seconds instead of about 29
seconds. Synthetic 10- and 100-change tests enforce worker, process-count, deadline,
and output bounds rather than claiming production throughput. A future native
batch-status adapter may replace fan-out without changing the public report.

### Observability and operations

Text output names blocked versus unavailable evidence and prints the exact next
command where one exists. JSON preserves native issues, governance findings, and
structured infrastructure errors without stack traces. Empty active scope is a
successful report with zero counts, while enumeration failure is exit `2`.

Operators can compare the aggregation with `openspec list --json`,
`openspec status --change <change> --json`,
`openspec validate <change> --json`, and
`./trade dev design-check <change> --format json`. No telemetry, log file, or
persistent audit record is added. `./trade` routes this developer query through
`uv run --frozen --no-sync`, so inspecting workflow state cannot synchronize the
project environment. Text and JSON are emitted only after collection; machine JSON
stdout is not mixed with progress output.

### Validation strategy

Unit tests will inject adapters rather than require real subprocesses for lifecycle
matrix coverage: every ordered row, strict versus missing/stale approval, new change,
deleted marker, existing governed, historical exemption, incomplete authoring,
implementation pending, archive-ready, native validation failure, unsupported
schema, malformed dependency response, mixed-generation drift, midnight capture,
timeout, and partial list-mode failure. Contract tests validate every required JSON
field, enum, nullability rule, embedded design report, additive-field policy,
deterministic ordering, explicit errors, omission counts, and exit precedence.

Executor tests use fake processes for output flooding, inherited-pipe holders,
process-group timeout, TERM/KILL escalation, interrupt cleanup, command deadline,
and deterministic four-worker collection. Synthetic 10- and 100-change tests assert
process count, retained-output bounds, and no child remains. CLI tests cover parser
shape, frozen/no-sync shell routing, lazy imports and runtime-package boundaries,
text and JSON output, unknown change behavior, and current-repository smoke behavior.
Completion also runs focused pytest, `python -m compileall trade_py tests`, native
OpenSpec validation, `./trade dev check --show-plan`, `./trade dev check`, and
`git diff --check`. Tests use repository fixtures or temporary directories and never
real trading data.

### Alternatives and trade-offs

1. **Documentation-only cleanup** would explain commands but cannot detect stale
   active changes or distinguish artifact and task completion at runtime.
2. **A wrapper that creates/applies/archives changes** would reduce keystrokes but
   duplicate native write semantics and increase accidental mutation risk.
3. **A read-only aggregate command** is selected because it resolves ambiguity while
   preserving native ownership and rollback simplicity.
4. **Parsing Markdown directly** could avoid subprocesses but would duplicate
   OpenSpec rules and drift from the installed implementation.
5. **Unbounded sequential fan-out** was rejected after review measurements showed
   about 29 seconds at the current 11-change scope. Four bounded workers reduce
   latency while retaining deterministic sorted assembly and one cancellation owner.
6. **Running native OpenSpec directly on the source tree** was rejected because
   multiple commands can observe mixed generations. An immutable temporary snapshot
   plus source digest verification provides one publishable evidence generation.

The selected design accepts a dependency on native OpenSpec JSON shape. A narrow
adapter and explicit malformed/unavailable states contain that risk.

### Rollout and rollback

Land the typed owner module and focused tests first, then add the lazy CLI route and
frozen/no-sync shell route, then validate the real repository in text and JSON modes.
The command is additive and has no default workflow side effects, migration, feature
flag, or data restoration requirement.

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

Calling `evaluate_changes` once avoids shelling out through the public facade,
reloading policy per change, or copying governance rules. The aggregator derives the
required-name set from shared Git provenance, requests current-date strict reports,
validates `trade.design.report.v1`, and embeds each complete report without changing
design-quality behavior.

### Decision 4: Fail explicitly on unavailable evidence

The command may show partial evidence, but it cannot recommend implementation or
archive when required native or governance evidence is unavailable. Infrastructure
errors take exit precedence over change-owned blockers.

### Decision 5: Bind one report to one evidence generation

Native commands execute against a bounded temporary snapshot while design-quality
reads the source with no-follow checks. Matching artifact digests and final source
verification bind both paths. Drift produces `collection_status = "unavailable"`
instead of a mixed lifecycle.

### Decision 6: Support one native schema explicitly

Version 1 implements the repository's `spec-driven` strategy with tasks required for
apply and archive readiness. Preserving `schemaName`, `applyRequires`, and the full
artifact graph makes unsupported schemas visible. A second schema requires a
reviewed strategy and contract tests, not heuristic fallback.

## Risks / Trade-offs

- [Native OpenSpec JSON shape changes] -> Validate required fields in one adapter and
  return explicit infrastructure errors rather than guessing.
- [The recommendation oversimplifies lifecycle] -> Preserve all source evidence and
  use the reviewed precedence table and literal actions instead of automating writes.
- [Status fan-out consumes resources] -> Cap at four workers, 100 changes, 60 seconds,
  and explicit process/report byte budgets.
- [Historical ungoverned changes are mislabeled] -> Share Git-base provenance with
  the quality gate and fail closed when provenance is unavailable.
- [Concurrent edits mix evidence] -> Use one native snapshot, artifact digests, and a
  final source-generation verification.
- [Partial results appear successful] -> Carry per-change errors and make aggregate
  exit precedence deterministic.

## Migration Plan

No artifact or data migration is required. Add the command and tests, validate it
against current active changes, document the relationship to native commands, and
remove it by source revert if its recommendations prove misleading.

## Open Questions

None blocking. Automated archive cleanup and historical governance migration remain
separate future proposals because both require mutation or policy semantics.
