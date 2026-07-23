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
  task counts, native validation, design governance, lifecycle, and one next
  action
- **AND THEN** the command does not create, edit, apply, archive, or cache any
  OpenSpec or runtime artifact

#### Scenario: Inspect one active change

- **WHEN** a user runs `./trade dev openspec <change>` for an active change
- **THEN** the system reports exactly that change with the same evidence and
  lifecycle semantics used by list mode

#### Scenario: No active changes exist

- **WHEN** native OpenSpec successfully reports an empty active change set
- **THEN** the system returns a successful empty report with zero summary counts
- **AND THEN** it does not describe the empty scope as unavailable or failed

### Requirement: Artifact completion and implementation completion remain distinct

The system SHALL retain native authoring completion and task completion as
separate evidence. It MUST NOT interpret native artifact `isComplete` as proof
that implementation tasks are complete.

#### Scenario: Artifacts exist but implementation is pending

- **WHEN** native artifact status is complete and one or more tracked tasks are
  unchecked
- **THEN** the lifecycle is `implementation`
- **AND THEN** the next action directs the user to continue the native apply
  workflow rather than archive the change

#### Scenario: Authoring artifacts are incomplete

- **WHEN** one or more schema-required OpenSpec artifacts are not complete
- **THEN** the lifecycle is `authoring`
- **AND THEN** the next action identifies the first actionable native artifact
  or native status command

#### Scenario: Completed governed change is ready to archive

- **WHEN** native validation passes, all tracked tasks are complete, at least
  one task exists, and a governed change has current strict approval
- **THEN** the lifecycle is `archive-ready`
- **AND THEN** the next action recommends the native archive workflow without
  executing it

### Requirement: Governance and validation block unsafe progression

The system SHALL classify invalid or insufficient change-owned evidence as
`blocked` and SHALL NOT recommend implementation or archive while required
evidence is failing.

#### Scenario: Native validation fails

- **WHEN** native OpenSpec validation returns issues for an active change
- **THEN** the lifecycle is `blocked`
- **AND THEN** the report preserves the validation issues and recommends fixing
  and rerunning native validation

#### Scenario: Governed design is not approved

- **WHEN** a governed change has complete authoring artifacts but design-quality
  reports blockers, warnings requiring resolution, missing review, or stale
  approval
- **THEN** the lifecycle is `review` or `blocked` according to the reported
  governance state
- **AND THEN** the next action recommends the diagnostic or strict design-check
  sequence rather than implementation

#### Scenario: Historical change is not governed

- **WHEN** design-quality reports `NOT_GOVERNED` for an existing historical
  change and native evidence is otherwise valid
- **THEN** the report exposes `NOT_GOVERNED` without relabeling it as approved
- **AND THEN** lifecycle derivation follows native authoring and task evidence
  unless governance is explicitly required for that change

### Requirement: Machine-readable reporting and failures are stable

The system SHALL provide deterministic text and JSON reports and SHALL
distinguish change-owned blockers from invocation or infrastructure failures.

#### Scenario: JSON output is requested

- **WHEN** the user passes `--format json`
- **THEN** the system emits one `trade.openspec.workflow.v1` document containing
  top-level status, exit code, ordered changes, ordered errors, and summary
  counts
- **AND THEN** identical repository evidence and arguments produce identical
  lifecycle, ordering, and next-action fields

#### Scenario: One change fails during list collection

- **WHEN** active change enumeration succeeds but status, validation, or
  governance evidence for one change is unavailable or malformed
- **THEN** the system preserves successful sibling summaries
- **AND THEN** it records an explicit error for the affected change and returns
  a nonzero aggregate exit

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
