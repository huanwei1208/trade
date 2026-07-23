# 29 Plan - BTC Observatory Exchange-Style K-line V2

Date: 2026-07-22

Status: Complete - implemented-diff review, digest-bound approval, and squash
integration passed

Integrated commit: `566c5587fe216df4563fcc555437486c88de7a2a` on local `master`

Owning OpenSpec change: `btc-research-workspace` (amendment; not a competing
parallel change)

## 1. Outcome

Optimize the BTC Observatory Market view so its primary K-line behaves like a
modern exchange chart while preserving the Observatory's stricter evidence and
lifecycle semantics.

The default Market surface will show one selected lifecycle channel as a clear,
full-width daily candlestick chart with:

- right-side price scale and bottom UTC time scale;
- volume histogram;
- crosshair-driven OHLCV readout backed by the original API strings;
- drag pan, wheel/pinch zoom, fit/reset, go-to-latest, and fullscreen controls;
- responsive desktop, tablet, and mobile sizing;
- keyboard date navigation and an accessible selected-candle summary;
- a persistent distinction between Formal and unpublished Candidate/Observed
  data.

The existing three-layer Formal/Candidate/Observed SVG remains available as an
explicit Compare view and as a source-level rollback path. The new chart does
not blend lifecycle channels, invent intraday data, claim a live market feed,
or change backend data contracts.

## 2. Change classification and required gates

Tier: **Non-trivial**.

Reasons:

- it replaces the primary renderer and introduces a frontend dependency;
- it has multiple viable implementation approaches and meaningful performance,
  accessibility, compatibility, and lifecycle-truth trade-offs;
- it changes a public Web interaction surface and URL-restorable presentation
  state;
- it touches multiple frontend modules, tests, styles, and dependency metadata.

Required sequence:

1. Record this plan in `docs/` before implementation.
2. Amend the existing `btc-research-workspace` OpenSpec artifacts.
3. Run the diagnostic design check.
4. Run the six-role design consensus review and resolve all P0 findings.
5. Bind the review to the current artifact digest and full commit SHA.
6. Pass `./trade dev design-check btc-research-workspace --strict`.
7. Implement in committed, test-backed slices in this worktree.
8. Run focused and repository quality gates.
9. Run the six-role review again against the implemented diff and resolve every
   P0 finding.
10. Close this plan with commit, validation, performance, rollout, and residual
    risk evidence.

Production code must not change before step 6 passes.

## 3. Current evidence and problem

The current page already has safe selected-snapshot requests, three independent
lifecycle series, daily OHLC candles, volume bars, a selected-date evidence
lens, linear/log scale, non-color quality markers, and explicit unpublished
state.

The renderer is still a fixed-geometry custom SVG evidence graphic rather than
an exchange-style chart:

- geometry is based on a fixed 860 x 300 coordinate system;
- the time axis has only three labels;
- interaction is click-to-select plus a date input;
- it has no pointer-following crosshair, right price scale, native drag pan,
  wheel/pinch zoom, fit/reset, go-to-latest, or fullscreen behavior;
- three side-by-side lifecycle candles become visually dense at long ranges;
- the SVG scales responsively but does not maintain a usable mobile chart
  height;
- log/linear initialization does not follow later range changes reliably.

The existing API is sufficient for this phase. A selected series already
contains daily decimal-string OHLCV, date, provider/instrument, lifecycle,
quality, revision, and provenance metadata. The current provider contract is
OKX `BTC-USDT` `1Dutc` primary with Binance `BTCUSDT` `1d` as assurance shadow,
not as an end-user exchange selector.

Therefore this phase is frontend-only and daily-only.

## 4. Product and information architecture

### 4.1 Default Market view

```text
+-----------------------------------------------------------------------+
| BTC / USDT | active Context contract | Formal/Candidate/Observed state |
| O ... H ... L ... C ... Vol ... | newest supplied bar | freshness    |
+-----------------------------------------------------------------------+
| [90D] [1Y] [All] [Linear/Log] [Fit] [Newest bar] [Fullscreen]       |
|                                                                       |
|                         CANDLE CHART                                  |
|                                                       right price axis |
|                                                                       |
|                         VOLUME                                        |
| UTC ------------------------------------------------------ time axis   |
+-----------------------------------------------------------------------+
| Market | Compare lifecycle layers                                    |
+-----------------------------------------------------------------------+
| Selected-date evidence (desktop side panel / mobile drawer)           |
+-----------------------------------------------------------------------+
```

The chart is visually dominant. Context, freshness, publication state, and
failure warnings remain visible rather than being hidden in a tooltip.
It also says “Local Observatory snapshot · daily bars · not live.” TradingView
is identified only as the charting library; OKX/Binance remain data provenance
and assurance identities supplied by Context, not renderer branding.

### 4.2 Market versus Compare

- **Market**: one selected lifecycle channel, rendered with exchange-style
  interaction. This is the default.
- **Compare**: the existing three-layer Formal/Candidate/Observed composite SVG,
  separately labelled as a lifecycle comparison rather than selected-snapshot
  truth.
- The mode is additive URL state, proposed as `obsChart=market|compare`.
  Missing or unknown values safely fall back to `market`; all existing URLs
  remain compatible.
- Switching modes never changes lifecycle channel, knowledge selector,
  snapshot, range, or selected date.
- Request topology is explicit: Market resolves Context then selected series and
  never fetches composite; Compare resolves Context then composite and never
  fetches selected series. An explicit date pin in either mode may request Date
  Evidence directly from Context `snapshot_id`; composite OHLC never substitutes
  for selected-channel evidence.

### 4.3 Lifecycle truth

- Formal is the only published baseline.
- Evaluated Candidate and Observed remain visibly unpublished in the chart
  frame, legend, latest-value treatment, and selected-candle summary.
- Market displays the selected channel only; Compare displays independent
  layers. No value is averaged, substituted, or merged across channels.
- Missing or quarantined dates remain visible gaps/markers; the renderer must
  not bridge them into fabricated candles.
- Selected-channel requests remain pinned to the Context `snapshot_id`.
- Composite retains its separate selector-equivalent multi-snapshot identity.
- `PIT_NOT_PROVEN`, mismatch, corrupt, stale, denied, unavailable, and failed
  states remain explicit and cannot reuse an older payload as current truth.

## 5. Selected technical design

### 5.1 Renderer

Use TradingView Lightweight Charts behind a repository-owned React component.
It is selected because it provides the required Canvas candlestick rendering,
time and price scales, crosshair events, pan/zoom behavior, responsive APIs, and
volume support without rebuilding a chart engine in application code.

Dependency obligations:

- pin the package through the existing frontend package manager and generated
  lock file;
- retain required TradingView attribution and license notices;
- do not depend on hosted scripts, public CDNs, telemetry, or provider calls;
- isolate library types and callbacks behind local adapter/component boundaries
  so the renderer can be reverted or replaced.

HTML5 Canvas is sufficient for the bounded daily series. WebGL is not required.

### 5.2 Component boundaries

- `lib/observatoryChart.ts`: pure vendor-neutral conversion and presentation
  model. It validates the strict daily contract, emits a UTC daily lattice,
  gaps/diagnostics/marker metadata, retains an original-row lookup for exact
  readout strings, and never aggregates or computes formal metrics.
- `components/observatory/ExchangeKlineChart.tsx`: owns chart creation,
  candlestick/volume series, subscriptions, visible range, resize observer,
  controls, keyboard selection, fullscreen integration, and complete cleanup.
- `lib/observatory.ts`: owns the typed `obsChart` schema, default,
  serialize/deserialize/normalize behavior, including legacy persisted objects
  without the new field. `App.tsx` owns browser URL cleanup/whitelisting and
  local persistence. `ObservatoryPage.tsx` consumes normalized typed state and
  owns request identity/panel composition; it does not own chart geometry.
- `components/observatory/CompositeChart.tsx`: retained for Compare and rollback;
  only compatibility fixes necessary for shared state may be made.
- `styles/observatory.css`: owns chart-specific layout, responsive height,
  controls, lifecycle framing, focus states, and mobile drawer behavior.

### 5.3 Numeric and time handling

- Dates must be real Gregorian UTC `YYYY-MM-DD` values. Geometry strings must
  match strict decimal syntax before finite conversion; whitespace, hexadecimal,
  exponent-only shortcuts, `NaN`, and infinities are rejected.
- OHLC is all-or-none for a candle, strictly positive, with
  `high >= max(open, close, low)` and `low <= min(open, close, high)`. Volume is
  optional for candle display; a supplied volume must be non-negative. Missing
  volume stays unavailable and never becomes zero.
- Input may arrive out of order but is sorted ascending only after validation.
  Duplicate dates are never resolved first/last: every duplicated date becomes
  `DUPLICATE_DATE`, has no candle geometry, and stays visible in renderer
  diagnostics. A malformed date makes the series invalid.
- The adapter consumes rows plus Context `excluded_dates`. Between the first and
  last supplied/declared date it emits a UTC daily lattice with whitespace for
  omitted, missing, unobserved, quarantined, duplicated, or client-invalid dates;
  it does not extrapolate before/after those bounds. Reasons combine
  deterministically and retain safe evidence references.
- The OHLCV legend and selected-candle accessibility summary use the original
  server strings, not re-serialized floating-point values.
- No browser-calculated return, percentage change, indicator, signal, or
  recommendation is introduced.
- Provider/instrument/quote/interval labels come only from active
  `ObsContext.contract`; UTC is the frozen Observatory display policy and the
  primary interval must be the supported UTC-daily contract. Populated row provenance must agree. Missing contract
  identity or mixed/mismatched provenance makes the chart unavailable with a
  safe reason code. Binance shadow is an assurance reference, never a selected
  feed.
- Volume is labelled `Volume` without inventing a unit that the API does not
  currently provide.
- Adapter output includes supplied/rendered/invalid counts, affected dates and
  safe reason codes, with state `ready`, `partial-invalid`, `empty`, or
  `invalid`. Partial-invalid is a persistent warning; zero valid candles is
  chart-unavailable. These are renderer diagnostics, not purpose fitness or a
  server quality score.

### 5.4 Interaction and accessibility

- Pointer crosshair updates a non-live visual OHLCV summary. Events are coalesced
  through one `requestAnimationFrame` and commit React state only when the UTC
  date changes. Hover never writes URL state or starts a request.
- Only an explicit click, Enter/Space pin, or date-input commit sets `obsDate`
  and starts at most one keyed, snapshot-pinned Date Evidence request. A new pin
  aborts the prior request. Pan, zoom, resize, scale, fullscreen, and passive
  crosshair events never fetch.
- Left/right keyboard navigation covers the union of candle and explicit
  excluded dates, announces no-candle/excluded state, and pins only on explicit
  commit. A separate `aria-live="polite"` summary announces pinned/keyboard
  selection once; hover is not live.
- Mobile gestures explicitly keep one-finger vertical drag for page scroll,
  horizontal drag for chart pan, and pinch for zoom.
- Fit/reset restores the selected range; Newest bar scrolls to the newest
  supplied daily bar.
- Fullscreen uses the platform Fullscreen API when available and retains a safe
  in-page fallback state when unavailable.
- Controls are native buttons with names, focus indicators, pressed state, and
  disabled state.
- The Canvas has an accessible name/description and an adjacent live text
  summary; meaning does not rely on red/green color alone.
- Reduced-motion and high-contrast behavior must remain usable.

### 5.5 Renderer failure and recovery

- The chart is loaded as a lazy chunk only when Market mounts; its loader and
  error isolation sit outside the vendor-owned subtree, next to the always
  reachable Market/Compare switch.
- Module load, chart creation, series creation, data application, resize, or
  callback failure is contained locally. The UI keeps Context/lifecycle warnings,
  shows only safe codes (`CHART_MODULE_LOAD_FAILED`, `CHART_CREATE_FAILED`,
  `CHART_DATA_REJECTED`, or `CHART_RUNTIME_FAILED`), never raw exceptions/paths,
  and offers user-triggered Retry plus Compare. There is no automatic retry loop.
- Partial construction is disposed idempotently. An identity generation and
  disposed guard rejects queued crosshair/resize/fullscreen work after cleanup;
  pending animation frames are cancelled. Fullscreen exit occurs only when the
  component owns `document.fullscreenElement`, fallback state clears, focus is
  restored, and chart removal happens at most once.
- The page displays the required notice and link as charting-library attribution:
  “TradingView Lightweight Charts™ Copyright (c) 2025 TradingView, Inc.” with a
  link to `https://www.tradingview.com/`.

### 5.6 Resource and performance ownership

The page owns at most one mounted exchange-chart instance in Market mode and one
legacy composite in Compare mode. Mode changes and unmount must detach all
crosshair/range/fullscreen subscriptions and the `ResizeObserver` before chart
removal.

Budgets:

- daily-only selected Market series, currently about 730 rows for All;
- no polling, streaming, worker, retry loop, or live provider call;
- no one-DOM-node-per-candle structure;
- no remount or series recreation for crosshair movement;
- visible crosshair updates stay local to the chart/summary and do not trigger
  network requests;
- repeated mount/unmount tests must show one create/remove pair and no duplicate
  event subscription;
- Compare retains its existing 720-point-per-layer SVG geometry budget.
- the chart dependency is a lazy Vite chunk; main-entry gzip growth must be no
  more than 8 KiB and the chart chunk no more than 60 KiB gzip, or the design is
  reviewed again before closeout;
- deterministic 730-row and 7,300-row fixtures must keep one chart/two series,
  at most one Canvas marker per date, constant non-evidence DOM, zero passive
  event requests, and exact cleanup. More than 7,300 supplied/declared dates is
  an explicit `CHART_CAPACITY_EXCEEDED` unavailable state, never silent truncation;
- a Chromium smoke on this host records baseline/post-build raw+gzip assets,
  adapter time, initial chart-ready time, and a 100-event crosshair burst. Review
  thresholds are 100/500 ms adapter time and 1.5/3.0 seconds initial readiness
  for 730/7,300 rows; the crosshair burst must coalesce to at most one commit per
  frame and must not recreate chart/series or issue requests.

## 6. Alternatives and trade-offs

### A. Extend the existing SVG into a full chart engine

Rejected. It avoids a dependency but requires custom axes, hit testing, gesture
handling, pan/zoom transforms, density management, accessibility synchronization,
and cleanup logic. The maintenance and correctness surface is larger than the
product-specific code.

### B. Embed TradingView's hosted Advanced Chart widget

Rejected. It would display an external feed and hosted behavior instead of the
snapshot-pinned local Observatory evidence. It also weakens offline operation,
provenance, lifecycle semantics, and network boundaries.

### C. Replace all lifecycle charts with one Market chart

Rejected. A single exchange-style series is clearer for normal inspection, but
removing the composite would erase the direct Formal/Candidate/Observed
comparison and make rollback harder.

### D. Add intraday intervals and live candles now

Rejected. The current API contract is daily and immutable. Intraday/live needs
an explicit interval, bar-finality, pagination, streaming, and volume-unit
contract and must be a separate OpenSpec change.

### E. Selected approach

Add a repository-owned Lightweight Charts Market surface while retaining the
legacy composite as Compare. This maximizes exchange-like usability while
keeping local data authority, lifecycle truth, URL compatibility, and a small
rollback boundary.

## 7. Implementation slices and commit plan

### Slice 0 - plan and approved design

- add this durable plan;
- amend proposal, design, specification, design-quality obligations, and tasks;
- run diagnostic design checks;
- complete six-role review and strict approval.

Commit: docs/OpenSpec only, before production code.

### Slice 1 - pure model and chart engine wrapper

- add/pin the chart dependency and generated lock update;
- add the pure daily-series adapter with exact-string lookup and lifecycle model;
- add the chart wrapper with candle/volume rendering, crosshair, pan/zoom,
  scale, fit/latest, resize, keyboard, fullscreen, and cleanup;
- add focused adapter/component tests with a deterministic chart-library mock.

Commit only after focused tests, typecheck, and diff checks pass.

### Slice 2 - workspace integration and responsive display

- add URL-compatible Market/Compare mode;
- integrate selected-channel Market data without changing request semantics;
- retain Compare and Date Evidence synchronization;
- optimize context density, chart-first layout, mobile behavior, focus, and
  unpublished treatment;
- extend page, URL, accessibility, and Playwright interaction tests.

Commit only after focused tests, typecheck, build, and diff checks pass.

### Slice 3 - review remediation and closeout

- run repository quality gates and performance smoke;
- run final six-role review against the implementation diff;
- resolve every P0 finding and applicable P1 finding;
- update OpenSpec tasks/review evidence and this plan's closeout section;
- push the feature branch after the third validated commit;
- squash-merge to master only after confirming both worktrees remain clean and
  no unrelated user changes would be overwritten.

## 8. Test and validation matrix

### Pure adapter

- reverse ordering; strict Gregorian dates and decimal syntax; positive/ordered
  OHLC; optional, non-negative volume; linear/log eligibility;
- exact/conflicting/mixed-state duplicates become `DUPLICATE_DATE`, never
  first/last selection;
- rows plus Context `excluded_dates` form an in-bounds UTC daily lattice with
  missing/unobserved/quarantined/client-invalid whitespace and combined reasons;
- backend-string `marker_position`, actual-output-shaped fixtures, and revision
  markers only when supplied by the selected-series contract;
- Context contract and populated row provenance match; unknown/mixed values fail
  closed;
- exact original decimal strings retained for readout;
- Formal versus unpublished lifecycle presentation;
- `ready`, persistent `partial-invalid`, `empty`, `invalid`, excluded-only, and
  capacity-exceeded series.

### Component

- lazy module loading plus chart/series/data failure isolation, safe error codes,
  explicit retry, Compare escape path, and full partial-construction cleanup;
- candle and volume data mapping;
- rAF-coalesced non-live hover summary and explicit click/Enter/date-input pin;
- keyboard previous/next selection and direct date input compatibility;
- linear/log scale transitions, fit/reset, latest, and fullscreen fallback;
- resize observer behavior without instance recreation;
- deferred fullscreen resolve/reject and queued callbacks after unmount;
- loading, empty, partial-invalid, invalid, unavailable, capacity, and failure
  frame states with safe diagnostics;
- no network call from passive chart events; exactly one keyed Date Evidence
  request is allowed after an explicit pin.

### Page and URL

- missing/unknown `obsChart` defaults to Market;
- legacy localStorage objects missing `chartMode` normalize to Market; URL cleanup
  and denied-link whitelisting preserve `obsChart` safely;
- Market/Compare round-trip without changing existing query state;
- Market requests Context then selected series only; Compare requests Context
  then composite only; explicit Compare date pins use Context snapshot directly;
- rapid channel/range/date changes cannot display stale identity;
- candidate/observed publication warning remains persistent;
- Date Evidence remains synchronized in both modes.

### E2E and accessibility

- desktop, tablet, and mobile chart dimensions;
- hover/click/keyboard, pan/zoom, reset/latest, and fullscreen entry/exit;
- one-finger vertical page scroll, horizontal chart pan, pinch zoom, no horizontal
  page overflow;
- named controls, focus order, selected-candle text alternative, non-color
  lifecycle meaning, and no critical axe regressions;
- screenshots for Formal, candidate-ahead, gap/quarantine, All, and mobile.
- 730/7,300 structural and Chromium performance smokes plus raw/gzip asset delta.

### Commands

```bash
openspec validate btc-research-workspace --strict
./trade dev design-check btc-research-workspace
./trade dev design-check btc-research-workspace --strict
npm --prefix trade_web/frontend run test:unit -- <focused files>
npm --prefix trade_web/frontend run typecheck
npm --prefix trade_web/frontend run build
npm --prefix trade_web/frontend run test:e2e -- <focused files>
./trade dev check --show-plan
./trade dev check
git diff --check
```

Tests use fixtures and temporary state only. They do not read or mutate real
BTC parquet, catalogs, databases, manifests, or provider services.

## 9. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Canvas hides evidence from assistive technology | Non-live hover readout, live pinned summary, excluded-date navigation, named controls, and direct date input |
| Candidate/Observed looks formally published | Persistent unpublished frame/label and lifecycle-aware selected summary |
| Float conversion changes displayed values | Geometry-only parsing; exact server strings for all readouts |
| Chart library leaks observers/subscriptions | Single owner, explicit unsubscribe/remove, repeated mount/unmount tests |
| Long range slows interaction | Daily-only bounded series, Canvas renderer, no per-candle DOM, performance smoke |
| Invalid rows silently make a plausible partial chart | Structured adapter diagnostics, persistent partial warning, fatal zero-valid state |
| Renderer chunk/create/update fails | Local safe error state with manual retry and always reachable Compare |
| New URL state breaks bookmarks | Additive parameter; old and unknown values fall back to Market |
| Chart dependency or attribution becomes unsuitable | Repository wrapper plus retained Compare renderer enables source revert |
| UI implies a live exchange feed | “Local Observatory snapshot · daily bars · not live”; “Newest bar”; renderer attribution separate from Context provenance |
| Existing data is stale/degraded | Preserve Context warnings and fail-closed panel states above the chart |

## 10. Rollout and rollback

Rollout is frontend-only behind the existing fresh Observatory capability gate.
No data migration, API deployment ordering, or durable browser-cache migration
is required. Existing bookmarks remain valid.

Transport/cache freshness remains fail-closed: loading, cached, revalidating,
stale response, error, disabled, missing, corrupt, or unregistered capability
does not mount the page. The backend capability state `catalog_stale` remains
inspectable when and only when its response is fresh and successful with
`enabled=true` and `show_nav=true`; the page then exposes the explicit stale
evidence instead of hiding it.

Rollback is a source revert of the Market integration and dependency. The
existing composite renderer remains present and can become the default again;
no database, Catalog, parquet, manifest, snapshot, or research receipt needs
restoration.

## 11. Closeout record

This is the implementation closeout record; final review and integration fields
are completed in this same section rather than in a separate plan.

- Pre-implementation design review: approved by all six roles on 2026-07-22
  against `eeb9753a8a0d7180f5cd957835833859199ec0c0`; no unresolved P0 findings.
- Pre-implementation artifact digest:
  `sha256:07ccaea558a55254c9f6bfcbe4e31acf2882eb3b52f418d7f16973f287a8612d`.
- Pre-implementation strict design check: PASS before production code changed.
- Implementation commits include `d7639ba` (strict adapter), `1b841a1`
  (renderer), `f3caf68` (Market integration), `1fcc5ca` (bundle budgets),
  `fc87214`/`f8f6285`/`b30a506` (gap overlay and teardown), `badadb8`
  (data-quality and observability remediation), `81e98f8`/`4eb4f29`
  (snapshot-cache coherence), and `e36a2b2` (complete runtime recovery).
- Feature branch delivery: all validated implementation and closeout commits are
  pushed to `origin/wt/btc-observatory-exchange-kline-20260722` before squash
  integration.
- Frontend unit tests: PASS, 174/174 across adapter, chart, components, page,
  resource/cache, helpers, navigation, bundle budgets, and App suites.
- Typecheck/build: PASS. Production main-entry gzip is 161,641 bytes and the
  lazy chart gzip is 60,678 bytes. Main grew 5,491 bytes from the 156,150-byte
  baseline (maximum 164,342); chart remains below the 61,440-byte ceiling.
- E2E/a11y: PASS, 18 Chromium scenarios, including three axe surfaces, Market
  and Compare request ownership, URL restore, capability fail-closed behavior,
  explicit date pinning, refresh/cache coherence, and recovery boundaries.
- Performance smoke classification: **added**. The current `master` Chromium
  run measured 10.0 ms / 483 ms at 730 rows and 37.6 ms / 393 ms at 7,300 rows
  (adapter / chart-ready).
  Both are within the 100/500 ms adapter and 1.5/3.0 second readiness budgets;
  100 passive crosshair events issue no Date Evidence request.
- Responsive visual check: desktop Market, desktop Compare, and 390 px mobile
  screenshots inspected; the chart remains full-width/readable and mobile page
  scroll is preserved.
- `./trade dev check --show-plan`: PASS plan generation, 50 eligible files and
  12 checks.
- `./trade dev check`: PASS, 50 files and 12 results, including strict design,
  basedpyright, Ruff, frontend ESLint/Prettier/TypeScript, config, lock,
  suppression, and text gates.
- `git diff --check`: PASS.
- Final implemented-diff six-role review: APPROVED against immutable target
  `e36a2b29e4ed77e8b2ca4083a9f9c2dee1f81ea3`, with reliability 9.8,
  performance 9.8, architecture 9.9, data quality 9.6, observability 9.8, and
  future-data boundaries 9.8; no unresolved P0/P1 findings.
- Digest-bound strict approval: PASS for completed-task commit
  `0d55f5bb23f7df9ed11e0ad3560a758220d4cd51` and final artifact digest
  `sha256:782be3d78e052a77aa09fcf0c8b2f9d53de0f881175f96ba4f6da671eb75f2e8`;
  `reviewed_commit_status=verified` with no findings.
- Baseline debt: the formerly failing exact-identity 304 test is now covered
  and the full frontend unit suite is green. The repository-wide direct ESLint
  command retains unrelated pre-existing unused-symbol findings; the
  selector-aware unified repository gate passes.
- Squash integration: this approved branch is delivered by the receiving
  `master` squash commit; intermediate feature commits are not preserved on
  `master`.
- Remaining risks: daily/snapshot-only data is intentionally not a live or
  intraday exchange feed; the lazy chart chunk has 762 bytes gzip headroom;
  `MarketSummary` still derives presentation separately from the strict chart
  adapter; and two bounded diagnostic accounting details remain accepted P2s
  because they do not alter rendered truth or fail-closed behavior.

## 12. Follow-up optimization: timeframe controls and non-navigating chart clicks

User feedback identified two interaction problems in the completed chart:

1. The chart only exposed a daily view, while exchange users expect selectable
   weekly, monthly, and yearly bars.
2. A normal chart click felt like a page redirect because it committed the
   URL-backed Date Evidence state and the vendor attribution logo could navigate
   away from the workspace.

### Scope and chosen behavior

- Add `1D`, `1W`, `1M`, and `1Y` display timeframes. The backend remains the
  authoritative UTC-daily source; higher timeframes are deterministic client
  display aggregation only and never change the API interval contract.
- Aggregate OHLCV with exact decimal-string arithmetic: first open, maximum
  high, minimum low, last close, and summed volume when supplied. Partial
  buckets retain a visible diagnostic marker and bounded bucket metadata
  (start/end, covered/valid counts, reason/evidence references); empty buckets
  remain whitespace. The browser uses bounded fixed-point `BigInt` arithmetic
  (maximum 128 decimal digits, explicit `AGGREGATE_DECIMAL_OVERFLOW` failure),
  never JavaScript `Number` for aggregate extrema or sums.
- A timeframe bucket's canonical evidence date is its latest valid constituent
  UTC daily row. Explicit inspection pins that daily date; the aggregate bucket
  itself is never presented as a server-provided Date Evidence date. If a valid
  row lacks volume, aggregate volume is unavailable and the bucket is marked
  partial; invalid-volume rows remain excluded by the existing strict adapter.
- Range-edge truncation is not itself partial: covered dates are the bounded
  daily lattice dates in the active request window. A bucket is partial only
  when covered dates are missing, excluded, invalid, or lack required volume.
- Add additive `obsTimeframe` URL state with `1D` as the safe default. Existing
  URLs and saved state remain valid and restore the daily view.
- A normal chart click becomes local inspection only. It updates the readout and
  crosshair without changing the URL, opening Date Evidence, or navigating.
  Explicit `Inspect this date`, Enter/Space, and date-input actions remain the
  only evidence-pinning actions.
- Timeframe is controlled page state passed down to the panel/chart; changing it
  derives a memoized display model from the confirmed daily model and never
  changes request keys, Context identity, or Date Evidence state.
- Remove the in-canvas outbound attribution logo that can intercept chart
  clicks; retain the repository-owned footer attribution link and NOTICE.

### Acceptance and validation

- Unit tests cover exact weekly/monthly/yearly aggregation, month/year boundary
  buckets, partial and empty buckets, timeframe URL round trips, and click-versus
  explicit-pin request behavior.
- Chromium coverage verifies timeframe switching stays on the Observatory page,
  ordinary chart clicks issue no Date Evidence request, and explicit inspection
  still opens the correctly pinned evidence.
- Existing daily lifecycle, provenance, gap, cache, Compare, a11y, build-budget,
  and performance contracts remain green.

### Implementation closeout (2026-07-22)

- Implemented in `5a33780` with metadata/provenance hardening in `862df07`.
- Added URL-safe `1D/1W/1M/1Y` controls, exact bounded fixed-point aggregation,
  canonical latest-valid daily evidence mapping, and local-only ordinary clicks.
- Explicit Inspect/Enter/Space/date-input actions still pin Date Evidence; the
  in-canvas attribution logo is disabled while the footer attribution remains.
- Validation: 177/177 frontend unit tests, TypeScript typecheck, production
  build, bundle-budget check, and diff hygiene pass. Implemented-diff review had
  no P0 findings; an unbounded reason-code and provenance gap were fixed in
  `862df07` before closeout.
