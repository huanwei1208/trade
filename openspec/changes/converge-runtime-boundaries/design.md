## Context

The repository is a mixed local trading research system with a Python control
plane, FastAPI/React product surface, SQLite and parquet state, and a C++ engine.
Recent work has already established useful boundaries: lazy CLI dispatch,
`trade_py/data/operations`, Observatory routers and query facades, per-handler
EventBus idempotency, channel-specific executors, and repository quality gates.

The remaining runtime concentration is measurable:

- `trade_web/backend/app.py` is 3,811 lines and registers 65 routes. Observatory
  already demonstrates the intended extraction pattern through a self-contained
  router registered by the application factory.
- `trade_py/db/trade_db.py` exposes 105 methods. Its constructor opens a
  write-capable SQLite connection, configures pragmas, ensures tables, runs
  migrations, creates indexes, and seeds defaults.
- the Web application's `_db()` helper constructs this object repeatedly from
  route and helper code, so ownership and closure are caller-dependent.
- `EventBus` separates five workloads by channel and records handler state before
  execution, but `ThreadPoolExecutor` admission is unbounded and overload has no
  typed operational state.

Two concurrent branches constrain this design. `wt/web-ctrlc-20260721` already
owns prompt Web shutdown changes in the EventBus, Web CLI, ingest pool, and
FastAPI lifespan. `wt/btc-web-workspace-20260721` owns the BTC frontend workspace
proposal. This change must rebase after those branches as needed and must not
duplicate their behavior.

## Design Quality Brief

### Requirements and acceptance

The change must make runtime ownership auditable without changing business
semantics. Acceptance requires all of the following:

1. One Web process-owned resource container initializes its write-capable
   `TradeDB` exactly once, provides it to services/routes, and closes resources in
   a deterministic order during lifespan shutdown.
2. A focused system/runtime router is extracted from `app.py`; its existing
   route paths, methods, parameters, status codes, and response payloads remain
   contract-compatible.
3. EventBus admission is bounded per channel. A full channel returns a typed
   saturation outcome, leaves durable event/handler state replayable, and does
   not claim handler completion.
4. Shutdown rejects new admission with an explicit state while already admitted
   work follows the configured graceful or non-waiting shutdown policy.
5. Operators can inspect workers, capacity, admitted work, active handlers,
   saturation count, and lifecycle state without scanning market data or
   mutating runtime files.
6. Temporary-root tests cover success, saturation, shutdown, submission failure,
   replay, route parity, resource closure, and bounded capacity.
7. `/api/run` owns bounded child processes outside FastAPI execution, records a
   stable run identity and terminal state in existing `job_runs`, reconciles
   stale command state after restart, and prevents parent-loss from leaving an
   untracked detached workflow.
8. Recovery remains bounded but fair: unavailable or saturated low-ID events
   cannot permanently starve later channels, transient lease-renewal failures do
   not silently permit duplicate execution, and live/replay paths enforce the
   same JSON-object payload contract.
9. Web command ownership is exclusive per data root. A second live owner fails
   closed before reconciliation or admission, while terminal audit writes remain
   owned and retryable until their exact outcome is durable.
10. The full resource shutdown has one finite wall-clock deadline. Incomplete
    command, handler, or claim-heartbeat cleanup leaves the container stopping,
    retains the database, and can be retried without fabricating success.
11. Runtime HTTP work has reviewed query bounds, calendar reads use one range
    query, heavy status inspection leaves the event loop, and sparse replay
    candidate lookup uses indexed keyset branches rather than scanning completed
    history.

Non-goals are a whole-project package rewrite, a DB/schema migration, a new
distributed queue, or changes to quantitative/data contracts.

### Ownership and boundaries

`trade_web/backend/app.py` remains the composition root only. A new
`trade_web/backend/runtime/` package owns the Web resource container, bounded
workflow-command runner and the first extracted system/runtime router. HTTP
functions validate transport input, call services, and translate typed service
outcomes; they do not create DB connections, run CLI workflows in-process, or
implement event-state transitions.

`trade_py/bus/` remains the owner of topics, channel routing, durable event
dispatch, handler admission, replay, and runtime capacity snapshots. If the
existing module needs decomposition, extraction stays inside this package:
`models.py` for typed outcomes, `admission.py` for bounded permits, and
`runtime.py` for the bus implementation. Public compatibility imports remain in
`trade_py.bus`.

`trade_py/db/trade_db.py` remains the compatibility DB facade in this change.
Persistent formats stay intact. Runtime code uses focused locked semantic
facade methods rather than reaching through `_conn` or carrying arbitrary SQL
through HTTP modules; the command runner reuses the existing `job_runs` table
instead of adding a second audit store. Existing status and event-handler
indexes support replay candidate keysets, so this correction adds no table,
column, index, DB version, or destructive migration. The resource container
makes lifecycle ownership explicit; later repository extraction can then
proceed by domain without changing request construction again.

Standalone CLI commands retain explicit local resource ownership. The existing
data operations package remains the read-only status owner. Observatory remains
under its existing router/query/catalog boundaries. C++ and frontend code are
outside this change.

Dependency direction is:

```text
FastAPI create_app
  -> WebResourceContainer
       -> TradeDB + EventBus + RuntimeCommandRunner + existing services
  -> focused routers
       -> application/runtime services
            -> TradeDB facade or EventBus

RuntimeCommandRunner
  -> existing job_runs audit facade
  -> supervised CLI child process group

CLI/scheduler
  -> EventBus public facade
       -> bounded channel admission
       -> durable handler state in TradeDB
```

### Data and state invariants

Durable SQLite event and per-handler rows remain authoritative; an in-memory
permit or executor future is never evidence of completion.

Event state transitions preserve the current identities:

```text
event persisted
  -> each eligible handler marked pending/started
  -> admission accepted -> handler runs -> ok|error
  -> admission saturated|shutting_down|submission_failed
       -> handler remains non-ok and replayable
```

Every admitted handler owns exactly one channel permit. The permit is released
exactly once after handler completion or failed executor submission. Saturated
work acquires no permit. Already-succeeded handlers are still skipped on replay.
Parent event IDs, event IDs, DAG row-qualified handler names, payload bytes, and
topic-to-channel routing remain unchanged.

New publications accept only JSON objects. Omitted payload is the only case
normalized to `{}`; explicit null, arrays, strings, numbers and booleans fail
before durable insertion. The validated payload is serialized once, and live
dispatch receives a decoded canonical snapshot of the same bytes so later
caller mutation cannot diverge from replay. Deterministic child handoffs perform
the same validation before their idempotency identity is inserted. Historical
malformed durable rows retain their fail-closed replay quarantine.

Runtime admission failures use reserved persistence provenance owned only by
EventBus. Arbitrary handler/provider exception text, even when it resembles an
admission message, remains terminal until explicit operator replay. Agenda
publication uses a deterministic key derived from the agenda identity; an
exception after durable insertion recovers that event rather than creating a
second one. A durable nested agenda child may be deferred, but its agenda row
cannot remain ambiguously running.

Each Web command has one existing `job_runs` identity with stage `web_command`.
One interprocess owner lock per canonical data root is acquired before stale
reconciliation and command admission and held through durable terminal cleanup.
Lock contention fails closed; it never terminalizes another live owner's rows.
Spawn, PID ownership and process-local capacity are operational state; the
durable run row is the audit source for running, successful, failed, terminated,
or stale-reconciled completion. A failed terminal write remains an exact
process-owned pending completion and blocks successful shutdown until a bounded
retry commits it. Raw request payloads are not persisted there.

The Web resource container has one lifecycle:
`new -> started -> stopping -> stopped`. Start is idempotent only for the same
container instance; use after `stopping` or `stopped` is rejected. Shutdown
closes admission before closing executors and closes DB after components that
write final state have stopped. A failed stop remains fail-closed but may be
retried from its unfinished ownership stage; it does not permanently strand the
container in `stopping`. One owner-level monotonic deadline bounds command
termination, executor drain and claim-heartbeat completion. Deadline expiry
does not close or release the database while a writer remains owned.

Capacity counters are process-local observations. They report configured
capacity and current admitted/active counts, not durable business truth. Unknown
or unavailable counters remain explicit rather than becoming zero success.

### Contracts and compatibility

No existing route or EventBus payload is removed. The first router extraction
uses contract tests to compare route path, method, parameter defaults, response
shape, and error mapping before and after registration.

Existing accepted `EventBus.publish(topic, payload, parent_event_id)` callers
keep their durable event return on accepted admission for object payloads. New typed
`publish_with_outcome` or equivalent service behavior exposes overload to
boundaries that can return `503`, defer scheduler work, or display operational
state. The final API name is frozen during implementation review; it must not
make saturation look like a successfully dispatched event.

A non-accepted HTTP publication has already persisted an event. Its response
therefore identifies `event_id`, durable deferred state and recovery of that
existing identity; it does not emit automatic-resubmission guidance or
`Retry-After` that would create another event.

`/api/run` keeps accepted `target` and `limit`, adds `pid` and stable `run_id`,
and returns explicit capacity, lifecycle, audit-persistence and spawn failures.
Public responses use stable reason codes and sanitized messages; raw SQLite,
filesystem and process exceptions remain in payload-safe correlated server
logs. Completion is queryable through the existing run surface. The Web process
never calls the CLI workflow implementation in-process.

Runtime HTTP and SSE parameters are bounded at the transport edge. Calendar
lookups use one locked date-range facade rather than one query per day, list and
stream limits have finite maxima, and status scans execute outside the async
event loop with explicit degraded reason codes.

The additive runtime capacity view is versioned and contains only process-local
operational metadata. Existing `/api/status` fields remain compatible. If the
capacity view is nested into status, it is additive; alternatively a focused
`/api/runtime/capacity` route may be added without changing existing paths.

Existing pending/error rows and old events remain readable and replayable.
Database tables, parquet layouts, and Catalog contracts stay at their current
versions.

### Persistent-write safety

`TradeDB.event_log` and `event_handler_runs` remain the authoritative writers and
readers for durable dispatch state. Event and handler identity are persisted
before executor admission; no future, permit, counter, or in-memory queue entry
can make an event successful. The existing `(event_id, handler_name)` uniqueness
and succeeded-handler lookup remain the idempotency boundary.

All durable transitions continue under locked `TradeDB` facade methods and
SQLite transaction/commit behavior. Runtime routes and services do not execute
private or unlocked SQL against the shared connection. Sync-state reads and
writes, Web projections, calendar ranges, replay candidates and command audit
transitions all stay inside the facade owner. Admission adds no second database,
spool, manifest, or shadow writer. A permit is acquired only after durable
identity exists. If admission or submission fails, the durable handler remains
non-ok and replayable; partial results are aggregated from handler rows before
the parent event may finalize.

The Web resource container serializes DB lifecycle but does not change reader
consistency: callers observe committed SQLite/WAL state through the same facade.
Corrupt or unavailable predecessor DB state fails startup or the owning
operation; the change never replaces it with a new empty DB as recovery.

Validation uses temporary database roots and fault injection. Before rollout, a
small fixture records an event with multiple handlers, forces one accepted and
one saturated/submission-failed result, restarts the bus, replays only the
non-ok handler, and verifies the final audit chain. Existing backup commands
remain the recovery mechanism for real DB files; this change performs no live
data migration and needs no backup rewrite. Rollback restores prior admission
wiring while preserving all committed event and handler rows.

### Failure and recovery

Invalid channel configuration fails application startup before the resource
container is published. Partial startup closes already-created resources in
reverse ownership order and returns the original exception with context.

When a channel is full, admission returns `saturated` immediately or within a
small configured enqueue timeout. The durable event and non-ok handler row stay
visible. The caller receives an actionable outcome; daemon/scheduler callers can
defer, HTTP callers identify the persisted event without advising resubmission,
and operators can replay that event after capacity recovers.

If executor submission raises after a permit is acquired, the permit is released,
the handler run remains replayable with a stable submission-failure reason, and
the exception is not swallowed. If some handlers for one event are admitted and
another is saturated, the event is partial/pending, never `ok`; replay skips the
completed handlers and retries only non-ok handlers.

Shutdown first changes lifecycle state so new work is rejected, then applies the
configured wait policy to admitted work. This design consumes rather than
duplicates the pending Ctrl+C branch's Web shutdown behavior.

Crash recovery remains SQLite replay. Periodic replay keeps bounded rotating
progress and wraps only after advancing through the keyspace; unavailable
handlers and one saturated channel cannot consume every future recovery pass.
Candidate selection is split into status-indexed and handler-indexed keyset
branches, so empty or sparse recovery does not scan completed event history.
Claim renewal retries transient SQLite failures with bounded backoff. Claim
tokens include PID and Linux process-start identity; stale time alone cannot
reclaim a claim while that exact owner is still alive, including an outage that
lasts beyond the nominal lease interval. Definitive ownership loss is visible
and fail-closed rather than silently allowing an old worker to report success. A
DAG job committed successful remains successful if only its idempotent child
handoff fails; replay reuses the result and retries the handoff.

Workflow children are supervised so loss of the FastAPI owner does not leave an
untracked detached process group. Startup first acquires exclusive data-root
command ownership, then reconciles stale `web_command` runs before accepting new
work. Cooperative shutdown closes command admission first, terminates owned
process groups against one deadline, retries exact terminal audit writes, then
drains EventBus and every claim heartbeat before closing the DB. A failure at
any stage preserves ownership for a later retry.

### Performance and capacity

Each channel has finite configured workers and admitted capacity. Initial
defaults should preserve current workers and use a conservative multiple of
workers for waiting work; exact defaults require six-role approval and a blocked-
handler capacity test. Configuration rejects nonpositive workers, capacity below
workers, and values beyond the repository's reviewed operational bound.

Admission is O(1) and does not scan event history. Sparse replay is bounded by
indexed candidate keysets rather than total completed history. Capacity
snapshots are O(number of channels). Route extraction must not add DB opens or
extra payload queries. Runtime route parameters have finite public maxima,
calendar uses one range query, and heavy status inspection is offloaded from the
event loop. The Web resource container removes repeated schema/migration work
from request construction and provides one connection lock owner per process.

At 10x burst input, memory remains bounded by channel and command capacities plus
durable SQLite rows. Producers receive saturation rather than growing executor
queues. NLP saturation cannot consume signal/decision permits or monopolize
periodic recovery because channels retain separate admission ownership and
replay advances its durable cursor.

Capacity validation blocks handlers with deterministic events, submits beyond
the configured bound, asserts accepted work never exceeds capacity, checks
saturation latency, then releases work and verifies all permits return to zero.

### Observability and operations

Each channel reports a stable name, lifecycle state, workers, total admitted
capacity, admitted count, active handler count, available permits, accepted
count, saturation count, submission-failure count, and last saturation time.
Counters are monotonic for one process generation and reset visibly on restart.

Structured logs include event ID, handler name, topic, channel, admission
outcome, and configured capacity without logging full sensitive payloads.
Saturation is warning-level and rate-limited or aggregated; submission failure is
error-level with root cause.

The runtime status surface distinguishes `ready`, `saturated`, `stopping`,
`stopped`, and `unavailable`. Empty channels are not failures. Missing resource
initialization is unavailable, not a fabricated healthy zero.

Operators recover by reducing producers, waiting for capacity, inspecting pending
handler rows, and invoking the existing replay path for the persisted event.
Command runs expose stable IDs and terminal results through existing operations
surfaces. No automatic deletion, duplicate POST guidance, payload loss, or
invisible retry loop is introduced.

### Validation strategy

Unit tests own the permit state machine, invalid capacity, accepted/saturated
outcomes, permit release, shutdown rejection, and executor submission failure.
EventBus tests use temporary `TradeDB` roots to verify durable event/handler
states, partial multi-handler admission, per-handler idempotency, replay, parent
links, final event status, rotating recovery fairness, transient claim renewal,
DAG handoff-only retry, canonical live/replay payload parity, prolonged renewal
outage fencing, no-handler restart recovery, agenda post-commit idempotency,
reserved failure provenance, sparse-history query plans, and heartbeat shutdown.

Web tests create the application against `tmp_path`, assert resource start/close
counts, exercise the extracted routes through `TestClient`, and compare response
contracts. A regression test verifies repeated requests do not repeatedly
construct/migrate `TradeDB`. Command tests verify durable start/finish records,
spawn failure, saturation, stale-run reconciliation, owner-loss behavior,
overlapping-owner rejection, terminal persistence retry, one-deadline
process-group shutdown, and retry of an incomplete container stop.

A bounded performance smoke blocks workers and proves admitted tasks never
exceed the configured capacity. Compileall covers Python syntax. Repository
quality planning and checks cover formatting, lint, typing, tests, design
approval, and protected runtime paths.

No live provider, real DB, real parquet, or market-data probe is needed for this
change.

### Alternatives and trade-offs

**Big-bang clean architecture rewrite:** rejected. Existing focused packages and
parallel BTC work provide working seams. A broad rename would create conflicts
without improving failure semantics first.

**Split `app.py` only:** rejected as the first and only fix. Moving decorators
without resource ownership would leave repeated write-initializing DB creation
and make the architecture look cleaner without changing its runtime behavior.

**Use a shared singleton without a container:** rejected. The current global
EventBus already shows the ambiguity of process-global ownership and first-DB
binding. An explicit lifespan-owned container is testable and has deterministic
teardown.

**Rely on `ThreadPoolExecutor`'s unbounded queue:** rejected because overload
becomes memory growth and delayed work with no producer signal.

**Replace EventBus with Redis/Kafka:** rejected for this phase. SQLite already
provides durable IDs, replay, and local operation. Bounded admission solves the
verified local failure mode with lower migration and operational cost.

**Block producers indefinitely:** rejected. Bounded waiting with a typed outcome
keeps Web and scheduler callers diagnosable and cancellable.

### Rollout and rollback

1. Rebase after the Web Ctrl+C branch or explicitly incorporate its accepted
   lifecycle contract. Resolve conflicts without weakening its prompt-shutdown
   tests.
2. Implement and commit the Web resource container with focused lifecycle tests.
   Preserve all routes in place.
3. Extract only system/runtime routes and commit parity tests. Do not touch BTC
   Observatory frontend work.
4. Add typed bounded admission behind the EventBus facade, default it in tests,
   and run replay/partial/saturation coverage.
5. Add the read-only capacity status and capacity smoke. Enable bounded admission
   for production defaults only after the full focused suite passes.
6. Isolate `/api/run` behind the owned command runner, durable existing
   `job_runs` audit state, crash-safe supervision, and retryable shutdown.
7. Run implementation consensus review, strict design approval, repository
   quality checks, compileall, focused pytest, and diff checks.

Rollback reverses slices: disable command-runner wiring, disable bounded
admission while retaining typed models, restore in-file route registration, then
restore prior resource construction. Reversion requires no durable-state
restoration. Persisted pending events and `job_runs` remain readable by both
versions. Any rollout showing orphaned commands, unexpected saturation, event
completion drift, request incompatibility, or shutdown regression triggers
rollback before further module extraction.
