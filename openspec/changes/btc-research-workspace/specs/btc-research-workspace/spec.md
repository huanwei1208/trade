## ADDED Requirements

### Requirement: Lifecycle-aware market workspace

The capability-gated BTC workspace SHALL open in a Market task flow that
identifies the selected lifecycle channel, the Formal baseline relationship,
purpose fitness, and immutable context before chart interpretation. It SHALL
render the selected channel as the primary daily K-line and SHALL retain Formal,
evaluated candidate, and latest observed as independent layers in an explicit
Compare mode, never as a blended price series.

#### Scenario: Market opens with unpublished newer data

- **WHEN** an authorized workspace receives an `ObsContext` whose observed or
  evaluated-candidate watermark is newer than Formal
- **THEN** the Market flow identifies the lifecycle relationship and retains the
  existing non-published visual treatment for the newer layer
- **AND THEN** it does not call the newer value formal, published, validated, or
  a trading signal

#### Scenario: Market renders an exchange-style daily K-line

- **WHEN** the selected-channel snapshot-pinned series is confirmed
- **THEN** Market renders its supplied daily OHLCV using a right price scale,
  UTC time scale, volume, crosshair readout, pan/zoom, fit/latest, responsive
  sizing, and fullscreen controls
- **AND THEN** the visible and accessible OHLCV readout uses the original API
  strings while numeric parsing is limited to finite chart geometry
- **AND THEN** Candidate or Observed remains persistently labelled unpublished
  and the chart makes no intraday, live-feed, indicator, or recommendation claim
- **AND THEN** it identifies itself as a local daily Observatory snapshot that
  is not live, derives provider/interval labels only from the active Context,
  and identifies TradingView only as the charting library

#### Scenario: User opens lifecycle comparison

- **WHEN** the user selects Compare
- **THEN** Market renders the retained independent Formal, Candidate, and
  Observed composite under its own fingerprint basis
- **AND THEN** switching Market/Compare does not alter the selected channel,
  knowledge cut, snapshot, range, or selected date

#### Scenario: Market and Compare requests remain mode-local

- **WHEN** Market is active
- **THEN** the workspace resolves Context then selected series and does not
  request composite
- **AND WHEN** Compare is active
- **THEN** the workspace resolves Context then composite and does not request
  selected series
- **AND THEN** an explicit Compare date pin may request Date Evidence directly
  with Context `snapshot_id`; composite values never substitute for it

#### Scenario: Daily chart input is partially or wholly invalid

- **WHEN** selected rows or Context exclusions contain malformed dates, duplicate
  dates, invalid decimal/OHLC relationships, mixed provenance, or missing bars
- **THEN** the adapter validates strict Gregorian UTC dates, strict decimal
  syntax, positive enclosing OHLC, optional non-negative volume, unique dates,
  and active-Context provenance before creating geometry
- **AND THEN** rows plus Context `excluded_dates` produce an in-bounds UTC daily
  lattice whose invalid/missing/quarantined dates are whitespace with safe
  reasons and no first/last duplicate selection
- **AND THEN** partial-invalid data has a persistent renderer warning, while a
  malformed series or zero valid candles is chart-unavailable rather than a
  plausible empty/normal chart

#### Scenario: User inspects a market date

- **WHEN** a user selects a chart date in Market
- **THEN** the workspace requests Date Evidence only for the selected date,
  selected lifecycle channel, and resolved Context `snapshot_id`
- **AND THEN** it presents provider, reconciliation, clocks, markers, and
  lineage from the server response without recalculating an outcome in the
  browser
- **AND THEN** it renders the evidence as current only when its returned
  snapshot identity equals the active Context identity

### Requirement: Assurance separates data fitness from market presentation

The workspace SHALL provide an Assurance task flow for gates, findings, purpose
fitness, and immutable run lineage. It SHALL distinguish not-formally-published
from blocked, unavailable, stale, or failed data rather than reducing every
state to a single trust number.

#### Scenario: Formal consumption is blocked

- **WHEN** the context purpose-fitness contract blocks Formal-system consumption
  or the trust payload contains a failed gate
- **THEN** Assurance displays the supplied blocked/failed state and associated
  evidence from the resolved Context `snapshot_id`
- **AND THEN** Market does not replace that state with a neutral score or an
  optimistic fallback

#### Scenario: Run lineage is requested

- **WHEN** a user opens the run-lineage subflow
- **THEN** the workspace fetches and renders the existing paginated runs payload
  and run diff only through the existing read-only endpoint builders
- **AND THEN** it does not fetch all run details eagerly or mutate catalog state
- **AND THEN** it labels Lineage as catalog-wide immutable history rather than
  claiming that it is same-snapshot proof for the selected Market view

### Requirement: Research evidence is descriptive and non-directional

The workspace SHALL expose H1 in a Research task flow using server-provided
hypothesis and research-run data. It SHALL keep research evidence distinct from
Market and Assurance, label it as non-directional, and never transform it into
a buy, sell, rank, score, or recommendation.

#### Scenario: H1 evidence is available

- **WHEN** the backend returns a current H1 hypothesis and research run
- **THEN** Research selects the API entry whose `hypothesis_id` is `H1` and
  renders the registered method, evidence identifiers, state, and
  unavailable/qualification messages supplied by the API
- **AND THEN** the DOM includes descriptive non-recommendation language
- **AND THEN** it presents the H1 dataset snapshot as separately scoped
  research evidence, never as confirmation of a selected Market snapshot

#### Scenario: Research evidence is unavailable

- **WHEN** the hypothesis or research-run request has no payload or fails
- **THEN** Research shows an explicit loading, unavailable, or error state
- **AND THEN** it does not display a synthetic effect, confidence, or success
  result

### Requirement: Point-in-time snapshot coherence

The workspace SHALL resolve selected-channel `ObsContext` before rendering
selected-snapshot Market or Assurance facts. Its immutable `snapshot_id`,
effective knowledge cut, knowledge mode, and revision policy SHALL bind
selected-channel series, Trust, and Date Evidence. Composite comparison SHALL
remain an independent-layer comparison with its own fingerprint and SHALL NOT
be presented as selected-snapshot proof.

#### Scenario: Historical Market bookmark remains coherent

- **WHEN** a user opens a Market or Assurance bookmark with a historical
  `knowledgeAsOf`
- **THEN** the workspace resolves Context once for that selected channel and
  knowledge selector
- **AND THEN** it sends the resolved `snapshot_id` for selected-channel series,
  Trust, and any selected Date Evidence request
- **AND THEN** it suppresses a panel whose returned snapshot differs, is absent,
  or fails PIT proof rather than showing latest catalog evidence beside the
  historical Market view

#### Scenario: Composite layer identity is inconsistent

- **WHEN** the composite comparison lacks the layer Context identity for the
  active selected channel
- **THEN** Market renders the comparison as unavailable or failed
- **AND THEN** it does not borrow Context, purpose fitness, Trust, Date
  Evidence, or prices from a different layer to imply coherence

### Requirement: Fail-closed workspace availability

The workspace SHALL remain reachable only after the existing fresh capability
authorization. Presentation refactoring SHALL distinguish transport/cache
freshness from the backend capability's evidence state.

#### Scenario: Capability response is not freshly authorized

- **WHEN** an application launch or direct `obsLens` URL has a cached, loading,
  revalidating, stale-response, failed, disabled, catalog-missing,
  catalog-corrupt, or route-registration-error capability result
- **THEN** navigation remains hidden and the Observatory workspace does not mount
- **AND THEN** the application resolves to the existing safe page behavior
- **AND THEN** an attempted direct link can be copied from a non-sensitive
  unavailable notice without exposing catalog internals

#### Scenario: Fresh catalog-stale evidence is inspectable

- **WHEN** capability returns a fresh successful `catalog_stale` payload with
  `enabled=true` and `show_nav=true`
- **THEN** navigation and the workspace remain available
- **AND THEN** the page presents its explicit stale/unavailable evidence rather
  than treating `catalog_stale` as a cached/stale transport response

### Requirement: URL compatibility

The workspace SHALL retain the current Observatory URL contract. Human labels
may map existing lens values to Market, Assurance, Lineage, and Research, but
the serialized values and query parameter names remain stable.

#### Scenario: Existing bookmark is restored

- **WHEN** a user opens a valid existing URL using `obsLens`, `obsChannel`,
  `knowledgeAsOf`, `obsRange`, `obsRun`, `obsCompare`, or `obsDate`
- **THEN** the workspace restores the equivalent task/lifecycle/date state
- **AND THEN** subsequent state updates preserve the same parameter names and
  valid serialized lens values

#### Scenario: Chart presentation state is restored

- **WHEN** a URL has `obsChart=market` or `obsChart=compare`
- **THEN** the corresponding selected-series or lifecycle-comparison surface is
  restored without changing any existing selector
- **AND THEN** missing or unknown `obsChart` values safely restore Market
- **AND THEN** legacy persisted objects missing chart mode are normalized by the
  shared Observatory schema before URL serialization or page render

#### Scenario: Existing lineage deep link maps to Assurance

- **WHEN** a user opens an existing `obsLens=runs` URL
- **THEN** the workspace visibly identifies the Assurance / Run Lineage
  subflow while retaining `obsLens=runs` in the URL
- **AND THEN** it does not load Market chart, Trust, or Research evidence until
  the user enters the corresponding task

### Requirement: Explicit unknown and failed states

Every request-driven workspace region SHALL distinguish loading, unavailable or
empty, and failed states. Missing lifecycle fields, rows, evidence, gates, or
research values SHALL not be converted to zero, a neutral score, an assumed
Formal status, or a normal success render.

#### Scenario: One panel fails while other evidence remains confirmed

- **WHEN** a panel-specific request such as Date Evidence, gates, runs, or H1
  fails after the Market context has loaded
- **THEN** only the affected panel displays a labeled error state
- **AND THEN** other panels retain their own confirmed evidence labels without
  claiming that the failed panel succeeded

#### Scenario: A selector changes while an earlier request is pending

- **WHEN** a user changes channel, committed knowledge selector, date, run,
  compare run, or H1 run while an earlier request is pending
- **THEN** the workspace aborts the superseded request and clears its current
  truth state immediately
- **AND THEN** only a complete response whose request identity matches the
  active selection may render as confirmed

#### Scenario: A cached or revalidated request fails

- **WHEN** a same-identity ETag revalidation or a fresh request fails
- **THEN** the affected region displays failed or explicitly labelled previous
  evidence with its original identity
- **AND THEN** it never renders a cached payload from another channel, snapshot,
  knowledge cut, date, or run as current truth

### Requirement: Bounded and accessible evidence exploration

The workspace SHALL bound its browser work at extended history while preserving
auditable evidence access. It SHALL request server range windows for `30D`,
`90D`, and `1Y`, retain `All` as an explicit request, avoid persistent browser
storage of Observatory payloads, and provide keyboard-operable date inspection
with announced asynchronous state.

The selected K-line SHALL own one bounded Canvas chart instance and SHALL remove
all chart subscriptions, resize observation, and fullscreen listeners on mode
change or unmount. Pointer interaction SHALL have an equivalent keyboard and
text-summary path. Passive crosshair, hover, pan, zoom, resize, scale, and
fullscreen events SHALL NOT start network requests. Only an explicit click,
Enter/Space, or date-input pin may set `obsDate` and start one keyed,
snapshot-pinned Date Evidence request; a later pin SHALL abort the prior one.

#### Scenario: Extended history is rendered

- **WHEN** a user selects `30D`, `90D`, or `1Y`
- **THEN** the series request includes the corresponding Context-derived
  `from`/`to` window
- **AND THEN** chart geometry and Assurance coverage remain within their
  deterministic display budgets rather than rendering one interactive DOM node
  per raw historical date

#### Scenario: Validated history reaches the renderer envelope

- **WHEN** fixtures contain 730 or 7,300 supplied/declared UTC dates
- **THEN** Market keeps one chart, one candle series, one volume series, at most
  one Canvas marker per date, constant non-evidence DOM, and exact cleanup
- **AND THEN** more than 7,300 dates is explicit
  `CHART_CAPACITY_EXCEEDED`, never silent truncation or a frozen partial chart

#### Scenario: Keyboard date inspection

- **WHEN** a keyboard user focuses the Market date inspector and selects a date
- **THEN** the workspace opens the same snapshot-pinned Date Evidence as a
  pointer selection
- **AND THEN** it announces loading or failure and moves focus to the evidence
  panel, with Close returning focus to the inspector

#### Scenario: Chart renderer is replaced or unmounted

- **WHEN** the user changes chart mode, the selected series identity changes, or
  the workspace unmounts
- **THEN** the previous renderer subscriptions and resize/fullscreen observers
  are detached and the chart is removed exactly once
- **AND THEN** crosshair movement, resize, and keyboard navigation do not create
  a new API request or duplicate chart instance

#### Scenario: Chart module or renderer operation fails

- **WHEN** lazy module load, chart creation, series creation, data application,
  resize, fullscreen, or a renderer callback fails
- **THEN** the failure remains inside the Market chart region, partial resources
  are cleaned idempotently, and Context/lifecycle warnings plus the external
  Market/Compare switch remain available
- **AND THEN** the UI shows only a safe renderer code, offers user-triggered
  Retry and Compare, starts no retry loop, and never exposes a raw exception,
  stack, path, or payload
- **AND THEN** queued animation/fullscreen/observer callbacks after replacement
  or unmount are ignored by the disposed identity and cannot recreate state
