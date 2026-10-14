## ADDED Requirements

### Requirement: BTC workspace follows observation-to-evidence tasks

The BTC workspace SHALL organize its primary experience into **Observe**,
**Analyze**, **Assurance**, and **Research** views. Observe SHALL remain the
default and SHALL answer what the selected BTC market snapshot contains.
Analyze SHALL explain descriptive behavior on an immutable analysis product.
Assurance SHALL expose fitness, quality, coverage, revision, and lineage.
Research SHALL expose registered hypotheses and Study results without turning
them into a recommendation.

#### Scenario: User opens the workspace without a view selector
- **WHEN** a freshly authorized user opens the existing Observatory page without a valid `obsLens`
- **THEN** the workspace opens Observe for the selected lifecycle channel
- **AND THEN** it resolves and displays the immutable market context before any dependent chart, metric, assurance, or research fact is presented as current

#### Scenario: User moves from an observation to its evidence
- **WHEN** the user selects a candle, analysis metric, quality finding, or Study result and explicitly requests its evidence
- **THEN** the workspace opens an evidence rail bound to that item's immutable reference and selection identity
- **AND THEN** the rail shows provenance, clocks, method or policy identity, coverage, and reason codes supplied by the owning query contract
- **AND THEN** closing the rail restores focus to the initiating control without changing the selected lifecycle channel or knowledge cut

#### Scenario: Research is separately scoped
- **WHEN** a Study result was produced from a DatasetSnapshotRef different from the active market or analysis snapshot
- **THEN** Research displays both identities and a clear `different_input_snapshot` relationship
- **AND THEN** the workspace does not describe the Study result as confirmation of the active Observe or Analyze view

### Requirement: Observe preserves lifecycle-aware BTC inspection

Observe SHALL retain the existing selected-channel daily K-line, `1D`/`1W`/`1M`/
`1Y` display timeframes, local viewport restoration, Market/Compare modes,
explicit date evidence, Formal/evaluated-candidate/observed separation, and
point-in-time failure behavior. It SHALL add a compact observation strip whose
values are server-provided and bound to the same market snapshot. Once V2 is
enabled, no V2 Observe or Analyze component SHALL display the legacy
`display_estimate` return, drawdown, realized-volatility, percentile, or another
browser-computed business metric. Those estimates MAY exist only inside the
complete legacy-page rollback bundle.

#### Scenario: Selected observed data is newer than Formal
- **WHEN** the selected observed snapshot has a later market watermark than the Formal baseline
- **THEN** Observe shows the observed data as unpublished and identifies the Formal watermark separately
- **AND THEN** it does not call the newer value canonical, validated, recommended, or safe for automated decisions

#### Scenario: Observation strip is shown
- **WHEN** the selected market snapshot and its Observe projection are confirmed
- **THEN** the strip shows the supplied latest OHLCV, bar time, selected-channel lifecycle state, freshness, and coverage state
- **AND THEN** every value carries the same market snapshot identity as the chart
- **AND THEN** absent values remain unavailable rather than becoming zero, unchanged, or neutral
- **AND THEN** it does not derive a return, drawdown, volatility, percentile, range, or volume statistic from chart rows

#### Scenario: Chart compatibility behavior remains available
- **WHEN** the user restores a valid existing chart mode, timeframe, selected date, or local viewport
- **THEN** the existing K-line behavior and evidence-pin rules remain equivalent
- **AND THEN** ordinary hover, pan, zoom, resize, and click inspection remain local and do not start a network request

### Requirement: Analyze presents descriptive BTC behavior without advice

Analyze SHALL present snapshot-bound descriptive BTC behavior in four
work-focused sections: Performance, Volatility and Range, Drawdown and
Distribution, and Coverage and Revisions. It SHALL use only metrics and series
returned by the Datasets-owned analysis product and SHALL NOT calculate a
business metric from OHLCV in the browser.

#### Scenario: Descriptive analysis is available
- **WHEN** a compatible analysis DatasetSnapshotRef is resolved for the active market snapshot
- **THEN** Analyze presents the returned multi-window metrics and rolling series with units, window, sample count, coverage, method version, and as-of clock
- **AND THEN** the view labels the facts as descriptive historical observations
- **AND THEN** it contains no buy/sell language, target price, forecast,
  directional probability, asset rank, confidence score, or recommendation

#### Scenario: Analysis product does not match the active snapshot
- **WHEN** the BFF cannot prove that the analysis input lineage includes the active market DatasetSnapshotRef under the selected knowledge and revision policy
- **THEN** Analyze is unavailable with `analysis_snapshot_mismatch`
- **AND THEN** it does not reuse an analysis payload from a previous channel, knowledge cut, or revision policy
- **AND THEN** it does not calculate a browser fallback

#### Scenario: Metric is partial or unavailable
- **WHEN** a metric lacks its required lookback, contains excluded dates, or fails its method's minimum sample policy
- **THEN** the metric displays `partial` or `unavailable` with supplied coverage and reason codes
- **AND THEN** its numeric value is omitted when the owning contract marks it unavailable
- **AND THEN** the surrounding section remains usable for independently confirmed metrics

#### Scenario: User changes the metric window
- **WHEN** the user selects a supported analysis window
- **THEN** the UI selects a precomputed metric/series from the confirmed analysis response or requests the corresponding bounded query
- **AND THEN** it does not derive a new metric from chart geometry or visible candles
- **AND THEN** unsupported windows are rejected to the documented default without an unbounded query

### Requirement: Assurance exposes fitness before detail

Assurance SHALL prioritize purpose fitness, freshness, coverage, and blocking
findings before catalog run detail. Gates and lineage SHALL remain available as
drill-down views, with selected-snapshot evidence distinguished from
catalog-wide history.

#### Scenario: Manual observation is allowed but formal use is blocked
- **WHEN** the selected snapshot permits manual observation and blocks Formal-system consumption
- **THEN** Assurance displays both purpose results independently with their supplied reason and evidence references
- **AND THEN** Observe and Analyze retain a persistent unpublished or blocked-use cue
- **AND THEN** no aggregate trust number hides the blocking finding

#### Scenario: User inspects a catalog run
- **WHEN** the user opens legacy `obsLens=runs` or selects Run lineage in Assurance
- **THEN** the existing paginated run list, detail, and diff remain available
- **AND THEN** catalog-wide facts are labelled separately from selected-snapshot assurance
- **AND THEN** the page does not eagerly load every run detail or artifact

### Requirement: Research distinguishes Study evidence from market description

Research SHALL display the current H1 receipt and future registered Study
results through Studies contracts. Each result SHALL expose hypothesis and
method identity, immutable DatasetSnapshotRef, validation state, evaluation
window, sample count, uncertainty or explicit absence, promotion/staleness
state, and evidence references. It SHALL NOT be presented as an automatic
decision.

#### Scenario: Validated Study result is available
- **WHEN** Studies returns a validated result with complete immutable references
- **THEN** Research presents the registered hypothesis, validation method, result, uncertainty, and lifecycle state
- **AND THEN** it includes explicit non-recommendation language and the input snapshot relationship to the active workspace
- **AND THEN** it provides an evidence drill-down without copying Study logic into the UI

#### Scenario: Study is stale after a data revision
- **WHEN** a StudyResultRef is marked stale because an input DatasetSnapshotRef was superseded
- **THEN** Research prominently displays `stale_due_to_revision` and the affected input reference
- **AND THEN** the old result remains auditable but is not shown as current evidence
- **AND THEN** the read-only workspace does not trigger the rerun itself

#### Scenario: Evidence gap exists
- **WHEN** a Study reports insufficient data or an EvidenceGap
- **THEN** Research displays the gap, required evidence class, and process status when supplied
- **AND THEN** it does not call Capture, build a Dataset, or run the Study from the query path

### Requirement: Workspace states remain explicit and independently recoverable

Each request-driven region SHALL keep transport state (`idle`, `loading`,
`confirmed`, `failed`), observation condition (`nonempty`, `empty`, or absent
before confirmation), and product availability (`complete`, `partial`,
`unavailable`, `stale`) as orthogonal axes where applicable. `empty` means a
successful query over a valid scope with zero matching observations; it SHALL
use a non-retryable, non-numeric presentation distinct from unavailable and
failed.
Stale prior evidence SHALL be separately labelled with its original identity.
A region SHALL NOT infer success from another region or convert absence to a
neutral numeric value.

#### Scenario: Analysis fails while Observe remains confirmed
- **WHEN** the analysis query fails after the market context and chart are confirmed
- **THEN** Analyze shows a scoped failure and retry action
- **AND THEN** Observe remains available under its confirmed identity
- **AND THEN** the failure does not downgrade, upgrade, or relabel the market lifecycle state

#### Scenario: Selection changes during in-flight work
- **WHEN** channel, knowledge cut, revision policy, view, metric selection, date, or Study selection changes while a request is pending
- **THEN** the superseded request is cancelled or ignored by identity
- **AND THEN** old current-truth content is cleared or explicitly retained only as labelled previous evidence
- **AND THEN** only a response matching the complete active identity may become confirmed

#### Scenario: Valid query returns no matching evidence
- **WHEN** a confirmed owner query observes a valid scope with no matching metric, Study, lineage, or evidence records
- **THEN** the region presents `empty` with the queried scope and stable reason code
- **AND THEN** it does not show a retryable failure, unavailable-product message, zero-valued metric, or stale prior row

#### Scenario: State axes are combined
- **WHEN** a region presents a completed empty product
- **THEN** it uses `transport=confirmed`, `condition=empty`, and `availability=complete`
- **AND THEN** a policy-sufficient nonempty partial product uses `confirmed`, `nonempty`, and `partial`
- **AND THEN** a transport failure has no observation condition and cannot reuse a prior availability state as current

### Requirement: URL and navigation compatibility is additive

The workspace SHALL retain the existing Observatory page key, capability gate,
and query parameter names. Existing `obsLens=overview|trust|runs|research`
values SHALL restore equivalent destinations. The additive
`obsLens=analysis` value SHALL open Analyze. Missing or unknown values SHALL
restore Observe without deleting other valid selectors.

#### Scenario: Existing bookmark opens after V2 rollout
- **WHEN** a bookmark contains any valid existing Observatory URL selectors
- **THEN** the workspace restores the same lifecycle channel, chart mode,
  timeframe, knowledge cut, date, and run selections
- **AND THEN** `overview` maps to Observe, `trust` to Assurance summary, `runs`
  to Assurance lineage, and `research` to Research

#### Scenario: V2 is rolled back
- **WHEN** the V2 feature flag is disabled after a user has visited Analyze
- **THEN** the legacy workspace safely maps unknown `obsLens=analysis` to its Observe default
- **AND THEN** all older selectors and existing API paths continue to work

### Requirement: Layout is dense, responsive, and accessible

The workspace SHALL use an unframed task layout with a compact context header,
one primary work surface, and an evidence rail only when evidence is selected.
It SHALL avoid nested cards and decorative page sections. Controls, charts,
tables, labels, and error states SHALL remain usable at supported desktop and
mobile widths without overlap, hidden meaning, or color-only status.

#### Scenario: Wide desktop workspace
- **WHEN** the viewport is at least 1280 CSS pixels wide
- **THEN** the context header and task navigation remain stable while the primary work surface uses the available width
- **AND THEN** an opened evidence rail uses a bounded secondary column without shrinking the chart below its minimum usable width
- **AND THEN** no section is wrapped in a decorative outer card

#### Scenario: Narrow mobile workspace
- **WHEN** the viewport is 360 CSS pixels wide
- **THEN** task navigation is horizontally operable, controls wrap without clipping, and content follows context, primary evidence, details, then actions
- **AND THEN** the evidence rail becomes an in-flow region or accessible sheet with explicit close and focus restoration
- **AND THEN** no text, chart control, status, table, or loading state overlaps another element

#### Scenario: Non-pointer user explores evidence
- **WHEN** a keyboard or assistive-technology user navigates the workspace
- **THEN** every task, segmented mode, metric selector, chart evidence pin, table row action, disclosure, retry, and close action is operable and named
- **AND THEN** loading and failure changes are announced without stealing focus
- **AND THEN** charts have equivalent textual summaries and status does not rely on color alone
