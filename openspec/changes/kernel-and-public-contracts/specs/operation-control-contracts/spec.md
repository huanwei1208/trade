## ADDED Requirements

### Requirement: Actor context SHALL be established from trusted adapter evidence

`ActorContext` SHALL identify origin, principal kind and identifier, authority
scopes, bounded delegation, assurance, provenance and establishment time.
Mutation authority SHALL be established only from adapter-controlled CLI,
authenticated HTTP/SDK, registered scheduler, verified parent-event or
Bootstrap system evidence. Caller payload fields SHALL NOT establish identity
or authority. A decoded wire actor SHALL remain unverified until re-established
against trusted local evidence.

#### Scenario: A payload claims an administrator actor
- **WHEN** a command body contains actor, user, principal or authority fields that are not established by the adapter
- **THEN** those fields confer no authority and the mutation is denied or attributed to the separately established actor

#### Scenario: A verified scheduler submits a command
- **WHEN** Platform Scheduling creates a command from a registered schedule and lease
- **THEN** it establishes a system actor whose provenance links to that schedule identity without embedding credentials

#### Scenario: An anonymous query is allowed
- **WHEN** an interface policy explicitly permits an anonymous read-only query
- **THEN** the actor is marked `anonymous` with `anonymous_allowed` assurance and receives only the declared query scope

### Requirement: Command and query envelopes SHALL use typed owner payloads

Command and query envelopes SHALL compose Kernel metadata, trusted
`ActorContext`, a finite deadline and one typed owner DTO. They SHALL expose a
canonical payload digest but SHALL NOT expose raw idempotency secrets, live
callbacks, framework request objects or arbitrary payload dictionaries.

#### Scenario: A command is retried after transport timeout
- **WHEN** the same actor scope, canonical command and idempotency identity are resubmitted
- **THEN** command ingress can resolve the same digest and existing operation without depending on transport retry metadata

#### Scenario: A framework object enters a command
- **WHEN** a DTO contains a FastAPI request, Pydantic model, ORM object, DataFrame, connection, filesystem path or service object
- **THEN** contract validation or the architecture guard rejects it before serialization

### Requirement: Operation receipts SHALL report durable admission and terminal state truthfully

An `OperationReceipt` SHALL contain version, operation identity and kind,
command name/digest, trusted actor, correlation/causation identities, scoped
idempotency digest, closed operation state, safe reason, timestamps and optional
process linkage. A receipt SHALL exist only after durable admission identity is
created. Duplicate admission SHALL return the existing receipt. Raw payloads
and raw idempotency keys SHALL NOT be exposed.

#### Scenario: Persistence fails before operation identity is committed
- **WHEN** command ingress cannot durably claim an operation
- **THEN** it returns an `ErrorEnvelope` without fabricating an operation receipt or operation ID

#### Scenario: A duplicate accepted command is observed
- **WHEN** the same scoped idempotency identity is admitted again
- **THEN** the existing operation receipt is returned and no second owner transaction is created

#### Scenario: An operation reaches a terminal state
- **WHEN** an operation becomes completed, compensated, failed, cancelled or deadline-exceeded
- **THEN** its terminal timestamp is set once and no later transition returns it to running or waiting

### Requirement: Process views SHALL be bounded read-only recovery projections

A `ProcessView` SHALL expose process identity/type, correlation/causation,
idempotency digest, closed process and observation states, current step,
retry/limit/next-attempt, deadline, last safe error, compensation and
dead-letter states, no more than 50 ordered transitions, permitted recovery
actions and timestamps. It SHALL NOT expose raw command/event payload, SQL,
credentials, business-table rows, artifact bytes or traceback. Querying the
view SHALL NOT execute a recovery action.

#### Scenario: A process is blocked
- **WHEN** an operator queries a blocked process
- **THEN** the view reports the blocking reason, deadline, last observed step and permitted recovery actions without retrying, redriving or mutating the process

#### Scenario: Process history exceeds the wire budget
- **WHEN** more than 50 transitions exist
- **THEN** the owner returns a deterministic bounded window plus truncation metadata and retains full durable history outside the public DTO

#### Scenario: A process cannot be observed
- **WHEN** the process query store is unavailable or no observation completes before the caller deadline
- **THEN** the view or error reports `unavailable` or `not_observed` and does not represent the result as empty, healthy or completed

### Requirement: Status families SHALL remain orthogonal and closed

The system SHALL represent admission, operation, process, observation,
query-condition, control and shutdown states as separate closed enums.
`unknown`, `not_observed` and
`unavailable` SHALL remain distinct from `empty`, `partial`, `stale`,
`quarantined`, `blocked`, success and terminal error. Adding an enum value SHALL
require a new wire-schema version and compatibility review.

#### Scenario: A query returns no business rows
- **WHEN** the owner successfully observes a valid empty result
- **THEN** it reports observation `observed` and condition `empty`, not `unknown` or `unavailable`

#### Scenario: A legacy status is unknown
- **WHEN** a mapper encounters a status not covered by its reviewed source version
- **THEN** it fails closed to an unknown observation plus a safe error and never maps the status to success

#### Scenario: A legacy process is terminated
- **WHEN** a legacy row says `terminated` without durable cancellation intent and terminal cancellation evidence
- **THEN** the target contract does not claim `cancelled` and reports conservative failed or unknown terminal observation

### Requirement: Error envelopes SHALL be safe, versioned and transport-neutral

`ErrorEnvelope` SHALL contain exact schema name/version, stable reason code,
closed category and observation state, retryability and optional bounded
retry-after, correlation/operation/process links, occurrence time, safe message
and safe recovery hint. It SHALL NOT contain arbitrary extra fields, raw
exception text, traceback, credential, SQL, path or raw payload. HTTP status,
CLI exit code and SSE framing SHALL remain interface-adapter mappings.

#### Scenario: An Observatory error is mapped
- **WHEN** a legacy `ObservatoryError` contains reason, message, evidence refs and arbitrary extra fields
- **THEN** the mapper emits only whitelisted safe fields and uses a stable generic message if the original message is not proven safe

#### Scenario: A retry-after value is present
- **WHEN** a retryable saturation or availability failure has an owner-approved finite delay
- **THEN** the envelope carries bounded integer milliseconds and the HTTP adapter may preserve its existing `Retry-After` representation

### Requirement: Cancellation SHALL distinguish request acceptance from terminal cancellation

A cancellation API SHALL return a `ControlReceipt` with control identity,
operation/process linkage, actor, request time, finite control deadline and
closed disposition. `accepted` SHALL mean only that cancellation intent was
durably admitted. An operation or process SHALL enter `cancelled` only after
the owner records terminal cancellation evidence. Signal delivery, caller
disconnect or observation timeout alone SHALL NOT prove cancellation.

#### Scenario: A cancel request is accepted while work is still running
- **WHEN** the owner durably records cancellation intent before work exits
- **THEN** the control receipt is accepted while the operation remains running or waiting until a terminal owner receipt is observed

#### Scenario: Cancellation control times out
- **WHEN** intent cannot be admitted or applied before the finite control deadline
- **THEN** the response reports deadline-exceeded or unavailable with the last operation/process link and does not claim the work was cancelled

### Requirement: Shutdown SHALL have one finite deadline and explicit residual ownership

A shutdown API SHALL close admission and return a `ShutdownReceipt` containing
owner/control identity, request/deadline/completion times, closed shutdown
state, graceful/forced termination counts, bounded residual-owner counts and a
safe error. `completed` SHALL require zero live owned work and released
non-reentrant resources. Deadline-exceeded or incomplete shutdown SHALL retain
owner fencing and report residual work.

Every potentially blocking shutdown stage, including lock acquisition,
persistence retry, queue drain, thread/future/executor/subprocess wait and
process-tree termination, SHALL consume the remaining shared deadline. A
bounded public API SHALL NOT perform an unbounded join after its deadline.

#### Scenario: A child process ignores graceful termination
- **WHEN** the child remains alive after the graceful portion of the shared deadline
- **THEN** the process owner applies its reviewed forced process-tree policy within the same deadline and records the outcome and residual ownership

#### Scenario: An executor task cannot be interrupted
- **WHEN** executor shutdown would wait beyond the shared deadline
- **THEN** shutdown returns incomplete or deadline-exceeded without an unbounded `shutdown(wait=True)`, keeps the ownership fence closed and reports the residual task

#### Scenario: Multiple callers request shutdown
- **WHEN** concurrent callers stop the same owner
- **THEN** they observe the same bounded stop attempt or its terminal receipt and no caller waits indefinitely on another caller

#### Scenario: Shutdown completes
- **WHEN** all owned work is terminal, durable receipts are committed and non-reentrant resources are released before the deadline
- **THEN** exactly one completed shutdown receipt reports zero residual owners
