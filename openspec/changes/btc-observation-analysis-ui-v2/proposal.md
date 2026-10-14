## Why

The current BTC Observatory is materially safer and more capable than the
generic Data page, but its implementation and information architecture stop at
daily chart inspection, lifecycle assurance, and one H1 receipt. Actual-code
audit found that `ObservatoryPage.tsx` still owns a 700-plus-line request graph,
while `OverviewPanels.tsx` calculates returns, drawdown, and realized-volatility
percentiles in the browser as explicitly marked display estimates. The user
therefore cannot move cleanly from "what did BTC do?" to "how unusual is this
observation, under which immutable data and method?" without mixing presentation
logic with analysis semantics.

This change designs a second-generation BTC observation and analysis workspace
as an interface child of `restructure-trade-architecture-v1`. It preserves the
existing K-line, lifecycle, assurance, and H1 capabilities while moving reusable
analysis ownership to Datasets/Studies contracts and keeping the Web layer a
read-only query composition surface.

## What Changes

- Define a task-oriented BTC workspace with four top-level views:
  **Observe**, **Analyze**, **Assurance**, and **Research**. Observe remains the
  compatible default and retains the current selected-channel K-line, lifecycle
  comparison, date evidence, timeframe, and viewport behavior.
- Replace browser-computed market-summary estimates with a snapshot-bound
  descriptive-analysis contract. Every metric carries its immutable input
  reference, event/knowledge/available clocks, window, method version, units,
  sample and coverage state, evidence references, and explicit unavailable
  reasons. Formal products use standard DatasetVersionRef/DatasetSnapshotRef;
  any AnalysisSnapshotDescriptor is query-only and cannot become a Study input.
- Assign reusable BTC return, realized-volatility, drawdown, and distribution
  series to a versioned derived Dataset product. Assign hypotheses, forward
  outcomes, statistical validation, and promotion state to Studies. The UI and
  BFF do not calculate either class of business fact.
- Define a Context-first BFF/query flow: resolve one immutable workspace
  context, then lazily request only the active view using that context identity.
  A transport-neutral workspace query application serves peer HTTP V2, HTTP
  compatibility, and SDK adapters. Hidden views are not prefetched, query paths
  are read-only, and one panel's failure does not turn another panel's stale
  payload into current truth.
- Preserve existing `/api/v1/observatory/*` routes, payloads, capability gate,
  page key, and deep links through compatibility adapters. Add only versioned
  workspace query DTOs and the additive `obsLens=analysis` URL value; old or
  unknown values continue to restore the safe Observe view.
- Define a quiet, information-dense responsive layout: compact identity and
  freshness header, stable chart/analysis work area, evidence rail on wide
  screens, and a single-column ordered flow on narrow screens. The design uses
  existing icons and chart assets, avoids nested cards, and keeps unavailable,
  unpublished, stale, partial, and failed states visible without relying on
  color alone.
- Establish explicit budgets for response size, rows, concurrent requests,
  rendering, cancellation, caching, and mobile behavior. No view starts a
  provider request, data repair, dataset build, study run, lifecycle transition,
  or polling loop. The initial envelope is four active requests per
  subject/workspace, 32 active plus 32 queued per process, one-second admission
  wait, 15-second query deadline, 2 MiB per slice, and 2,000 Observe or analysis
  points per response. The 7,300-position history is range/cursor-addressable,
  not one response.
- Make runtime shutdown hardening a prerequisite after actual-code audit found
  unbounded concurrent-stop, startup-cleanup, and executor-tail waits and showed
  that Uvicorn can replace the CLI SIGINT handler during stuck lifespan
  shutdown. Browser abort is not treated as owner termination; capacity remains
  held until cooperative exit or owned-process reap. The runtime child owns one
  12-second process deadline, CI signal-to-reap within 15 seconds, and a
  supervisor-authored terminal receipt for forced exit.
- Split future delivery into independently reviewable child changes for runtime
  hardening, descriptive Datasets, Study queries, transport-neutral workspace
  queries, React workspace, and compatibility cutover. A conditional external
  evidence child is mandatory before news/stream/L2 overlays. This design change
  itself modifies no production code, API behavior, database, artifact, or real
  data.

### Relationship to existing changes

- `btc-observatory-research-lab-v1` remains the implemented legacy source for
  immutable BTC context, selected series, assurance, lineage, and H1 evidence.
  Its Catalog and resolver are compatibility inputs, not the target bounded
  context.
- `btc-research-workspace` remains authoritative for the exchange-style K-line,
  PIT-safe request identity, lifecycle labels, chart cleanup, and existing URL
  contract.
- `btc-kline-viewport-cache` remains authoritative for identity-bound local
  viewport state. This design neither stores evidence in browser storage nor
  changes the viewport key.
- `restructure-trade-architecture-v1` remains authoritative for target
  Datasets, Studies, Interfaces, Processes, Platform, and Bootstrap ownership.
  Observatory remains a product surface/BFF, never a fifth business context.

## Capabilities

### New Capabilities

- `btc-workspace-information-architecture`: Defines the Observe, Analyze,
  Assurance, and Research task flows, responsive composition, evidence
  interaction, explicit states, and URL/navigation compatibility.
- `btc-snapshot-analysis-contract`: Defines immutable, point-in-time descriptive
  BTC analysis products and the boundary between Datasets-owned reusable
  metrics and Studies-owned experimental or forward-looking results.
- `btc-workspace-bff-contract`: Defines Context-first read composition, query
  budgets, process admission, owner cancellation, cache behavior, failure
  isolation, shutdown prerequisites, and compatibility adapters for
  HTTP/Web/SDK consumers.

### Modified Capabilities

None. Existing active BTC change requirements remain in force and are consumed
as prerequisites rather than rewritten by this design.

## Impact

### Intended future implementation surface

- Frontend composition under
  `trade_web/frontend/src/pages/observatory/`,
  `trade_web/frontend/src/components/observatory/`, URL helpers, typed API
  models, styles, Vitest tests, and Playwright scenarios.
- A focused compatibility BFF under the future
  `src/trade/interfaces/http/` boundary, initially adapted through
  `trade_web/backend/observatory/` while package migration is incomplete.
- Datasets contracts/query handles for a reusable BTC descriptive-analysis
  DatasetVersion and Studies contracts/query handles for StudyResultRef and
  validation evidence.
- SDK query DTOs shared by Web and notebooks. CLI command names, scheduler,
  event entry points, and the C++ engine are unchanged.

### Public contracts and compatibility

- Existing `observatory` navigation authorization, `obsLens`, `obsChannel`,
  `obsChart`, `obsTimeframe`, `knowledgeAsOf`, `obsRange`, `obsDate`, `obsRun`,
  and `obsCompare` semantics remain readable.
- `obsLens=analysis` is additive. Missing or unknown lens values fail closed to
  Observe; existing `overview`, `trust`, `runs`, and `research` bookmarks retain
  equivalent destinations.
- Existing `/api/v1/observatory/*` routes remain available through the
  compatibility window. New workspace DTOs use additive versioned paths and do
  not silently change existing methods, selectors/defaults, status codes,
  headers/ETags, complete payload field/type/optional semantics, capability,
  errors, or SSE-or-none behavior.
- The current Data page BTC adapter remains compatible and is not redirected by
  this change.

### Governance, data safety, and rollout

Design-quality governance applies with the public-contract, point-in-time, and
runtime-concurrency profiles. The design introduces no predictive output:
descriptive metrics cannot imply a future return, signal, score, rank, or
recommendation, and Studies results retain their own validation and unavailable
states.

This design performs no persistent write or schema migration. A future
Datasets-owned analysis-product child will separately govern any immutable
artifact/table write, lineage, publication, migration, and rollback. Until that
child is strictly approved and available, Analyze returns an explicit
`analysis_product_unavailable` state rather than computing a browser fallback.

Rollout is route- and feature-flagged. The existing Observatory workspace remains
the rollback surface until runtime shutdown, OpenAPI, complete compatibility,
BFF, URL, visual, accessibility, PIT, read-only, capacity, and residual-owner
checks pass. Rollback selects the legacy page/BFF adapter and retains all
immutable source/product facts; it requires no data deletion or migration
reversal. Future news, social, macro, on-chain, stream or L2 capability is out
of scope and requires a separately approved external-evidence design with
rights, temporal, replay and backpressure governance.

Dark-launch dual-read is deterministic and finite: at most 1% identity-hash
sampling, two active shadows per process, no queue, a two-second ceiling, and
automatic stop after seven days, 1,000 completed identities, or an earlier
read/latency/RSS threshold. The 320-attempt capacity gate has failing server
event-loop and RSS thresholds; it is not report-only evidence.
