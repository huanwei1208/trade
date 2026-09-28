## ADDED Requirements

### Requirement: Platform persistence and events SHALL precede Context extraction

Platform SHALL provide a minimal public persistence and events foundation
after the `kernel-and-public-contracts` child has published its framework-free
IDs, envelopes, `ActorContext`, `OperationReceipt`, error and policy-reference
DTOs, but before Capture, Datasets, Studies or Decision Support owns a new
durable transition. The foundation SHALL provide a context-local transaction port that
atomically commits the owner's aggregate transition, immutable receipt/audit
record and outbox record; it SHALL NOT provide a business repository or a
cross-context transaction. The foundation SHALL also provide durable command
ingress idempotency, consumer inbox/receipt deduplication, lease/ack recovery,
ordered delivery policy, bounded retry and a dead-letter/redrive record.
Command ingress SHALL scope an idempotency claim by trusted actor/tenant
authority and command kind and SHALL bind the canonical command digest. The
same scoped key and digest SHALL return the existing receipt; the same scoped
key with a different digest SHALL fail with a stable conflict and SHALL create
no second owner transaction, Process generation or context command.

#### Scenario: A process dies after a context transaction commits

- **WHEN** Capture, Datasets, Studies or Decision Support commits local state,
  audit evidence and an outbox record, and the dispatcher dies before consumer
  acknowledgement
- **THEN** a later dispatcher lease recovery delivers the same immutable
  envelope to an inbox-deduplicated consumer, records exactly one effective
  consumer receipt and does not repeat the context transition

#### Scenario: Delivery exhausts its policy

- **WHEN** an outbox envelope exceeds its declared retry, ordering or deadline
  policy
- **THEN** Platform records a bounded dead-letter entry with correlation,
  causation, payload digest and failure reason, requires an audited redrive
  command, and never drops or silently reorders the envelope

#### Scenario: Concurrent ingress reuses a key for different command content

- **WHEN** two requests concurrently claim one trusted actor scope, command kind
  and idempotency key with different canonical command digests
- **THEN** only one digest may own the durable claim, the conflicting request
  returns the stable idempotency-conflict receipt or error, and no second owner
  transaction, Process generation or context command is created

### Requirement: Ordered delivery SHALL use a durable OrderingContract

For every envelope that declares ordering, Platform SHALL persist an
`OrderingContract` containing ordering scope/key, fenced producer epoch,
transactionally assigned sequence, consumer expected sequence, stale/duplicate
rule, bounded gap timeout and head-of-line failure policy. A consumer SHALL
not apply sequence `N+1` before the required handling of `N`; a stale,
duplicate or gap-expired envelope SHALL create an explicit receipt,
quarantine/reconciliation action or dead-letter outcome under the contract.
Unordered envelopes SHALL explicitly declare that ordering is not required.

#### Scenario: Sequence N+1 arrives before N after a restart

- **WHEN** a consumer lease expires and a dispatcher delivers sequence `N+1`
  before sequence `N` for the same ordered scope
- **THEN** the consumer retains durable expected-sequence state, does not
  apply `N+1`, and waits, replays, or routes the gap through the declared
  bounded reconciliation path without silently changing aggregate order

### Requirement: Artifact commit visibility SHALL be crash-recoverable

Capture SHALL use a prepare, verify, commit-marker and receipt protocol for
artifact bytes stored outside the context database. A receipt/outbox record
SHALL reference only a verified committed artifact. Startup reconciliation SHALL
classify prepared, orphaned, digest-mismatched and receipt-without-artifact
states deterministically, preserve diagnostics and either safely recover or
quarantine them without publishing an ambiguous reference.

#### Scenario: The runtime fails between raw-byte staging and receipt commit

- **WHEN** a Capture worker stages raw bytes and crashes before the context
  receipt transaction commits
- **THEN** reconciliation identifies the staged artifact as prepared or
  orphaned, performs no Dataset publication, and records an idempotent
  recovery or quarantine outcome before the request may be retried

#### Scenario: The database receipt exists but artifact verification fails

- **WHEN** recovery resolves a committed Capture receipt whose referenced
  artifact is absent or whose digest differs from the recorded digest
- **THEN** the receipt is marked integrity-failed or quarantined, all formal
  downstream consumption is blocked, and recovery preserves the mismatch
  evidence rather than substituting another artifact

### Requirement: Migration startup SHALL be coordinated and mixed-version safe

Platform Persistence SHALL provide a `DatabaseRuntime` and
`MigrationCoordinator` that select explicit read-only, compatible-writer or
migration-leader startup modes. A migration leader lock, schema capability
generation and supported minimum/maximum generation SHALL fence incompatible
writers. Context migration registration SHALL remain context-owned, while the
coordinator runs registrations in a declared dependency order. The foundation
SHALL introduce an explicit `LegacySchemaBootstrapAdapter` for the existing
`TradeDB` migration history; it does not require Context repositories that
have not yet been extracted. A later owner-transition child SHALL replace each
legacy registration/delegation only after its Context repository and reader
exist. New Bootstrap entrypoints SHALL NOT trigger global schema initialization
as an implicit `TradeDB` constructor side effect.

#### Scenario: Two binary generations start against one SQLite database

- **WHEN** a process with an older supported generation and a process requiring
  a newer migration generation start concurrently
- **THEN** only the elected migration leader may change schema, an incompatible
  writer is rejected or starts read-only with a stable reason code, and no
  mixed-generation business write is accepted outside the compatibility range

#### Scenario: A context migration is interrupted

- **WHEN** a registered context migration stops before its checkpointed replay
  or compatibility bridge is ready
- **THEN** the coordinator records the checkpoint and capability state, the
  old compatible reader remains available, and a retry resumes idempotently
  without reapplying destructive work

### Requirement: Capacity evidence SHALL be comparable across child changes

Platform SHALL define a versioned `CapacityEnvelope` result contract for every
1x/10x gate. It SHALL record fixture cardinality and duration, source/credential
and stream shape where applicable, concurrency, runner resource profile,
latency percentiles, admission/rejection counts, SQLite lock/write time,
scan bytes/files, CPU/memory/disk peaks, backlog/recovery time and explicit
overload outcome. A child SHALL reserve named limits in that envelope and
shall not activate a source, query, delivery or interface surface using an
illustrative parent value as a production limit.

In addition to isolated child evidence, every cumulative cutover SHALL produce
one `CombinedCapacityEnvelope` for the exact deployment topology that will
coexist after that cutover. The combined fixture SHALL run the newly selected
surface concurrently with all already selected Capture, Dataset, Study,
Process, outbox/replay, BFF/SSE and maintenance workloads applicable to that
deployment. It SHALL declare a whole-runner allocation for CPU, memory, disk
space and throughput, SQLite writer/lock time, file descriptors, connections,
workers and child processes; name each subsystem reservation; and prove that
the aggregate allocation fits the runner without starvation. Isolated child
passes SHALL NOT substitute for this cumulative result. An overload fixture
SHALL prove admission shedding, bounded backlog and recovery fairness without
silently dropping work or changing query semantics.

#### Scenario: A Dataset child reports a 10x query result

- **WHEN** a Dataset child completes its 10x QueryBudget fixture
- **THEN** it emits a CapacityEnvelope result with the declared workload,
  threshold, observed scan/resource/latency values and explicit pass, defer or
  overload result that can be compared with another child without inferring
  undocumented measurement conditions

#### Scenario: A new BFF coexists with capture and replay load

- **WHEN** an interface child proposes selecting a BFF while Capture workers,
  Dataset queries, Process/outbox replay and existing SSE clients remain active
- **THEN** the cutover runs one combined 10x topology, records both aggregate
  and per-subsystem allocations and observed peaks, proves finite overload and
  recovery behavior, and blocks selection even if every isolated child result
  passed when the combined allocation or fairness contract fails

### Requirement: Platform capabilities SHALL remain technical and separately owned

Platform SHALL expose six technical capability areas with no business
aggregate semantics:

- `execution` owns command execution, execution ownership, bounded
  concurrency, timeout, cancellation, retry, child-process control, shutdown
  participation and execution receipts;
- `events` owns envelopes, ingress/outbox/inbox admission, dispatch, replay,
  idempotency, ordering, delivery leases, acknowledgement and dead-letter
  state;
- `scheduling` owns schedules, fire leases, next/missed fire, catch-up policy
  and command-envelope emission;
- `persistence` owns connections, read-only sessions, owner-local transaction
  primitives, locks and migration-runner mechanics;
- `settings` owns versioned technical configuration and secret-safe access,
  but not SourceManifest or business policy; and
- `backup` owns consistency-cut manifests, verified staged restore,
  activation/recovery state and receipts.

Business SQL, repositories, migrations, lifecycle transitions and provider
policy SHALL remain in their owning Context. Platform public APIs and stored
records SHALL NOT contain BTC, Kline, Dataset, Study, Recommendation,
Portfolio or other business vocabulary. Generic capability implementations
MAY be selected by Bootstrap behind Context-owned ports; this SHALL NOT give
Platform ownership of the consuming aggregate.

#### Scenario: A scheduler is configured to refresh BTC data

- **WHEN** a schedule reaches its next fire for a business refresh
- **THEN** Platform Scheduling records the generic fire/lease state and emits
  a command envelope, while the Process contract carries the refresh meaning
  and no Platform module calls a provider, queries a business table or embeds a
  BTC-specific transition

### Requirement: Platform composition SHALL have one explicit Bootstrap owner

`bootstrap` SHALL be the only production composition root for CLI, Web,
worker, scheduler and native lifecycle assembly. It SHALL wire concrete
repositories, adapters, Platform implementations, context use cases and
Process Managers through declared capabilities. Existing `trade_py` and
`trade_web` construction paths SHALL remain compatibility shims until their
selected entrypoints are delegated; no Interface child may create a second
runtime container or bypass Bootstrap.

#### Scenario: An HTTP route is migrated to a new BFF

- **WHEN** an existing FastAPI route is delegated to an Interfaces BFF
- **THEN** the BFF obtains a query/use-case handle from Bootstrap, does not
  instantiate a `TradeDB`, EventBus, provider client or native binding itself,
  and preserves its legacy route contract through the compatibility adapter

### Requirement: Runtime handler selection SHALL be exclusive and reversible

Platform SHALL provide a generic, generation-fenced handler selector, while
Processes SHALL own the semantic decision to select a legacy or Process
handler for a process type. A forward transition SHALL use
`legacy_selected -> denying_legacy -> quiescing_legacy ->
process_switch_prepared -> process_selected`. Rollback SHALL use the symmetric
`process_selected -> denying_process -> quiescing_process ->
legacy_switch_prepared -> legacy_selected` transition. Admission denial,
owned-operation and delivery-lease census, selector compare-and-swap and
terminal selection evidence SHALL be durable. Only the selected generation may
claim new work.

No forward or rollback selector compare-and-swap may occur until the losing
handler has denied new admission, has zero owned operations and residual child
processes, and Platform Events has settled or explicitly transferred its inbox,
outbox and delivery leases. A blocked or crashed transition SHALL remain in its
last durable state with one permitted recovery action; it SHALL NOT infer a
winner from process liveness or run both handlers. Process handler selection
therefore depends on the implemented Bootstrap lifecycle and Platform Events
containment evidence, not only on compatible command DTOs.

#### Scenario: A legacy handler ignores quiescence during forward selection

- **WHEN** a Process child denies legacy admission but a non-cooperative legacy
  handler still owns an operation or child process
- **THEN** selection remains `quiescing_legacy`, the Process handler cannot
  claim new work, Bootstrap applies its bounded cancellation and TERM/KILL
  policy, and an operator sees the blocking owner and permitted retry or
  rollback action

#### Scenario: The runtime crashes around a selector compare-and-swap

- **WHEN** the runtime crashes immediately before or after a forward or rollback
  selector compare-and-swap
- **THEN** restart uses the durable generation, quiescence census and delivery
  settlement receipts to select exactly one handler, rejects stale-generation
  claims and resumes or reverses the transition idempotently

### Requirement: Bootstrap SHALL own one bounded shutdown lifecycle

Bootstrap SHALL expose one idempotent runtime lifecycle for CLI, Web, workers
and schedulers. The first stop request SHALL atomically change admission from
`running` to `stopping`, reject new commands and assign one monotonic shutdown
deadline shared by every owned component. Components SHALL receive only their
remaining budget and SHALL NOT create nested unbounded waits or replace the
owner deadline with independent full-duration timeouts. Repeated stop requests
SHALL join or inspect the same shutdown attempt.

The owner SHALL stop resources in dependency order: close external command and
schedule admission; stop Process and event dispatch claims; request cooperative
task cancellation; send TERM and then KILL to owned child-process groups within
finite sub-budgets; drain executors, queues, SSE heartbeats and delivery leases;
flush owner-local receipts/outbox state; and close repositories/database
connections last. A component that cannot stop before its budget expires SHALL
record a typed timeout with resource identity and remaining work. The runtime
SHALL remain `stopping` and retryable instead of reporting `stopped` while
daemon threads, owned child processes, leases or database users remain live.

The existing `converge-runtime-boundaries` Web resource-container behavior is
the initial compatibility seed, not proof that all entrypoints already satisfy
this lifecycle. Its owner deadline, stop ordering and retryable stopping state
SHALL be preserved while the foundation extends the same contract to CLI,
workers and schedulers.

Bootstrap SHALL register each resource in the lifecycle owner immediately after
acquisition and before the resource may admit work. If construction fails
before `running`, Bootstrap SHALL deny admission and clean up only the acquired
resource set in reverse dependency order under one monotonic startup-cleanup
deadline. Startup cleanup SHALL use the same child-process group termination,
executor/lease drain, database-last and typed receipt rules as ordinary
shutdown. A cleanup timeout SHALL remain retryable `stopping` with the startup
failure and live-resource census; it SHALL NOT report a clean startup failure
while a daemon thread, non-daemon thread, process, lease or database user is
still owned.

#### Scenario: A child process ignores cooperative shutdown

- **WHEN** an owned provider, native or worker child process does not exit after
  cancellation and TERM within its allocated deadline
- **THEN** Bootstrap kills the entire owned process group within the remaining
  global budget, records TERM/KILL and exit evidence, continues bounded cleanup
  of independent resources, and leaves no untracked child consuming the runner

#### Scenario: An executor is still draining at the deadline

- **WHEN** executor work or an SSE heartbeat cannot drain before the shared
  monotonic deadline
- **THEN** Bootstrap records a shutdown-timeout receipt identifying the live
  resource and cancellation outcome, does not close a database still in use,
  and leaves the lifecycle in retryable `stopping` rather than blocking
  indefinitely or falsely reporting success

#### Scenario: Stop is requested more than once

- **WHEN** signal handling, HTTP lifespan cleanup and a caller each request
  shutdown for the same runtime
- **THEN** all requests observe the same attempt and deadline, no component is
  closed concurrently twice, and a later retry resumes only unresolved cleanup
  steps from durable or in-memory owner state

#### Scenario: Construction fails after a worker and database are acquired

- **WHEN** Bootstrap has acquired a database and started a worker but a later
  adapter fails before the runtime reaches `running`
- **THEN** no external admission opens, both acquired resources are registered
  under one startup attempt, the worker is cancelled and its process group
  terminated before the database closes, and timeout leaves a visible,
  retryable `stopping` state rather than an unbounded `wait=True` cleanup

#### Scenario: Shutdown completes within its budget

- **WHEN** all admitted operations settle or cancel, child process groups exit,
  delivery and heartbeat work drains, and repositories close before the
  deadline
- **THEN** Bootstrap records one terminal `stopped` receipt with component
  outcomes and no owned non-daemon thread, process, lease or open database
  connection remains
