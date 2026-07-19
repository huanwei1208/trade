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
