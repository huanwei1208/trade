## ADDED Requirements

### Requirement: Studies SHALL run only from immutable Dataset snapshots

Studies SHALL own `Study`, `Hypothesis`, `StudySpec`, `StudyRun`,
`ValidationReport`, `StudyResult`, `StudyResultRef`, `PromotionReceipt` and
`EvidenceGap`. A formal StudyRun SHALL accept `DatasetSnapshotRef` inputs only.
It SHALL NOT read a provider, CaptureArtifact, raw file, moving latest alias,
current business database state or HTTP request payload directly. A formal
StudyRun SHALL reject a snapshot unless Datasets has marked its declared
point-in-time/revision policy as proven by the formal-PIT-and-revision-semantics
gate, including its immutable canonicalization and quality policy references.

#### Scenario: A study command supplies raw provider content

- **WHEN** a caller attempts to run a formal Study with a provider response,
  CaptureArtifact, raw file path, DataFrame or `latest` dataset selector
- **THEN** Studies rejects the command before execution and reports that an
  immutable DatasetSnapshotRef is required

#### Scenario: A registered study runs from a snapshot

- **WHEN** a registered StudySpec receives declared DatasetSnapshotRefs, a
  deterministic method/seed policy and valid sample eligibility
- **THEN** it records the input references, feature/label definitions,
  walk-forward/placebo/benchmark policy and output identity in an immutable
  StudyResult with a ValidationReport

#### Scenario: A snapshot lacks formal PIT proof

- **WHEN** a caller supplies an immutable DatasetSnapshotRef whose required
  clock, revision mapping, canonicalization policy or quality policy is
  incomplete or unproven
- **THEN** Studies rejects the formal run with an explicit PIT-not-proven or
  policy-lineage reason and does not downgrade the run to a hidden current-data
  query

### Requirement: Formal Study references SHALL reserve their evidence closure

Studies SHALL acquire a durable, finite `EvidenceClosureReservationRef` from
each upstream evidence owner before committing a formal `StudyResultRef`,
`ValidationReport` or `PromotionReceipt`, covering the exact immutable
references and transitive closure it will retain. Studies SHALL then
commit its aggregate, reservation refs and confirmation outbox in one
Studies-owned transaction. Upstream owners SHALL confirm the reservation
idempotently from that outbox, and a replayable reconciliation command SHALL
recover a committed-but-unconfirmed reference. A missed confirmation deadline
SHALL become `reconciliation_required` and remain
protected; the owner SHALL release it only after a transaction-bound
`ReferenceAborted` receipt proves that no formal Study reference committed.
A committed reference SHALL remain protected until explicit owner-authorized
retirement. This protocol SHALL NOT use a cross-Context transaction.

#### Scenario: A StudyResult commit crashes before reservation confirmation

- **WHEN** Studies has committed a StudyResult and its confirmation outbox but
  crashes before Datasets confirms the evidence-closure reservation
- **THEN** replay uses the same result identity and reservation refs to confirm
  protection idempotently; GC continues to treat the closure as reserved and
  no duplicate StudyResult is created

#### Scenario: A reservation cannot be acquired

- **WHEN** an upstream closure is missing, withdrawn, digest-mismatched, already
  fenced for deletion or cannot be durably reserved before its deadline
- **THEN** Studies does not commit the formal result or promotion, records a
  typed evidence-reservation refusal and leaves any acquired reservations for
  bounded owner-managed release

#### Scenario: A worker crashes before the StudyResult commit

- **WHEN** Studies acquires reservations but crashes before its owner-local
  result transaction commits
- **THEN** no formal result becomes visible; Studies recovery emits an
  idempotent ReferenceAborted receipt bound to the failed local transaction
  before upstream release, while an unknown result remains
  reconciliation-required and protected without deleting evidence retained by
  another reference

### Requirement: Studies SHALL express evidence gaps without performing capture

Studies SHALL emit `EvidenceGapDeclared` when a registered input snapshot is
insufficient, unavailable or outside declared coverage, and SHALL NOT import
Capture implementation or call a provider. The owning Process Manager SHALL
convert an accepted gap into Capture, Dataset and rerun commands while
preserving the insufficient-data result.

#### Scenario: A study lacks the declared sample coverage

- **WHEN** a StudyRun cannot meet its preregistered coverage, maturity or
  sample policy from its DatasetSnapshotRef
- **THEN** it completes with `insufficient_data`, emits an EvidenceGap with
  exact missing dimensions and does not silently broaden the sample or fetch
  data

#### Scenario: An evidence gap is later closed

- **WHEN** Datasets releases a snapshot satisfying an accepted EvidenceGap
- **THEN** the CloseEvidenceGap process submits a new Study command with the
  released DatasetSnapshotRef and preserves the prior insufficient-data result
  as historical evidence

### Requirement: Study results SHALL be versioned, validated and revision-aware

Study results SHALL carry snapshot lineage, hypothesis/spec version, method,
validation status and explicit promotion/rejection state. A Dataset revision
that affects referenced lineage SHALL make the result stale or require review;
it SHALL NOT rewrite the existing result.

#### Scenario: An upstream Dataset revision arrives

- **WHEN** a PropagateRevision process finds a StudyResult whose snapshot
  lineage includes a superseded DatasetVersion
- **THEN** Studies marks the result stale with revision evidence and either
  accepts a rerun command or opens an explicit review according to the
  StudySpec policy

#### Scenario: A result is promoted

- **WHEN** a validated StudyResult meets its published promotion criteria
- **THEN** Studies creates a PromotionReceipt referencing the immutable result
  and its DatasetSnapshotRefs; the receipt does not make the result a mutable
  current alias
