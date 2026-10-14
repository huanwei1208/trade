## ADDED Requirements

### Requirement: Architecture implementation SHALL be phased and reversible

Implementation SHALL proceed through independently reviewable child OpenSpec
changes: guardrails/baselines, Kernel/public contracts, Platform
persistence/events/Bootstrap foundation, formal PIT/revision semantics, Capture,
Datasets, Studies, Decision Support, Processes, operational
SLI/SLO/alert/runbook evidence, CLI/HTTP/SDK compatibility, BTC
observation/analysis UI, package/Web layout and finally legacy cleanup.
Guardrail baseline reconciliation
MAY refine the initial frozen interface generation without delegating handlers.
Every child SHALL use a dedicated worktree, have focused tests, state affected
public contracts, record data safety and define a rollback path. No Context
extraction that emits a context outbox or accepts cross-context commands SHALL
precede the Platform foundation; the Platform foundation SHALL not require
not-yet-extracted Context repositories; no formal DatasetSnapshot/Study
migration SHALL precede the formal PIT/revision gate; Processes and Interfaces
SHALL NOT expose Decision Support state before its owner contracts exist; and
the BTC workspace and package layout SHALL NOT be prerequisites for the
business ownership boundaries they consume.

#### Scenario: A child change needs a new context-owned table

- **WHEN** the child introduces a new durable record or migration
- **THEN** it states the authoritative writer, idempotency key, readers,
  transaction boundary, additive versioning, forward/backward compatibility,
  shadow replay or copy plan, cutover gate and rollback source before code is
  implemented

#### Scenario: A child fails its cutover comparison

- **WHEN** a compatibility, lineage, PIT, replay or projection comparison fails
  during staged cutover
- **THEN** the child retains immutable new records for audit, restores the
  prior compatible reader or pointer, reports the failure explicitly and does
  not delete artifacts or run an unreviewed cross-context repair

### Requirement: Migration coordination and release bridges SHALL have one authority

Every durable child migration SHALL declare its `DatabaseRuntime` capability
range, migration-leader/follower startup behavior, context migration
registration, checkpoint/replay policy and mixed-version writer fence. A
legacy-to-new release bridge SHALL have one named authoritative generation and
an append-only materialization journal; startup reconciliation SHALL repair
only a replaceable projection/pointer from the authority and dual readers SHALL
be compared before retirement. The global `TradeDB` facade may delegate during
the compatibility window but SHALL NOT remain a schema initializer or
cross-domain write authority.

#### Scenario: A legacy pointer materialization stops after the new release commits

- **WHEN** a Datasets release generation commits but the compatibility pointer
  materialization stops before completion
- **THEN** startup reconciliation uses the append-only journal and the
  authoritative release generation to finish or restore the projection, dual
  readers remain distinguishable, and the legacy pointer cannot independently
  advance or overwrite the new release

### Requirement: Legacy interfaces SHALL retire only after explicit exit criteria

The system SHALL retain each existing import path, directory, table reader, CLI
command, HTTP route, notebook access pattern or pointer format until its
replacement passes compatibility and consumer evidence for a documented time
window. No legacy surface SHALL be removed solely because an equivalent
directory now exists.

#### Scenario: A current pointer is replaced by a Dataset release

- **WHEN** a Dataset release pointer is ready to replace a legacy `current`
  artifact pointer
- **THEN** the implementation performs dual-read comparison or a readiness-gated
  pointer switch, preserves the prior generation as rollback source and keeps
  old consumers compatible until retirement criteria are satisfied

### Requirement: Restorable backups SHALL be verified before activation

Platform Backup SHALL create a manifest that identifies archive members,
immutable content digests, size, creation generation, schema capability range
required context artifacts, the SQLite snapshot/WAL boundary, each external
artifact-store generation and the outbox/inbox/process watermark that forms one
recoverable consistency cut. Each protected deployment SHALL declare measured
recovery point and recovery time objectives, backup frequency and retention,
and the maximum acceptable lag between owner databases, immutable artifacts and
delivery/process state. A backup whose members cannot be proven to share the
declared cut SHALL be marked incomplete and SHALL NOT be an activation source.

Restore SHALL validate archive member safety, manifest integrity and SHA-256
digests before extraction into a staged temporary root, validate the staged
database/artifacts against the manifest, and only then activate the selected
generation. Restore order SHALL be owner databases and migration ledgers,
immutable artifact stores, outbox/inbox/process delivery state, authoritative
release records, rebuildable projections and finally interface admission. A
projection or current pointer SHALL be rebuilt or reconciled from the restored
authority rather than used to override it. Restore SHALL persist a
`RestoreOperation` state machine
`prepared -> staged_verified -> writers_fenced -> activated ->
health_verified -> committed`, with explicit rollback/reconciliation states.
`MigrationCoordinator` SHALL fence writers/readers, journal one
generation compare-and-swap activation, require runtime rebind/readiness and
reconcile a crash at every intermediate state. Every restore attempt SHALL
append an audited receipt with actor, source, target, result and explicit
corruption/mismatch state; a failed verification or post-activation health
window SHALL leave or restore the prior active generation.

#### Scenario: A backup archive is corrupt or contains an unsafe member

- **WHEN** restore sees a missing manifest entry, SHA-256 mismatch, traversal
  member or incompatible schema capability
- **THEN** restore rejects the archive before activation, records a
  restore-verification-failed receipt with the reason, and preserves the
  previous active database/artifacts without extracting unverified content into
  them

#### Scenario: Activation fails after writers are fenced

- **WHEN** a staged verified restore has fenced writers but the runtime crashes
  during generation activation or fails its bounded health window
- **THEN** restart reconciliation resolves the journal to either the verified
  restored generation or the prior generation, rebinds runtimes only after
  readiness succeeds, and records the rollback/health outcome without exposing
  two writable generations

#### Scenario: A backup misses its declared consistency cut or recovery objective

- **WHEN** the database snapshot, WAL watermark, immutable artifact generation
  and delivery/process watermark do not form the same declared cut, or a restore
  rehearsal exceeds its RPO or RTO
- **THEN** Platform marks the backup or rehearsal non-compliant with measured
  lag and duration, prevents production activation from that receipt, preserves
  the previous active generation and raises the owner/escalation path from the
  operational matrix

### Requirement: Retention and garbage collection SHALL preserve reachable lineage

Retention governance SHALL assign Capture artifacts, Dataset
versions/snapshots/releases, Study results, process/audit/outbox records and
backups declared retention classes,
legal-hold state, capacity visibility and a tombstone protocol. Garbage
collection SHALL be dry-run capable, idempotent and authorized; it SHALL not
delete content referenced by a live or retained DatasetVersion, Snapshot,
StudyResult, release, process, outbox delivery, backup or legal hold. A delete
or archival action SHALL append a tombstone/receipt with prior digest, policy,
actor and recovery location where applicable.

Every retained or newly created formal reference SHALL first acquire a durable
reservation over its complete transitive evidence closure and SHALL confirm or
release that reservation through an owner-authorized receipt. A reservation
SHALL bind reservation ID, consumer context and reference identity, closure
digest, owner generation, confirmation deadline, correlation/idempotency
identity and state `pending`, `confirmed`, `reconciliation_required` or
`released`. Reaching the confirmation deadline SHALL move `pending` to
`reconciliation_required`, retain the GC block and raise owner-visible recovery;
it SHALL NOT auto-release evidence because the consumer commit may have
succeeded before its confirmation outbox was delivered.

Confirmation SHALL require a `ReferenceCommitted` receipt bound to the consumer
transaction and outbox identity. Release SHALL require a `ReferenceAborted` or
audited retirement receipt bound to the same reservation and consumer-local
transaction evidence. If the consumer is unavailable or reports `unknown`, the
reservation SHALL remain fail-closed and visible for reconciliation. A Process
Manager MAY coordinate status requests and receipts, but neither Platform nor
the evidence owner SHALL infer consumer commit state from lease age, process
liveness or a missing event.

A GC plan SHALL bind an immutable sorted target set and target-set generation,
then atomically close new reservations that intersect any target before its
final reachability census. The final census and per-target delete authorization
SHALL share the same target-level fence generation. A reservation for any
different proof, snapshot, StudyResult, DecisionCase, process, backup or legal
hold whose closure intersects a target SHALL lose the fence compare-and-swap or
force that target out of the plan; closure identity alone SHALL NOT make
intersecting evidence independent.

For each target, GC SHALL persist `planned -> prepared -> deleted` state before
unlinking bytes. The immutable deletion receipt and `prepared -> deleted`
transition SHALL commit atomically in the owner WAL domain. Restart SHALL
distinguish a still-live target, an absent target with matching prepared
evidence, and a mismatched/third state; the last state fails closed for
operator reconciliation. A delete operation SHALL never treat an absent file
as successful without the matching prepared target identity and digest.

#### Scenario: A raw Capture artifact reaches its nominal expiry

- **WHEN** retention evaluation finds a CaptureArtifact past its nominal
  retention period but it remains reachable from a retained DatasetSnapshot or
  StudyResult
- **THEN** garbage collection retains or archives the artifact according to
  policy, records why deletion is blocked, and preserves replay/integrity
  verification for the protected lineage

#### Scenario: Another reference races with an intersecting GC plan

- **WHEN** GC has planned a manifest target and a concurrent DatasetSnapshot or
  StudyResult reservation includes that same target through a different
  evidence closure
- **THEN** the target-level fence admits exactly one side: the reservation
  prevents target preparation or the closed GC target rejects the reservation;
  GC repeats its final census under the same generation and cannot unlink the
  target while the concurrent reference can become formal

#### Scenario: Confirmation delivery exceeds its deadline

- **WHEN** a consumer has acquired a reservation and its confirmation deadline
  passes before the evidence owner receives either a committed or aborted
  receipt
- **THEN** the owner records `reconciliation_required`, continues blocking GC,
  requests consumer status through the Process contract and never treats age,
  process death or missing delivery as proof that the formal reference was not
  committed

#### Scenario: An abandoned reservation is released

- **WHEN** reconciliation receives a `ReferenceAborted` receipt that binds the
  reservation, consumer transaction identity and durable evidence that no
  formal reference committed
- **THEN** the evidence owner releases exactly that reservation idempotently and
  leaves every shared, confirmed, unknown or independently retained closure
  protected

#### Scenario: The runtime crashes around physical deletion

- **WHEN** GC crashes before or after unlinking a prepared target
- **THEN** restart reconciles the durable target identity, digest and state,
  appends or verifies one deletion receipt without double deletion, and blocks
  on an absent or changed target that lacks matching prepared evidence

### Requirement: Data safety SHALL be preserved during migration

Real data SHALL be read-only by default. Tests and migration rehearsals SHALL
use temporary roots. Any approved live probe SHALL be explicitly read-only and
shall not substitute for fixture coverage. Migration and rollback tests SHALL
prove behavior against representative immutable fixtures.

#### Scenario: A migration requires historical artifact processing

- **WHEN** an implementation needs to derive new metadata from historical
  artifacts
- **THEN** it uses an idempotent checkpointed replay or non-destructive shadow
  copy, validates a bounded fixture/sample before cutover, records lineage and
  retains a prior generation or backup snapshot for rollback
