## ADDED Requirements

### Requirement: Reusable BTC descriptive analysis is a Datasets product

Reusable BTC descriptive analysis SHALL be published by Datasets as an
immutable, versioned derived Dataset product. Its formal build inputs SHALL be
immutable DatasetVersionRef or DatasetSnapshotRef values. The product SHALL
carry lineage, semantic schema, method policy, unit, timezone, event-time,
available-time, knowledge-cut, revision-policy, quality, and coverage
identities. The UI, BFF, provider adapter, and moving database state SHALL NOT
be formal build inputs.

#### Scenario: Analysis product is built
- **WHEN** Datasets builds a BTC descriptive-analysis version
- **THEN** every input is a verified immutable DatasetVersionRef or DatasetSnapshotRef
- **AND THEN** the output identifies the source BTC daily-bar snapshot, transform and method policy versions, schema, units, UTC calendar policy, available-time policy, revision policy, and lineage digest
- **AND THEN** the output is published through the standard DatasetVersionRef and DatasetSnapshotRef contracts
- **AND THEN** canonical serialization of identical ordered inputs, dependency manifests, schema/method/environment policies, and lineage yields the same content digest
- **AND THEN** wall-clock build time, run id, release pointer, and receipt metadata do not enter that content digest

#### Scenario: Moving input is supplied
- **WHEN** a formal analysis build is asked to read `latest`, current directory contents, a provider response, an unpinned DataFrame, or current database rows
- **THEN** the build is rejected before publication
- **AND THEN** no DatasetVersionRef or DatasetSnapshotRef is issued

#### Scenario: Product cannot prove point-in-time input
- **WHEN** a required source row lacks a provable available-time or violates the requested knowledge/revision policy
- **THEN** the affected metric/series is excluded or marked unavailable under the method policy
- **AND THEN** a formal analysis DatasetSnapshotRef is not published as complete
- **AND THEN** missing temporal proof is never replaced by collector-now, file mtime, or zero

### Requirement: Analysis references bind market, product, and method identity

Every formal analysis product SHALL use the standard Datasets
`DatasetVersionRef` and `DatasetSnapshotRef` contracts. An analysis query MAY
return a non-authoritative `AnalysisSnapshotDescriptor` containing the formal
analysis DatasetSnapshotRef, source market DatasetSnapshotRef, schema,
transform-environment and method-policy identities, knowledge cut, revision
policy, lineage relationship, and operational creation clock. The descriptor
SHALL NOT define a second artifact-reference type or be accepted as a formal
DatasetBuild or StudyRun input. A consumer SHALL be able to verify that the
analysis Dataset lineage contains the selected market snapshot without
resolving a filesystem path.

#### Scenario: Workspace binds analysis to selected market evidence
- **WHEN** the BFF composes a selected market context with an analysis response
- **THEN** it verifies the standard analysis DatasetSnapshotRef and source market snapshot relationship
- **AND THEN** it returns both immutable references and a relationship value of `same_snapshot`, `derived_from_snapshot`, `different_snapshot`, or `unproven`
- **AND THEN** only `same_snapshot` or a policy-approved `derived_from_snapshot` may be shown as current Analyze evidence

#### Scenario: Reference is tampered or unverifiable
- **WHEN** owner, type, version, digest, schema, source reference, or method-policy identity does not verify
- **THEN** the response fails closed with `analysis_reference_invalid`
- **AND THEN** the consumer does not open a path, scan a directory, or fall back to the latest product

#### Scenario: Descriptor is supplied as a formal input
- **WHEN** a DatasetBuild or StudyRun is given an AnalysisSnapshotDescriptor instead of its verified DatasetSnapshotRef
- **THEN** the formal operation rejects the descriptor as an input type
- **AND THEN** it does not unwrap, resolve, or substitute a moving analysis product

### Requirement: Metric values include method and availability semantics

Each descriptive metric SHALL be represented as a structured `MetricObservation`
rather than a bare number. It SHALL include `metric_id`, display label, value or
explicit absence, unit, direction-neutral interpretation class, window,
observation/event as-of, knowledge cut, available time, sample count, expected
sample count, coverage ratio, coverage state, quality state, method id/version,
input and standard output DatasetSnapshotRef values, availability basis, clock
confidence/source reference, evidence references, and reason codes.
The Datasets child SHALL freeze a purpose-by-availability-basis-by-confidence
admissibility matrix. A market-boundary proxy, installation observation, or
collector clock SHALL NOT be upgraded to provider-publication evidence, and a
purpose that requires stronger proof SHALL fail closed.

#### Scenario: Complete metric is returned
- **WHEN** a metric meets its method's temporal, sample, coverage, and quality requirements
- **THEN** the response sets `state=confirmed`, provides its decimal value and unit, and identifies its method, window, sample, coverage, clocks, and references
- **AND THEN** the value is serialized as an exact decimal string when decimal preservation is required

#### Scenario: Metric is unavailable
- **WHEN** the method cannot calculate a valid value because lookback, temporal proof, unit identity, or minimum sample requirements are unmet
- **THEN** the response sets `state=unavailable`, omits the numeric value, and provides stable reason codes and evidence references
- **AND THEN** zero, the prior value, a neutral percentile, or an imputed normal state is not substituted

#### Scenario: Metric is partial
- **WHEN** the method permits a result with incomplete but policy-sufficient coverage
- **THEN** the response sets `state=partial`, reports actual and expected samples, coverage, exclusions, and the numeric value if policy permits it
- **AND THEN** the UI must visibly retain the partial state beside that value

#### Scenario: Metric query succeeds with no observations
- **WHEN** a valid immutable analysis query has no observations in its requested supported scope
- **THEN** the response sets `observation_state=observed` and `condition=empty`, omits a numeric value, and returns stable scope and reason identity
- **AND THEN** empty is not reported as unavailable, failed, partial, zero, or retryable transport failure

#### Scenario: Clock evidence is weaker than the declared purpose
- **WHEN** a metric purpose requires provider-publication proof but the input clock is only a market-boundary proxy or installation observation
- **THEN** the metric is unavailable with its actual availability basis and confidence
- **AND THEN** the query does not relabel or extrapolate that clock as stronger evidence

### Requirement: Initial descriptive metric set is bounded and versioned

The initial analysis product SHALL support a bounded registry of descriptive
historical metrics: close return over approved trailing windows, realized
volatility over approved windows, peak-to-current and maximum drawdown, true or
high-low range where source semantics permit it, volume change only when volume
identity is comparable, and empirical distribution percentile over a declared
historical window. Each metric SHALL have one versioned method definition and
minimum-sample/coverage policy. Arbitrary user expressions SHALL NOT execute in
the query or UI path.

#### Scenario: Supported metric is queried
- **WHEN** a consumer requests a registered metric and supported window
- **THEN** Datasets returns the prebuilt or boundedly projected observation under its registered method version
- **AND THEN** the response identifies whether the window is calendar-day, available-bar, rolling-observation, or drawdown-episode based

#### Scenario: Unsupported metric or window is queried
- **WHEN** a consumer supplies an unregistered metric id, arbitrary expression, or unsupported window
- **THEN** the query returns `analysis_selector_invalid`
- **AND THEN** it performs no dynamic code execution, provider access, dataset build, or unbounded scan

#### Scenario: Volume identity is absent
- **WHEN** source volume has no stable comparable unit or mixes incompatible venue semantics
- **THEN** volume-derived observations are unavailable with `volume_unit_unproven`
- **AND THEN** price-based observations remain independently queryable

### Requirement: Rolling points preserve point-in-time eligibility

Every rolling metric point SHALL declare either `as_known_at_point` or
`restated_at_snapshot_cut` temporal basis. For `as_known_at_point`, every
constituent row and revision used at event point `t` SHALL have the required
availability and revision evidence no later than that point's declared
knowledge boundary, and the result available time SHALL be the maximum eligible
input clock. Missing, late, quarantined, or future-visible inputs SHALL remain
explicit gaps. A restated point SHALL NOT claim point-in-time identity or become
an input to a Study requiring point-in-time evidence.

#### Scenario: Late row enters a rolling window
- **WHEN** a source row's available time is later than an `as_known_at_point` window boundary
- **THEN** that row is excluded from the point and the output records an explicit temporal gap
- **AND THEN** a later point may use the row only when its own knowledge boundary permits it

#### Scenario: Restated series is requested
- **WHEN** a consumer requests `restated_at_snapshot_cut`
- **THEN** every point identifies the restatement policy and snapshot knowledge cut
- **AND THEN** the series is labelled restated and is rejected as input to a point-in-time Study

### Requirement: Rolling series are immutable, bounded projections

An analysis series SHALL identify one metric method and one immutable analysis
DatasetSnapshotRef. It SHALL return ordered UTC points with event date,
available time and its evidence basis, value or explicit gap, quality/revision
state, and evidence reference. Queries SHALL require a supported range and
SHALL enforce response-point and byte budgets without silent truncation.

#### Scenario: Rolling volatility series is requested
- **WHEN** the user opens a supported realized-volatility series for a confirmed analysis snapshot and range
- **THEN** the query returns points in deterministic UTC event-date order with method/version, units, input reference, and per-point availability
- **AND THEN** excluded, revised, or unavailable points remain explicit gaps or marked points rather than interpolated normals

#### Scenario: Series exceeds its contract budget
- **WHEN** the requested range would exceed the maximum points or encoded bytes
- **THEN** the query returns `analysis_query_budget_exceeded` with supported coarser resolutions or bounded ranges
- **AND THEN** it does not silently drop early or late points

### Requirement: Revisions follow method dependency manifests

A source Dataset revision SHALL produce a new derived DatasetVersion rather than
mutating an existing analysis product. Every metric method SHALL publish a
dependency manifest covering source columns, clocks, units, market identity,
finality, quality, and eligibility fields. Any changed dependency value SHALL
change source identity, produce a new analysis version, identify affected metric
points, and stale every dependent StudyResultRef. A tolerance may classify
quality impact but SHALL NOT hide lineage identity change. The old and new
relationships SHALL remain queryable and auditable.

#### Scenario: BTC source snapshot is superseded
- **WHEN** Datasets releases a revised BTC daily-bar DatasetVersion
- **THEN** the previous analysis DatasetVersion remains immutable
- **AND THEN** a new analysis build uses the revised immutable input and records the supersession/lineage relationship
- **AND THEN** queries against the old reference continue to return its historical facts with a stale/superseded relationship

#### Scenario: High, volume, or availability changes without a close change
- **WHEN** a source revision changes high, low, volume, unit, available time, finality, quarantine, or another declared dependency while close is unchanged
- **THEN** every method whose dependency manifest includes that field receives a new output identity
- **AND THEN** affected metric points and Study results are marked stale or rebuilt under the new source snapshot

#### Scenario: Current workspace sees old analysis after revision
- **WHEN** the active market snapshot is newer than the available analysis product
- **THEN** the BFF returns `analysis_pending_for_snapshot` or `analysis_stale_for_snapshot`
- **AND THEN** the UI does not label the old metrics current or recompute them locally

### Requirement: Studies own inferential and forward-looking results

The system MUST assign every hypothesis, forward outcome, label, effect
estimate, model fit, confidence interval, significance test, placebo,
walk-forward result, benchmark, multiple-testing correction, validation state,
promotion, or rejection to Studies, and each formal StudyRun SHALL read only
DatasetSnapshotRef inputs. Such results SHALL NOT be added to the descriptive
analysis Dataset or inferred by the UI.

#### Scenario: Historical regime description has no future label
- **WHEN** Datasets publishes a volatility percentile or drawdown state using only as-of historical data
- **THEN** Analyze may display it as a descriptive observation
- **AND THEN** it does not claim that price will rise, fall, persist, mean-revert, or reach a target

#### Scenario: H1 evaluates a future volatility outcome
- **WHEN** H1 compares later realized volatility with a registered historical condition
- **THEN** the computation and result are owned by a StudyRun bound to DatasetSnapshotRef
- **AND THEN** Research displays its validation, sample, uncertainty, evidence, and lifecycle state
- **AND THEN** Analyze does not copy its result into a market-status metric

#### Scenario: Study input is not immutable
- **WHEN** a StudyRun is given an AnalysisSnapshotDescriptor, raw artifact, provider response, moving current state, or a DatasetSnapshotRef that cannot be verified
- **THEN** the request is rejected before a formal StudyRun is created
- **AND THEN** it does not query Capture, a provider, or a raw artifact
- **AND THEN** `insufficient_data` is reserved for an accepted, verified DatasetSnapshotRef whose eligible sample is inadequate

#### Scenario: Study consumes the descriptive analysis product
- **WHEN** a Study needs a published descriptive-analysis Dataset as an input
- **THEN** it receives that product's verified standard DatasetSnapshotRef
- **AND THEN** no AnalysisSnapshotDescriptor or UI/BFF response type enters the StudyRun input contract

### Requirement: Analysis has no recommendation semantics

The analysis contract SHALL be direction-neutral and SHALL NOT expose buy/sell,
long/short, risk-on/risk-off command, target price, expected future return,
direction probability, position size, asset ranking, or recommendation fields.
Any future Decision Support use SHALL consume a separately governed
StudyResultRef and DatasetSnapshotRef through its own contract.

#### Scenario: Consumer requests a directional conclusion
- **WHEN** a consumer asks the descriptive-analysis query for a trade direction, target, probability, or recommendation
- **THEN** the query rejects the selector as unsupported
- **AND THEN** it returns no synthesized neutral or directional fallback

#### Scenario: High volatility is displayed
- **WHEN** a confirmed metric places current realized volatility in a high historical percentile
- **THEN** the response and UI describe the historical percentile, window, sample, and method
- **AND THEN** they do not map `high` to buy, sell, avoid, increase risk, or reduce risk
