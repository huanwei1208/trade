## ADDED Requirements

### Requirement: Workspace context is resolved before dependent slices

The BTC workspace BFF SHALL first resolve one read-only `WorkspaceContext`
containing asset contract identity, selected lifecycle channel, selected market
DatasetSnapshotRef, effective knowledge cut, knowledge mode, revision policy,
watermarks, purpose fitness, context version, and request/correlation identity.
Observe, Analyze, and selected-snapshot Assurance queries SHALL require that
context identity. Research and catalog-wide lineage SHALL expose their separate
scope explicitly.

#### Scenario: Workspace opens
- **WHEN** a client requests a supported BTC workspace context
- **THEN** the BFF resolves the context through Datasets contracts or the legacy Observatory compatibility query
- **AND THEN** it returns one immutable selected-market reference plus the effective temporal/revision selectors
- **AND THEN** no dependent owner query starts until that context is confirmed

#### Scenario: Dependent query supplies a stale context
- **WHEN** an Observe, Analyze, or selected-snapshot Assurance query supplies a context id or market reference different from the active selection
- **THEN** the BFF returns `workspace_context_mismatch`
- **AND THEN** it does not substitute the newest context or combine responses from both identities

### Requirement: BFF composes owner query contracts without owning business facts

The transport-neutral BTC workspace query application SHALL call context-owned
read/query contracts and return framework-free workspace DTOs. HTTP V2, HTTP
compatibility, and SDK adapters SHALL depend on that application as peers;
React SHALL call the HTTP adapter at runtime and SHALL NOT be a Python import
dependency. The HTTP BFF MAY perform authorization, bounded parallel
composition, identity verification, response shaping, cache metadata, and
status/error mapping. Neither application nor adapters SHALL query owner tables
directly, read parquet or artifact paths, call providers, calculate analysis
metrics, repair data, build or publish Datasets, execute Studies, move lifecycle
pointers, or write business state.

#### Scenario: Analyze slice is composed
- **WHEN** the client requests Analyze for a confirmed context
- **THEN** the application resolves the compatible analysis DatasetSnapshotRef and non-authoritative AnalysisSnapshotDescriptor through Datasets query contracts
- **AND THEN** it verifies immutable-reference and lineage relationships before returning metrics and series descriptors
- **AND THEN** no metric is derived from the Observe OHLCV response inside the BFF

#### Scenario: Research slice is composed
- **WHEN** the client requests Research
- **THEN** the BFF queries Studies for registered hypotheses and StudyResultRef values
- **AND THEN** it maps the input snapshot relationship to the active workspace without changing the Study result
- **AND THEN** it does not start a StudyRun or close an EvidenceGap

#### Scenario: Read-only guard observes a write
- **WHEN** a workspace GET attempts a database write, artifact write, provider call, repair, publish, or lifecycle transition
- **THEN** the read-only guard fails the request and records a safe operational diagnostic
- **AND THEN** no partial business mutation is committed

### Requirement: Query slices are versioned and view-local

The BFF SHALL expose versioned, bounded query DTOs for `context`, `observe`,
`analyze`, `assurance`, `lineage`, `research`, and `evidence`. The client SHALL
request only the active view and explicit drill-down. Hidden views SHALL NOT be
prefetched by default. A composite all-page response SHALL NOT be required for
correctness.

#### Scenario: Observe is active
- **WHEN** the client opens Observe
- **THEN** it requests context followed by the Observe slice and only an explicitly selected date's evidence
- **AND THEN** it does not request Analyze, Assurance detail, Lineage, or Research payloads

#### Scenario: Analyze is active
- **WHEN** the client opens Analyze
- **THEN** it requests context followed by the bounded analysis summary and only the selected metric series or evidence detail
- **AND THEN** it does not load every rolling series, every window, or every evidence reference eagerly

#### Scenario: User switches views rapidly
- **WHEN** a client changes the active view before a slice response completes
- **THEN** the old request is cancelled where supported and ignored by complete request identity otherwise
- **AND THEN** only the active view's matching response can enter confirmed state

### Requirement: Complete request identity prevents stale truth

Each request identity SHALL include endpoint/contract version, asset id, selected
channel, WorkspaceContext id, immutable market or analysis reference, effective
knowledge cut, knowledge mode, revision policy, view, selector/range, evidence
target, and refresh generation as applicable. Cache reuse and conditional
requests SHALL be allowed only for the same semantic identity.

#### Scenario: Channel changes during an ETag revalidation
- **WHEN** the prior observed response is revalidating and the user switches to Formal
- **THEN** the observed response cannot satisfy, populate, or remain labelled as the Formal request
- **AND THEN** the new context resolves before Formal-dependent slices begin

#### Scenario: Server returns not modified
- **WHEN** a conditional request receives `304 Not Modified`
- **THEN** the client reuses payload bytes only when the cached semantic identity and schema version exactly match the active request
- **AND THEN** a missing or mismatched cache entry becomes unavailable or a full retry, never a cross-identity fallback

### Requirement: Failure and freshness states are structured

Workspace payloads and errors SHALL distinguish transport failure, capability
denial, successful empty result, context unavailable, product unavailable,
partial product, stale product, identity mismatch, PIT not proven, quality
blocked, query-budget exceeded, and unsupported selector. Every error SHALL use
the transport-neutral versioned ErrorEnvelope or its legacy-compatible mapping
with safe message, stable code, category, retryability, server request id,
correlation id, and bounded evidence references. ErrorEnvelope SHALL NOT contain
HTTP status or headers. The HTTP adapter SHALL map error category/code to HTTP
status and bounded `Retry-After`; SDK preserves the same neutral envelope without
transport fields.

The baseline mapping SHALL be: invalid selector/version `400`; authorization or
capability denial `403`; unknown explicit evidence identity `404`; context,
reference, PIT, quality, or lifecycle conflict `409`; response-byte overflow
`413`; process admission saturation `429` with bounded Retry-After; owner
deadline `504`; and unavailable technical dependency `503`. A successful empty
query SHALL return `200` with `condition=empty`. The query-contract child SHALL
freeze every code and legacy exception in the route compatibility matrix.

The server SHALL create a unique request id for each attempt. It MAY accept an
authenticated correlation id only under a bounded allowlisted syntax and SHALL
otherwise replace it with an opaque server value. Request and correlation ids
SHALL propagate through response header/body, owner QueryExecutionContext, logs,
and receipts; neither identifier SHALL enter business or cache identity.

#### Scenario: Analysis product has not been built
- **WHEN** the active market snapshot has no compatible analysis product
- **THEN** Analyze receives `analysis_product_unavailable` or `analysis_pending_for_snapshot`
- **AND THEN** Observe and selected-snapshot Assurance remain independently available
- **AND THEN** the BFF does not treat the condition as a killed request, success, or zero metrics

#### Scenario: One owner query times out
- **WHEN** one requested slice exceeds its bounded deadline
- **THEN** that slice returns a timeout ErrorEnvelope and retains its capacity permit until owned work actually exits
- **AND THEN** already confirmed independent slices keep their own identities and states
- **AND THEN** the server does not continue an unbounded background query solely for the disconnected client

#### Scenario: Workspace process is shutting down
- **WHEN** the serving process receives shutdown while workspace queries or owned child processes are active
- **THEN** admission closes before cancellation propagates to every owned query and child process group
- **AND THEN** shutdown waits only through a finite documented grace period before escalating owned child process groups from graceful termination to forced termination
- **AND THEN** every owned process is reaped, while a Python thread that cannot be terminated is reported as residual rather than falsely reported reaped
- **AND THEN** late results are discarded and a bounded ShutdownReceipt identifies stage, deadline, graceful/forced counts, residual owner/category, and last safe error
- **AND THEN** shutdown does not wait for or signal unrelated processes, shared external services, or another runtime owner's resources

#### Scenario: Serving process misses the shutdown deadline
- **WHEN** the process has not exited within the single 12-second monotonic shutdown budget
- **THEN** the supervisor force-terminates and reaps it, and CI observes process exit within 15 seconds of the first signal
- **AND THEN** the supervisor atomically appends the authoritative terminal ShutdownReceipt with forced exit code 124
- **AND THEN** an absent, interrupted, or incomplete in-process receipt is never reported as completed

#### Scenario: Runtime hardening prerequisite is absent
- **WHEN** `runtime-owner-shutdown-and-recovery-hardening-v1` lacks current strict approval, implementation evidence, or real Uvicorn subprocess proof
- **THEN** the V2 workspace routes and page remain unregistered or disabled
- **AND THEN** the legacy Observatory remains the selected surface
- **AND THEN** a browser AbortController or idle-only shutdown probe is not accepted as substitute evidence

### Requirement: Owner queries consume one bounded execution context

Every workspace owner query SHALL accept a transport-neutral
`QueryExecutionContext` containing monotonic deadline, cancellation token,
request id, correlation id, semantic request identity, owner identity, and
bounded child budget. Browser abort or HTTP disconnect alone SHALL NOT be
treated as proof that owner work stopped. Cooperative adapters SHALL check
cancellation between scan/page/map steps and apply native I/O timeouts.
Potentially permanent or non-cooperative reads SHALL execute in an owned,
bounded, terminable process or SHALL remain unavailable.

When a slice calls multiple owners, it SHALL use one structured-concurrency
scope. Deadline, disconnect, or a failure that prevents a valid partial result
SHALL cancel unfinished siblings and join them only within the shared remaining
budget. A response may include only completed, identity-verified owner results.

#### Scenario: Client disconnects during a blocking owner read
- **WHEN** disconnect cancellation reaches an owner query that has not completed
- **THEN** the owner receives cancellation and no new child work is admitted
- **AND THEN** its capacity permit remains owned until cooperative exit or bounded process termination is observed
- **AND THEN** the ShutdownReceipt or query receipt reports residual work if the deadline expires

#### Scenario: One sibling fails during bounded composition
- **WHEN** one owner fails while another owner query remains active in the same slice
- **THEN** the application cancels siblings not needed for a valid declared partial result
- **AND THEN** it joins owned siblings only through the shared deadline
- **AND THEN** no late or mismatched sibling result enters the response

### Requirement: Request, response, and rendering budgets are enforceable

The BFF and client SHALL enforce finite budgets per slice. Initial design
envelopes SHALL be no more than four active requests per subject/workspace, one
in-flight request per complete slice identity, 32 active requests and 32 queued
requests per serving process, one-second maximum admission wait, 2,000 Observe
positions per V2 response, 2,000 analysis series points per response, 100 metric
observations per summary, 50 lineage rows per page, 100 evidence references per
response, 2 MiB uncompressed JSON per slice, and 15 seconds server/query
deadline. The BTC product MAY retain 7,300 daily positions, but V2 SHALL access
that history through bounded range/cursor responses; 7,300 is not a
single-response promise. Same complete identities SHALL use bounded singleflight.
Exceeding a budget SHALL be explicit and SHALL NOT silently truncate evidence.

#### Scenario: Analysis series request is within budget
- **WHEN** a requested metric series contains at most 2,000 points and the encoded response fits the byte budget
- **THEN** the BFF returns the complete ordered slice with range and point counts
- **AND THEN** the client renders it with bounded Canvas/SVG work and bounded accessible summaries

#### Scenario: Evidence fan-out exceeds budget
- **WHEN** a query would return more evidence references, rows, points, or bytes than its contract allows
- **THEN** the BFF returns a budget error or an explicit paginated/summary response with omitted counts and continuation contract
- **AND THEN** it does not silently discard references or start unbounded parallel reads

#### Scenario: Ten-times workload is exercised
- **WHEN** capacity tests run 320 concurrent attempts against the 32-active/32-queued process envelope and maximum supported slice sizes
- **THEN** admission, queue wait, latency, memory, cancellation, cache, and error rates are measured against documented thresholds
- **AND THEN** overload produces bounded rejection/degradation rather than process exhaustion or cross-user identity reuse

#### Scenario: Maximum Observe response is encoded
- **WHEN** the compact Observe DTO contains 2,000 legal positions and maximum bounded slice metadata
- **THEN** its canonical uncompressed JSON encoding is no more than 2 MiB
- **AND THEN** provider, instrument, immutable reference, and policy metadata common to the slice are not redundantly repeated in every row

#### Scenario: Rollout capacity thresholds are evaluated
- **WHEN** the declared 1x fixture workload runs on the recorded CI host/runtime
- **THEN** accepted-request p95 owner+BFF latency is no more than 5 seconds and p99 no more than 12 seconds
- **AND THEN** five context/view cycles return browser heap to within 20 MiB of the post-first-cycle baseline
- **AND THEN** long-task p95 is no more than 100 ms and interaction p95 no more than 250 ms
- **AND THEN** a 320-attempt overload never grows the queue beyond 32, never OOMs, and leaves zero residual owned process groups after shutdown
- **AND THEN** server event-loop lag is no more than 100 ms p95 and 250 ms p99
- **AND THEN** peak server RSS delta is no more than 256 MiB, retained RSS after a 60-second cooldown is no more than 32 MiB above warmed baseline, and three repeated runs show no monotonic retained-RSS growth

### Requirement: Compatibility dual-read is deterministic and strictly bounded

Dark-launch comparison SHALL sample no more than 1% of eligible complete request
identities using a fixed versioned identity hash. A process SHALL run at most two
shadow reads, SHALL NOT queue shadow work, and SHALL give each shadow the lesser
of two seconds or the primary request's remaining deadline. Shadow work SHALL
never delay, fail, or alter the primary response.

Dual-read SHALL stop after the earlier of seven days or 1,000 completed shadow
identities. It SHALL stop sooner when rolling owner-read amplification exceeds
1.01x, main-path p95 latency regresses by more than 5%, or shadow-attributable
RSS exceeds 32 MiB against the recorded non-shadow baseline.

#### Scenario: Eligible request is not selected
- **WHEN** the versioned identity hash falls outside the configured one-percent sample
- **THEN** only the primary query runs
- **AND THEN** no probabilistic or unseeded sampling changes that decision

#### Scenario: Shadow capacity is full
- **WHEN** two shadow reads are active or no shadow time budget remains
- **THEN** the comparison is skipped with a bounded counter
- **AND THEN** it is not queued and the primary request remains unaffected

#### Scenario: Dual-read window completes or breaches a stop threshold
- **WHEN** seven days, 1,000 completed identities, or any amplification/latency/RSS stop threshold is reached
- **THEN** new shadow admission closes automatically
- **AND THEN** the compatibility report retains completed comparison evidence and the main route continues without shadow reads

### Requirement: Caching is immutable-reference aware and bounded

Server and browser caching SHALL be limited to read-only payloads keyed by
complete semantic identity and immutable reference. Browser evidence payloads
SHALL use bounded in-memory caching only unless a separately governed encrypted
offline mode is introduced. LocalStorage SHALL remain limited to non-evidence
presentation preferences such as the existing identity-bound K-line viewport.

#### Scenario: Same immutable analysis is revisited
- **WHEN** a user returns to the same confirmed analysis DatasetSnapshotRef and selectors
- **THEN** a bounded same-identity memory/ETag cache may serve or revalidate it
- **AND THEN** cache metadata retains source identity, schema version, stored time, and validation state

#### Scenario: Browser restarts
- **WHEN** a browser restarts after viewing analysis or evidence
- **THEN** market, analysis, assurance, and research payloads are fetched or revalidated rather than restored from LocalStorage
- **AND THEN** the existing viewport preference may restore only under its already defined identity policy

### Requirement: Legacy Observatory contracts remain compatible

The system MUST keep existing `/api/v1/observatory/*` routes, status codes, ETag
behavior, capability gate, complete response payload fields/types/optional
semantics, headers, and error shape available during the published compatibility
window. New workspace routes SHALL be additive and versioned. Compatibility
adapters SHALL map legacy context, series, trust, runs, and H1 responses
conservatively and SHALL NOT invent immutable references or analysis facts
absent from legacy responses. A route matrix SHALL freeze method, path/query/body
defaults, status, headers, payload, SSE-or-none, capability, and error behavior.

#### Scenario: Legacy frontend is served with the new backend
- **WHEN** a pre-V2 frontend calls the existing Observatory endpoints
- **THEN** it receives compatible methods, paths, selectors/defaults, status codes, headers/ETags, complete payload semantics, errors, capability behavior, and SSE-or-none behavior
- **AND THEN** no V2 analysis field is required for existing Observe, Assurance, Lineage, or H1 behavior

#### Scenario: New frontend runs before analysis backend cutover
- **WHEN** the V2 frontend is enabled while only compatible legacy Observe/Assurance/Research queries are available
- **THEN** those views use the compatibility adapter
- **AND THEN** Analyze is explicitly unavailable behind its capability bit
- **AND THEN** it does not calculate browser display estimates as a substitute

#### Scenario: Compatibility adapter cannot prove an identity
- **WHEN** a legacy response lacks a required owner, immutable reference, digest, clock, or method identity
- **THEN** the adapter returns `unproven` or unavailable for the affected V2 fact
- **AND THEN** it does not synthesize an id from a path, mutable current pointer, or response time

### Requirement: Web, SDK, and notebook share query DTO semantics

The versioned transport-neutral workspace query contracts SHALL be usable by
HTTP adapters and the SDK without exposing ORM models, repositories, database
connections, DataFrames, filesystem paths, or framework-specific response
objects. HTTP V2, HTTP compatibility, and SDK adapters SHALL be peers over the
same query application; SDK SHALL NOT import FastAPI/BFF response shaping.
Notebook consumers SHALL NOT modify `sys.path`, scan the repository, read
internal parquet directly, or import adapters.

#### Scenario: Notebook requests BTC analysis
- **WHEN** a notebook requests a confirmed analysis snapshot and metric series through the SDK
- **THEN** it receives the same reference, method, metric, clocks, availability, and error semantics as the Web BFF
- **AND THEN** it does not need to locate repository files or call an internal repository

#### Scenario: SDK consumer receives an unavailable metric
- **WHEN** a metric is unavailable under the owning contract
- **THEN** the SDK exposes the structured unavailable state and reason codes
- **AND THEN** it does not coerce the result to `0`, `NaN`, an empty DataFrame, or a successful optional value without status

#### Scenario: SDK receives an application error
- **WHEN** the transport-neutral query application returns ErrorEnvelope
- **THEN** the SDK exposes code, category, retryability, request/correlation identity, safe message, and bounded evidence refs
- **AND THEN** the SDK DTO contains no HTTP status, header, or Retry-After field

### Requirement: External evidence and streaming require a separate governed capability

This daily BTC workspace SHALL NOT expose news, social, macro, on-chain, stream,
L2, or external-event overlays under this change. Before any such route,
capability, SSE channel, replay, or redrive is implemented, a separate OpenSpec
change SHALL set `external_event_data=true` and define Capture SourceManifest,
source rights and deletion, original source timezone/value, event, publication,
observed, received, first-seen, available and revision clocks, temporal
precision/confidence, finality, correction/retraction, multi-source immutable
reference sets, Dataset/Study ownership, bounded projection, capacity, reconnect
and replay semantics. It SHALL separately assign Capture quarantine, Platform
delivery DLQ, immutable-artifact replay, event-envelope redelivery, and explicit
provider-refetch Command ownership.

#### Scenario: Future external overlay is proposed
- **WHEN** a child proposes news, sentiment, macro, on-chain, stream, L2, or SSE evidence
- **THEN** `btc-external-evidence-overlays-v1` or an equivalent governed child completes strict design approval before code
- **AND THEN** rights withdrawal prevents serving and invalidates affected caches without inventing a replacement fact
- **AND THEN** the daily workspace contracts remain unchanged until that capability is explicitly enabled

#### Scenario: Workspace GET requests missing stream history
- **WHEN** a read query cannot satisfy an overlay range from its bounded projection
- **THEN** it returns unavailable, cursor-expired, or resync-required under the future contract
- **AND THEN** it does not call a provider, request Capture, replay/redrive an event, or scan an unbounded log

### Requirement: BFF observability is bounded and privacy-safe

The BFF SHALL emit correlation-aware operational telemetry for slice name,
contract version, result state, reason code, owner-query latency, response
bytes, cache outcome, cancellation, deadline, and identity-mismatch count. Logs
and metrics SHALL NOT include access tokens, raw payloads, full evidence content,
local paths, or unbounded reference arrays.

Metrics SHALL use a fixed low-cardinality label allowlist: route/slice, contract
version, result category, reason family, owner class, channel, knowledge mode,
revision policy, cache outcome, and bounded lag/size buckets. Request id,
correlation id, context/ref digest, evidence id, URL, and raw source key SHALL
appear only in bounded structured logs or audit receipts. Shutdown receipts and
read-path write attempts SHALL be auditable; routine request logs may be sampled
under a documented retention policy.

Initial rollout SHALL target accepted-request availability of at least 99% over
24 hours and accepted-slice p95 latency of at most 5 seconds over 30 minutes.
Identity mismatch, read-path write attempt, and residual owned-process counts
SHALL each be zero. Current-product analysis lag SHALL be no more than one
expected daily release interval. Any identity/write event, any shutdown
residual, availability below 99%, p95 above 5 seconds for 15 minutes, analysis
lag beyond one interval, or eligible budget rejection above 5% for 15 minutes
SHALL halt rollout and invoke the owned rollback runbook.

#### Scenario: User reports a failed Analyze panel
- **WHEN** an Analyze request returns a structured failure
- **THEN** the UI exposes a safe correlation id and reason code
- **AND THEN** operators can correlate it with bounded BFF/owner-query timing and result-state telemetry
- **AND THEN** telemetry does not reveal raw market rows, credentials, or filesystem layout

#### Scenario: Stale response is discarded
- **WHEN** a response arrives after its request identity was superseded
- **THEN** the client records a bounded stale-response-discard diagnostic
- **AND THEN** the payload is not rendered, persisted, or logged in full

#### Scenario: Rollout alert fires
- **WHEN** an initial SLI threshold is breached
- **THEN** the alert identifies the owning runtime/query/product/cutover team, the bounded dashboard evidence, and the feature/route rollback action
- **AND THEN** V2 expansion stops until the breach is resolved and the rollback or forward-recovery receipt is recorded
