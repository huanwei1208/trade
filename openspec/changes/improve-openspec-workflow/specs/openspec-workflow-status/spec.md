## ADDED Requirements

### Requirement: Active OpenSpec workflow status is aggregated read-only

The system SHALL expose `./trade dev openspec [change] [--format text|json]`
as a read-only aggregation of active OpenSpec evidence. It SHALL preserve
native OpenSpec as the authority for artifact status, task progress, and
validation, and SHALL preserve design-quality as the authority for governance.

#### Scenario: List active changes

- **WHEN** a user runs `./trade dev openspec` in a valid repository
- **THEN** the system reports every active change in deterministic name order
- **AND THEN** each change includes native artifact status, completed and total
  task counts, native validation, the complete versioned design-governance report,
  collection status, lifecycle, and one typed next action
- **AND THEN** the command does not create, edit, apply, archive, or cache any
  source OpenSpec or runtime artifact
- **AND THEN** native OpenSpec reads one bounded temporary snapshot and
  design-governance evidence is digest-bound to that same source generation

#### Scenario: Inspect one active change

- **WHEN** a user runs `./trade dev openspec <change>` for an active change
- **THEN** the system reports exactly that change with the same evidence and
  lifecycle semantics used by list mode

#### Scenario: No active changes exist

- **WHEN** native OpenSpec successfully reports an empty active change set
- **THEN** the system returns a successful empty report with zero summary counts
- **AND THEN** it does not describe the empty scope as unavailable or failed

#### Scenario: Source evidence changes during collection

- **WHEN** a source OpenSpec artifact changes after the command captures its
  bounded snapshot or its governance digest differs from the snapshot digest
- **THEN** the affected change has collection status `unavailable` and a null
  lifecycle
- **AND THEN** the command returns infrastructure exit `2` and does not derive a
  recommendation from mixed generations

#### Scenario: Unsupported native schema is active

- **WHEN** native status does not report task-bearing `schemaName =
  "spec-driven"` with `tasks` required for apply
- **THEN** the affected change has collection status `unavailable`
- **AND THEN** the error details preserve only the native schema name and raw
  payload digest and require a reviewed schema strategy rather than publishing
  an unvalidated artifact graph or guessing task semantics

### Requirement: Artifact completion and implementation completion remain distinct

The system SHALL retain native authoring completion and task completion as
separate evidence. It MUST NOT interpret native artifact `isComplete` as proof
that implementation tasks are complete.

#### Scenario: Artifacts exist but implementation is pending

- **WHEN** native artifact status is complete and one or more tracked tasks are
  unchecked
- **THEN** the lifecycle is `implementation`
- **AND THEN** the next action command is
  `openspec instructions apply --change <change>` rather than archive
- **AND THEN** the change is a successful workflow position and does not cause a
  nonzero aggregate exit

#### Scenario: Authoring artifacts are incomplete

- **WHEN** one or more schema-required OpenSpec artifacts are not complete
- **THEN** the lifecycle is `authoring`
- **AND THEN** the next action command is
  `openspec instructions <artifact> --change <change>` for the first ready
  incomplete artifact in native order
- **AND THEN** the change is a successful workflow position and does not cause a
  nonzero aggregate exit

#### Scenario: Completed governed change is ready to archive

- **WHEN** native validation passes, all tracked tasks are complete, at least
  one task exists, and a governed change has current strict approval
- **THEN** the lifecycle is `archive-ready`
- **AND THEN** the next action command is `openspec archive <change>` without
  executing it

### Requirement: Governance and validation block unsafe progression

The system SHALL classify invalid or insufficient change-owned evidence as
`blocked` and SHALL NOT recommend implementation or archive while required
evidence is failing.

#### Scenario: Native validation fails

- **WHEN** native OpenSpec validation returns issues for an active change
- **THEN** the lifecycle is `blocked`
- **AND THEN** the report preserves the validation issues and recommends fixing
  and running `openspec validate <change> --strict`

#### Scenario: Required governance is invalid

- **WHEN** governance is required and the strict design report is `FAIL`,
  `REQUIRED_MISSING`, with at least one active non-review governance finding
- **THEN** the lifecycle is `blocked`
- **AND THEN** the next action command is
  `./trade dev design-check <change> --strict` and implementation is not
  recommended

#### Scenario: Governed design awaits current approval

- **WHEN** complete valid authoring evidence has a valid strict design report
  that is not approval-eligible and has a nonempty active finding set limited to
  `core.review.missing`, `core.review.stale`, and `core.review.incomplete`
- **THEN** the lifecycle is `review`
- **AND THEN** the next action command is
  `./trade dev review --slug <change> --scope openspec/changes/<change>`
- **AND THEN** the change is a successful workflow position and does not cause a
  nonzero aggregate exit

#### Scenario: Historical change is not governed

- **WHEN** Git merge-base provenance proves the change already existed without a
  governance marker and native evidence is otherwise valid
- **THEN** the report exposes `NOT_GOVERNED` without relabeling it as approved
- **AND THEN** lifecycle derivation follows native authoring and task evidence

#### Scenario: New or previously governed change lacks a marker

- **WHEN** a change is absent from the merge-base OpenSpec tree or an existing
  governance marker was deleted
- **THEN** governance is required and missing governance blocks the change
- **AND THEN** unavailable Git provenance fails closed instead of classifying
  the change as historical

### Requirement: Machine-readable reporting and failures are stable

The system SHALL provide deterministic text and JSON reports and SHALL
distinguish change-owned blockers from invocation or infrastructure failures.

#### Scenario: JSON output is requested

- **WHEN** the user passes `--format json`
- **THEN** the system emits one `trade.openspec.workflow.v1` document containing
  required top-level schema, status, exit code, UTC evaluation date, source,
  limits, ordered changes, ordered errors, and complete summary counts
- **AND THEN** each change uses explicit collection-status/lifecycle enums,
  nullable unavailable tasks/native/governance values, complete native evidence,
  an unmodified `trade.design.report.v1`, typed next action, errors, and native
  issue omission counts
- **AND THEN** identical repository evidence, arguments, and evaluation date
  produce identical lifecycle, ordering, and next-action fields

#### Scenario: Design backend response is malformed

- **WHEN** the design batch or an embedded `trade.design.report.v1` is malformed,
  inconsistent, or carries the wrong change, date, digest, status, or counts
- **THEN** the affected collection is `unavailable` with null lifecycle
- **AND THEN** the top-level status is `ERROR` with exit code `2`, rather than a
  change-owned `blocked` result

#### Scenario: One change fails during list collection

- **WHEN** active change enumeration succeeds but status, validation, or
  governance evidence for one change is unavailable or malformed
- **THEN** the system preserves successful sibling summaries
- **AND THEN** the affected change has collection status `unavailable`, null
  lifecycle, and an explicit error
- **AND THEN** the top-level status is `ERROR` and exit code is `2`

#### Scenario: Scope cannot be trusted

- **WHEN** repository discovery or active change enumeration fails, times out,
  exceeds the output bound, or returns malformed required JSON
- **THEN** the command exits with infrastructure status `2`
- **AND THEN** it emits an actionable error instead of an empty success report

#### Scenario: Requested change is not active

- **WHEN** the user requests an unknown or inactive change name
- **THEN** the command exits with request or infrastructure status `2`
- **AND THEN** the report identifies the requested name and how to list active
  changes

#### Scenario: External process exceeds a bound

- **WHEN** a Git or native OpenSpec process exceeds its timeout/output budget,
  the managed design-quality batch exceeds the remaining deadline/output budget,
  the command-wide deadline expires, or the user interrupts the command
- **THEN** the executor terminates and reaps every active process group
- **AND THEN** parent-managed design-quality Git children inherit the batch group
  rather than opening detached sessions
- **AND THEN** the command emits bounded diagnostics and never leaves a child
  process running

#### Scenario: Final report exceeds its output budget

- **WHEN** the fully sorted JSON report exceeds 16 MiB before publication
- **THEN** the command discards all per-change records and emits one fixed bounded
  `workflow.report.too_large` ERROR document with exit code `2`
- **AND THEN** it does not emit partial JSON or truncate an embedded governance
  report

#### Scenario: Read-only shell route is invoked

- **WHEN** a user invokes `./trade dev openspec`
- **THEN** the shell wrapper runs the Python CLI with `uv run --frozen --no-sync`
- **AND THEN** workflow inspection does not synchronize project dependencies
