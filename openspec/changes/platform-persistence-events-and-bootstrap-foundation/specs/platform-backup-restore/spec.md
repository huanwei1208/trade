## ADDED Requirements

### Requirement: Backup creation SHALL certify a bounded immutable generation

Platform Backup SHALL create a `BackupManifest` before a snapshot is eligible
for restore or remote publication. The manifest SHALL contain schema/version,
backup/snapshot identity, source generation, creation time, database schema
capability range, required Context/artifact set, archive SHA-256 and size, and a
deterministically ordered member list. Each member SHALL contain normalized
relative path, kind, size, SHA-256, required/optional state and owner namespace.

Backup creation SHALL use an explicit consistency strategy for each included
database or mutable artifact: SQLite online backup or an equivalent
read-transaction snapshot for the database, and an immutable committed
generation/ref for external artifacts. It SHALL not recursively tar a live data
root while writers can mutate included files. The manifest and certification
receipt SHALL be written atomically after all staged bytes are hashed. A failed
or partial snapshot SHALL remain `preparing`/`failed`, SHALL not be published as
restorable and SHALL preserve bounded diagnostics.

Hash equality alone SHALL NOT make a backup trusted because an attacker could
replace both archive and manifest. `BackupCertification` SHALL bind the
canonical bounded manifest digest, archive digest/size, backup/source generation,
schema capability and creation time to an independently configured
`BackupTrustPolicyRef`, signing key ID/version, signature algorithm and detached
signature. The trust policy SHALL be outside the archive and SHALL define
approved algorithms, trusted key versions, validity interval, revocation state,
backup/source namespace and allowed restore environment. Private key material
SHALL remain behind a signing port and SHALL never enter manifests, logs,
receipts or archives. A signing outage SHALL leave the backup hashed but
`uncertified`; it SHALL not silently fall back to digest-only certification.

#### Scenario: SQLite receives writes during backup
- **WHEN** a backup starts while compatible writers continue
- **THEN** the archive contains one database snapshot generation produced by the reviewed SQLite snapshot mechanism rather than a mixture of copied database, WAL and SHM moments

#### Scenario: An artifact changes during staging
- **WHEN** a mutable path identity, size or digest changes between selection and staged verification
- **THEN** certification fails and the manifest is not marked restorable

#### Scenario: Remote publication is partial
- **WHEN** the archive uploads but the manifest upload or remote digest verification fails
- **THEN** the backup remains not-published with an explicit retryable outcome and is never selected as the latest verified remote generation

#### Scenario: Both archive and manifest are replaced
- **WHEN** archive bytes and their matching digest manifest are supplied without a valid detached signature from the configured trust policy
- **THEN** Platform reports `untrusted_certification`, excludes the backup from automatic restore and extracts no member

#### Scenario: A signing key is revoked
- **WHEN** certification refers to a key version revoked for the backup creation interval or target environment
- **THEN** verification fails closed even when all member and archive digests match

### Requirement: RestoreOperation SHALL verify before extraction or activation

Every restore SHALL create an append-only `RestoreOperation` owned by Platform
Backup with identity, trusted actor, source backup, prior and target generation,
correlation/causation, migration capability decision, state, current step,
deadline, manifest/archive digests, safe reason/error and audit timestamps.

Before extracting a member, restore SHALL parse and bound the manifest and archive
directory, reject absolute paths, traversal, links, devices, FIFOs, sockets,
duplicate normalized paths, undeclared members, missing required members,
case/Unicode-normalization collisions, per-member or aggregate size/count excess,
unsupported compression, digest/size mismatch and incompatible schema capability.
It SHALL extract only declared regular files/directories into a no-follow staged
root on the target filesystem, then re-hash and validate the staged database and
required artifacts. It SHALL never call an unrestricted archive `extractall`.

Before parsing archive members, restore SHALL verify the detached certification
against the current trusted policy/key registry and the intended target
environment. Parsing and extraction SHALL be streaming and use checked integer
counters. V1 hard refusal ceilings SHALL be 64 MiB encoded canonical manifest,
100,000 members, 2 TiB archive bytes, 2 TiB declared and actual extracted bytes,
4,096 UTF-8 bytes/128 normalized segments per path and 100:1 aggregate actual
extracted-to-archive byte ratio; implementation `CapacityProfile` values SHALL
be lower finite values established by fixture evidence. Restore SHALL reject an
unknown compressed size, counter overflow, archive read beyond the encoded-byte
bound, actual member/aggregate bytes beyond declarations or policy, and any
expansion-ratio breach at the first observed byte.

The selected `RestoreCapacityProfile` SHALL also bound verifier peak RSS,
verification scratch/spill bytes, archive pass count, bytes reread/hashed and total
verification deadline. Duplicate/collision/member indexing SHALL use a deterministic
bounded in-memory index and spill to the reserved staged filesystem before its memory
budget is crossed. Spill bytes SHALL be included in disk preflight and continuous
reserve accounting. The verifier SHALL reject before exceeding memory, scratch,
archive-pass, reread-byte or deadline bounds; a nominally streaming parser SHALL not
retain all member metadata without a profile bound or repeatedly rescan a multi-
terabyte archive.

Before creating the staged root, restore SHALL reserve or prove available space
for the profile's bounded archive download when needed, maximum staged
extraction, verification scratch, journal/WAL growth and preserved prior-
generation rollback margin, plus an explicit nonzero safety reserve. It SHALL
recheck available and consumed bytes during streaming extraction and stop
without activation when the reserve would be crossed. Sparse-file logical size
and allocated size SHALL both be bounded; quotas and filesystem errors SHALL
remain explicit unavailable/verification outcomes.

The core state path SHALL be:
`prepared -> staged_verified -> writers_fenced -> activated ->
health_verified -> committed`.
Failure/recovery states SHALL be `verification_failed`, `fence_failed`,
`activation_incomplete`, `health_failed`, `rollback_pending`, `rolled_back` and
`failed`. Only `committed`, `verification_failed`, `rolled_back` and `failed`
are terminal. Every transition SHALL be durable and idempotent.

#### Scenario: The archive contains traversal
- **WHEN** an archive member normalizes outside the staged root or is a link/device
- **THEN** restore records `verification_failed` before extraction and the active generation remains unchanged

#### Scenario: A declared member has another digest
- **WHEN** staged bytes do not match the manifest SHA-256 or size
- **THEN** restore rejects the generation, preserves mismatch evidence and exposes no restored reader

#### Scenario: Compressed bytes expand beyond policy
- **WHEN** actual extracted bytes exceed a declared member/aggregate bound or the 100:1 hard expansion ceiling while streaming
- **THEN** extraction stops, partial staging remains non-authoritative, restore records `verification_failed` and no writer is fenced

#### Scenario: Disk reserve becomes insufficient
- **WHEN** preflight or an in-progress checked extraction cannot preserve staging, verification, journal/WAL, prior-generation rollback and safety-reserve bytes
- **THEN** restore stops with an explicit resource-unavailable outcome before activation and does not delete the prior generation to create space

#### Scenario: Directory verification exceeds its working-set profile
- **WHEN** duplicate/collision/member validation would exceed verifier RSS, spill, archive-pass, reread-byte or deadline bounds
- **THEN** verification stops before extraction or fencing with an explicit resource-unavailable result and retains bounded diagnostics rather than rescanning or growing memory without limit

#### Scenario: Restore restarts after staged verification
- **WHEN** the process crashes with a durable `staged_verified` operation
- **THEN** reconciliation revalidates the staged identity and resumes fencing without re-downloading or activating unverified bytes

### Requirement: Activation SHALL be one fenced generation compare-and-swap

After staged verification, Platform Backup SHALL request the sole Platform
Persistence `GenerationActivationCapability`. That capability SHALL acquire one
database-scoped activation lease, close new writer admission, acquire/revoke the
immutable required-owner set in ascending canonical owner-namespace order, drain
or durably retain each writer under one finite deadline and compare-and-swap the
activation journal from expected prior generation to verified target. Platform
Backup SHALL not write the journal or acquire owner writer leases directly.
Runtime readers/writers SHALL rebind only to the journal-selected generation and
only after schema capability, repository probes and required artifact/reference
checks pass.

Activation SHALL never expose two writable generations. A crash before journal
commit leaves the prior generation active; a crash after journal commit is
reconciled from the journal and operation state. A bounded health window SHALL
either move to `health_verified`/`committed` or activate the preserved prior
generation and record `rolled_back`. Writer fences SHALL not reopen merely
because an HTTP/CLI observation timed out. Acquisition SHALL follow the
Persistence canonical order and release in reverse order. Admission SHALL remain
closed and the global activation lease SHALL remain held until either target or
rolled-back prior generation is rebound and readiness-verified.

Before requesting activation, Platform Backup SHALL persist and supply the exact
`GenerationReadinessEvidence` for the target and a current
`RollbackCandidateReceipt` for the prior generation. Both SHALL bind owner/probe/
artifact/capability digests, binary/config generation and activation attempt. A
missing, changed, expired or unreadable readiness/rollback receipt SHALL fail before
fencing. Platform Backup SHALL consume activation-authority-unavailable/inconsistent
outcomes without selecting a directory or writing the activation journal itself.

#### Scenario: Activation loses power before compare-and-swap
- **WHEN** writers are fenced but the activation journal does not contain the target commit
- **THEN** restart retains or restores the prior generation and resumes/rolls back the operation without selecting the staged root by directory presence

#### Scenario: Activation commits but runtime rebind fails
- **WHEN** the journal points to the target but required repository or artifact health fails
- **THEN** the operation enters rollback, compare-and-swaps back to the preserved prior generation and reopens admission only after prior-generation readiness

#### Scenario: A stale runtime writes after restore
- **WHEN** a runtime holding the pre-restore fence attempts a transaction after target activation
- **THEN** the transaction is rejected and cannot mutate either generation

#### Scenario: Another activation starts during restore
- **WHEN** migration or another restore attempts activation while the database-scoped activation lease is held
- **THEN** it receives a bounded conflict/unavailable receipt and cannot acquire owner leases or append a competing journal generation

#### Scenario: Target readiness was produced by another probe generation
- **WHEN** staged bytes are valid but the target readiness evidence does not match the current owner set, probe set, binary/config generation or activation attempt
- **THEN** restore remains staged, fences no writer and requires a new readiness verification

### Requirement: Backup and restore evidence SHALL be immutable and operator-visible

Platform SHALL store immutable backup certification, remote publication,
restore transition, activation, health and rollback receipts. An authorized
operator query SHALL distinguish preparing, verified, published, corrupt,
incompatible, restoring, active, rolled-back and unavailable states without
reading archive bytes. It SHALL expose manifest/archive digests, generation,
capability range, trust-policy/signing-key identity and verification status,
bounded member/count/declared/actual/compressed size and expansion/disk-reserve
summary, current state/step, last safe failure, timestamps and permitted control
actions.

Logs, metrics and public errors SHALL not expose credentials, service-account
paths, archive contents or arbitrary exception text. Remote drivers SHALL have
finite timeout/retry/cost bounds and SHALL use staging plus digest verification;
remote availability SHALL not be represented as local backup validity.

Trust-policy fixtures SHALL cover expired and not-yet-valid keys, unsupported or
downgraded algorithms, unavailable policy registry and policy-generation
substitution in addition to revoked and wrong-environment keys. Every such failure
SHALL occur before archive-directory parsing or extraction.

#### Scenario: A corrupt backup is listed
- **WHEN** certification or later integrity verification detects corruption
- **THEN** the query reports `corrupt` with safe digest/generation evidence and excludes that backup from automatic restore selection

#### Scenario: A restore action is queried
- **WHEN** an operator reads a non-terminal restore operation
- **THEN** the query has no side effect and returns the exact current step, retained generation/fence state and allowed recovery controls

#### Scenario: A remote credential error occurs
- **WHEN** upload/download authentication fails
- **THEN** Platform reports a stable unavailable reason and safe driver identity without returning the key path, token or raw response

### Requirement: Legacy backup commands SHALL remain compatibility surfaces

Existing backup CLI, function and HTTP contracts SHALL remain compatible until
the interface compatibility child selects Platform Backup. This includes
`trade backup create|push|restore|list`, existing function signatures and current
HTTP backup status. The implementation SHALL not mark the current
`scripts.backup.restore_backup_snapshot` extraction result as a verified
`RestoreOperation`; the legacy path remains explicitly uncertified.

The first Platform Backup implementation SHALL run side-by-side on temporary
roots, generate independently verifiable manifests and require an explicit
feature/capability selection. It SHALL not activate real data by default.
Legacy retirement requires command/API snapshots, corrupt/unsafe archive
fixtures, crash-at-every-state reconciliation, a successful prior-generation
rollback and the minimum compatibility window.

#### Scenario: The legacy restore command is still selected
- **WHEN** the Platform restore capability is disabled or not ready
- **THEN** the current command behavior remains compatible and status identifies the result as legacy/uncertified rather than fabricating staged verification

#### Scenario: Platform restore is piloted
- **WHEN** an authorized test selects the new path
- **THEN** it operates only on a temporary fixture root and does not overwrite or activate the repository's real data root

#### Scenario: Compatibility comparison fails
- **WHEN** legacy command/API snapshots or restored fixture checks differ unexpectedly
- **THEN** cutover is cancelled, the legacy selection stays active and all verified staging evidence is retained for diagnosis
