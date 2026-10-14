## ADDED Requirements

### Requirement: Target Bootstrap SHALL be the sole production composition root

The target architecture SHALL have one `trade.bootstrap` package as the only
production module allowed to assemble concrete Platform implementations, owner
repositories/adapters, Context use cases, Process managers and Interface
handlers. It SHALL expose explicit application profiles for `cli`, `http`,
`worker`, `scheduler` and `migration`; each profile SHALL declare required and
optional capabilities, database startup mode, owner instance/fence, lifecycle
order and compatibility selections.

Bootstrap SHALL compose through framework-free contracts and shall not contain
business rules, provider interaction, SQL, artifact parsing, process flow or
HTTP/CLI response shaping. Contexts, Processes and Interfaces SHALL not
instantiate `TradeDB`, EventBus, provider clients, native bindings, scheduler
loops or Platform adapters directly. Platform SHALL not import Bootstrap.

#### Scenario: The HTTP profile starts
- **WHEN** an HTTP application requests its Bootstrap profile
- **THEN** Bootstrap constructs one owned capability graph and Interface handlers receive only query/use-case/process/status handles

#### Scenario: A CLI query needs read-only state
- **WHEN** a status/show command selects the CLI read profile
- **THEN** Bootstrap supplies a read-only database/query capability and does not run migrations, seeds, EventBus or a worker runtime

#### Scenario: An Interface constructs an adapter
- **WHEN** a target HTTP, CLI, SDK, schedule or event module instantiates a database, EventBus or provider implementation
- **THEN** architecture checks reject the second composition root and require an injected Bootstrap handle

### Requirement: Bootstrap lifecycle SHALL be explicit, fenced and truthful

Every Bootstrap profile SHALL have a closed lifecycle `new`, `starting`,
`ready`, `stopping`, `stopped` or `failed` and one immutable generation. Startup
SHALL acquire database/runtime capabilities before constructing dependents,
record each acquired owner and unwind only those resources in reverse order
after a partial failure. Readiness SHALL require every mandatory capability and
shall identify optional degraded capabilities separately.

Shutdown adoption SHALL use the approved Kernel control/deadline/receipt
contracts only after `runtime-owner-shutdown-and-recovery-hardening-v1` is
strictly approved and implemented. Until then, Bootstrap compatibility profiles
SHALL delegate current lifecycle behavior without mapping free-form exceptions
to fabricated `ShutdownReceipt` facts. A profile SHALL not report `stopped`
while it retains a live process group, executor task, Python thread,
persistence audit, writer lease or inflight start.

#### Scenario: Startup fails after database acquisition
- **WHEN** a later mandatory capability fails during construction
- **THEN** Bootstrap closes admission and unwinds only the acquired generation in reverse order, preserving explicit residual ownership if cleanup cannot finish

#### Scenario: A shutdown deadline expires
- **WHEN** an adopted owner cannot drain, persist terminal state or release its fence before the shared deadline
- **THEN** Bootstrap returns incomplete/deadline-exceeded with retained fence and residual owner rather than closing the database or claiming success

#### Scenario: Shutdown hardening is not ready
- **WHEN** a current Web, EventBus, command-runner or daemon profile is requested before the hardening child completes
- **THEN** Bootstrap keeps the legacy compatibility lifecycle selected and does not advertise formal shutdown guarantees

### Requirement: Compatibility shims SHALL delegate one selected profile

Existing `trade_py` and `trade_web` entrypoints SHALL remain public compatibility
surfaces. Each migrated entrypoint SHALL delegate to exactly one named Bootstrap
profile through a thin shim while preserving existing arguments, environment
selection, exit/status semantics, route/payload/SSE shape and lifecycle timing.
An entrypoint that has not passed its compatibility child SHALL remain on the
legacy path.

There SHALL be no simultaneous independent Web/CLI/scheduler containers for one
logical owner generation. A global legacy EventBus facade MAY point to the
Bootstrap-owned bus during the compatibility window but SHALL not create or
replace it. Removal requires a consumer inventory, compatibility snapshots,
minimum 30-day window and a rollback selection.

#### Scenario: FastAPI delegates after approval
- **WHEN** the HTTP compatibility slice passes route/OpenAPI/SSE and lifecycle fixtures
- **THEN** `create_app` obtains its runtime handles from one Bootstrap HTTP profile without changing existing public responses

#### Scenario: A CLI command is not migrated
- **WHEN** its argument/exit/data compatibility evidence is incomplete
- **THEN** the command keeps its current construction path and cannot partially mix legacy and target owners

#### Scenario: Two shims request the same owner
- **WHEN** concurrent entrypoints would create separate writable runtimes for one data root
- **THEN** owner fencing admits one generation and returns an explicit conflict/unavailable result to the other

### Requirement: CapacityEnvelope SHALL make every 1x and 10x gate comparable

Platform SHALL define a versioned, deterministic `CapacityEnvelope` for
measurement results. It SHALL contain fixture identity/digest, scenario,
cardinality and duration, opaque source/stream classifications and closed
`credential_mode` when applicable,
binary/config generation, concurrency, worker and queue limits, runner CPU/
memory/disk profile, monotonic start/finish/duration, latency percentiles,
admission/rejection/dead-letter counts, SQLite transaction/lock/write time,
scan bytes/files, CPU/memory/disk peaks, backlog/recovery time, threshold policy
reference and closed result `pass`, `defer` or `overload`.

`credential_mode` SHALL be a closed non-secret class. Canonical and operator
projections MAY carry an opaque policy-reference digest, but SHALL NOT contain
credential values, names, environment-variable names, key IDs, account/tenant IDs,
headers, tokens, paths or provider topology. Negative codec fixtures SHALL reject
those fields.

Every envelope SHALL reference one immutable, digest-bound `CapacityWorkloadProfile`
and `CapacityThresholdPolicy`. The workload profile SHALL define exact operation
mix, cardinalities, arrival rates, payload-byte distributions, ordering-key/class
skew, warm-up, steady-state and recovery duration, failure injection, runner
normalization and the exact axes multiplied from 1x to 10x. The threshold policy
SHALL define pass/defer/overload limits for accepted p95/p99 latency, SQLite lock
wait and lock hold, transaction duration, queue/backlog growth and drain, maximum
starvation interval, CPU, peak/retained RSS, DB/WAL/scratch/disk growth, archive
passes/bytes reread and crash/recovery time. Missing profile identity, required
measurement or runner comparability SHALL produce `defer`; implementations SHALL
not choose workload meaning or pass thresholds after observing results.

Each child SHALL reserve named finite limits before activating a capability.
Illustrative parent values, host CPU count or existing ThreadPool defaults SHALL
not silently become production limits. The envelope SHALL record measurement
failure as unavailable rather than a zero. Sampling, if required, SHALL be
deterministic and digest-bound.

#### Scenario: A 10x delivery run completes
- **WHEN** Platform Events processes the declared 10x fixture
- **THEN** the result records the exact digest-bound scaled axes, workload mix, backlog, class/key fairness, worker/queue limit, SQLite lock wait/hold, latency, resource peaks and recovery outcome against the predeclared threshold policy under one comparable envelope

#### Scenario: Resource telemetry is unavailable
- **WHEN** peak memory or disk measurement cannot be observed
- **THEN** the envelope reports the field unavailable and the gate defers rather than filling zero or passing on incomplete evidence

#### Scenario: A child proposes a larger limit
- **WHEN** Capture, Datasets or an Interface changes a reserved queue, batch or concurrency limit
- **THEN** it supplies new 1x/10x envelopes and a reviewed threshold policy before cutover

#### Scenario: Two runs use different workload definitions
- **WHEN** envelopes differ in workload-profile digest, runner normalization or required measurement availability
- **THEN** the gate reports them non-comparable and defers rather than claiming a regression, improvement or pass

#### Scenario: Capacity metadata contains credential detail
- **WHEN** a producer attempts to encode a credential name, environment variable, key/account identity, token, header or path in a capacity result
- **THEN** the codec rejects the envelope and emits only a safe invalid-evidence diagnostic

### Requirement: Platform capabilities SHALL remain technical and bounded

The Bootstrap capability registry SHALL contain explicit technical capabilities
for persistence, events, execution, scheduling, settings, backup and status
queries. Platform source and contracts SHALL not introduce BTC, Kline, provider,
Dataset, Study, recommendation, portfolio, news or other business aggregate
vocabulary. Business command/event payloads remain owner contracts and are
opaque to generic routing except for schema identity and digest verification.

Queues, worker pools, query windows and status histories SHALL be finite.
Capability queries SHALL distinguish empty, partial, stale, blocked,
not-observed, unavailable and unknown and SHALL not start work or repair state.
Execution adapters MAY own subprocess/process-tree mechanics only behind an
approved Platform port; business use cases and Interfaces SHALL not create
processes directly.

Every capability profile SHALL publish bounded telemetry-freshness evidence and
alert ownership for oldest outbox age, terminal-persistence unavailable, persistent
ordering gaps, activation incomplete/authority unavailable/rollback pending,
residual shutdown owners, shutdown-link integrity `delivery_failed` or
`delivery_outcome_unknown`, required-codec snapshot integrity, message-contract
health and backup certification/trust failures. Freshness SHALL carry observation
time, expected interval, stale-after bound and source status. Missing or stale
required telemetry SHALL be `unavailable` or `defer`, never healthy. Alert policy
SHALL name threshold, evaluation window, owner, runbook and
acknowledgement/escalation path without putting unbounded identities into metric
labels.

Before opening ingress, Bootstrap SHALL freeze the static owner-codec registry and
ask Platform Persistence to validate the sole authoritative current
`RequiredOwnerCodecManifestV1` against the exact stable 16-shard revision vector
under the same closed retention-mutation gate, current owner fence, exclusive
snapshot lease and finite startup deadline. It SHALL compare no more than 4,096
entries with no more than 13 registry-key comparisons per entry and SHALL NOT scan
durable projection, replay, receipt or audit rows. A missing, non-current,
incomplete, corrupt, stale-fence, stale-revision or over-capacity snapshot, missing
required codec or descriptor/capability identity mismatch SHALL keep ingress closed
with the exact Kernel readiness product.

Caller and readiness DTOs SHALL remain redacted. A separately authorized bounded
operator query SHALL expose the Kernel-defined
`MessageContractHealthObservationV1` with only public failure code, descriptor
count, manifest-entry count, one exact closed cause and its exact closed recovery
action. It SHALL contain no descriptor, registry key, dependent identity, actor,
payload, callback, exception text, credential or path. The cause/action relation
SHALL be the exact Kernel V21 relation and SHALL accept no arbitrary hint:

- codec exception/result type/output/round-trip and projection malformed/too-large
  causes map to `inspect_owner_codec`;
- missing/incomplete/digest-mismatched snapshot causes map to
  `repair_manifest_snapshot`;
- stale-fence/read-timeout causes map to `retry_bootstrap`;
- missing required binding maps to `restore_required_codec`;
- codec/required-binding identity mismatch, duplicate registry key and static
  binding mismatch map to `rollback_codec_release`; and
- registry capacity conflict maps to `reduce_registry_capacity_pressure`.

The query SHALL be observational only. It cannot repair a snapshot, mutate the
registry, restore a codec, roll back a release, reopen ingress or start another
workflow.

#### Scenario: Platform routes a Capture event
- **WHEN** a future `CaptureCommitted` envelope enters delivery
- **THEN** Platform validates generic envelope metadata/digest and routes it without importing Capture domain or interpreting source semantics

#### Scenario: Operations queries capacity
- **WHEN** an Interface requests Platform status
- **THEN** the bounded query returns technical lifecycle/backlog/capacity evidence and performs no replay, migration, restore or data repair

#### Scenario: A critical metric stops updating
- **WHEN** a required backlog, activation, shutdown or backup-trust telemetry source exceeds its declared stale-after bound
- **THEN** status and gates report telemetry unavailable/defer, an owned alert is eligible, and no zero or last-known value is presented as current health

#### Scenario: A required historical codec is unavailable
- **WHEN** the current required-codec snapshot cannot prove the exact executable codec identity under the frozen registry
- **THEN** Bootstrap keeps ingress closed, returns the redacted required-codec-unavailable readiness product and exposes only the exact authorized cause/action observation

#### Scenario: The manifest is internally complete but not current
- **WHEN** its owner/fence or source-revision digest differs from the frozen current window
- **THEN** Bootstrap rejects it and does not scan dependent durable rows or select a stale snapshot

#### Scenario: An operator inspects message-contract health
- **WHEN** an authorized query asks why registry readiness failed
- **THEN** it returns one bounded exact cause/action pair with safe counts and performs no registry, snapshot or lifecycle mutation

#### Scenario: Shutdown-link delivery is ambiguous
- **WHEN** a claimed integrity signal reaches `delivery_outcome_unknown`
- **THEN** Platform health keeps the outcome visible and non-healthy while Bootstrap does not trigger an automatic resend

#### Scenario: A business name enters Platform
- **WHEN** a proposed Platform module or table encodes a BTC-, Dataset- or Study-specific rule
- **THEN** architecture review rejects it and moves the rule to its owner Context or Process contract

### Requirement: Foundation activation SHALL require explicit prerequisites

Foundation implementation SHALL begin only after this change has current
digest-bound six-role approval and strict design-check, and only after the frozen
`kernel-and-public-contracts` V21 candidate at commit
`3cdb25e0ad8a377d8ece0469333a582700f5bf2b` and portable artifact digest
`sha256:a7ec722f8e922cdc8630920a771b7a43a0945c0e765dd2347ac51c7bd316e75b`
has its own current digest-bound strict approval and is merged or otherwise present
as governed input. This V21 candidate is not yet an approved implementation
prerequisite, so Platform implementation and strict handoff remain blocked. An
equivalent later commit is acceptable only when the governed Kernel artifact digest
remains exact; any digest change requires an explicit compatibility review, an
update to this prerequisite and renewed Platform review/strict approval.
Architecture guardrails SHALL be updated with the exact target legacy bridge and
Platform table bindings before those paths write.

No current runtime may adopt formal owner shutdown/control behavior before
`runtime-owner-shutdown-and-recovery-hardening-v1` passes strict approval and its
persistence-retry, concurrent-stop, startup-cleanup, executor-tail, monotonic,
crash-takeover and real signal-to-reap implementation fixtures. No Context may
emit formal outbox or accept formal ingress until Platform transaction, inbox,
lease recovery and duplicate/crash fixtures pass.

#### Scenario: Kernel V21 is not strictly approved and present
- **WHEN** an implementation PR cannot consume the exact V21 candidate with its own current strict approval
- **THEN** it remains blocked and does not recreate local IDs, envelopes, actors, receipts or errors

#### Scenario: Kernel prose or contracts drift
- **WHEN** the available Kernel artifact digest differs even though its change name or branch is unchanged
- **THEN** Platform implementation remains blocked until compatibility is dispositioned and this design regains digest-bound review and strict approval

#### Scenario: A Context wants to migrate first
- **WHEN** Capture or another Context proposes a durable command/outbox before the Platform foundation passes its implementation gates
- **THEN** the Context child is blocked rather than inventing another transaction, event or runtime substrate

#### Scenario: Design artifacts drift
- **WHEN** implementation changes a reviewed contract, state machine, table owner or capacity policy
- **THEN** the design digest is invalidated, the affected roles re-review it and strict approval is regained before code continues
