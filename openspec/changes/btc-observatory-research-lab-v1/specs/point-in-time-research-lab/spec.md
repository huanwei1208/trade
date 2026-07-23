## ADDED Requirements

### Requirement: Four clocks are preserved on every researchable fact
The system SHALL distinguish, for each researchable fact, event/bar-open/bar-close
time, `available_at`, `first_seen_at`/`fetched_at`, and `certified_at`/`published_at`,
and SHALL record `revision_recorded_at`, `valid_from_run`, and
`valid_to_run`/`superseded_by` for revisions.

#### Scenario: Backfill without proven capture is marked
- **WHEN** historical data was backfilled but not actually captured by this installation at the historical time
- **THEN** the fact is marked `backfilled`/`PIT-unproven` and does not claim to reconstruct what the installation knew

### Requirement: Knowledge mode is explicit and never impersonated
The system SHALL support `market_available` and `installation_observed` knowledge
modes, SHALL NOT let one impersonate the other, and SHALL default the latest
Observe view and historical replays to `installation_observed`/latest when the
caller does not specify. Research SHALL fix one mode in the hypothesis contract and
SHALL NOT carry over old results after a UI mode switch.

#### Scenario: Installation-observed default for latest
- **WHEN** a caller requests the latest Observe view without a knowledge mode
- **THEN** the system resolves `installation_observed` at latest

#### Scenario: Modes do not mix
- **WHEN** a query fixes `market_available`
- **THEN** the response never blends `installation_observed` first-seen facts into the same series

### Requirement: Evidence coverage gates installation-observed PIT
The system SHALL produce an evidence coverage report per asset/provider/contract/
data family recording earliest proven knowledge time, proven/partial/unproven
intervals, first-seen/publication/revision ledger coverage, gap reason codes, and
supportable knowledge modes. When legacy data lacks first_seen_at, immutable
artifacts, or publication/revision evidence, `installation_observed` queries SHALL
return `PIT_NOT_PROVEN` and SHALL NOT fabricate a complete history from mtime,
today's manifest, or guessed times.

#### Scenario: Legacy interval returns PIT_NOT_PROVEN
- **WHEN** an `installation_observed` query targets a time before `first_proven_present_at`
- **THEN** the system returns `PIT_NOT_PROVEN` with the coverage interval and does not synthesize a curve

### Requirement: As-of selection controls the whole snapshot context
The system SHALL make the as-of selector control the entire Snapshot Context: data
version, prices/volumes, features/thresholds, quality findings, events/context, and
research results with outcome maturity. Trimming only the right edge of a chart
SHALL NOT be treated as point-in-time.

#### Scenario: Later revision does not pollute older as-of
- **WHEN** a revision is recorded after knowledge time T
- **THEN** an `as_known` view at T does not include the later revision

#### Scenario: Pending outcome is not zero
- **WHEN** an outcome has not matured at knowledge time T
- **THEN** the outcome is reported as pending and is not shown as 0

#### Scenario: Thresholds read only the past
- **WHEN** a threshold/percentile is computed at anchor T
- **THEN** only data available before T contributes to it

### Requirement: Snapshot identity priority and view fingerprint are deterministic
The system SHALL resolve identity in priority order: `snapshot_id` fixes all
identity parameters (conflicts return `INVALID_SNAPSHOT_SELECTOR`); then exact
run_id/release_id subject to knowledge visibility; then
channel + knowledge_as_of + knowledge_mode + revision_policy; then `latest` frozen
to the current Catalog generation's asset-scoped effective knowledge cut and
concrete run/release ids. `view_fingerprint` SHALL derive from `snapshot_id` plus
the participating operational/quality fact fingerprints, date range, metric
versions, lens, pagination/sort, and serialization version.

#### Scenario: Deterministic known-at replay
- **WHEN** the same knowledge time is replayed under frozen fixtures
- **THEN** the resulting snapshot hash is identical

#### Scenario: Restated view is labeled not-PIT
- **WHEN** `revision_policy=latest_restated` is used
- **THEN** the view persistently shows `RESTATED_NOT_PIT` and is not accepted as historical replay or walk-forward input

### Requirement: Research runs bind to immutable snapshots via the existing H1 authority
The system SHALL register formal CryptoResearchRun records only through explicit
CLI/Operations workflows that re-validate snapshot identity, artifact hashes,
PIT/eligibility, and hypothesis version; execute in an isolated temp directory with
a versioned kernel; atomically write immutable outputs, manifest, and receipt; and
map H1 onto the existing `validation_run_id`/`generation_id`/current pointer without
creating a competing current-selection authority. Web/GET/SDK SHALL NOT write
research runs.

#### Scenario: Dry-run registers nothing
- **WHEN** `trade research btc run --dry-run` is invoked
- **THEN** no receipt, artifact, or pointer is written

#### Scenario: Failed run leaves no half state
- **WHEN** a research run fails mid-execution
- **THEN** no partial run is registered and the existing current pointer is unchanged

#### Scenario: Promotion appends a receipt without rewriting the old run
- **WHEN** an imported exploratory run is promoted
- **THEN** promotion re-runs from a clean environment under the pre-registered contract, appends a promotion receipt, and does not modify the original run in place

#### Scenario: Current authority stays single
- **WHEN** a research run completes
- **THEN** the current pointer moves only if the existing lifecycle computes `activate_run=true` via the existing atomic writer, and the command never sets the pointer itself

### Requirement: Observe and Investigate never show future outcomes
The system SHALL ensure Observe/Investigate surfaces (DOM and API) never leak
future labels, and SHALL separate feature and future-outcome regions only inside the
Research lens.

#### Scenario: No future label leakage in Observe
- **WHEN** an Observe/Investigate response is inspected
- **THEN** it contains no future outcome labels for any date

#### Scenario: Superseded research snapshot not shown as current
- **WHEN** a research snapshot is superseded
- **THEN** the prior result is retained as history and not shown as the current conclusion of the new snapshot
