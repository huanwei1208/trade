## Context

`trade_web/frontend/src/pages/observatory/ObservatoryPage.tsx` already consumes
the read-only BTC Observatory contract. It fetches the context and independent
composite layers, then conditionally mounts Trust, Runs & Lineage, and Research
lenses. The flow is semantically safe, but task discovery is weak: the default
screen starts with low-level selectors and four equal-weight tabs instead of
answering the latest market-state question first. This change reorganizes that
same client surface into a BTC Research Workspace.

The backend owns all data semantics. `trade_web/backend/observatory/` resolves
Formal, evaluated-candidate, and observed channels from immutable data. The
frontend must never parse canonical files, recompute formal metrics, merge
channels, or infer a successful/neutral result when data is unavailable.

## Design Quality Brief

### Requirements and acceptance

The primary user is a researcher reviewing locally available BTC daily data.
Within one screen they must be able to identify: the selected lifecycle channel,
its Formal relationship, permitted purpose, current watermarks, and the
evidence path for any date. A separate Assurance mode must expose gates and
immutable runs without making them look like a trading decision. A Research
mode must show the registered H1 evidence with language that is explicitly
descriptive and non-directional.

Acceptance requires:

- Market opens as the default task flow with one selected-channel exchange-style
  daily K-line. The existing three-layer composite SVG remains an explicit
  Compare mode and source-level rollback surface.
- The Market chart provides a right price axis, UTC time axis, volume,
  crosshair-backed exact-string OHLCV readout, drag pan, wheel/pinch zoom,
  fit/reset, go-to-latest, fullscreen, responsive sizing, and keyboard date
  navigation without claiming intraday or live data.
- Formal, evaluated candidate, and observed are never merged or visually
  rebranded as equivalent published data.
- Market and Assurance resolve one selected-channel `ObsContext` first. Its
  immutable `snapshot_id` then pins selected-channel series, Trust, and Date
  Evidence; no panel may combine a historical Context with current gates or
  date rows.
- Every request-driven region has explicit confirmed, loading,
  empty/unavailable, and failed handling. A query-key change or failed request
  cannot reuse prior data as current truth; no missing data becomes zero or a
  neutral conclusion.
- Existing `obsLens` URLs and capability-gated navigation stay compatible.
- All behavior changes receive focused frontend tests for snapshot propagation,
  stale-response cancellation, direct URL mode mapping, explicit unavailable
  states, and bounded rendering, plus the native typecheck/build and repository
  quality checks.

Non-goals are trading advice, data ingestion, backend contract changes, and
cross-asset expansion.

### Ownership and boundaries

`trade_web/frontend/src/pages/observatory/` owns workspace-level view
composition and request orchestration. Mode containers there own all GET state,
request identity, retries, and cancellation. A dedicated typed Observatory
resource hook at the frontend API boundary owns ETag-aware, bounded in-memory
reuse. Page code may select which already-owned presentational component to
render, but it does not calculate market or research facts.

`trade_web/frontend/src/components/observatory/` owns cohesive visual
representations: context/state summary, the repository-owned exchange-chart
wrapper, composite comparison, date evidence, trust and gate evidence, run
lineage, and H1 research evidence. A new workspace
header or mode navigation component belongs there because both the page and
future BTC deep links need the same vocabulary.

`trade_web/frontend/src/lib/observatory.ts` owns URL-state-compatible labels,
the `obsChart` schema/default/serialize/deserialize/legacy-normalize contract,
range bounds, selection, comparison downsampling geometry, and pure display
helpers. `App.tsx` owns browser URL cleanup/whitelisting and persisted-state
normalization. `trade_web/frontend/src/lib/observatoryChart.ts` owns only the
vendor-neutral daily-series conversion model, strict data validation, UTC daily
lattice, marker/diagnostic mapping, and original-row lookup required by the
exchange-chart wrapper.
`trade_web/frontend/src/lib/api.ts` remains the typed same-origin API boundary.
`App.tsx` and `AppShell.tsx` retain the fresh capability authorization and
navigation ownership, including a non-sensitive unavailable notice that preserves
an attempted direct workspace link without mounting the workspace. Backend
routes, resolver logic, catalog reads, and research calculations remain untouched
in their existing owners.

All components in `components/observatory/` are presentational after this change:
in particular, Run Lineage receives already-resolved detail/diff state and never
starts a browser fetch itself. This avoids three incompatible request lifecycles
and makes every panel obey the same cancellation and truth-state contract.

### Data and state invariants

- Asset identity remains `crypto.BTC`; its contract, quote, interval, timezone,
  provider, watermarks, and purpose fitness come from `ObsContext`.
- A selected-channel Context is the Market/Assurance evidence anchor. Once it
  resolves, its `snapshot_id`, resolved channel, effective knowledge cut,
  knowledge mode, revision policy, and view fingerprint define the active
  selected-snapshot identity. Selected-channel series, Trust, and Date Evidence
  must request that exact `snapshot_id` and confirm that their returned identity
  matches it before rendering as current.
- `formal`, `evaluated_candidate`, and `observed` are independent backend
  channels. Formal is the only published baseline. Market renders exactly the
  selected channel; Candidate and Observed retain persistent unpublished,
  non-color framing. Compare renders the channels as independent layers and
  never blends their values.
- Composite is an intentional independent-layer comparison, not a
  selected-snapshot payload: the backend rejects `snapshot_id` for composite
  views. It uses the same committed `knowledge_as_of`, range, and revision
  selector as Market, exposes its own `fingerprint_basis`, and must never
  populate selected-channel Context, Trust, Date Evidence, purpose fitness, or
  summary facts. If the layer that corresponds to the selected channel does not
  carry the selected Context `snapshot_id`, the chart is unavailable until a
  reload resolves a coherent comparison.
- Prices and volumes remain backend-provided decimal strings. A chart renderer
  may parse a finite decimal only for geometry; its external OHLCV readout and
  accessible selected-candle summary use the original server strings. Invalid
  or incomplete rows become omitted/marked evidence, never zero. The browser
  does not calculate a return, indicator, signal, or recommendation.
- A chart date is a real Gregorian UTC `YYYY-MM-DD`. Geometry accepts strict
  decimal syntax only: all OHLC fields are required, finite, and positive;
  supplied volume is finite and non-negative; `high`/`low` enclose open and
  close. Missing volume remains unavailable. Malformed dates invalidate the
  series. Duplicate dates are never resolved first/last: the duplicated date
  has no candle and carries `DUPLICATE_DATE` renderer evidence.
- The adapter consumes rows plus selected Context `excluded_dates`, sorts only
  after validation, and emits a UTC daily lattice between the first and last
  supplied/declared date. Omitted, missing, unobserved, quarantined, duplicate,
  and client-invalid dates become whitespace with deterministic combined
  reasons; no gap is extrapolated outside those bounds.
- Adapter state is `ready`, `partial-invalid`, `empty`, or `invalid` with
  supplied/rendered/invalid counts, affected dates, and safe renderer reason
  codes. Partial-invalid is persistently visible and accessible; zero valid
  candles is unavailable. These diagnostics never become backend quality or
  purpose-fitness facts.
- Contract/provider/instrument/quote/interval labels come only from active
  `ObsContext.contract`; UTC is the frozen Observatory display policy and the
  primary interval must be the supported UTC-daily contract. Populated row provenance must agree. Missing or
  mixed identity is unavailable, Binance shadow remains an assurance reference,
  and volume remains unitless. Per-row revision markers render only when the
  selected-series payload actually supplies them; quarantine comes from Context.
- Browser code may select a raw server row for display, map API states to labels,
  window request dates, convert finite daily values to renderer geometry,
  downsample comparison SVG geometry, and describe layer structure.
  It must not compute extrema, returns, confidence, quality, formal eligibility,
  research outcome, ranking, or recommendation. The client-calculated “Window
  peak close” is removed rather than preserved under a new label.
- The page query state is the source for a deliberate deep link:
  `obsLens`, `obsChannel`, `knowledgeAsOf`, `obsRange`, `obsRun`, `obsCompare`,
  `obsDate`, and additive `obsChart`. `obsChart` accepts `market` or `compare`;
  missing/unknown values restore `market`. The internal lens serialization
  remains stable while human labels change to Market, Assurance, Run lineage,
  and Research. The visible
  mapping is:

  | Serialized lens | Visible location | Semantic scope |
  | --- | --- | --- |
  | `overview` | Market | Default selected-snapshot market evidence |
  | `trust` | Assurance / Gates | Selected-snapshot quality and coverage |
  | `runs` | Assurance / Run lineage | Catalog-wide immutable run history, not proof for the current Market snapshot |
  | `research` | Research | Separately scoped H1 receipt, never inferred as evidence for the selected Market snapshot |

- A selected date is optional. It only triggers Date Evidence for that date,
  selected channel, and resolved Context `snapshot_id`; closing it clears the
  selection without changing lifecycle data.
- Every resource has one of `confirmed`, `loading`, `unavailable`, `failed`,
  or optional `stale-previous` state. The implementation chooses the safest
  default—clearing old data on identity change or failure. If a future screen
  deliberately displays old data, it must render it only under a prominent
  “previous cached evidence — not current” state with its original identity.

### Contracts and compatibility

The public contract is presentation-level. The existing `PageKey` remains
`observatory`, capability authorization remains a fresh successful
`show_nav === true` response, and all API route builders/typed payloads remain
unchanged. Existing saved URLs retain their exact serialized values:
`overview`, `trust`, `runs`, and `research`; the UI maps them to task labels
rather than introducing a new URL version. `obsChart` is an additive
presentation selector; it does not alter channel, snapshot, knowledge, range,
run, compare-run, or selected-date identity.

Legacy localStorage objects are merged through the canonical Observatory
normalizer before page render or URL serialization. `App.tsx` adds `obsChart` to
both the URL cleanup set and denied-link safe whitelist. Future interval/source
selectors require independent validated parameters; they cannot overload
`obsChart` or silently select another provider/data family.

No backend response field becomes required beyond the current optional typed
models. When a field is absent, the UI renders a labeled unknown/unavailable
state instead of synthesizing a number. Existing navigation stays hidden for
disabled, missing, corrupt, error, loading, stale-response, cached, or
revalidating capability results. A fresh successful backend `catalog_stale`
state remains visible under its existing `enabled/show_nav` contract. Rollback
is a frontend source revert because no state migration or durable artifact is
created.

`knowledgeAsOf` remains a committed URL selector rather than a request per
keystroke: the visible input keeps a draft and writes the URL on Enter or blur.
Mode-specific controls prevent an irrelevant Market selector from looking as if
it governed global Lineage or Research data. Market exposes channel, range, and
knowledge; Assurance exposes the selected channel and its evidence window; Run
Lineage exposes run/compare selection; Research exposes no synthetic Market
selector.

The existing market endpoint supports `snapshot_id` for selected-channel series,
Trust, and Date Evidence but deliberately rejects it for composite comparison.
Runs and Research also have separate immutable authorities and no snapshot
selector in the frozen API. The frontend must not invent cross-scope joins:
Lineage is labelled catalog-wide, while Research shows its own
`dataset_snapshot_id`/`knowledge_as_of` and a “separately scoped research
evidence—not confirmation of the selected Market snapshot” notice whenever a
Market identity exists in retained URL state.

### Failure and recovery

The workspace must preserve existing fail-closed availability:

- While capability transport/cache state is loading, stale-response,
  revalidating, cached, disabled, missing, corrupt, failed, or unregistered,
  `App.tsx` routes a direct Observatory request to Today and hides its navigation
  link. A denied direct link retains a copyable attempted URL and a
  non-sensitive unavailable notice. A backend `catalog_stale` state remains
  mountable only from a fresh successful payload with `enabled=true` and
  `show_nav=true`, so the page can expose explicit stale evidence.
- A selected-channel Context failure blocks its dependent selected-series, Trust,
  and Date Evidence requests. Context absence is rendered as unavailable/error,
  never as a BTC header filled with em dashes.
- A composite, trust, runs, hypothesis, research-run, or date-evidence request
  can fail independently. Its affected panel displays an explicit error while
  other confirmed panels remain labeled with their own snapshot or immutable
  run identity.
- Any returned snapshot, date, run, hypothesis, or composite-layer identity
  that differs from the active request identity is discarded. A superseded
  request is aborted, not merely ignored after it spends network capacity.
- An absent layer is shown as absent; it is not copied from another channel.
  Missing dates remain chart gaps.
- `PIT_NOT_PROVEN`, `QUALITY_BLOCKED`, `CHANNEL_UNAVAILABLE`,
  `SNAPSHOT_NOT_FOUND`, catalog stale/corrupt, integrity failures, missing
  OHLCV, quarantined rows, and revisions remain their supplied unknown,
  blocked, or marked states. None promotes a row to Formal/published/current
  truth.
- Candidate or observed data that advances beyond Formal remains visibly
  unpublished and never changes the purpose-fitness result by browser logic.
- Refresh uses the existing application refresh token. It repeats read-only GET
  requests for the active mode, including selected Date Evidence, run detail,
  run diff, and research run; it does not start sync, catalog rebuild, research
  execution, or any provider network call.
- Module-load, chart-create, series-create/data-apply, resize, and unexpected
  renderer callback failures are contained below the external Market/Compare
  switch. They preserve Context/lifecycle warnings, render only safe codes
  (`CHART_MODULE_LOAD_FAILED`, `CHART_CREATE_FAILED`, `CHART_DATA_REJECTED`,
  `CHART_RUNTIME_FAILED`), expose manual Retry and Compare, and never show raw
  errors, stacks, paths, or payloads. Retry has no loop. Partial construction and
  queued callbacks use an identity/disposed guard and idempotent cleanup.

Recovery for an unavailable backend is operational: restore or verify the
backend Catalog using its existing tools, then refresh. The UI offers no false
recovery action and writes no data.

### Performance and capacity

The request matrix is mode-gated:

| Visible mode | Initial reads | Deferred reads |
| --- | --- | --- |
| Market / selected K-line | selected-channel Context; selected-channel bounded series | one selected Date Evidence |
| Market / Compare | selected-channel Context; bounded composite comparison | one selected Date Evidence |
| Assurance / Gates | selected-channel Context; selected-channel bounded coverage series; same-snapshot Trust | one selected Date Evidence after entering Market |
| Assurance / Run lineage | paginated runs only | selected run detail and explicit base/compare diff |
| Research | H1 hypothesis list and its explicit H1 research run | none unless the user refreshes |

Market never requests composite; Compare never requests selected series.
Compare date pinning uses selected Context `snapshot_id` directly and validates
the returned date/snapshot without gating on selected-series confirmation.
Composite OHLC cannot populate selected-channel summary or Date Evidence. In
Market, selected-series summary panels render; in Compare, lifecycle comparison
and selector-independent “what changed” render while selected-series metrics do
not. Their errors and retries remain mode-local.

Market and Assurance issue Context first, then derive server `from`/`to`
parameters from its market watermark plus `30D`, `90D`, or `1Y`. `All` is an
explicit user request for the complete supported history, not an accidental
unbounded default. URL range remains round-trippable even when a mode does not
surface the control.

No Observatory payload is persisted to `localStorage`. A small byte-capped
in-memory LRU may retain only a canonical full request identity, its ETag, and
its parsed response. Revalidation sends `If-None-Match` only for that same
identity; a `304` may reuse only that entry. A 304 without matching memory
payload is failed/unavailable, never a silent success. This avoids synchronous
large-payload parsing and semantic cache collisions across channel, as-of,
snapshot, date, or run selectors.

At 10x historical range, chart request windows bound transport except for
explicit `All`. The selected daily series uses one Canvas chart instance, one
candlestick series, and one volume series; crosshair movement performs no fetch
and does not recreate the chart or series. Compare keeps a 720-point-per-layer
SVG geometry budget through deterministic display-only downsampling. Chart
interaction uses library subscriptions plus an adjacent keyboard-operable date
input/summary, not one interactive DOM node per date. Mode change and unmount
detach crosshair/range/fullscreen subscriptions, disconnect the
`ResizeObserver`, and remove the chart exactly once. Coverage renders a bounded
recent window and a concise count/continuation affordance rather than a button
per catalog date. Runs remain
cursor-bounded; no detail, diff, research, polling, animation loop, client-side
research calculation, or default all-run expansion is added. Structural budget
tests, not unstable wall-clock benchmarks, verify those limits.

The vendor library is a Market-only lazy Vite chunk. Main-entry gzip growth is
limited to 8 KiB and the chart chunk to 60 KiB gzip; exceeding either requires
design review before closeout. Crosshair callbacks retain model/lookup in refs,
coalesce with one `requestAnimationFrame`, and commit only when the business date
changes. Hover is non-live; only click/keyboard/date-input pinning writes URL
state and may start one keyed Date Evidence request. A newer pin aborts the old
request. At 730 and 7,300 supplied/declared dates, tests retain one chart, two
series, at most one Canvas marker per date, constant non-evidence DOM, and exact
cleanup. Beyond 7,300 dates the chart fails explicitly with
`CHART_CAPACITY_EXCEEDED`; it never silently truncates. Bundle deltas and a
Chromium 730/7,300 adapter/readiness/crosshair smoke are recorded in the plan.

### Observability and operations

The header presents snapshot/run identity, lifecycle state, watermarks, and
purpose fitness from `ObsContext`, making a human-visible audit trail before
they inspect charts. Assurance names gates/findings and links run identifiers
through existing lineage components. Date Evidence retains provider, basis,
four clocks, markers, revision, and run lineage.

An `ObservatoryErrorState` presentation component converts safe
`ApiError.detail` fields into status, reason code(s), evidence references, and
retry guidance without displaying local paths or raw exceptions. Every async
state uses `aria-busy`, a status or alert live region, and non-color text.
Date inspection is keyboard operable; a Canvas-accessibility layer exposes a
named chart, left/right candle navigation, an adjacent exact-string OHLCV live
summary, named native controls, focus states, and non-color lifecycle meaning.
Passive hover uses a separate non-live visual readout. The polite live region
announces only an explicitly pinned or keyboard-committed date once. Keyboard
navigation covers the union of candle and Context-excluded dates.
Selecting or pinning a date announces the selected date and moves focus to the
evidence panel, while Close returns focus to the date control. Existing browser tests cover fail-closed navigation and
label/DOM invariants; new tests cover keyboard access and failed/unavailable
fixtures. Operators continue to use the existing capability endpoint and CLI
for catalog diagnosis; this frontend change adds no telemetry, logs,
operational command, or alert.

Local renderer diagnostics expose only asset, channel, sanitized snapshot ID,
knowledge cut, range, chart mode, counts, affected dates, and safe reason codes.
They never expose raw exceptions, paths, or payloads. Backend/catalog codes point
to the existing read-only catalog status/verify workflow; renderer codes point
to manual Retry or Compare; fullscreen unavailability retains in-page mode.

### Validation strategy

Focused Vitest tests cover mode labels/defaults, four-lens URL mapping, stable
URL values, status summary behavior, explicit errors/unavailable states, H1
non-recommendation language, and the absence of browser-computed window peaks.
Deferred fetch fixtures prove a channel/as-of/date/run/hypothesis change aborts
the earlier request and cannot render its response under the new identity.
Request-spy tests prove:

- Market sends bounded `from`/`to` series requests only after Context and never
  loads Trust, Runs, or H1;
- Assurance uses the exact resolved Context `snapshot_id` for coverage, Trust,
  and Date Evidence; historical `knowledgeAsOf` cannot drift to a later catalog
  snapshot;
- Lineage and Research are mode-gated, refresh their selected evidence, and
  expose their separate immutable scope rather than pretending to be selected
  Market snapshot proof;
- cache/304 reuse is keyed by complete identity and failure never renders a
  different query's cached payload as current;
- `PIT_NOT_PROVEN`, quality/catalog/integrity errors, absent channels, missing
  OHLCV, quarantined/revised rows, and unavailable H1 all remain explicit
  non-success states;
- chart/calendar render structure obeys its display budgets, creates and removes
  one renderer/subscription set, and keeps date inspection keyboard accessible;
- Market/Compare state restores additively without changing existing URL
  selectors; crosshair, resize, fit/latest, scale, and fullscreen fallback have
  deterministic component tests.

Existing tests remain responsible for three-layer semantics, missing-date chart
gaps, non-color markers, date-evidence clocks, and capability fail-closed
navigation. E2E mocks must assert received query parameters rather than
returning success for every selector.

Validation runs in this order:

1. targeted `npm --prefix trade_web/frontend run test:unit`;
2. native frontend `typecheck`, `lint`/format through the repository gate, and
   `build`;
3. `./trade dev check --show-plan`, `./trade dev check`, and `git diff --check`;
4. existing E2E and a11y scripts when Playwright/browser dependencies are
   available; any missing runtime is reported as a validation blocker, not
   bypassed by test changes.

No test uses real data, opens a live provider connection, or mutates a catalog,
database, or parquet file.

### Point-in-time and predictive evidence

This is a point-in-time presentation change, not a new model or prediction.
The existing server resolver is the authority for `installation_observed`,
`as_known`, immutable snapshot selection, and `PIT_NOT_PROVEN`. The frontend
does not create decision, feature, label, outcome, or promotion facts.

- **Clocks and timezone:** Market date/bars retain server-provided event/bar,
  available, fetched/first-seen, publication/certification, and revision
  evidence in UTC. An absent clock is shown as explicit unavailable with its
  server provenance; it is never inferred from browser time.
- **Snapshot identity:** Context supplies the selected snapshot/run/release,
  effective knowledge cut, knowledge mode, revision policy, and fingerprint.
  Same-snapshot Market/Assurance requests must echo that identity. Composite
  retains its multi-layer `fingerprint_basis`; Research retains its own
  `dataset_snapshot_id` and is not joined into the market snapshot.
- **Coverage and leakage:** Historical views honour server PIT proof. A
  `PIT_NOT_PROVEN` response blocks the affected view; later revisions, current
  gates, current research, and future labels cannot fill the gap. Date Evidence
  retains `research_visibility=not_visible`; only the separately labelled
  Research view may show its existing future-outcome region.
- **Research display:** H1 metrics, evidence, state, and uncertainty are
  server-provided receipt fields only. The UI makes no out-of-sample,
  calibration, regime, sample, horizon, baseline, or promotion claim when that
  receipt does not contain the corresponding qualification. It renders
  unavailable rather than a numeric fallback.
- **Future data families:** A later news or sentiment feature must be a
  separately versioned `data_family` with its own source, coverage, semantic
  precision, `available_at`, revision, and immutable snapshot/run evidence. It
  may appear only as separately labelled research evidence, never as a Market
  chart layer, market watermark, lifecycle channel, or inherited purpose-fitness
  result. No-observation is `unknown`/`unobserved` unless successful source
  receipts prove zero events. Any causal language requires a separately
  pre-registered H3/PIT validation contract.
- **Future hypothesis selection:** This slice accepts the existing H1 only. A
  later multi-hypothesis API requires an explicit `hypothesis_id` URL state and
  server-defined ordering/default; a missing selected hypothesis must become
  unavailable, never fall back to the first item or another data family.

### Alternatives and trade-offs

1. **Leave the current four equal tabs intact.** Rejected because lifecycle
   status, data confidence, and H1 research are not equally frequent tasks;
   users have to build their own mental model before seeing the current state.
2. **Build a new BTC-only backend summary API.** Rejected for this slice because
   the Observatory context/composite/trust/runs/research contracts already
   expose the required facts. A duplicate summary would create another contract
   and drift risk.
3. **Rename serialized lenses to new route values.** Rejected because saved URLs
   and test fixtures would lose compatibility for a cosmetic information
   architecture change. Human labels can change without changing contract keys.
4. **Show one blended “BTC price” line.** Rejected because it would erase the
   Formal/Candidate/Observed lifecycle boundary and could misrepresent
   unpublished data as Formal.
5. **Treat a current research receipt or catalog run as proof for a historical
   Market selection.** Rejected because Research and catalog-wide Lineage have
   their own frozen authorities and no same-snapshot selector. They remain
   separately labelled evidence rather than an invented cross-scope join.
6. **Keep broad persistent browser caches for Observatory payloads.** Rejected
   because cache collision or failed revalidation can make an older selected
   snapshot appear current. Bounded same-identity memory/ETag reuse is the only
   allowed optimization.
7. **Extend the current SVG into an exchange chart engine.** Rejected because it
   would add custom axes, hit testing, gesture transforms, density management,
   accessibility synchronization, and cleanup behavior to product code.
8. **Embed a hosted TradingView widget or add intraday/live data.** Rejected
   because a hosted feed would not represent the snapshot-pinned local series,
   while intraday/live requires new bar-finality, pagination, streaming, and
   volume-unit contracts.

The chosen approach uses TradingView Lightweight Charts behind a
repository-owned React wrapper for the selected daily series. It adds no hosted
script, CDN, telemetry, provider call, or backend contract. The package and
generated lock remain pinned, required attribution is preserved, and the
existing composite stays available for comparison and source rollback. The page
shows the NOTICE attribution and TradingView link as “charting library,” separate
from the local selected-series provider and “not live” data provenance.

### Rollout and rollback

Rollout is an ordinary frontend deployment behind the existing capability gate.
The workspace is reachable only from a fresh successful capability payload with
`enabled=true` and `show_nav=true`; that includes the existing inspectable
`catalog_stale` state as well as ready. It can be released with the existing
backend because no route or payload version changes.

Before release, validate ready, fresh `catalog_stale`, and every fail-closed
transport/cache fixture plus the frontend build. A disabled/missing/corrupt
installation remains unaffected because the navigation entry stays absent. Rollback reverts the
frontend source; it does not roll back or alter data, Catalog generations,
research receipts, browser storage, or API routes.

## Implementation outline

1. Introduce a keyed Observatory GET resource and typed presentation state that
   clears current truth on identity replacement, aborts superseded requests,
   uses bounded same-identity ETag reuse, and preserves structured safe API
   errors.
2. Refactor `ObservatoryPage` into Market, Assurance/Gates, Assurance/Run
   Lineage, and Research containers. Keep every request hook in the page
   container layer; keep existing visual components reusable and fetch-free.
3. Resolve selected-channel Context first. Pin selected-channel series, Trust,
   and Date Evidence to its snapshot; validate returned identities. Keep
   composite as a separately labelled, selector-equivalent layer comparison and
   suppress it on selected-layer mismatch.
4. Consolidate Market around contextual state, scoped controls, a budgeted
   lifecycle chart, concise non-computed evidence summary, and accessible
   on-demand Date Evidence. Consolidate Assurance around same-snapshot
   gates/findings and explicitly separate catalog-wide lineage. Keep Research
   H1-only, explicitly chosen by `hypothesis_id === "H1"`, and evidence-only.
5. Extend focused frontend tests before/with each behavior change. Preserve
   capability/navigation, chart integrity, PIT propagation, request budget,
   race/error, URL compatibility, and accessibility assertions.
6. Add the selected-channel exchange K-line through a pure adapter and
   repository-owned chart wrapper; mode-gate the retained composite as Compare,
   preserve exact strings and publication framing, and validate resize/event
   cleanup, keyboard access, responsive layout, and the additive `obsChart`
   contract.
7. Correct the frontend `marker_position` type to the existing backend string
   contract, add an actual-query-output-shaped fixture, and keep revision
   markers conditional on supplied row evidence without expanding the backend.

## Follow-up amendment: timeframe and click interaction

### Requirements and acceptance

The Market chart adds `1D`, `1W`, `1M`, and `1Y` display controls. Daily API
rows remain the only authoritative input. Aggregated bars use the first valid
open, exact maximum high, exact minimum low, last valid close, and exact summed
volume when all contributing volume values are supplied. A bucket with some
missing/invalid daily evidence remains visibly partial; a bucket with no valid
daily bar remains whitespace. The additive `obsTimeframe` URL value defaults to
`1D` for missing or unknown input.

Ordinary chart clicks update only local inspection state. They do not call the
page URL-state writer, do not mount Date Evidence, and do not navigate to the
chart vendor. Evidence pinning remains explicit through the Inspect button,
Enter/Space, or date input. The in-canvas outbound attribution logo is disabled;
the repository footer link and NOTICE remain the attribution authority.

### Ownership and boundaries

`observatoryChart.ts` owns pure exact-decimal bucket aggregation and diagnostic
mapping. `ExchangeKlinePanel` derives the display model from the validated daily
model. `ExchangeKlineChart` owns timeframe controls, local inspected date, and
explicit pin affordances; `ObservatoryPage` continues to own URL state and Date
Evidence requests. `App.tsx` only serializes the additive `obsTimeframe` value.
No backend, API payload, provider, or lifecycle-channel owner changes.

### Data and state invariants

The source interval remains `1Dutc` and all aggregation uses UTC calendar
boundaries: ISO weeks begin Monday, months begin on day one, and years begin on
January one. Aggregation never combines lifecycle channels or changes the
selected snapshot identity. Exact decimal strings are retained for aggregate
readouts; numeric conversion is geometry-only. Local inspection is not a
committed evidence selection, so it cannot start a Date Evidence request.

The aggregation representation is bounded fixed-point `BigInt`: decimal strings
are parsed into signed integer/fraction parts, aligned by scale for extrema and
sum, and formatted deterministically with trailing fractional zeroes removed.
Inputs exceeding 128 total decimal digits produce an explicit
`AGGREGATE_DECIMAL_OVERFLOW` renderer failure rather than rounding. A bucket's
canonical evidence date is the latest valid daily constituent. Its metadata
retains bounded bucket start/end, covered/valid counts, source interval,
selected snapshot/channel identity, and capped reason/evidence references. A
missing volume in any otherwise valid contributor makes aggregate volume
unavailable and marks the bucket partial; an invalid-volume row follows the
existing strict adapter and contributes no OHLCV.

The active request window defines the covered daily lattice, so a bucket clipped
by the requested range edge is not partial solely because the full calendar
week/month/year is outside the window. Partial means a covered date is missing,
excluded, invalid, or lacks required volume. `timeframe` is controlled page
state passed to the panel/chart; its memoized display derivation does not enter
API request keys and does not invalidate Context or Date Evidence.

### Failure, performance, and validation

Invalid/empty/partial buckets use explicit renderer diagnostics and never become
zero-valued candles. The aggregation pass is O(n) over the already bounded daily
model and does not add DOM nodes, requests, polling, or persistent cache state.
Unit tests cover decimal extrema/sums, UTC week/month/year boundaries, partial
and empty buckets, URL normalization, click isolation, and explicit pinning.
Chromium tests cover timeframe switching, no-navigation clicks, explicit Date
Evidence pinning, a11y, and the existing 730/7,300 performance envelope.

### Rollout and rollback

This remains a frontend-only additive presentation change. Existing URLs restore
`1D`; reverting the frontend removes the controls without data or API migration.
