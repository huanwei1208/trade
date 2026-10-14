# BTC Observation and Analysis UI v2 Tasks

This architecture child is design and migration-preparation only. Tasks that
change production behavior are intentionally delegated to separately governed
child changes after this design receives strict approval and user confirmation.

## 1. Audit and design approval

- [x] 1.1 Audit and review actual BTC source evidence across Web, BFF, query, DTO, style, and test paths plus [validates:btc-ui.compatibility] [validates:btc-ui.task-flow] [validation:review]
  the architecture parent and existing BTC OpenSpec changes. Objective: establish
  the real implementation baseline and avoid duplicating the K-line, viewport,
  Catalog, or H1 designs. Inputs: `ObservatoryPage.tsx`, `MarketWorkspace.tsx`,
  Observatory components/helpers/tests, `router.py`, query facade/SDK, parent
  architecture artifacts, and three existing BTC changes. Outputs: current-state
  evidence and supersession/compatibility decisions in proposal/design. Affected
  contracts: Observatory URL, HTTP, selected-snapshot, K-line, assurance, H1,
  Data-page BTC consumer. Validation: source paths and line-count/route/contract
  inventories are cited and cross-checked against active changes. Rollback:
  documentation-only correction. Completion evidence: the Current-State Audit
  and Relationship sections identify existing owners and non-duplicated scope.
- [x] 1.2 Author and review governed design evidence: proposal, Design Quality Brief, three capability specs, target [validates:btc-ui.task-flow] [validates:btc-analysis.product-boundary] [validates:btc-ui.bff-boundary] [validates:btc-ui.temporal-coherence] [validation:review]
  dependency/runtime diagrams, budgets, rollout/rollback, child-change plan, and
  governance marker. Objective: define an implementable UI architecture without
  changing production behavior. Inputs: task 1.1 audit and repository design
  policy. Outputs: complete governed artifacts under this change. Affected
  contracts: WorkspaceContext, standard DatasetSnapshotRef,
  AnalysisSnapshotDescriptor, MetricObservation, transport-neutral query
  application/BFF slices, URL/API/SDK compatibility, responsive Web behavior.
  Validation:
  OpenSpec artifacts contain normative scenarios and every selected policy
  profile has concrete evidence. Rollback: edit or remove only this design
  change before approval. Completion evidence: proposal/design/specs/tasks and
  `design-quality.toml` exist and map every obligation.
- [x] 1.3 Run `openspec validate btc-observation-analysis-ui-v2 --strict`, [validates:btc-ui.compatibility] [validates:btc-analysis.product-boundary] [validates:btc-ui.bff-boundary] [validates:btc-ui.temporal-coherence] [validation:test]
  `./trade dev design-check btc-observation-analysis-ui-v2`, and
  `git diff --check`; resolve every deterministic blocker and own every warning.
  Objective: prove native schema and policy completeness before semantic review.
  Inputs: frozen artifacts from task 1.2. Outputs: zero-issue native validation,
  non-strict design report, artifact/policy digests. Affected contracts: all
  three capabilities. Validation: commands exit zero and report the intended
  `contract`, `forecast`, and `concurrency` profiles. Rollback: correct only
  governed design artifacts and rerun. Completion evidence: command output and
  task checkmark record the exact result.
- [x] 1.4 Run the first-round six-role design review in a separate review worktree for [validates:btc-ui.task-flow] [validates:btc-analysis.product-boundary] [validates:btc-ui.bff-boundary] [validates:btc-ui.temporal-coherence] [validation:review]
  reliability, performance, architecture, data quality, observability, and
  news/future integration. Objective: challenge UI semantics, temporal
  correctness, data ownership, workload bounds, compatibility, and future
  event-data isolation. Inputs: current artifact digest and cited source
  baseline. Outputs: six file/line reports and one consensus with P0/P1/P2
  disposition. Affected contracts: all three capabilities. Validation: every
  judge returns a substantive report; contradictions receive at most one
  reconciliation round; all findings are evidence-backed. Rollback: discard the
  review-only worktree and no review evidence is fabricated. Completion
  evidence: all six judges returned `CHANGES REQUIRED`; reports and consensus
  are retained outside governed artifact digest, with findings covering standard
  Dataset refs, per-point PIT, field-level revision impact, runtime shutdown,
  owner cancellation/admission, full compatibility, empty state, payload
  limits, observability, and conditional external evidence.
- [x] 1.5 Resolve all P0 and material P1 findings, rerun the non-strict check, [validates:btc-ui.compatibility] [validates:btc-analysis.product-boundary] [validates:btc-ui.bff-boundary] [validates:btc-ui.temporal-coherence] [validation:review]
  record current digest-bound `design-review.toml`, and run
  `./trade dev design-check btc-observation-analysis-ui-v2 --strict`.
  Objective: obtain genuine design approval before any child implementation.
  Inputs: task 1.4 consensus. Outputs: resolved design/spec/task evidence,
  approved six-role record, strict exit zero. Affected contracts: all three
  capabilities. Validation: zero unresolved P0, every material P1 is resolved or
  assigned to a named child, and strict approval binds the current date, commit,
  policy, and artifact digest. Rollback: modify design, invalidate old approval,
  and repeat review. Completion evidence: strict PASS and approved digest.
## 2. Compatibility and test baselines

- [ ] 2.1 Prepare a frozen compatibility inventory for the later implementation [validates:btc-ui.compatibility] [validates:btc-ui.bff-boundary] [validation:test]
  changes. Objective: make all existing BTC consumers and public behaviors
  testable before delegation. Inputs: current URL parser/serializer, capability
  gate, OpenAPI, Observatory response fixtures, Data-page BTC adapter, SDK, K-line
  and viewport tests. Outputs: proposed URL/HTTP/SDK/BFF/OpenAPI golden fixture
  matrix and consumer/retirement map. Affected contracts: all existing
  `obs*` selectors, `/api/v1/observatory/*`, capability/ETag/error behavior,
  Data-page selected series, notebook/SDK. Validation: every route/method/input/
  status/payload/SSE-or-none/capability/error shape and frontend consumer has a
  named snapshot or explicit no-test reason. Rollback: retain existing routes
  and tests unchanged. Completion evidence: the query-contract child proposal
  includes the frozen matrix and parity exit criteria.
- [ ] 2.2 Prepare the UI interaction and responsive acceptance matrix. [validates:btc-ui.task-flow] [validates:btc-ui.compatibility] [validation:test]
  Objective: turn the Observe/Analyze/Assurance/Research information architecture
  into testable behavior without coding it in this change. Inputs: information
  architecture spec, existing desktop/mobile E2E/a11y suites, current CSS/layout
  and chart constraints. Outputs: view/state/evidence/focus matrix plus
  360x800, 768x1024, 1280x800, and 1600x900 screenshot/canvas checks. Affected
  contracts: task navigation, evidence rail, controls, chart/table layout,
  loading/partial/unavailable/failed states. Validation: every normative UI
  scenario maps to a component/contract test or Playwright visual/a11y check;
  overlap and nonblank canvas checks are explicit. Rollback: keep the legacy
  page selected. Completion evidence: the Web child proposal includes the
  matrix, budgets, and feature-flag rollback.
## 3. Datasets and Studies boundary preparation

- [ ] 3.1 Create `btc-descriptive-analysis-product-v1` as an independent [validates:btc-analysis.product-boundary] [validates:btc-ui.temporal-coherence] [validation:test]
  governed child after the prerequisite package/contracts and formal PIT
  changes are ready. Objective: implement the reusable BTC analysis product in
  Datasets, not React or the BFF. Inputs: DatasetSnapshotRef, formal PIT/revision
  policy, current BTC daily contract, metric-method table, immutable-ref rules.
  Outputs: child proposal/design/spec/tasks for method registry, build/version/
  snapshot/release, standard DatasetSnapshotRef, query-only
  AnalysisSnapshotDescriptor, field/method dependency manifest, lineage,
  quality, query projection, repository/adapters, and rollback. Affected
  contracts: DatasetVersionRef/DatasetSnapshotRef, MetricObservation, analysis
  series, Dataset lineage/revision. Validation: exact-decimal and per-point
  temporal golden fixtures cover return, volatility, range, drawdown,
  percentile, coverage, missing/late/quarantine/revision/minimum samples,
  market/unit identity, changed high/low/volume/clock/quality with unchanged
  close, identical input determinism, tamper rejection, and no moving inputs.
  The child freezes a purpose-by-availability-basis-by-confidence admissibility
  matrix and a fixture-by-fixture table with exact values/states/reasons for
  identical/conflicting duplicates, non-final bars, OHLC violations,
  missing/late clocks, 251/252 boundaries, zero variance, field revisions and
  tampering.
  Rollback: select
  the prior verified analysis release or disable analysis capability while
  retaining immutable artifacts. Completion evidence: child strict design
  approval defines one Dataset owner and no UI/BFF business calculation.
- [ ] 3.2 Create `btc-study-workspace-query-contract-v1` as an independent [validates:btc-analysis.product-boundary] [validates:btc-ui.temporal-coherence] [validation:test]
  Studies-owned child. Objective: prevent forward labels, inference, validation,
  and promotion from leaking into descriptive Analyze metrics. Inputs: H1
  receipt, Study lifecycle parent spec, DatasetSnapshotRef and query descriptor,
  revision flow.
  Outputs: governed child artifacts, transport-neutral StudyResultRef
  relationship query, stale/evidence-gap states, and forbidden-field/dependency
  test plan. Affected contracts: Research slice, Study result input refs,
  stale-after-revision mapping. Validation: contract tests prove formal StudyRun
  accepts only verified DatasetSnapshotRef, reject descriptor/moving/raw/provider
  inputs, and reject forecast/recommendation fields in the descriptive analysis
  schema; deterministic Study fixtures retain their own
  method/sample/uncertainty/lifecycle. Type/ref verification failure is rejected
  before StudyRun creation; `insufficient_data` is reserved for a verified
  DatasetSnapshotRef whose eligible sample is inadequate. Rollback: retain legacy H1
  rendering and keep new relationship unavailable. Completion evidence: the
  named child owns every inferential field in Studies.
## 4. Runtime, BFF, and SDK boundary preparation

- [ ] 4.1 Create `runtime-owner-shutdown-and-recovery-hardening-v1` as an independent governed [validates:btc-ui.bff-boundary] [validation:test]
  prerequisite child before V2 route activation. Objective: close the audited
  shutdown hang paths across EventBus terminal persistence, current runtime
  resources/commands/app/web CLI, FastAPI serving process and owned child
  process trees, and make owner cancellation/admission truthful. Inputs: these
  audited owners, public operation-control contracts, and real Uvicorn probes.
  Outputs: child proposal/design/spec/tasks
  for one 12-second monotonic shutdown deadline, bounded concurrent stop and
  startup cleanup, executor-tail behavior, QueryExecutionContext,
  32-active/32-queued process admission, process-group reap, in-process stage
  receipts, and supervisor-owned terminal ShutdownReceipt. Affected contracts:
  runtime operation receipts and internal query execution only; public
  Observatory payloads remain unchanged. Validation:
  real subprocess tests cover idle, active cooperative query, non-cooperative
  owned child, startup failure, concurrent stop, exhausted deadline and SIGINT;
  signal-to-reap is at most 15 seconds on CI for a 12-second runtime budget,
  graceful exit is 0, forced deadline exit is 124, owned processes are reaped,
  Python thread residuals are reported rather than falsely cleared, supervisor
  terminal receipts survive child receipt absence/interruption, and unrelated
  processes are never signalled. Rollback: revert runtime implementation and keep all V2 routes/page
  disabled. Completion evidence: child strict approval, focused tests and
  implemented-diff review pass before V2 activation.
- [ ] 4.2 Create `btc-workspace-query-contracts-v1` as an independent governed [validates:btc-ui.bff-boundary] [validates:btc-ui.compatibility] [validates:btc-ui.temporal-coherence] [validation:test]
  child. Objective: introduce WorkspaceContext and active-view query slices
  through a transport-neutral application while preserving legacy Observatory
  contracts. Inputs: approved public refs/DTOs, separate Dataset/Study query
  contracts, runtime hardening, current router/facade, full URL/OpenAPI route
  matrix and query budgets. Outputs: framework-free query DTOs, peer versioned
  HTTP V2/HTTP compat/SDK adapters,
  context/observe/analyze/assurance/lineage/research/evidence endpoints,
  compatibility mapper, capability bits, transport-neutral ErrorEnvelope, and
  HTTP-only status/header/Retry-After mapping. Affected
  contracts: additive workspace API, legacy Observatory HTTP/ETag/error behavior,
  SDK/notebook semantics. Validation: OpenAPI/DTO/full per-route legacy
  snapshots, context-first topology, same-identity ETag, mismatch rejection,
  partial-owner errors and Web/SDK parity. Rollback: disable additive route
  registration and select the legacy adapter. Completion evidence: child strict
  approval and deterministic dark-launch dual-read with no legacy removal:
  fixed identity-hash sampling at no more than 1%, two active shadows per
  process, no queue, at most two seconds, automatic stop at seven days or 1,000
  completed identities, and earlier stop on 1.01x read amplification, 5% p95
  regression, or 32 MiB shadow RSS.
- [ ] 4.3 Define and validate read-only, deadline, cancellation and capacity [validates:btc-ui.bff-boundary] [validates:btc-ui.temporal-coherence] [validation:test]
  guards in the query-contract child. Objective: ensure the BFF cannot become a
  workflow or unbounded aggregation owner. Inputs: owner query ports,
  QueryBudget, QueryExecutionContext, Platform status/error APIs, hardened
  resource cancellation/admission, and specified 1x/320-attempt envelopes.
  Outputs: instrumented read-only integration fixtures and capacity-result
  schema. Affected contracts: every workspace GET, cache identity, timeout
  ErrorEnvelope, response budgets, telemetry. Validation:
  provider/write/repair/publish/Study-run spies fail the read; disconnect and
  deadline propagate cancellation while permits remain owned until exit;
  four-request subject, 32-active/32-queued process, 1-second admission, 2 MiB,
  2,000 Observe/series, 100-metric, pagination and 320-attempt overload cases
  remain bounded and preserve valid partial reports. Compact encoded DTO goldens
  prove byte ceilings. The 320-attempt gate fails above 100/250 ms server
  event-loop p95/p99, 256 MiB peak RSS delta, 32 MiB retained RSS after a
  60-second cooldown, or monotonic retained-RSS growth across three runs.
  Rollback: disable the new BFF; no business state exists to migrate. Completion
  evidence: child tests distinguish timeout/tool error from unavailable product
  and separately report residual threads while showing zero residual owned
  process groups.
## 5. Web and compatibility cutover preparation

- [ ] 5.1 Create `btc-observation-analysis-web-v2` as an independent governed [validates:btc-ui.task-flow] [validates:btc-ui.compatibility] [validates:btc-ui.bff-boundary] [validation:test]
  frontend child after query contracts are approved. Objective: implement the
  four-task UI with no business calculation or compatibility break. Inputs:
  approved BFF DTOs, current K-line/viewport components, UI acceptance matrix,
  existing URL/capability helpers. Outputs: focused page containers, typed
  resource clients, compact context header, Analyze views, evidence rail,
  responsive styles and feature gate. Affected contracts: Web navigation, URL,
  request topology, visual/a11y behavior, K-line compatibility. Validation:
  Vitest/typecheck/build/bundle plus Playwright functional/a11y/visual/canvas
  checks at all target viewports, rapid-switch cancellation, independent
  failures, successful empty states, measured heap/long-task/interaction/bundle
  budgets, and a static/contract guard proving every V2 Observe/Analyze
  component rejects raw OHLCV for metric calculation and never calls
  `display_estimate`. A four-page cursor fixture verifies viewport/range fetch,
  cross-page deduplication, cancellation, cache eviction, resident-point caps,
  and cache-size encoding below the 100 ms long-task gate. Rollback: turn off V2 and restore the complete legacy
  page bundle without data cleanup. Completion evidence: child strict approval,
  focused green tests, and implemented-diff six-role review.
- [ ] 5.2 Create `btc-workspace-compatibility-cutover` only after analysis, [validates:btc-ui.compatibility] [validates:btc-ui.temporal-coherence] [validation:test]
  runtime, Study-query, workspace-query, and Web children meet their independent
  exit criteria. Objective:
  switch Observe/Assurance/Research composition and V2 default safely while
  keeping old clients and the Data-page BTC adapter working. Inputs: dual-read
  reports, compatibility snapshots, feature/capability telemetry, rollback
  runbook. Outputs: staged percentage/local gate, monitored default, consumer
  inventory, and later retirement proposal. Affected contracts: legacy and V2
  HTTP, URL, SDK, Data page, page assets. Validation: full per-route parity, PIT
  identity, read-only, error/status, process admission, latency/payload,
  shutdown, accessibility, SLI/alert and rollback drills pass before each stage.
  Rollback: the runbook names flag/route owners, exact mechanism, smoke checks,
  five-minute decision target and escalation path; select legacy routes/page and
  previous verified Dataset release; retain immutable facts. Completion evidence:
  one reviewable cutover PR with no legacy deletion.
- [ ] 5.3 Create conditional `btc-external-evidence-overlays-v1` before any [validates:btc-ui.temporal-coherence] [validation:review]
  news, social, macro, on-chain, stream, L2, SSE-overlay, replay or redrive
  capability. Objective: prevent future heterogeneous evidence from bypassing
  Capture, rights, PIT and capacity governance. Inputs: parent Capture/Datasets/
  Studies contracts and concrete source manifests. Outputs: child artifacts with
  `external_event_data=true` and a parent-Capture obligation map covering source
  values/timezone, event/published/observed/received/first-seen/available/
  revision clocks, precision/confidence, finality, correction/retraction,
  rights/retention/deletion and multi-source immutable refs. It separately maps
  Capture quarantine, Platform delivery DLQ, immutable-artifact replay,
  event-envelope redelivery, provider-refetch Commands, bounded projection,
  shared SSE hub, per-client byte/item queues and cursor expiry/resync. Affected
  contracts: only the future capability;
  current daily workspace remains unchanged. Validation: Workspace GET cannot
  call provider/capture/replay, rights withdrawal blocks serving, and bounded
  stream backpressure/reconnect tests pass. Rollback: disable overlay and retain
  daily V2. Completion evidence: separate strict approval before code.
## 6. Final handoff audit

- [ ] 6.1 Review child-proposal evidence against this design before any [validates:btc-ui.task-flow] [validates:btc-analysis.product-boundary] [validates:btc-ui.bff-boundary] [validates:btc-ui.compatibility] [validates:btc-ui.temporal-coherence] [validation:review]
  implementation starts. Objective: prove ownership, dependency order,
  compatibility and rollback remain complete after child decomposition. Inputs:
  child governed artifacts and current architecture parent. Outputs:
  prompt-to-artifact checklist covering every capability requirement, DTO,
  route, budget, test, gate, risk and rollback. Affected contracts: all
  capabilities and child boundaries. Validation: uncertainty is treated as not
  ready; every requirement maps to concrete child owner/task/evidence and no
  child depends on an unapproved future big-bang move. Rollback: revise the
  child or this design, invalidate review digest and regain strict approval.
  Completion evidence: dependency audit records package/contracts and formal
  PIT prerequisites before Datasets/BFF/Web cutover.
- [x] 6.2 Review final handoff evidence and confirm this design change modified no production code, real data, [validates:btc-ui.compatibility] [validation:review]
  schema, generated artifact or runtime behavior and record the approved handoff.
  Objective: close the design round without accidentally beginning
  implementation. Inputs: git diff/status, strict report, review consensus and
  child order. Outputs: final design status and user decisions/confirmation
  request. Affected contracts: none at runtime. Validation: only files under
  this OpenSpec change and an intentional architecture-parent task reference, if
  added, appear in the design diff; production tests are not claimed as changed.
  Rollback: revert documentation commits only. Completion evidence: clean
  worktree after commit, production-code-changed=no, and implementation-ready
  only if strict approval passes.
