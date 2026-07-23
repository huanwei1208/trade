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
