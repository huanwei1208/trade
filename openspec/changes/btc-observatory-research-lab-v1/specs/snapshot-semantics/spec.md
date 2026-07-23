## ADDED Requirements

### Requirement: Rebuildable Snapshot Catalog projected from immutable facts
The system SHALL maintain a Snapshot Catalog that is a versioned projection of the
existing immutable manifests, `btc_current.json`, and publish/rollback audits, and
SHALL be able to fully rebuild the Catalog from those immutable facts. The Catalog
SHALL NOT be a second source of truth and SHALL carry a `catalog_schema_version`
and a source fingerprint. Read paths SHALL only verify the Catalog fingerprint and
SHALL NOT build, migrate, or write the Catalog while servicing a GET/SDK read.

#### Scenario: Deterministic full rebuild
- **WHEN** the Catalog is rebuilt twice from the same immutable manifests and audits
- **THEN** both rebuilds produce byte-identical projection content hashes

#### Scenario: Catalog lost then rebuilt
- **WHEN** the Catalog projection is deleted and rebuilt from manifests and audits
- **THEN** the resolved Formal, Evaluated Candidate, Latest Observed, and Latest Staged references match the pre-deletion values

#### Scenario: Stale Catalog during a read
- **WHEN** a GET/SDK read observes that the Catalog source fingerprint no longer matches the underlying manifests
- **THEN** the read returns `CATALOG_STALE` and does not update the projection in the read path

### Requirement: Current and Candidate are lifecycle positions, not quality grades
The system SHALL treat Published Current, Latest Staged, and Evaluated Candidate
as lifecycle positions distinct from quality. Product copy SHALL use "Candidate"
to mean Evaluated Candidate, and any view needing Latest Staged or the most recent
ready candidate SHALL use its full explicit name.

#### Scenario: Fresh candidate but stale current
- **WHEN** the Evaluated Candidate watermark is later than the Published Current watermark
- **THEN** the system reports both watermarks and never presents the Candidate as Published

#### Scenario: Good-quality candidate held unpublished
- **WHEN** a Candidate is quality-assured but blocked from publication by long-run evidence insufficiency
- **THEN** the Candidate quality state and the publication blocker are reported separately

### Requirement: Read-side state is expressed on orthogonal axes
The system SHALL expose acquisition, quality, lifecycle, and research states on
separate axes plus independent freshness and compatibility dimensions, and SHALL
NOT collapse them into a single readiness value. These projections SHALL preserve
the original manifest value and a `mapping_policy_version`, SHALL NOT write back to
`data_readiness`, and SHALL NOT relax any publish gate.

#### Scenario: Certified-at-publish preserved under later incompatibility
- **WHEN** current code re-evaluation marks a published release as replay-mismatch
- **THEN** the historical certification is preserved and the mismatch is reported only as `compatibility_state`

#### Scenario: Per-date quarantine within a degraded run
- **WHEN** a run is degraded and contains assured, quarantined, and missing dates
- **THEN** quarantine is reported per date and is not treated as a mutually exclusive run quality state

#### Scenario: Manifest missing maps to unknown, not ready
- **WHEN** a run manifest is missing or its version is unknown
- **THEN** quality state is `unknown` and the system does not infer `ready`

### Requirement: Purpose fitness is derived from facts, not guessed by the frontend
The system SHALL compute purpose fitness for manual_observation,
exploratory_research, formal_system_consumption, strict_research, and
automated_decision from explicit policy, and SHALL return `allowed`, `status`,
`reason_codes`, and `evidence_refs` rather than a bare boolean. Purpose fitness
SHALL be unidirectionally derived and SHALL NOT write back to `data_readiness`,
release, or research lifecycle.

#### Scenario: Formal consumption requires a formal baseline
- **WHEN** only a degraded candidate exists and no active formal release is resolvable
- **THEN** formal_system_consumption is not allowed and strict_research is not allowed, each with explicit reason codes

#### Scenario: Automated decision stays closed by default
- **WHEN** data exists and research is validated
- **THEN** automated_decision remains not allowed unless independently authorized

### Requirement: Semantic channels resolve on three orthogonal dimensions
The system SHALL resolve snapshots along a lifecycle channel
(`observed` | `evaluated_candidate` | `formal` | exact run/release), a knowledge
cut (`latest` | `knowledge_as_of=T`), and a revision policy
(`as_known` | `latest_restated`). Known-at and latest-restated SHALL NOT be
disguised as channels.

#### Scenario: Latest Observed eligibility
- **WHEN** a run has a verifiable primary canonical artifact, at least one final bar, and no D0 identity/integrity blocker
- **THEN** it is eligible as Latest Observed even if D1-D4 warnings, quarantine, or degraded readiness are present, which remain continuously visible

#### Scenario: Latest Observed ordering does not regress to older as-of
- **WHEN** an older as-of backfill run is staged after a newer market observation
- **THEN** Latest Observed orders by canonical market watermark, effective as-of, capture completed-at, then run_id, and does not let the backfill preempt the newer observation

#### Scenario: Evaluated Candidate does not regress on poor latest evaluation
- **WHEN** the most recently evaluated candidate is invalid or rendering-blocked
- **THEN** the context still returns that candidate with error evidence, its series does not enter any composite layer, and the response returns `QUALITY_BLOCKED` or `CHANNEL_UNAVAILABLE` without falling back to an older ready run

#### Scenario: Formal Baseline resolves from the publication ledger
- **WHEN** resolving `formal` at `latest`
- **THEN** the active release is resolved from the publication/rollback ledger and any `btc_current.json` pointer is used only as an accelerator that must agree with the release receipt, manifest, and artifact hash

#### Scenario: No qualifying run for a channel
- **WHEN** no run qualifies for a requested channel
- **THEN** the channel returns `CHANNEL_UNAVAILABLE` with reason codes

### Requirement: Legacy timestamp adapter orders deterministically without mtime
The system SHALL use a schema-versioned adapter to derive ordering timestamps for
manifests that lack `staged_at`, `assurance_completed_at`, and
`capture_completed_at`, coalescing to `manifest.created_at` only for tie-breaks and
then `run_id`. The adapter SHALL return `time_provenance`, `time_precision`, and
`LEGACY_TIME_UNPROVEN`, and SHALL NEVER read filesystem mtime.

#### Scenario: Legacy manifest ordering
- **WHEN** two legacy manifests lack precise stage times
- **THEN** ordering uses each selector's business key, then `created_at`, then `run_id`, and the response carries `LEGACY_TIME_UNPROVEN`

#### Scenario: Legacy time never proven from mtime
- **WHEN** precise installation-observed time is requested for a legacy run
- **THEN** the system returns coverage-based `partial` or `PIT_NOT_PROVEN` and never substitutes filesystem mtime

### Requirement: Composite is a comparison projection, never a dataset
The system SHALL return composite comparisons as independent formal,
evaluated_candidate, and latest_observed layers, each keeping its own snapshot_id,
OHLCV, contract, and hash. Overlapping dates SHALL NOT be overridden, averaged, or
merged into one truth. Each row SHALL express membership, availability_state,
quality_flags, revision_state, and render_role orthogonally. Any research call
requiring a single dataframe from a composite SHALL return `COMPOSITE_NOT_DATASET`.

#### Scenario: Observed newer than candidate
- **WHEN** Latest Observed watermark exceeds the Candidate watermark
- **THEN** the composite adds an observed-only layer and does not merge OHLCV across layers

#### Scenario: Composite rejected as research input
- **WHEN** a caller requests a research dataset from a composite comparison
- **THEN** the system returns `COMPOSITE_NOT_DATASET` and requires selecting one immutable snapshot

### Requirement: Snapshot identity is a deterministic content hash
The system SHALL define `snapshot_id` as the SHA-256 of a normalized serialization
of the asset contract id/version, resolved run/release ids, artifact SHA-256s in
stable order, effective knowledge cut, knowledge_mode, revision_policy,
quarantine/inclusion policy, and resolver policy version. `requested_at`,
`rendered_at`, page ranges, chart metrics, and sort order SHALL NOT enter
`snapshot_id`. A `latest` request SHALL freeze to the asset-scoped relevant fact
sequence at request start and SHALL NOT retain a moving alias.

#### Scenario: Stable identity for repeated latest requests
- **WHEN** two `latest` requests occur with no change to BTC-relevant facts or query parameters
- **THEN** the returned `snapshot_id`, `view_fingerprint`, and `ETag` are identical

#### Scenario: Other-asset updates do not perturb BTC identity
- **WHEN** the Catalog is updated for a different asset
- **THEN** the BTC `snapshot_id`, `view_fingerprint`, and `ETag` remain unchanged

#### Scenario: Selector conflict is rejected
- **WHEN** a `snapshot_id` is combined with conflicting run/release/channel/knowledge parameters
- **THEN** the system returns `INVALID_SNAPSHOT_SELECTOR`

### Requirement: Reads never trigger writes or network
The system SHALL guarantee that context/series/date/trust/runs/research GET and SDK
reads do not call providers, create data files, run migrations, mutate the DB,
switch pointers, or produce research outcomes, and SHALL read a consistent snapshot
under the existing shared lock.

#### Scenario: Read during a publish window
- **WHEN** a read occurs concurrently with a publish or Catalog rebuild
- **THEN** the reader observes one complete generation and never a mix of pointer and artifacts

#### Scenario: Integrity mismatch fails closed
- **WHEN** the current pointer, manifest, and artifact hash are inconsistent
- **THEN** the read fails closed with an integrity error and does not fall back to another file to keep drawing

### Requirement: Catalog generations are immutable, scoped, and content-addressed
The system SHALL persist each Catalog generation as install-once immutable
artifacts — a `generations/catalog-<generation_id>.sqlite` database and a
`generations/catalog-<generation_id>.manifest.json` generation manifest — plus an
install-once immutable `commits/catalog-switch-<operation_id>.json` switch receipt
for each committed pointer switch, under a mutable typed `catalog-current.json`
pointer, and SHALL NOT overwrite or unlink a live generation or receipt in place.
The `catalog-current.json` pointer SHALL be the only mutable file and SHALL carry at
least `pointer_schema_version`, `asset_id`, `catalog_scope`,
`catalog_schema_version`, `manifest_schema_version`, `projection_policy_version`,
`source_fingerprint`, `current_generation_id`, `current_manifest_ref`,
`current_manifest_sha256`, `previous_generation_id`, `head_commit_ref`,
`head_commit_sha256`, `switch_sequence`, and `switched_at`, pinning the head switch
receipt via `head_commit_ref` + `head_commit_sha256`. Each canonical-JSON switch
receipt SHALL carry at least `switch_receipt_schema_version`, `operation_id`,
`operation` (`publish` | `rollback`), `asset_id`, `catalog_scope`, `sequence`,
`previous_commit_ref`, `previous_commit_sha256`, `from_generation_id`,
`to_generation_id`, `to_manifest_ref`, `to_manifest_sha256`, `source_fingerprint`,
`expected_pointer_sha256` (an explicit `null` sentinel when absent), and
`occurred_at`; receipts SHALL form a hash-linked chain, and a generation SHALL be
"committed" only if it appears as a `to_generation_id` reachable from the current
pointer head. Every generation SHALL be bound to a `CatalogScope`
`(asset_id, data_family, source_contract_version, scope_policy_version)`, and
`generation_id` SHALL be a deterministic derivation over that scope, the catalog
schema version, the manifest schema version, the projection policy version, the
source fingerprint, and the full logical content hash; `pointer_schema_version` and
`switch_receipt_schema_version` SHALL NOT by themselves change `generation_id`. The
generation manifest SHALL carry at least the asset/scope,
pointer/manifest/schema/projection versions, `generation_id`, `source_fingerprint`,
`logical_content_hash`, the SQLite file SHA-256, the DB filename, the fact count,
and the fact-set hash. The `logical_content_hash` SHALL cover every Catalog field
the resolver consumes (runs, contracts, four clocks and provenance, gates, findings,
artifact refs, the `release_events` ledger and the `active_release_head` as separate
elements, the revision index, the authoritative source `btc_current` snapshot, and
the relevant fact set) — never a subset and never `catalog-current.json` itself; no
OHLCV payload SHALL be stored inside the Catalog SQLite.

#### Scenario: Identical inputs yield an idempotent generation
- **WHEN** two rebuilds run over the same scoped immutable facts
- **THEN** they derive the same `generation_id` and the second install is an idempotent no-op that does not overwrite the existing immutable artifacts

#### Scenario: Ordinary Catalog-row tamper is detected
- **WHEN** a single ordinary Catalog value (for example one gate result, finding, clock, artifact ref, or release target) inside a committed generation SQLite file is altered
- **THEN** the SQLite file SHA-256 and the deserialized `logical_content_hash` no longer reconcile and the read fails closed with `CATALOG_CORRUPT`

#### Scenario: Installed-but-uncommitted generation is an orphan
- **WHEN** a generation and manifest are installed on disk but no switch receipt reachable from the current pointer head names it as a `to_generation_id`
- **THEN** the generation is an orphan that is diagnosed only and never served or deleted

#### Scenario: Only-legacy pair requires an out-of-band rebuild
- **WHEN** only the legacy `catalog.sqlite` + `generation.json` pair exists and no `catalog-current.json` pointer is present
- **THEN** the read returns `CATALOG_STALE` with a `legacy_catalog_requires_rebuild` marker and does not migrate, overwrite, or delete the legacy pair in the read path

### Requirement: Catalog publish and rollback use durable CAS under the assurance lock
The system SHALL publish a new generation by freezing a scoped source snapshot and
the exact expected pointer SHA-256 (or an absent sentinel) under a shared BTC
assurance lock, then outside the lock projecting the candidate SQLite, committing
and closing its transaction, `fsync`-ing the DB, writing and `fsync`-ing the
generation manifest, and `fsync`-ing the candidate directory; then under the
exclusive BTC assurance lock rechecking the EXACT live source fingerprint and the
EXACT frozen expected pointer SHA-256; installing the immutable DB and manifest with
no-overwrite atomic renames and `fsync`-ing `generations/`; writing the immutable
switch receipt to a temp file, `fsync`-ing it, and no-overwrite atomic-renaming it
into `commits/` with a `fsync`; and, as the LAST step, atomically replacing
`catalog-current.json` with a file and parent-directory `fsync`. The system SHALL
NOT upgrade a shared lock to exclusive in place. If the exclusive recheck observes
that the current generation already equals the fully verified candidate and the
source/scope match, the operation SHALL return a success no-op
(`changed=false`/`committed=false`) and SHALL create no second committed switch;
only a different observed target/pointer SHA or a changed source fingerprint SHALL
be `CATALOG_CAS_CONFLICT`. A pointer-only `catalog rollback` SHALL be allowed only
when the target generation shares the current `CatalogScope`, is reader-supported,
has a `source_fingerprint` equal to the current authoritative BTC fact set, and is a
committed generation reachable from the current pointer head; otherwise it SHALL be
rejected with the single primary code `CATALOG_ROLLBACK_REJECTED`. Phase B SHALL
retain all committed generations and receipts with no destructive garbage
collection.

#### Scenario: Concurrent CAS yields one committed switch
- **WHEN** two writers attempt to publish and one observes an expected prior pointer SHA different from the one it froze
- **THEN** exactly one pointer switch commits and the other returns `CATALOG_CAS_CONFLICT` without overwriting any generation

#### Scenario: Same-candidate publish is a success no-op
- **WHEN** a publisher's exclusive recheck finds the current generation already equals its fully verified candidate with matching source fingerprint and scope
- **THEN** the operation returns success with `changed=false`/`committed=false` and writes no second switch receipt

#### Scenario: Stale-fingerprint rollback target is rejected
- **WHEN** a `catalog rollback --to-generation <id>` targets a historical generation built from a different `source_fingerprint` than the current authoritative BTC fact set
- **THEN** the operation returns the single primary code `CATALOG_ROLLBACK_REJECTED` (not also `CATALOG_STALE`) and does not switch the pointer, and the caller is directed to `BtcRunStore` authoritative rollback for a Formal/source truth change

#### Scenario: Supported projection rollback of the same fact set
- **WHEN** a rollback target is a committed reachable generation sharing the current scope and `source_fingerprint` and differing only in a reader-supported projection/policy version
- **THEN** the pointer-only CAS rollback succeeds, retaining every generation on disk for forensics

### Requirement: Reads bind one immutable generation with zero rebuild and zero writes
The system SHALL service every market context/series/date/trust/runs/diff GET and
SDK read by taking the shared BTC assurance lock only for the freeze/open/verify
critical section, freezing one typed pointer, verifying pointer ↔ head switch
receipt link consistency, opening exactly one immutable generation, verifying the
whole chain
(`pointer -> head switch receipt -> manifest -> file SHA-256 -> catalog_meta -> deserialized logical hash`),
deserializing one `CatalogReadSnapshot`, and reusing that snapshot across resolver,
query, diff, and SDK. A normal GET SHALL verify only the head switch receipt and
SHALL NOT scan the full receipt history; only rollback/history diagnostics traverse
the chain. Reads SHALL NOT call `build_catalog()`, SHALL NOT write, and SHALL
produce parquet/JSON response bytes outside the lock on the already-verified
immutable references. After the snapshot freezes its artifact refs, every
participating external artifact (canonical, primary, shadow, reconciliation, or
revisions) SHALL be opened and read exactly once and the exact bytes used to build
the response SHALL be SHA-256 checked against the frozen ref outside the lock; any
mismatch or missing participating artifact is `ARTIFACT_HASH_MISMATCH` and SHALL
abort the entire GET/SDK/diff/composite response with no partial 200, `null` layer,
or old fallback. A ready Catalog whose assurance lockfile is absent SHALL fail
closed, and a GET SHALL NOT create the lockfile. The existing research GET/H1
adapter is read-only under its own receipt/pointer contract, outside
`CatalogReadSnapshot` and outside this market read barrier, and SHALL NOT affect the
market Catalog source/logical hash, snapshot/`ETag`, or active head.

#### Scenario: Read performs no build and no write
- **WHEN** any market GET/SDK read resolves a snapshot from a ready Catalog
- **THEN** it performs zero `build_catalog()` calls and zero filesystem writes and observes one complete generation

#### Scenario: Participating external artifact tamper fails closed
- **WHEN** a participating canonical/primary/shadow/reconciliation/revisions artifact's bytes do not match the frozen ref SHA-256
- **THEN** the read returns `ARTIFACT_HASH_MISMATCH` and aborts the whole response rather than returning a partial 200 or stale fallback

#### Scenario: Lock cannot be acquired within the read deadline
- **WHEN** the shared assurance lock cannot be acquired within the read deadline
- **THEN** the read returns `CATALOG_LOCK_TIMEOUT` with `retry_after` (HTTP 503) rather than reading an unlocked or partial generation

### Requirement: Catalog facts are asset-scoped and legacy events are fail-closed
The system SHALL scope every generation manifest, `catalog-current.json` pointer,
publish audit, and rollback audit by `asset_id = crypto.BTC`, and SHALL write new
audits into a scope-decidable-before-parse namespace at
`audit/by-asset/crypto.BTC/{publish,rollback}/`. The system SHALL adapt a legacy
global authoritative audit into the BTC scope only when it is parseable, its
`event_type` is in the whitelist `{btc_canonical_publish, btc_canonical_rollback,
btc_legacy_predecessor_rollback}`, and it references a BTC-scoped run; a legacy
global authoritative file that is unparseable or unattributable SHALL be a
fail-closed migration blocker rather than a skipped record, and SHALL NOT be
silently ignored. Facts belonging to any other asset or `data_family`
(`news`/`sentiment`/`research`) SHALL NOT affect the BTC `source_fingerprint`,
active release, snapshot, or `ETag`. The release-event ledger SHALL be modelled
separately from the active Formal head, and a rollback event SHALL activate its
`to_run_id` rather than blanking the head, except for an explicit legacy-to-none
rollback.

#### Scenario: ETH event does not perturb BTC identity
- **WHEN** an ETH (non-BTC) manifest or audit is added or malformed
- **THEN** the BTC `source_fingerprint`, active release, snapshot, and `ETag` are unchanged and only the ETH scope is affected

#### Scenario: Unattributable legacy global audit blocks the generation
- **WHEN** a legacy global `audit/publish` or `audit/rollback` file is unparseable or cannot be attributed to a BTC-scoped run
- **THEN** the generation build fails closed as a migration blocker (`MANIFEST_INVALID` / `CATALOG_CORRUPT`) and does not silently `continue` past it

#### Scenario: Rollback event activates a prior run, not an empty head
- **WHEN** a rollback event references `to_run_id`
- **THEN** the active Formal head becomes `to_run_id` and is not blanked, except for an explicit legacy-to-none rollback
