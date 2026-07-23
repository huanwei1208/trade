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

### Requirement: Datasets SHALL own quality, lineage, revisions and point-in-time resolution

Datasets SHALL canonicalize schema, identity, units, timezone, event time,
observed time, available time, revision identity, missingness, duplicates and
source reconciliation. Quality, lineage, revision, catalog and release facts
SHALL have Datasets as their sole business owner. A required missing temporal
clock SHALL fail closed for formal point-in-time resolution.

#### Scenario: A row has no required availability clock

- **WHEN** a formal market-available or installation-observed snapshot requires
  a row's availability or fetched time and the relevant time is absent
- **THEN** snapshot resolution reports an explicit unavailable or
  PIT-not-proven outcome and does not silently treat the row as visible

#### Scenario: Sources disagree during reconciliation

- **WHEN** a DatasetBuild receives conflicting values from its declared Capture
  inputs
- **THEN** the configured reconciliation policy records a QualityReport and
  lineage evidence, chooses a documented canonical outcome only when policy
  permits it, or quarantines the candidate without advancing a release pointer

### Requirement: Catalogs and releases SHALL be projections over immutable products

Catalogs, current pointers and UI projections SHALL be rebuildable projections,
not second fact stores. A DatasetRelease SHALL reference an immutable version or
snapshot, and supersession or withdrawal SHALL create a later release state.

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
