## ADDED Requirements

### Requirement: Architecture implementation SHALL be phased and reversible

Implementation SHALL proceed through independently reviewable child OpenSpec
changes: guardrails/baselines, Platform persistence/events/Bootstrap foundation,
Kernel/contracts, formal PIT/revision semantics, Capture, Datasets, Studies,
Processes, CLI/HTTP/SDK compatibility, package/Web layout, then legacy cleanup.
Every child SHALL use a dedicated worktree, have focused tests, state affected
public contracts, record data safety and define a rollback path. No Context
extraction that emits a context outbox or accepts cross-context commands SHALL
precede the Platform foundation, and no formal DatasetSnapshot/Study migration
SHALL precede the formal PIT/revision gate.

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
and required context artifacts. Restore SHALL validate archive member safety,
manifest integrity and SHA-256 digests before extraction into a staged
temporary root, validate the staged database/artifacts against the manifest,
and only then activate the selected generation. Every restore attempt SHALL
append an audited receipt with actor, source, target, result and explicit
corruption/mismatch state; a failed verification SHALL leave the active root
untouched.

#### Scenario: A backup archive is corrupt or contains an unsafe member

- **WHEN** restore sees a missing manifest entry, SHA-256 mismatch, traversal
  member or incompatible schema capability
- **THEN** restore rejects the archive before activation, records a
  restore-verification-failed receipt with the reason, and preserves the
  previous active database/artifacts without extracting unverified content into
  them

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

#### Scenario: A raw Capture artifact reaches its nominal expiry

- **WHEN** retention evaluation finds a CaptureArtifact past its nominal
  retention period but it remains reachable from a retained DatasetSnapshot or
  StudyResult
- **THEN** garbage collection retains or archives the artifact according to
  policy, records why deletion is blocked, and preserves replay/integrity
  verification for the protected lineage

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
