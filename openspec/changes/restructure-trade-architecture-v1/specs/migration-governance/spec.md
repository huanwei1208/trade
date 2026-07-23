## ADDED Requirements

### Requirement: Architecture implementation SHALL be phased and reversible

Implementation SHALL proceed through independently reviewable child OpenSpec
changes: guardrails/baselines, Kernel/contracts, Capture, Datasets, Studies,
Processes/Platform, CLI/HTTP/SDK compatibility, package/Web layout, then
legacy cleanup. Every child SHALL use a dedicated worktree, have focused tests,
state affected public contracts, record data safety and define a rollback path.

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
