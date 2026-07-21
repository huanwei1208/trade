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
- Make Market the default: a concise state header, purpose-fitness result,
  lifecycle-aware price comparison, and a date inspector that opens only when a
  user selects a chart date.
- Move gate findings and immutable run lineage into Assurance, including a clear
  distinction between data unavailable, data blocked, and data merely not
  formally published.
- Keep H1 evidence in Research with explicit non-directional and
  non-recommendation language; it continues to render server-provided
  hypothesis/run values only.
- Resolve the selected lifecycle Context before Market/Assurance facts. Use its
  immutable `snapshot_id` to pin selected-channel series, Trust, and Date
  Evidence. Keep the composite chart as a separately labelled lifecycle
  comparison under the same committed knowledge selector; do not use it as a
  substitute for selected-snapshot facts.
- Treat catalog-wide Lineage and the existing H1 receipt as separately scoped
  immutable evidence, not as a claim that they confirm the selected Market
  snapshot. A future multi-hypothesis or news/sentiment surface needs its own
  explicitly selected, versioned data-family contract.
- Preserve the current additive Observatory route, capability gate, URL
  ownership, API paths, channel semantics, three independent chart layers, and
  existing non-color accessibility treatment.
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
- No client-side cross-scope join: Research and global Lineage do not acquire a
  market snapshot selector merely to make a historical Market screen look more
  complete.
- No persistent browser cache of Observatory payloads, unbounded historical
  SVG/calendar DOM, or knowledge-as-of request per keyboard character.
- No removal or redirect of Today, Candidates, Symbol, Data, Research, Ops, or
  the capability-gated Observatory navigation entry.

## Affected Contracts

- **Web navigation and URL:** the existing `observatory` page key and
  `obsLens`, `obsChannel`, `knowledgeAsOf`, `obsRange`, `obsRun`, `obsCompare`,
  and `obsDate` query parameters remain compatible. `obsLens` values stay
  `overview`, `trust`, `runs`, and `research`; they map to the renamed workspace
  labels rather than changing serialized values.
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
fresh-capability gate. A disabled, missing, stale, corrupt, loading, or failed
capability response continues to hide the navigation entry and prevents page
mounting. The backend contract and real data are never mutated.

Rollback is a source revert: the existing route, serialized URL state, and API
contracts are unchanged, so the prior page implementation can be restored without
data migration or cleanup.

## Validation

- Extend focused Vitest coverage for task-oriented mode labels, current-state
  summary, non-recommendation language, explicit unavailable/error states, URL
  compatibility, snapshot propagation, request cancellation, keyed cache/304
  reuse, direct-mode request budgets, and bounded chart/calendar rendering.
- Preserve existing capability-gating, composite-layer, date-evidence, and
  navigation tests.
- Run the frontend typecheck/build, `./trade dev check --show-plan`,
  `./trade dev check`, `git diff --check`, and the focused frontend test suite.
- Run frontend E2E/a11y tests when the existing Playwright runtime is available;
  report any environment blocker separately rather than weakening test coverage.
