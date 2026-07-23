## ADDED Requirements

### Requirement: Web resources have one explicit process owner

The Web application SHALL initialize write-capable database and runtime resources
through one lifespan-owned container, SHALL make route/service dependencies
explicit, and SHALL close resources in deterministic ownership order.

#### Scenario: Application starts successfully

- **WHEN** the FastAPI lifespan starts with a valid temporary data root
- **THEN** one resource container initializes one `TradeDB`, the EventBus and
  existing Web services, and all registered routes resolve dependencies from
  that container

#### Scenario: Startup fails partially

- **WHEN** a later resource fails after an earlier resource was initialized
- **THEN** the container closes initialized resources in reverse order, preserves
  the original failure context, and does not publish a partially started
  container

#### Scenario: Repeated requests reuse resources

- **WHEN** multiple requests exercise extracted and non-extracted Web routes
- **THEN** requests do not rerun `TradeDB` schema initialization or migrations
  and do not leak additional application-owned database connections

#### Scenario: Application stops

- **WHEN** the FastAPI lifespan exits
- **THEN** new runtime work is rejected, admitted work follows the configured
  shutdown policy, runtime services close, and the owned database closes last

#### Scenario: Shutdown fails and is retried

- **WHEN** a command or EventBus shutdown stage fails while the container is
  stopping and the operator invokes shutdown again after the dependency becomes
  cleanable
- **THEN** the container retries only unfinished ownership stages, retains the
  database while writers are live, and eventually reaches `stopped` in command,
  EventBus, database order

#### Scenario: Shutdown exceeds its owner deadline

- **WHEN** a command, handler, queued future, or claim heartbeat does not stop
  within the one owner-level wall-clock deadline
- **THEN** shutdown returns a bounded incomplete result, lifecycle remains
  `stopping`, the database and ownership locks remain retained, and a later
  shutdown attempt can continue cleanup without reporting stopped

### Requirement: HTTP routers remain thin and contract-compatible

The Web composition root SHALL register cohesive routers, while transport
handlers SHALL delegate business/runtime behavior to owned services and SHALL
preserve existing public HTTP contracts.

#### Scenario: System routes are extracted

- **WHEN** system/runtime routes move from the composition root to a focused
  router
- **THEN** their paths, methods, parameters, status codes, response payloads,
  error semantics, and capability gates remain compatible

#### Scenario: Route needs a runtime resource

- **WHEN** an extracted route reads DB or EventBus state
- **THEN** it receives an owned dependency and does not construct, migrate, seed,
  close a database, access private connection state, or carry SQL outside the DB
  facade

#### Scenario: Durable admission is deferred

- **WHEN** an HTTP producer persists an event but handler admission is not
  accepted
- **THEN** the response identifies the existing durable `event_id`, reports a
  deferred recovery action, and does not advise automatic POST resubmission or
  emit `Retry-After`

#### Scenario: Workflow command is accepted

- **WHEN** `/api/run` accepts a validated target within command capacity
- **THEN** it returns the compatible target and limit plus PID and stable run ID,
  executes outside the FastAPI process, and exposes terminal status through the
  existing runs surface

#### Scenario: Workflow command audit is unavailable

- **WHEN** `/api/run` cannot create its durable audit identity or the operating
  system rejects process creation
- **THEN** the response distinguishes audit persistence from spawn failure with
  stable reason codes and sanitized messages, while root causes remain only in
  payload-safe correlated server logs

#### Scenario: Runtime query input is excessive

- **WHEN** calendar, list, status, or SSE query input exceeds the reviewed
  public work bound
- **THEN** transport validation rejects it before scanning data, and accepted
  calendar/status work does not perform N+1 queries or block the async event
  loop

### Requirement: EventBus admission is bounded and explicit

Each EventBus channel SHALL have finite admitted-work capacity and SHALL return a
typed admission outcome instead of silently growing an unbounded executor queue.

#### Scenario: Capacity is available

- **WHEN** an eligible non-succeeded handler can acquire its channel permit
- **THEN** its durable handler state is recorded, executor submission is accepted,
  and exactly one permit remains owned until completion

#### Scenario: Channel is saturated

- **WHEN** a handler cannot acquire a channel permit within the configured
  admission policy
- **THEN** the outcome is `saturated`, no permit is consumed, the handler is not
  reported `ok`, and durable state remains replayable

#### Scenario: Executor submission fails

- **WHEN** executor submission raises after a permit was acquired
- **THEN** the permit is released exactly once, a stable submission-failure state
  is observable, the original root cause is preserved, and the handler remains
  replayable

#### Scenario: Event dispatch is partially admitted

- **WHEN** one event has multiple handlers and only a subset can be admitted
- **THEN** completed handlers retain idempotent success, non-admitted handlers
  remain retryable, and the event cannot finalize as successful

#### Scenario: Runtime is stopping

- **WHEN** a producer submits after shutdown admission closes
- **THEN** the outcome is `shutting_down`, no executor work is queued, and the
  durable event remains available for explicit recovery

#### Scenario: Payload is not a JSON object

- **WHEN** a live API or CLI producer supplies invalid JSON, an array, scalar, or
  null instead of an object payload
- **THEN** publication fails before durable insertion and does not coerce the
  value to an empty object, while historical malformed rows remain quarantined
  during replay

#### Scenario: Caller mutates an accepted payload

- **WHEN** a caller mutates its nested payload object after publication returns
- **THEN** live handlers and replay observe the same canonical snapshot that was
  durably inserted rather than the caller's later mutation

#### Scenario: Deterministic child payload is invalid

- **WHEN** a DAG or agenda child handoff supplies a non-object payload
- **THEN** validation fails before the handoff identity is inserted and a later
  valid retry can use that deterministic identity

#### Scenario: Recovery backlog spans channels

- **WHEN** a bounded replay pass encounters unavailable or saturated older
  handlers before recoverable work in another channel
- **THEN** rotating keyset progress remains bounded, later channels are
  eventually attempted, and only runtime shutdown stops the whole recovery pass

#### Scenario: Handler claim renewal is transiently unavailable

- **WHEN** one active handler's claim renewal encounters a transient SQLite
  failure
- **THEN** renewal continues with bounded backoff, the handler does not silently
  lose ownership, and another runtime cannot execute the same stale claim
  concurrently

#### Scenario: Renewal outage exceeds the lease interval

- **WHEN** renewal remains unavailable beyond the nominal stale interval while
  the claim token's exact PID and process-start identity are still alive
- **THEN** another runtime refuses age-only reclaim and cannot execute the same
  handler concurrently

#### Scenario: DAG child handoff fails after job success

- **WHEN** a DAG job result is durably successful but child-event handoff fails
- **THEN** the successful job run is not overwritten as failed, and replay reuses
  its result while retrying only the idempotent child handoff

#### Scenario: Agenda event persistence fails

- **WHEN** agenda rows are claimed but event persistence raises before returning
  a durable typed outcome
- **THEN** the scheduler contains the exception, restores the current and
  unattempted queued rows to pending, and remains alive

#### Scenario: Agenda persistence committed before an exception

- **WHEN** agenda event insertion committed but publication raised before the
  typed outcome reached the scheduler
- **THEN** a deterministic agenda dispatch key resolves the existing event and
  a retry does not create a second durable event

#### Scenario: Agenda child admission is deferred

- **WHEN** an agenda trigger creates a durable child but child handler admission
  is saturated or shutting down
- **THEN** the agenda row records the child identity and a truthful
  done/deferred outcome rather than remaining indefinitely running

#### Scenario: Handler error resembles runtime admission

- **WHEN** a handler or provider raises text beginning with an admission-like
  phrase
- **THEN** automatic replay treats it as terminal unless reserved provenance was
  written by EventBus admission machinery

#### Scenario: Sparse replay follows large completed history

- **WHEN** completed event history is large and replay candidates are absent or
  sparse
- **THEN** candidate selection uses existing status and handler indexes with a
  bounded keyset rather than scanning the completed history

#### Scenario: Shutdown waits for claim heartbeat ownership

- **WHEN** a handler finishes but its claim heartbeat remains inside a DB
  operation
- **THEN** EventBus remains `stopping`, the Web owner retains the database, and
  shutdown can be retried after the heartbeat exits

### Requirement: Runtime capacity is observable without data scans

The system SHALL expose a bounded read-only capacity snapshot for every EventBus
channel and SHALL distinguish normal emptiness, saturation and unavailable
runtime state.

#### Scenario: Operator inspects healthy capacity

- **WHEN** the runtime is started and no channel is saturated
- **THEN** status reports the process generation, lifecycle, workers, capacity,
  admitted count, active count and available permits per channel

#### Scenario: Operator inspects saturation

- **WHEN** a channel rejects admission because it is full
- **THEN** status and structured logs expose the channel, event/handler identity,
  saturation count and last saturation time without exposing the full payload

#### Scenario: Runtime capacity is unavailable

- **WHEN** the Web application has no started runtime container
- **THEN** status reports `unavailable` rather than a fabricated zero-capacity
  healthy state

### Requirement: Runtime boundary migration is incremental and reversible

The project SHALL migrate one cohesive boundary at a time and SHALL preserve the
current CLI, API, DB, event and data contracts throughout rollout.

#### Scenario: First implementation slice

- **WHEN** only resource lifecycle ownership is implemented
- **THEN** all existing routes and EventBus semantics continue to work and the
  change can be reverted through source rollback while persistent formats and
  data remain intact

#### Scenario: Bounded admission rollout fails

- **WHEN** validation detects event-status drift, lost replayability, request
  incompatibility, unexpected saturation or shutdown regression
- **THEN** bounded admission wiring is disabled or reverted while persisted
  pending events remain recoverable by the prior implementation

### Requirement: Web workflow commands have durable bounded ownership

The Web application SHALL execute workflow commands outside the FastAPI process,
SHALL bound concurrent admission, SHALL record lifecycle in the existing
`job_runs` audit surface, and SHALL prevent owner loss from leaving an untracked
detached workflow.

#### Scenario: Command exits

- **WHEN** an accepted workflow command exits successfully, fails, or is
  terminated during shutdown
- **THEN** its stable run row records the terminal status, elapsed time and safe
  exit context without persisting raw request payloads

#### Scenario: Command spawn fails

- **WHEN** the operating system rejects process creation
- **THEN** the attempted run is durably marked error, capacity is released, and
  the caller receives an explicit spawn-failed outcome

#### Scenario: Command terminal persistence fails

- **WHEN** a workflow exits but its exact terminal audit write fails
- **THEN** the owner retains the pending terminal result, retries idempotently,
  and cannot report successful shutdown or release its data-root lock while the
  durable row remains running

#### Scenario: A second command owner overlaps

- **WHEN** another live Web command runner already holds ownership for the same
  canonical data root
- **THEN** the new runner fails closed before reconciliation or admission and
  cannot change the live owner's durable rows

#### Scenario: Runtime starts after an interrupted owner

- **WHEN** startup observes stale `web_command` runs or command ownership left by
  a prior Web process
- **THEN** stale audit rows are reconciled and any still-owned process group is
  terminated or safely adopted before new command admission opens
