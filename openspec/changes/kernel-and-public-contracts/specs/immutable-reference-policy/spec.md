## ADDED Requirements

### Requirement: Immutable reference identity SHALL preserve owner, type, version and content

An owner-defined immutable reference SHALL contain owner namespace, reference
kind, opaque object identity, explicit version and content digest. Each
business Context SHALL define its own named reference DTO, implementation and
additional invariants. Kernel SHALL define neither a generic reference/policy
module nor Capture, Dataset, Study or Decision Support business references.

#### Scenario: Identical bytes have different business interpretations
- **WHEN** two Context owners use the same content bytes under different schemas or version identities
- **THEN** the content digest may match while the complete immutable references remain distinct

#### Scenario: A later Dataset child defines DatasetSnapshotRef
- **WHEN** formal PIT and revision semantics have passed their prerequisite child
- **THEN** Datasets defines the complete reference in `datasets.contracts` with Dataset-owned schema, clock and snapshot policy fields rather than importing a generic Kernel reference

### Requirement: Formal references SHALL exclude mutable aliases and storage locations

A formal immutable reference SHALL NOT contain or resolve implicitly through
`current`, `latest`, current directory contents, an arbitrary database query,
an unfixed DataFrame, provider response, filesystem path, credential-bearing
URI or private repository identity. Storage location and mutable projection
pointers SHALL remain adapter or projection concerns.

#### Scenario: A legacy Observatory ArtifactRef is inspected
- **WHEN** it contains run identity, SHA-256 and `relative_path`
- **THEN** compatibility code may expose it as a legacy artifact observation but SHALL NOT publish it as a formal CaptureArtifactRef or DatasetVersionRef

#### Scenario: A moving pointer is supplied to a formal build
- **WHEN** a formal DatasetBuild or StudyRun input names `current` or `latest`
- **THEN** the owner rejects it until a committed immutable version is resolved and recorded explicitly

### Requirement: Policy references SHALL identify immutable policy content

An owner-defined `PolicyRef` SHALL identify policy namespace/name, explicit
semantic version and content digest. It SHALL not embed an arbitrary executable
policy body or claim that a policy has been approved. The consuming owner SHALL
own the DTO and validate existence, compatibility and authorization.

#### Scenario: A process receipt cites a retry policy
- **WHEN** a later Platform or Process owner records policy identity
- **THEN** the receipt carries a PolicyRef and the owner verifies that exact version/digest rather than reading a moving configuration alias

### Requirement: Reference construction and wire decoding SHALL fail closed

Reference construction SHALL validate all identity fields before use.
Deserialization SHALL NOT prove that referenced content exists, is authorized,
is quality-assured, is point-in-time correct or has been published. An owner
port SHALL perform those checks and return explicit unavailable, stale,
quarantined or invalid state.

#### Scenario: A syntactically valid reference names missing content
- **WHEN** a reference round-trips successfully but the owner cannot resolve its content
- **THEN** the owner reports unavailable or invalid and does not substitute current content

#### Scenario: A reference has an unsupported version
- **WHEN** a consumer does not support the declared reference or policy version
- **THEN** it rejects the reference with a versioned safe error and no fallback to a moving alias

#### Scenario: Decoded identity is used as proof
- **WHEN** a syntactically valid reference has an unauthorized policy, an unproved PIT clock, an unproved quality state or a one-byte content-digest mismatch
- **THEN** the owner rejects it and decoding success is not converted into existence, authorization, publication, quality or PIT proof

### Requirement: Legacy artifacts SHALL remain explicitly observational

A path-bearing legacy artifact SHALL map only to a
`LegacyArtifactObservation` containing legacy owner/run/artifact identity,
declared digest, relative-location token, closed resolution state and closed
content-verification state. It SHALL NOT implement or inherit a formal
immutable-reference contract. Resolution states SHALL be `unresolved`,
`resolved`, `unavailable` or `unsafe_path`; verification states SHALL be
`not_checked`, `matched` or `mismatched`.
The exact state product SHALL allow `unresolved`, `unavailable` and
`unsafe_path` only with `not_checked`, and `resolved` only with `matched` or
`mismatched`. A pure mapper SHALL NOT produce `matched` or `mismatched`.

Matched/mismatched state SHALL require owner-local
`LegacyArtifactVerificationEvidence` with verifier namespace/version,
`verified_at: UtcInstant`, declared and actual content digests, legacy artifact
identity, owner generation, authorized root identity and stable pre/post file
identity. The verifier SHALL sample `verified_at` only after hashing and the
stable post-hash file/root/generation checks succeed, immediately before
constructing evidence; a clock/read failure emits no matched/mismatched
evidence. The owner verifier SHALL use root-relative no-follow traversal, reject
symlinks and non-regular files, prove root containment, and compare pre/post
identity, size and generation around hashing. Symlink replacement, TOCTOU
change, unsupported filesystem proof or generation change SHALL fail closed
without matched evidence. `verified_at` is verifier observation time only; it
is not event, publication, observed-at-source, received, available or PIT time.
`matched` proves only that the stable bytes read by that verifier before
`verified_at` match the declaration; it proves no authorization, publication,
quality, PIT or later-file state.

#### Scenario: A legacy path attempts traversal
- **WHEN** a legacy artifact contains an absolute path, traversal segment or credential-bearing URI
- **THEN** the mapper reports `unsafe_path`, retains no usable storage location in a formal contract and performs no filesystem access

#### Scenario: Legacy content differs from its declaration
- **WHEN** an owner fixture verifies bytes that differ by one byte from the declared digest
- **THEN** the observation reports `mismatched` and cannot be promoted to a Capture or Dataset reference

#### Scenario: A pure mapper sees a syntactically safe relative path
- **WHEN** no owner verifier has opened and hashed the artifact
- **THEN** the observation remains unresolved/not-checked and cannot claim matched content

#### Scenario: A path changes while content is hashed
- **WHEN** a symlink, file identity, size or owner generation changes between the verifier's pre/post checks
- **THEN** verification fails closed as unavailable or unsafe-path and emits no matched evidence

#### Scenario: Verification time is sampled
- **WHEN** hashing and stable post-hash file/root/generation checks succeed
- **THEN** the verifier samples one canonical UtcInstant before evidence construction, labels it only as verifier observation time and emits no evidence if that sample fails
