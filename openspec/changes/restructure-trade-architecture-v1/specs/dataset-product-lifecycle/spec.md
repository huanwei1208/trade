## ADDED Requirements

### Requirement: Datasets SHALL produce immutable data products

Datasets SHALL own `DatasetBuild`, `DatasetVersion`, `DatasetVersionRef`,
`DatasetSnapshot`, `DatasetSnapshotRef`, `DatasetRelease`, `QualityReport` and
`Lineage`. A formal DatasetBuild SHALL consume only immutable
`CaptureArtifactRef`, `DatasetVersionRef` or `DatasetSnapshotRef` inputs. It
SHALL NOT consume a moving latest pointer, an arbitrary DB query, a current
directory listing, an unpinned DataFrame or a provider response.

#### Scenario: A formal build is requested with a current alias

- **WHEN** a caller submits `latest`, a filesystem path, an arbitrary query
  result or an unpinned DataFrame as a formal DatasetBuild input
- **THEN** Datasets rejects the request before build execution with a stable
  input-identity error and records no DatasetVersion

#### Scenario: A build has immutable Capture inputs

- **WHEN** a DatasetBuild receives a declared ordered set of
  CaptureArtifactRefs and a schema/quality policy
- **THEN** it records the complete lineage, produces a new immutable candidate
  DatasetVersion or explicit failure/quarantine result, and never mutates an
  existing version in place

### Requirement: Formal Dataset references SHALL reserve their evidence closure

Datasets SHALL acquire durable, finite `EvidenceClosureReservationRef` values
before it commits a formal `DatasetVersionRef`, `DatasetSnapshotRef` or
`DatasetRelease`, covering
every upstream immutable reference and its transitive evidence closure.
Datasets-owned references SHALL be
reserved and confirmed in the same owner-local transaction; Capture-owned
closures SHALL be pre-reserved and then confirmed through the Datasets
transaction's replayable outbox. A committed-but-unconfirmed reservation SHALL
remain protected and reconcile idempotently. A confirmation-deadline breach
SHALL become `reconciliation_required` without releasing protection.
Capture MAY release an uncommitted reservation only after an idempotent
`ReferenceAborted` receipt binds the Datasets transaction identity and proves
that no Dataset reference committed. No part of this protocol SHALL require a
cross-Context transaction.

#### Scenario: A DatasetVersion commit crashes before Capture confirmation

- **WHEN** Datasets commits a DatasetVersion, its Capture reservation refs and
  confirmation outbox but crashes before Capture confirms the reservations
- **THEN** replay confirms the exact refs idempotently, the Capture closure
  remains protected from GC, and no duplicate DatasetVersion is created

#### Scenario: A Snapshot references a DatasetVersion under a deletion fence

- **WHEN** Datasets attempts to reserve a DatasetVersion closure whose target
  set is already closed by a generation-fenced GC plan
- **THEN** exactly one side wins the target-level fence; the Snapshot is either
  durably protected before commit or rejected with a typed reservation refusal,
  and the target is never both referenced and deleted

#### Scenario: A build crashes before its DatasetVersion transaction

- **WHEN** a build acquires upstream reservations but crashes before committing
  the DatasetVersion
- **THEN** no formal reference becomes visible; recovery emits a
  transaction-bound ReferenceAborted receipt before an upstream owner releases
  that reservation, and an unknown outcome remains reconciliation-required and
  protected without affecting other retained references

### Requirement: Datasets SHALL own quality, lineage, revisions and point-in-time resolution

Datasets SHALL canonicalize schema, identity, units, timezone, event time,
observed time, available time, revision identity, missingness, duplicates and
source reconciliation. Quality, lineage, revision, catalog and release facts
SHALL have Datasets as their sole business owner. A formal DatasetVersion and
DatasetSnapshot SHALL record immutable `CanonicalizationPolicyRef` and
`QualityPolicyRef` values, each including policy/version digest and explicit
unit, timezone, precision, duplicate, missingness and reconciliation
semantics. `DatasetVersionRef` SHALL include canonicalization-policy,
quality-policy, transform-code/environment, physical-layout and ordered-input
lineage identities. `DatasetSnapshotRef` SHALL include constituent-version,
knowledge-mode/effective-cut, revision/retraction-mapping,
clock-confidence/eligibility and snapshot-content identities. A required
missing temporal clock SHALL fail closed for formal point-in-time resolution.

The formal PIT child SHALL publish one canonical clock enum and a versioned
knowledge-mode eligibility matrix covering event, publication, available,
received, fetched, observed, first-seen and revision clocks. It SHALL declare
whether every source field is a distinct clock or a documented alias and SHALL
bind timezone, precision/confidence and fallback prohibition. A clock may not
be substituted merely because another collector clock exists.

#### Scenario: A row has no required availability clock

- **WHEN** a formal market-available or installation-observed snapshot requires
  a row's clock selected by the canonical knowledge-mode eligibility matrix and
  that required clock is absent
- **THEN** snapshot resolution reports an explicit unavailable or
  PIT-not-proven outcome and does not silently treat the row as visible

#### Scenario: Sources disagree during reconciliation

- **WHEN** a DatasetBuild receives conflicting values from its declared Capture
  inputs
- **THEN** the configured reconciliation policy records a QualityReport and
  lineage evidence, chooses a documented canonical outcome only when policy
  permits it, or quarantines the candidate without advancing a release pointer

#### Scenario: Multi-source identities or finality conflict

- **WHEN** two source-local identities collide after canonicalization, sources
  disagree on finality, or simultaneous supersession chains target the same
  logical observation
- **THEN** Datasets preserves every candidate source/revision/finality identity
  in lineage, applies the pinned reconciliation policy deterministically, and
  quarantines or returns an explicit conflict when that policy cannot prove one
  outcome; it never collapses the candidates by arrival order or moving latest

### Requirement: Quality and source finality SHALL have a total publication disposition

Datasets SHALL evaluate quality disposition `passed`, `warned` or `blocked`
independently from source finality `provisional`, `final` or `retracted`.
Quality policy SHALL define all nine combinations; an omitted pair SHALL fail
closed. `passed+final` MAY be eligible for formal publication after all other
PIT, rights and integrity gates pass. `warned+final` MAY be published only when
the pinned policy explicitly authorizes the warning class and the release keeps
that warning visible. `blocked+final` SHALL NOT publish.

Both `passed+provisional` and `warned+provisional` SHALL retain provisional
state and MAY produce only an explicitly non-formal candidate/provisional
product; neither may be relabelled final because quality passed. A
`blocked+provisional` product SHALL remain blocked. Any `retracted`
combination SHALL prevent a new formal release and SHALL withdraw, supersede or
restrict an affected release through a later immutable state according to
policy, without deleting the prior version. Capture quarantine and artifact
integrity failure remain separate fail-closed lifecycle states and cannot be
converted to a quality/finality pair that publishes.

#### Scenario: A quality-passed source record remains provisional

- **WHEN** canonicalization and quality checks pass but one required source
  input is still provisional
- **THEN** Datasets preserves `passed+provisional`, exposes its provisional
  reason and next-finality evidence, and does not issue a formal release or
  formal Study-eligible DatasetSnapshotRef

#### Scenario: A previously released source record is retracted

- **WHEN** a later Capture receipt marks a referenced observation retracted,
  regardless of its prior quality disposition
- **THEN** Datasets records the corresponding retracted disposition, creates a
  later withdrawal/supersession state, emits revision evidence for downstream
  propagation and leaves the prior immutable version auditable

### Requirement: Formal PIT and revision semantics SHALL be proven before formal use

Datasets SHALL resolve a formal DatasetSnapshot's declared knowledge policy
using a tested revision
mapping. `as_known` SHALL select only facts visible at the effective knowledge
cut; `latest_restated` SHALL create a distinct, explicitly non-PIT
transformation using mapped revisions/retractions and SHALL NOT merely label an
`as_known` selection. Missing required event, publication, available, received,
fetched, observed, first-seen or revision clocks selected by the canonical
eligibility matrix SHALL return explicit `PIT_NOT_PROVEN` or unavailable
outcomes. The formal-PIT-and-revision-semantics child change SHALL complete its
golden fixtures and release gate before any formal DatasetSnapshotRef or
StudyRun migration.

#### Scenario: A later restatement changes an earlier value

- **WHEN** a snapshot is resolved with `latest_restated` and a later captured
  revision maps to an earlier logical observation
- **THEN** Datasets returns a new immutable snapshot with the applied revision
  mapping and policy digest, while an `as_known` snapshot at a prior knowledge
  cut preserves the earlier visible version without mutation

#### Scenario: A formal request has an absent required clock

- **WHEN** a Dataset policy requires publication, availability or revision time
  and one selected input lacks that time or an adequate confidence level
- **THEN** Datasets rejects formal snapshot resolution with an explicit
  reason, does not publish a formal release, and does not make the row visible
  solely because it has a later collector timestamp

### Requirement: Dataset physical layout and query execution SHALL be budgeted

Every formal DatasetVersion SHALL declare its physical layout policy, including
partitioning, sort/order, file and row-group constraints, compression and
index/projection strategy where applicable. Dataset query handles SHALL carry a
`QueryBudget` with bounded files/partitions/rows/bytes, wall time, memory and
result size; SQLite, Parquet and DuckDB adapters SHALL validate their relevant
index, lock, scan and plan constraints. Exceeding a budget SHALL return an
explicit bounded/deferred/unavailable result rather than performing an
unbounded scan or silently changing query semantics.

#### Scenario: A broad query would scan beyond its declared budget

- **WHEN** a query selector resolves to more partitions, bytes or wall time
  than the Dataset query budget permits
- **THEN** the query handle rejects, pages or defers it with a stable reason
  and observed budget evidence, without reading arbitrary parquet files or
  bypassing the owner projection

### Requirement: Catalogs and releases SHALL be projections over immutable products

Catalogs, current pointers and UI projections SHALL be rebuildable projections,
not second fact stores. A DatasetRelease SHALL reference an immutable version or
snapshot, and supersession or withdrawal SHALL create a later release state.
The release bridge SHALL have one Datasets authority: a generation-stamped
release record drives any legacy pointer materialization journal, startup
reconciliation and dual-reader equality comparison. Legacy pointers SHALL NOT
independently advance a Dataset release.

#### Scenario: A catalog is lost or stale

- **WHEN** a catalog projection is missing, corrupt or behind an immutable
  DatasetRelease
- **THEN** `RebuildProjection` regenerates it from authoritative version,
  snapshot, release and lineage records without re-fetching providers or
  rewriting the immutable product

#### Scenario: A released Dataset is revised

- **WHEN** a new DatasetVersion is built from a superseding CaptureArtifact
- **THEN** Datasets creates a new release or candidate under explicit policy,
  preserves the earlier version and emits a revision-aware `DatasetReleased` or
  `DatasetWithdrawn` event for downstream propagation

### Requirement: Durable Dataset migration SHALL prove reconciliation equivalence

Each Dataset migration/cutover SHALL produce an immutable
`MigrationReconciliationManifest` that compares the bounded source and target
census, normalized row identities/values, required clocks, policy digests,
quality states, lineage refs, artifact digests and release/pointer generations.
The manifest SHALL enumerate allowed differences with an owner-approved reason
and threshold; an unexplained mismatch SHALL block cutover and retain the prior
compatible reader/pointer.

#### Scenario: A legacy release is cut over to a new Dataset repository

- **WHEN** a child change proposes making a new Dataset release authoritative
- **THEN** it persists a reconciliation manifest, passes declared row/lineage/
  clock/artifact thresholds, validates both readers against the same generation
  and can restore the verified prior pointer without deleting the new version

### Requirement: Semantic derived datasets SHALL retain derivation provenance

Datasets SHALL create an immutable `DerivationReceipt` when source text or
other Capture content is canonicalized into reusable semantic data, linked to
the input CaptureArtifactRefs or DatasetVersionRefs. The receipt SHALL identify
the model/provider/version, prompt/template, parser, environment/dependency
identity, parameter/seed policy, response/output digest, cost/usage evidence,
policy authorization and any human correction. It SHALL bind an immutable
semantic schema policy for output schema/version, embedding space/dimension,
tokenizer/chunking, normalization, entity taxonomy and compatibility range.
For deterministic local derivations it SHALL include executable transform/image
and dependency-lock digests, normalized input manifest and rerun-equality
evidence. For provider/nondeterministic derivations it SHALL include permitted
archival response/output evidence, model release, normalized request/prompt
identity, parameter/seed policy and explicit
`replay_verifiable_not_recomputable` state where exact recomputation is
unavailable. Human correction SHALL append a new correction receipt/version
with reviewer role, payload digest and justification rather than overwrite a
prior model or reviewer output. Fold-local semantic transforms remain
Study-local and are not published as derived datasets.

#### Scenario: A sentiment source is derived from captured news

- **WHEN** a Dataset build produces reusable sentiment or embedding fields from
  retained Capture artifacts
- **THEN** the published DatasetVersion includes its DerivationReceipt lineage
  and policy references, and a later reviewer correction produces a new
  versioned result linked to the prior output instead of mutating it in place

### Requirement: Formal and compatibility artifact reads SHALL verify integrity

Every formal or compatibility artifact reader SHALL resolve a manifest-backed
`ArtifactRef` and verify its recorded digest before parsing a raw receipt,
primary, shadow, canonical, reconciliation, revision, derived or result
artifact.
An explicitly non-formal diagnostic mode MAY expose only an
`integrity_unverified` state with no formal publication, quality conclusion or
Study eligibility. The Dataset and interface child changes SHALL include tamper
fixtures for each retained artifact class and legacy manifest migration.

#### Scenario: A compatibility reader finds a tampered revision artifact

- **WHEN** a compatibility query resolves a revision or reconciliation artifact
  whose bytes do not match its manifest-backed ArtifactRef digest
- **THEN** the reader rejects formal use, returns an integrity-failed or
  integrity-unverified state according to its mode, and preserves the digest
  mismatch evidence without substituting a different artifact
