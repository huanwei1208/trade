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
