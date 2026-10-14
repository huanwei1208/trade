## ADDED Requirements

### Requirement: DatabaseRuntime SHALL separate observation, writing and migration authority

Platform Persistence SHALL expose one framework-free `DatabaseRuntime` capability
with closed startup modes `read_only`, `compatible_writer` and
`migration_leader`. `read_only` SHALL open an existing database without creating a
directory, database, table, index, migration row, default setting or seed and SHALL
enforce query-only behavior at the connection and transaction boundary.
`compatible_writer` SHALL require a durable writer lease and a schema capability
generation inside its declared read/write range but SHALL NOT execute DDL or seed
state. `migration_leader` SHALL require an exclusive migration lease, a monotonically
increasing fence generation and an explicit `MigrationPlan`.

Every runtime handle SHALL identify database identity, owner namespace, startup mode,
schema generation, minimum/maximum readable and writable generations, owner instance,
fence generation, lease expiry and capability digest. A handle SHALL NOT expose a
raw connection through a public contract. A stale, expired or mismatched writer fence
SHALL be rejected in the same transaction before an owner write.

#### Scenario: A status command opens a database
- **WHEN** a query-only CLI or HTTP capability starts in `read_only` mode
- **THEN** no filesystem or schema state is created or changed and an absent database is reported as explicitly unavailable rather than initialized

#### Scenario: A supported writer starts
- **WHEN** the current schema generation is within the binary's declared write range and the runtime acquires the current writer fence
- **THEN** `compatible_writer` returns an owner-bound handle without running migrations or seeds

#### Scenario: A stale process writes after a fence changes
- **WHEN** a transaction presents writer generation N after generation N+1 has taken over
- **THEN** the transaction is rolled back with a stable stale-writer reason and no state, audit, inbox or outbox row is committed

### Requirement: Owner transactions SHALL be local and atomically durable

Platform Persistence SHALL provide an owner-bound local transaction primitive.
Within one physical database transaction, one owning Context or Platform component
MAY commit only:

1. its own aggregate or technical state transition;
2. its own immutable transition receipt or audit record;
3. a consumer inbox receipt and ordered-consumer head when it is consuming a
   message; and
4. zero or more Platform outbox records emitted by that same transition; and
5. at most one Platform codec-retention shard mutation when the same transition
   makes one codec-dependent durable identity visible or permanently
   unresolvable.

The transaction SHALL carry owner namespace, transaction identity, operation,
correlation and causation identities, writer fence generation, finite monotonic
deadline and an explicit outcome. The same transaction SHALL verify every referenced
outbox payload digest before commit. Platform SHALL provide connection, transaction,
lock and rollback primitives only; business SQL, repositories, aggregate invariants
and context migrations SHALL remain with the owner. No transaction SHALL write two
business Contexts, call a provider, wait on message delivery or span another
database.

Every SQLite owner transaction SHALL precompute bounded payloads and candidate keys
before `BEGIN IMMEDIATE`, set busy/lock wait to no more than the remaining monotonic
deadline, recheck that deadline after write-lock acquisition and immediately before
commit, and roll back on exhaustion. A versioned `PersistenceCapacityProfile` SHALL
bound open connections, statements, selected/changed rows, write-lock hold time,
retry attempts and jitter, WAL growth and checkpoint interference for each operation
class. Keyset/indexed selection SHALL replace unbounded scans inside a write
transaction. Lock-wait and lock-hold measurements SHALL be reported separately;
neither a successful SQLite call nor a fixed driver timeout may overrun the owner
deadline.

#### Scenario: A Capture transition emits an event
- **WHEN** a future Capture repository commits a capture receipt and
  `CaptureCommitted`
- **THEN** Capture state, its owner receipt and the immutable Platform outbox record become visible together or all remain absent

#### Scenario: A cross-Context write is requested
- **WHEN** one transaction attempts to update both a Datasets table and a Studies table
- **THEN** owner-scope validation rejects the transaction rather than expanding the Platform primitive into a shared business unit of work

#### Scenario: The process dies after commit
- **WHEN** the owner transaction commits and the process exits before a dispatcher observes its outbox row
- **THEN** the committed owner state and outbox remain recoverable and no caller must repeat the owner transition to recreate the message

#### Scenario: SQLite remains busy through the owner deadline
- **WHEN** another connection holds the write lock until an owner transaction's remaining monotonic budget expires
- **THEN** the owner transaction returns a bounded unavailable/deadline outcome, commits no owner/audit/inbox/outbox row and leaves no retrying background work

### Requirement: Codec retention accounting and required manifests SHALL be bounded and authoritative

Platform Persistence SHALL be the sole writer of codec-retention accounting for
every codec-dependent durable projection, replay, receipt or other resolvable
identity defined by the exact Kernel V21 generation after its prerequisite gate
passes. Processes SHALL store
only projection-independent immutable references and opaque links and SHALL NOT
write owner canonical payload/projection bytes, codec manifests or a Platform
codec-retention port.

Runtime accounting SHALL use exactly 16 Platform-owned retention shards. The shard
index SHALL use the frozen Kernel algorithm: the first four bytes of SHA-256 over
the length-framed durable dependent identity modulo 16. The owner-local transaction
that makes a dependent identity visible SHALL increment or create at most one row
for its exact registry key and codec identity in that shard. The transaction that
makes the identity permanently unresolvable SHALL decrement or remove that row only
after its retention horizon. Each mutation SHALL use at most three compare-and-swap
attempts under the dependent transaction's existing finite monotonic deadline;
exhaustion SHALL roll back the dependent identity and retention mutation together.
It SHALL NOT clone or rewrite a complete manifest.

Each nonzero shard row SHALL bind exact registry key, exact codec identity, shard
index, positive retained-reference count, conservative latest-required-retention
high-water mark and monotonically increasing shard revision. A conservative
high-water mark MAY remain later than the exact current maximum while the count is
positive, but SHALL never permit early retirement. Zero or negative counts, identity
mismatch, revision regression or early removal SHALL be corruption.

Bootstrap and codec retirement SHALL close both ingress and retention-mutation
admission, drain all admitted shard transactions under one finite deadline and hold
the current Platform owner fence plus one exclusive retention-snapshot lease. Under
that frozen window they SHALL read one stable ordered 16-shard revision vector,
aggregate no more than 4,096 entries from no more than 65,536 shard rows and publish
one immutable `RequiredOwnerCodecManifestV1` generation in one Platform persistence
transaction. The header SHALL bind schema version 1, positive monotonic generation,
current owner instance/fence, exact entry count, exact source-revision digest, exact
ordered-entry digest and committed marker. Entries SHALL be sorted by exact registry
key, repeat the snapshot generation and bind only the Kernel-approved fields. The
same transaction SHALL atomically switch the sole authoritative current pointer only
after the complete header and entries are written.

Readiness SHALL read the sole current pointer and complete matching generation in
one bounded transaction while the same mutation gate, fence, lease and exact frozen
16-shard revision vector remain valid. It SHALL reject a missing pointer/generation,
non-committed or mixed generation, owner/fence mismatch, count or digest mismatch,
stale source revision, duplicate/zero-count entry, timeout or over-capacity
aggregate. It SHALL NOT enumerate or scan durable projections, replay rows, receipts
or audit rows to reconstruct retention.

#### Scenario: A durable projection becomes visible
- **WHEN** an owner-local transaction commits a new codec-dependent projection identity
- **THEN** that identity and exactly one deterministic retention-shard increment become visible together, or both remain absent after no more than three CAS attempts

#### Scenario: A retained identity reaches the end of its lifecycle
- **WHEN** an identity is permanently unresolvable and its retention horizon has passed
- **THEN** the same owner-local transaction decrements or removes only its selected shard row and cannot retire the codec while any positive dependent count remains

#### Scenario: Bootstrap freezes required codecs during concurrent traffic
- **WHEN** Bootstrap closes both admissions, drains in-flight mutations and acquires the current owner fence plus exclusive snapshot lease
- **THEN** it binds one stable 16-shard revision vector and atomically publishes one complete immutable manifest generation and current pointer

#### Scenario: A manifest is internally complete but stale
- **WHEN** its owner/fence or source-revision digest does not match the frozen current window
- **THEN** readiness rejects it as required-codec unavailable rather than accepting internal completeness or scanning dependent rows for a replacement

#### Scenario: Processes attempts retention accounting
- **WHEN** a Process repository stores a handoff or workflow transition
- **THEN** architecture and port checks permit only projection-independent facts and reject owner codec bytes, manifests or retention mutation access

### Requirement: MigrationCoordinator SHALL run owner registrations under durable capability fencing

`MigrationCoordinator` SHALL accept versioned `MigrationRegistration` values from
Platform and each extracted Context. A registration SHALL identify owner, migration
ID and digest, from/to schema capability, dependencies, additive or new-generation
strategy, backward/forward compatibility, checkpoint store, idempotency key,
validation, cutover and rollback entrypoints. Platform SHALL order registrations by
declared dependencies and SHALL NOT contain their business SQL.

The coordinator SHALL persist migration lease, plan digest, current step,
checkpoint, capability-before/after, compatibility range, status, safe error,
timestamps and audit receipt. An interrupted migration SHALL resume only when its
registration digest and checkpoint agree. A changed registration under the same
identity, missing dependency, unknown generation, failed validation or incompatible
writer SHALL fail closed.

Before capability activation, the coordinator SHALL persist immutable
`GenerationReadinessEvidence` binding migration/restore plan and registration
digests, prior and target generations, required-owner-set digest, reader/writer
compatibility ranges, repository/artifact probe-set digest and result digest,
binary/config generation, produced/expiry times and activation fence. Old/new reader
parity, forward-read rejection, supported old-reader behavior, incompatible old
writer rejection, mixed-version restart and rollback readability SHALL be explicit
probe results. A changed or unavailable registration, compatibility rule, binary,
owner set or probe set SHALL invalidate the evidence; restart SHALL not reinterpret
it under newer code. Activation journal CAS and writer-admission reopening SHALL
compare the exact readiness-evidence identity.

While any writer that does not participate in `DatabaseRuntime` fencing can access
the database, an incompatible migration SHALL be prohibited. Only an additive
backward/forward-compatible migration or an externally proven exclusive maintenance
window MAY proceed. A capability table alone SHALL NOT be treated as proof that an
unaware legacy binary is fenced.

#### Scenario: Two participating binary generations start concurrently
- **WHEN** two Platform-aware binaries request migration leadership for one database
- **THEN** exactly one fence generation owns the migration lease, the follower starts in a compatible mode or is rejected, and no migration step runs twice

#### Scenario: An old unaware writer may still be running
- **WHEN** the coordinator cannot prove that every legacy writer has stopped or joined the writer-fence protocol
- **THEN** it blocks an incompatible schema cutover with `legacy_unfenced_writer` and leaves the previous generation writable

#### Scenario: A migration crashes after a checkpoint
- **WHEN** a registration stops after checkpoint K but before capability activation
- **THEN** restart verifies the registration digest, preserves the old compatible reader and resumes idempotently from K without repeating destructive work

#### Scenario: Readiness probes change after verification
- **WHEN** an activation restarts with a binary, configuration, owner set, compatibility rule or probe-set digest different from the persisted readiness evidence
- **THEN** activation remains closed and requires new verification rather than reusing or silently reinterpreting the prior result

### Requirement: Legacy schema bootstrap SHALL be isolated and temporary

The first implementation SHALL place the only target-to-legacy schema bridge at
`src/trade/platform/persistence/adapters/legacy_schema_bootstrap.py`. The bridge
SHALL expose only `LegacySchemaBootstrapAdapter`, SHALL be callable only by target
Bootstrap in `migration_leader` mode, and SHALL import only the exact legacy
bootstrap symbols approved in `architecture-baseline.toml`. Its implementation child
SHALL add source-verified writer, transaction and compatibility proof before the
guard accepts the bridge.

The adapter SHALL delegate the existing `TradeDB` schema/bootstrap history, close
all temporary resources, validate the expected legacy migration generation and
record one compatibility receipt. It SHALL NOT become a query repository, general
database facade or import path for a Context or Interface. Each owner-transition
child SHALL replace only its own legacy registration after its repository, old/new
reader comparison and rollback source exist. The bridge SHALL be removed after the
last registration satisfies its retirement window.

#### Scenario: A new database is explicitly initialized
- **WHEN** Bootstrap selects migration mode with a reviewed legacy bootstrap plan
- **THEN** only the bridge invokes the legacy initializer, records the observed legacy capability and returns no business repository

#### Scenario: A query path attempts bootstrap
- **WHEN** an HTTP BFF, CLI status command or Context use case imports or invokes the bridge
- **THEN** architecture and runtime capability checks reject the call and require a read-only or owner repository handle

#### Scenario: One Context migrates its table
- **WHEN** a later owner child passes dual-read and rollback gates for one legacy table
- **THEN** only that registration stops delegating to the legacy bridge while unrelated legacy tables and readers remain unchanged

### Requirement: Platform persistence metadata SHALL have one logical owner

The eventual additive Platform schema SHALL make Platform Persistence the sole
writer of schema capabilities, migration runs/checkpoints, writer leases, the
global activation lease, activation journal, codec-retention shards,
required-codec manifest generations and the authoritative current-snapshot
pointer. Platform Execution Operation
Control SHALL be the sole writer of operation claims, operation receipts and
refusal-audit metadata and SHALL consume Platform Persistence transaction
primitives without transferring logical ownership. Platform Events SHALL be the
sole writer of outbox routing/delivery, inbox receipt, ordering, gap-resolution
and dead-letter metadata. Platform Backup SHALL be the sole writer of backup
certification and restore-operation metadata and SHALL request generation
activation only through the Platform Persistence activation capability.

Existing `event_log`, `event_handler_runs`, `schema_migrations`,
`backup_snapshots`, `settings`, `job_runs` and `pipeline_dag` SHALL remain legacy
compatibility state until separately cut over. This child SHALL NOT claim mixed
business rows in `settings`, `job_runs` or `pipeline_dag` merely because the physical
tables are shared. Other Contexts and Interfaces SHALL consume Platform queries,
receipts or projections and SHALL NOT query Platform tables or `_conn` directly.

#### Scenario: A Web route needs delivery status
- **WHEN** an Operations BFF requests event backlog and dead-letter status
- **THEN** it uses a bounded Platform query contract and does not read `event_log`, delivery or inbox tables directly

#### Scenario: A business setting is encountered
- **WHEN** a legacy `settings` row carries risk, Capture source or model semantics
- **THEN** Platform does not assume semantic ownership; the row stays behind the compatibility adapter until its owning child classifies and migrates it

#### Scenario: Physical SQLite remains shared
- **WHEN** Platform and a Context temporarily use the same SQLite file
- **THEN** each table and transaction still has one logical owner and no shared physical file is interpreted as cross-owner write authority

#### Scenario: Ingress stores an operation receipt
- **WHEN** command admission creates or transitions Platform operation metadata
- **THEN** Platform Execution Operation Control remains the sole logical writer while Platform Persistence supplies only the fenced transaction primitive

#### Scenario: Backup requests activation
- **WHEN** a staged restore is ready to fence writers and change active generation
- **THEN** Platform Backup drives the restore workflow through the sole Platform Persistence activation capability and does not write the activation journal directly

### Requirement: Generation activation SHALL use one global fenced authority

Platform Persistence SHALL expose one internal `GenerationActivationCapability`
as the sole writer of the global activation lease, writer-admission gate and
activation journal. Platform Backup and `MigrationCoordinator` SHALL request
activation through that capability; neither SHALL acquire owner writer leases or
write activation state independently.

One activation attempt SHALL use a finite shared monotonic deadline and this
canonical acquire order:

1. before closing admission, validate the bounded complete owner set, exact
   `GenerationReadinessEvidence` and a durable `RollbackCandidateReceipt` binding
   prior generation, capability/owner/probe digests, required artifact identities,
   successful prior-readiness result, retention guarantee and rollback deadline;
2. compare-and-swap one database-scoped activation lease/fence;
3. close new compatible-writer admission for the expected active generation;
4. acquire or revoke owner writer leases in ascending canonical owner-namespace
   bytes;
5. drain or durably retain every admitted owner under its fence;
6. compare-and-swap the activation journal from the exact expected prior generation
   and readiness-evidence identity to the verified target generation; and
7. rebind and verify the selected generation before reopening admission.

The selected `ActivationCapacityProfile` SHALL bound required-owner cardinality and
reserve nonzero deadline slices for lease/fence acquisition, drain, journal CAS,
target rebind and prior-generation rollback. A stage may use unused earlier time but
SHALL NOT consume the reserved rollback slice. The complete owner set and both
readiness identities SHALL be validated before admission closes. A partial lease set
SHALL unwind in reverse order within the same remaining budget.

Every contender SHALL acquire only in that order and release in reverse order.
A failure before journal commit SHALL retain/select the prior generation. A
failure after target journal commit SHALL keep admission closed while recovery
either verifies target readiness or compare-and-swaps back to the prior
generation. Owner leases SHALL not reopen and the activation lease SHALL not be
released until the journal-selected target or prior generation has passed
required readiness probes. A stale activation or owner fence SHALL be rejected
inside the attempted write transaction. No Interface timeout, directory
presence, legacy status row or process-local lock SHALL override the durable
authority.

The activation journal SHALL be checksummed, append-only/fenced and internally
consistent with its lease, prior/target generation and readiness evidence. Missing,
unreadable, torn, corrupt or contradictory authority SHALL produce closed outcomes
`activation_authority_unavailable` or `activation_authority_inconsistent`.
Writer admission SHALL remain closed; status SHALL expose safe expected/observed
generation, journal-integrity evidence, fences and residual owners. Neither target
nor prior SHALL be automatically selected until an audited recovery operation
re-establishes authority. Directory presence, a restore operation row or a health
probe SHALL not reconstruct authority by itself.

#### Scenario: Restore and migration race
- **WHEN** Platform Backup and MigrationCoordinator concurrently request activation for one database
- **THEN** one database-scoped activation fence wins, the loser receives an explicit conflict/unavailable receipt and no owner lease or journal state is partially changed

#### Scenario: Owner fences are acquired concurrently
- **WHEN** an activation plan requires several owner namespaces
- **THEN** all contenders acquire them in the same ascending canonical order and a partial acquisition releases in reverse order before retry or failure

#### Scenario: Target health fails after journal commit
- **WHEN** the activation journal selects target but required readiness cannot pass
- **THEN** admission stays closed, the capability compare-and-swaps to the verified prior generation, rebinds and verifies it, then reopens prior admission and releases fences

#### Scenario: The prior generation is not a proven rollback candidate
- **WHEN** prior readiness, retained artifact identity or rollback-deadline evidence is absent, stale or invalid before activation
- **THEN** activation fails before writer admission closes and does not rely on an unverified prior generation as recovery

#### Scenario: The activation journal is torn or inconsistent
- **WHEN** restart cannot authenticate one internally consistent journal-selected generation and readiness identity
- **THEN** admission remains closed with `activation_authority_inconsistent`, no directory is selected automatically, and an audited authority-recovery procedure is required
