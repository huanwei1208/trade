## ADDED Requirements

### Requirement: Cross-context workflows SHALL be owned by durable Process Managers

Processes SHALL own cross-context workflow state and SHALL use commands,
past-tense domain events, outbox delivery and immutable references. Every
Process Manager record SHALL include `process_id`, `process_type`,
`correlation_id`, `causation_id`, `idempotency_key`, `state`, `current_step`,
`retry_count`, `deadline`, `last_error` and `compensation_state`.

#### Scenario: A duplicate command is delivered

- **WHEN** a scheduler, event replay or interface delivers a command with an
  idempotency key already claimed by a live or completed process
- **THEN** the Process Manager returns the existing process receipt, does not
  issue duplicate context commands and records the duplicate-delivery outcome

#### Scenario: A process crashes after a context commit

- **WHEN** a context transaction and outbox event commit but process execution
  stops before the process row advances to its next step
- **THEN** recovery replays the durable event, resumes from the idempotent
  current step and does not infer completion from in-memory work

### Requirement: Commands and events SHALL have durable handoff receipts

Every command ingress SHALL create or return an `OperationReceipt` containing
an operation ID, `ActorContext`, correlation/causation IDs, idempotency key,
accepted command digest, state, reason code and process linkage where relevant.
Platform Events SHALL persist an outbox envelope, consumer inbox claim,
delivery lease, acknowledgement, attempt history, ordering key, payload-size
limit, deadline and redrive/dead-letter state. A `ProcessView` SHALL expose
bounded list/detail/recovery query data without exposing business tables or raw
payloads.

`ActorContext` SHALL be derived from trusted CLI, HTTP authentication,
scheduler, event or system metadata rather than caller-supplied payload fields,
and SHALL identify origin, authenticated/system principal, authority scope,
delegation chain and explicit anonymous/unknown policy. Versioned DTOs SHALL
define `OperationReceipt` IDs/kind/command digest/scoped idempotency/timestamps/
terminal state, `ProcessView` step/deadline/retry/DLQ/bounded history/permitted
recovery actions, and `ErrorEnvelope` schema version/reason/state/retryability/
retry-after/correlation/operation/process references/safe recovery hint.
`unknown`, `not_observed` and `unavailable` SHALL remain distinguishable from
successful, empty or healthy state.

#### Scenario: A caller repeats an accepted command after a timeout

- **WHEN** a CLI, HTTP, scheduler or event adapter resubmits a command with the
  same actor scope and idempotency key after it cannot observe the first result
- **THEN** command ingress returns the existing OperationReceipt or ProcessView
  linkage, creates no second owner transaction, and records the duplicate
  attempt without leaking credentials or raw payload content

#### Scenario: A slow consumer causes delivery backlog

- **WHEN** a consumer cannot acknowledge deliveries within its configured
  lease, batch, in-flight, backlog-age or backlog-byte budget
- **THEN** Platform stops admitting unbounded work, makes backlog state visible
  through ProcessView/Operations queries, redelivers only under the ordering
  and retry policy, and routes exhausted work to an audited dead letter

### Requirement: Mutation compatibility SHALL use a receipt and recovery ledger

Interfaces and Processes SHALL record a mutation ledger row before delegating
each CLI, HTTP, Web, scheduler or event mutation. The row SHALL identify legacy
request/response/status behavior, command owner and canonical digest, trusted
ActorContext source, idempotency scope, returned OperationReceipt/ProcessView
selector, cancellation/retry/redrive authorization, ErrorEnvelope/legacy
mapping, snapshot validation, rollout gate and retirement condition. Background
work SHALL enter durable command ingress/process state before the corresponding
interface is migrated.

#### Scenario: A legacy action starts background work

- **WHEN** a compatibility route currently returns an action ID while a local
  thread or process continues the work
- **THEN** its ledger row maps the action to a durable OperationReceipt and
  ProcessView before delegation, preserves the legacy response shape during the
  compatibility window, and documents authorized retry, cancellation and
  redrive paths

### Requirement: Contexts SHALL publish facts and Processes SHALL issue commands

Contexts SHALL publish past-tense `CaptureCommitted`, `DatasetReleased`,
`DatasetWithdrawn`, `StudyCompleted`, `StudyValidated`,
`EvidenceGapDeclared` and `DecisionCaseAccepted` events through a durable
outbox. Process Managers SHALL issue `RequestCapture`, `BuildDataset`,
`PublishDataset`, `RunStudy`, `PromoteStudy` and `RebuildProjection` commands.
Neither source imports nor shared cross-context transactions SHALL implement
the workflow.

#### Scenario: A normal refresh runs

- **WHEN** a schedule emits a refresh command
- **THEN** RefreshDataset requests Capture, waits for CaptureCommitted, issues
  BuildDataset, observes DatasetReleased and requests RebuildProjection using
  immutable references and durable process state

#### Scenario: A candidate Dataset is published

- **WHEN** a Dataset candidate has passed its owner-controlled quality and
  release policy
- **THEN** Datasets executes `PublishDataset` as its own local transaction that
  records release generation, audit evidence and DatasetReleased outbox event;
  a Process may request that command after a cross-context trigger but may not
  own or directly mutate the release pointer

#### Scenario: A process deadline expires

- **WHEN** a required input, external dependency or retry policy exceeds the
  process deadline
- **THEN** the process transitions to `deadline_exceeded` or an explicit
  blocked state with last-error evidence and does not continue unbounded retry

### Requirement: Scheduling and event adapters SHALL remain technical boundaries

Platform Scheduling SHALL create command envelopes and manage schedule, lease,
missed-fire and catch-up state only. Event adapters SHALL decode an event, call
the owning Process Manager and record delivery result only. A scheduler, CLI
main, Web router or event handler SHALL NOT coordinate an entire business
workflow directly.

#### Scenario: An operator triggers a backfill from the CLI

- **WHEN** an existing CLI compatibility command requests a backfill
- **THEN** the interface validates transport arguments, creates an auditable
  command/process receipt and returns control without directly calling a
  provider, writing cross-context tables or performing the complete workflow
