## Why

BTC data is now available through the read-only Observatory API, but the current
Web experience presents it as a generic four-lens dashboard. A user has to infer
the current lifecycle state from a dense truth bar, switch among unrelated tabs,
and understand internal channel names before answering the basic questions:

1. what is the latest BTC observation and how far ahead is it of the Formal
   baseline;
2. may the data be used for manual observation or formal-system consumption;
3. what evidence, quality gates, and immutable run explain that answer; and
4. what does the registered H1 study say without turning it into a trade call.

The backend already exposes those facts with lifecycle boundaries and
fail-closed capability gating. The product gap is a focused BTC research
workspace that makes the evidence hierarchy legible without weakening the
underlying assurance semantics.

## What Changes

- Reframe the existing Observatory route as a BTC Research Workspace with three
  task-oriented areas: **Market**, **Assurance**, and **Research**. Assurance
  contains a Gates view and a direct-bookmarkable Run Lineage subflow; its
  existing `obsLens=runs` serialization remains unchanged.
- Make Market the default: a concise state header, purpose-fitness result, one
  selected-channel exchange-style daily K-line, and a date inspector that opens
  only when a user selects a chart date. The K-line has a right price scale,
  UTC time scale, volume, crosshair OHLCV readout, pan/zoom, fit/latest,
  fullscreen, responsive layout, and keyboard date navigation.
- Move gate findings and immutable run lineage into Assurance, including a clear
  distinction between data unavailable, data blocked, and data merely not
  formally published.
- Keep H1 evidence in Research with explicit non-directional and
  non-recommendation language; it continues to render server-provided
  hypothesis/run values only.
- Resolve the selected lifecycle Context before Market/Assurance facts. Use its
  immutable `snapshot_id` to pin selected-channel series, Trust, and Date
  Evidence. Keep the existing three-layer composite SVG as a separately
  labelled Compare mode under the same committed knowledge selector and as a
  rollback surface; do not use it as a substitute for selected-snapshot facts.
- Treat catalog-wide Lineage and the existing H1 receipt as separately scoped
  immutable evidence, not as a claim that they confirm the selected Market
  snapshot. A future multi-hypothesis or news/sentiment surface needs its own
  explicitly selected, versioned data-family contract.
- Preserve the current additive Observatory route, capability gate, API paths,
  channel semantics, three independent lifecycle channels, and existing
  non-color accessibility treatment. Add only `obsChart=market|compare` URL
  state; missing or unknown values safely restore Market.
- Use TradingView Lightweight Charts behind a repository-owned React wrapper for
  the selected daily series. Preserve original API decimal strings for readout,
  required attribution, bounded Canvas rendering, complete subscription cleanup,
  and the ability to revert to the retained composite renderer.
- Add repository-owned `1D`, `1W`, `1M`, and `1Y` display timeframe controls by
  aggregating the validated daily source in the browser with exact decimal
  arithmetic. Add additive `obsTimeframe` URL state with a safe `1D` default;
  the backend remains daily-only and no provider or interval selector is added.
- Make ordinary chart clicks local inspection only. Only explicit Inspect-date,
  Enter/Space, or date-input actions pin Date Evidence and update URL state. Keep
  attribution in the repository footer/NOTICE and remove the in-canvas outbound
  logo so chart interaction cannot unexpectedly navigate away.
- Load the vendor chart as a Market-only lazy chunk behind a local safe-error
  boundary. Module/create/series/data/callback failures retain Context warnings
  and the external mode switch, expose only sanitized renderer codes, and offer
  manual Retry or Compare without an automatic retry loop.
- Fail closed on malformed/duplicate dates, invalid decimal/OHLC structure,
  mixed provenance, and zero valid candles. Use rows plus Context
  `excluded_dates` to construct auditable daily gaps and expose persistent,
  non-authoritative renderer diagnostics for partially invalid data.
- Extract page-local state/data orchestration from the current large page into
  focused workspace containers and a typed request-keyed UI-state helper. It
  aborts superseded reads, clears stale current truth on selector changes, and
  uses only bounded same-identity memory/ETag reuse. No backend route,
  persistence, or BTC data-processing changes are introduced.

## Non-Goals

- No API, CLI, schema, catalog, parquet, or research-kernel change.
- No writes, refresh/sync/publish actions, provider calls, or automatic
  trading/recommendation capability.
- No new asset universe, real-time/tick display, technical-indicator wall, or
  client-side calculation of formal market/research metrics.
- No intraday interval, exchange-source selector, live candle, hosted chart
  widget, drawing suite, order book, or inferred volume unit.
- No browser-side change to the authoritative daily API interval or lifecycle
  channel; timeframe aggregation is presentation-only and remains visibly
  derived from daily snapshot evidence.
- No client-side cross-scope join: Research and global Lineage do not acquire a
  market snapshot selector merely to make a historical Market screen look more
  complete.
- No persistent browser cache of Observatory payloads, unbounded historical
  chart/calendar DOM, or knowledge-as-of request per keyboard character.
- No removal or redirect of Today, Candidates, Symbol, Data, Research, Ops, or
  the capability-gated Observatory navigation entry.

## Affected Contracts

- **Web navigation and URL:** the existing `observatory` page key and
  `obsLens`, `obsChannel`, `knowledgeAsOf`, `obsRange`, `obsRun`, `obsCompare`,
  and `obsDate` query parameters remain compatible. The additive `obsChart`
  parameter accepts `market` and `compare`; the additive `obsTimeframe`
  parameter accepts `1D`, `1W`, `1M`, and `1Y`; missing/unknown values mean
  `market` and `1D` respectively. `obsLens` values stay `overview`, `trust`, `runs`, and `research`;
  they map to the renamed workspace labels rather than changing serialized
  values.
- **Web API:** all `/api/v1/observatory/*` payloads and capability behavior are
  consumed unchanged. Existing `formal`, `evaluated_candidate`, and `observed`
  channel meanings remain authoritative.
- **Data and research:** the UI remains a read-only projection. Missing,
  blocked, stale, corrupt, loading, and failed responses remain explicit UI
  states and never become a neutral price, trust score, or investment signal.
- **Point in time:** Context is the selected Market/Assurance proof anchor.
  Selected-channel series, Trust, and Date Evidence use its resolved
  `snapshot_id`; `PIT_NOT_PROVEN` or identity mismatch blocks the affected
  panel. Composite, global Lineage, and H1 Research retain their own explicit
  evidence identities and cannot be presented as selected-snapshot proof.

## Compatibility and Rollout

This is a frontend-only, additive presentation change behind the existing
fresh-capability gate. Loading, cached, revalidating, stale-response, disabled,
missing, corrupt, failed, or unregistered capability results remain fail-closed.
A fresh successful `catalog_stale` payload with `enabled=true` and
`show_nav=true` remains intentionally mountable so its explicit stale evidence
can be inspected. The backend contract and real data are never mutated.

Rollback is a source revert: the existing route, serialized URL state, and API
contracts are unchanged, so the prior page implementation can be restored without
data migration or cleanup.

## Validation

- Extend focused Vitest coverage for task-oriented mode labels, current-state
  summary, non-recommendation language, explicit unavailable/error states, URL
  compatibility, snapshot propagation, request cancellation, keyed cache/304
  reuse, direct-mode request budgets, and bounded chart/calendar rendering.
- Add adapter and component coverage for daily ordering, invalid decimals,
  exact-string readout, gaps/markers, chart cleanup, crosshair selection,
  keyboard navigation, pan/zoom controls, responsive resize, Market/Compare URL
  restoration, and persistent unpublished state. Add exact timeframe aggregation,
  partial-bucket diagnostics, URL timeframe compatibility, and ordinary-click
  versus explicit-pin behavior coverage.
- Include strict real-date/decimal/OHLCV, duplicate-conflict, daily-lattice,
  Context-exclusion, actual-output-shaped marker/provenance, partial/fatal
  diagnostics, lazy-load/create/update recovery, rAF hover coalescing,
  Market/Compare request topology, 730/7,300 capacity, bundle-size, and mobile
  gesture coverage.
- Preserve existing capability-gating, composite-layer, date-evidence, and
  navigation tests.
- Run the frontend typecheck/build, `./trade dev check --show-plan`,
  `./trade dev check`, `git diff --check`, and the focused frontend test suite.
- Run frontend E2E/a11y tests when the existing Playwright runtime is available;
  report any environment blocker separately rather than weakening test coverage.
