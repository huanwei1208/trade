## ADDED Requirements

### Requirement: Capture SHALL record external interaction as immutable receipts

Capture SHALL own `SourceManifest`, `CaptureRequest`, `CapturePlan`,
`CaptureRun`, `CaptureArtifact`, `CaptureArtifactRef`, `CaptureGroup` and
`CaptureCheckpoint`. A committed artifact SHALL record source identity, request
identity, mode, received/fetched times, raw content digest, transport result,
cursor or segment identity and retry evidence. Capture SHALL NOT publish a
canonical Dataset or determine data quality.

#### Scenario: A provider returns a successful empty response

- **WHEN** a planned pull, push, stream, import or backfill partition completes
  with a valid empty response
- **THEN** Capture commits an immutable receipt with explicit `empty`
  availability and does not represent the attempt as a missing artifact or a
  successful Dataset

#### Scenario: A transport attempt fails transiently

- **WHEN** a provider returns a classified timeout, rate-limit or transient
  service failure within the SourceManifest retry policy
- **THEN** Capture records the failed attempt, schedules a bounded retry and
  leaves no ambiguous raw artifact or canonical Dataset pointer

### Requirement: Capture admission SHALL be durable across source and credential scope

SourceManifest SHALL declare provider/credential quota scope, request/byte/cost
windows, concurrent capture slots, page/CaptureRun ceilings, Retry-After
precedence, jitter, deadline, stream segment rotation/buffer/checkpoint bounds
and explicit defer/reject policy. Capture SHALL persist a durable admission
reservation/accounting claim before provider interaction so independently
started workers cannot exceed the same source/credential limit. A retry SHALL
persist its retry-after/deadline evidence and a stream SHALL advance a
checkpoint only after its segment receipt is durable.

#### Scenario: Two workers share one provider credential

- **WHEN** two Capture workers submit requests using the same SourceManifest
  credential scope near its configured window or concurrency limit
- **THEN** durable admission accepts only reservations within the shared limit,
  records explicit deferred/rejected outcomes for the remainder, and retains
  Retry-After/deadline/checkpoint evidence across worker restart

### Requirement: SourceManifest SHALL enforce source rights and downstream use

Every Capture request SHALL resolve a versioned immutable `SourceManifest` that
records verified source identity, provenance, license/attribution terms,
retention class, redistribution/export permissions, allowed downstream
processors and regions, credential scope, quota/cost policy, expiry/revocation
state and a policy digest. Capture SHALL reject a request, replay export,
derived use or artifact access that violates the resolved manifest, and SHALL
record the manifest version and policy decision in the Capture receipt. A
rights revocation SHALL create an auditable tombstone or access restriction; it
SHALL NOT overwrite the prior raw receipt or silently permit a previously
disallowed downstream use.

#### Scenario: A source forbids redistribution to a requested processor

- **WHEN** a CaptureArtifact is requested for a Dataset, Study, export or
  processor that is not permitted by its resolved SourceManifest
- **THEN** Capture returns an explicit rights-blocked outcome with the policy
  reference, records no unauthorized delivery or copy, and leaves the raw
  receipt available only to permitted audit/recovery readers

#### Scenario: Source terms are revoked after capture

- **WHEN** the SourceManifest for retained content is revoked or its retention
  deadline expires
- **THEN** Capture appends a rights tombstone/access restriction, emits a
  policy-aware event for protected downstream references, and preserves the
  receipt, digest and revocation reason for audit without deleting an artifact
  still protected by a live retention or legal-hold reference

### Requirement: Rights revocation SHALL propagate through retained lineage

Capture SHALL emit a `RightsRestrictionDeclared` event containing the
SourceManifest policy/version and protected CaptureArtifactRefs when rights
expire or are revoked. A `PropagateRightsRestriction` Process SHALL traverse
CaptureArtifact to DatasetVersion/Snapshot, StudyResult, DecisionCase and
projection lineage, applying the policy-selected `access_restricted`,
`withdrawn`, `stale` or `retained_for_audit_only` state. The Process SHALL
prevent prohibited export, BFF display and downstream processing, record
exceptions such as legal holds, and append a completion receipt. Renewal SHALL
create a later policy/restriction resolution and SHALL NOT erase earlier audit
evidence.

#### Scenario: Rights are revoked after semantic publication

- **WHEN** a SourceManifest revocation affects a retained artifact that has
  already produced a DatasetVersion and StudyResult
- **THEN** propagation restricts or withdraws affected consumers according to
  policy, retains legal-hold evidence, records any unresolved projection, and
  exposes a completion receipt without deleting the historical lineage

### Requirement: Capture SHALL support non-linear artifact consumption

CaptureArtifact references SHALL be immutable and reusable. One artifact MAY
feed multiple DatasetBuilds, one DatasetBuild MAY require multiple artifact
references, CaptureGroups SHALL express a required input set, and stream
segments SHALL be committed as separate immutable artifacts with checkpoint
lineage.

#### Scenario: A Dataset needs three sources

- **WHEN** a DatasetBuild declares Capture A, Capture B and Capture C as
  required inputs
- **THEN** the owning process waits for the declared group state and either
  submits reconciliation with all immutable references or produces an explicit
  partial, expired or unavailable outcome without silently substituting latest
  data

#### Scenario: A stream receives multiple segments

- **WHEN** a stream Capture receives ordered content segments and advances a
  cursor or offset
- **THEN** each segment has an immutable digest and receipt, checkpoint
  progression is auditable, and replay can read committed segments without
  reconnecting to the provider

### Requirement: Capture SHALL preserve temporal identity, corrections and finality

Capture SHALL retain the provider's event, publication, observed, received,
available, revision and finality fields separately with source timezone and
precision/confidence provenance. A missing provider publication or event time
SHALL remain explicitly absent or estimated under a declared policy; Capture
SHALL NOT substitute collector-now as a source publication/event time. Provider
normalization SHALL map correction, retraction, revision and finality identity
to immutable receipt fields and preserve the raw source value required to
reproduce the mapping.

#### Scenario: A news item has no provider publication time

- **WHEN** a provider record has content and a received timestamp but omits its
  publication time
- **THEN** Capture records the received/first-seen time and an explicit absent
  publication-time state, does not invent a publication time, and makes the
  artifact ineligible for a formal Dataset policy that requires publication
  time

#### Scenario: A provider retracts a previously captured record

- **WHEN** a provider emits a correction or retraction linked to a prior
  provider identity
- **THEN** Capture commits a later immutable correction/retraction receipt with
  prior-artifact linkage and finality state, leaving the original raw content
  and receipt addressable for lineage and policy-aware tombstoning

### Requirement: Capture quarantine SHALL remain distinct from delivery DLQ

Capture SHALL quarantine invalid, corrupt, rights-blocked or semantically
unusable source content with a durable artifact/receipt reason and a
no-refetch replay path. Platform Events SHALL own delivery dead letters for a
valid envelope that cannot reach a consumer. An audited redrive SHALL identify
whether it replays a committed artifact, re-delivers an envelope or requests a
new provider interaction; it SHALL NOT implicitly refetch a provider while
replaying a quarantined artifact or a delivery dead letter.

#### Scenario: A malformed payload reaches a Capture worker

- **WHEN** a provider response fails Capture integrity or source-contract
  validation after it has been received
- **THEN** Capture records the payload/diagnostic as quarantined, emits no
  consumable artifact reference, and an operator can retry validation or replay
  the committed bytes without making a provider call

### Requirement: Capture quarantine SHALL control access and revalidation

Capture SHALL create a `QuarantineReceipt` with classification, safe diagnostic
reference, access role/purpose, retention class, validator/policy version,
redaction state and immutable original digest. A quarantined artifact SHALL
transition only to `revalidated`, `tombstoned` or `retained_for_audit` through
an authorized command. Revalidation SHALL append a later receipt/reference
generation that proves the original bytes/digest and changed parser/policy; it
SHALL NOT mutate the original CaptureArtifact or permit restricted raw access.

#### Scenario: A parser policy is corrected after quarantine

- **WHEN** an authorized operator revalidates a quarantined artifact after a
  parser or policy change
- **THEN** Capture creates a new revalidation receipt with validator/policy
  identity, retains the original quarantine evidence, applies access controls
  to raw content and emits a consumable reference only when validation passes

### Requirement: Capture replay and supersession SHALL preserve provenance

Replay SHALL read an existing CaptureArtifact and SHALL NOT contact the
provider. A new observation of corrected provider content SHALL create a new
artifact and explicit supersession link; raw bytes and prior receipts SHALL NOT
be overwritten.

#### Scenario: An operator replays a failed downstream build

- **WHEN** the operator requests replay using a prior CaptureArtifactRef
- **THEN** the replay path resolves the recorded digest and receipt locally,
  records a new replay action and makes zero provider calls

#### Scenario: A provider revision changes prior content

- **WHEN** a later Capture detects content that supersedes a prior request or
  provider revision identity
- **THEN** Capture commits a new artifact, links it to the prior artifact,
  emits `CaptureCommitted` with supersession information and leaves the prior
  artifact addressable for lineage and rollback
