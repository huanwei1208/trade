## Why

The project has already converged its public CLI and added focused data,
Observatory, and quality packages, but three runtime boundaries still concentrate
unrelated behavior:

- `trade_web/backend/app.py` owns 65 routes and constructs `TradeDB` from a local
  helper throughout request handling.
- `TradeDB` construction opens SQLite, enables WAL, creates schema, runs
  migrations, ensures indexes, and seeds defaults, so a read-looking caller can
  acquire write-capable initialization behavior.
- `EventBus` isolates ingest, NLP, signal, decision, and I/O work into separate
  thread pools, but submission uses unbounded executor queues and exposes no
  stable overload result or per-channel capacity status.

These are not reasons for a broad rewrite. They are evidence that the next
architecture step should make runtime ownership explicit: application resources
own their lifecycle, HTTP handlers delegate to cohesive services, and durable
event submission has bounded, observable behavior.

## What Changes

- Add an application resource container that owns the Web process's `TradeDB`,
  EventBus, inference services, bounded workflow-command runner, and shutdown
  order. Request handlers obtain resources from this owner instead of
  constructing a write-initializing DB ad hoc.
- Split FastAPI registration by cohesive surface, starting with system/runtime
  routes. Keep `create_app()` as the composition root and preserve all existing
  paths, methods, payloads, and capability gates.
- Introduce bounded EventBus channel admission with explicit `accepted`,
  `saturated`, `shutting_down`, and `submission_failed` outcomes. Persisted
  events rejected before handler execution remain replayable and are never
  reported as completed.
- Run Web-triggered CLI workflows in owned child processes rather than inside
  FastAPI. Record accepted and failed launches in the existing `job_runs` audit
  surface, bound concurrent commands, reconcile stale command state after
  restart, and terminate owned process groups during shutdown.
- Hold exclusive command ownership per data root before stale reconciliation,
  retain failed terminal audit writes for retry, and fail closed rather than
  rewriting another live owner's run.
- Fence handler claims with process identity, use reserved runtime-admission
  provenance, make agenda handoff idempotent across post-commit ambiguity, and
  dispatch the canonical durable payload snapshot.
- Expose a read-only runtime capacity snapshot for status/operations surfaces:
  configured workers, bounded capacity, active handlers, admitted tasks,
  saturation count, and lifecycle state per channel.
- Bound the full shutdown and runtime HTTP cost, keep claim heartbeats owned
  until DB closure is safe, use one calendar range query, and select sparse
  replay candidates through existing indexed keysets.
- Keep channel routing, event IDs, per-handler idempotency, DAG row identity,
  parent-child event links, and replay behavior compatible.
- Deliver the change incrementally: first lifecycle ownership and tests, then a
  single extracted route surface, then bounded admission and observability.

## Non-Goals

- Trading, recommendation, forecast, backtest, factor, trust, and historical
  knowledge semantics remain unchanged.
- No DB schema, parquet layout, catalog, market-data, or news payload migration.
  HTTP changes are additive: durable deferred-event responses stop advising a
  duplicate POST retry, and `/api/run` adds stable run identity plus explicit
  overload/failure outcomes while retaining accepted fields.
- No replacement of SQLite, FastAPI, React, `ThreadPoolExecutor`, or the C++
  engine.
- No bulk split of `app.py`, `trade_db.py`, `jobs/__init__.py`, or frontend files.
- No duplicate of the existing `wt/web-ctrlc-20260721` shutdown fix or the
  `wt/btc-web-workspace-20260721` BTC workspace design.
- No new network calls, data refresh, model work, or writes to real `data/` during
  implementation or validation.

## Capabilities

### New Capabilities

- `runtime-boundary-ownership`: process-owned resource lifecycle, route/service
  boundaries, bounded event admission, overload semantics, and runtime capacity
  observability.

### Modified Capabilities

None. Existing CLI, HTTP, DB, event, data, and Observatory contracts remain the
authoritative compatibility surface.

## Affected Contracts

- **FastAPI:** route paths, methods, query parameters, SSE behavior, and
  Observatory registration remain compatible except for the documented additive
  `/api/run` run identity and explicit failure outcomes. Durable
  event-admission failures identify the already-persisted event and direct
  recovery to that identity rather than resubmission. Existing defaults remain
  accepted within finite reviewed maxima; invalid explicit non-object payloads
  fail before persistence and internal command errors are sanitized.
- **Application resources:** Web request handlers use one process-owned
  write-capable `TradeDB`, EventBus, and command-runner resource set, initialized
  once and closed once. Failed shutdown remains retryable without closing the DB
  under live writers. Standalone CLI commands keep their explicit DB lifecycle.
- **EventBus:** `publish()` remains durable-before-dispatch. A compatibility
  adapter preserves accepted-call behavior while new typed admission is used by
  HTTP and scheduler boundaries that need explicit overload handling.
- **Operations:** a new additive runtime-capacity payload exposes bounded channel
  state without scanning real data or changing event/job records.
- **Concurrency:** every channel has a finite admitted-work bound. Saturation
  never becomes success, never drops an event silently, and remains replayable.
  Periodic replay advances fairly across the durable keyspace and does not let a
  saturated or unavailable older channel starve later recoverable channels.
  Stale time alone cannot reclaim a claim whose exact process owner is alive,
  and incomplete shutdown retains DB ownership for retry.
- **Workflow commands:** `/api/run` preserves its accepted target/limit fields,
  adds `pid` and stable `run_id`, and stores completion status in `job_runs`.
  Process-local capacity is never the only audit record. Command admission and
  reconciliation require exclusive data-root ownership, and a failed terminal
  write remains owned until durable.

## Compatibility and Rollout

Implementation is additive and staged behind internal composition boundaries.
The first slice only centralizes Web resource lifecycle and extracts one route
group without changing responses. Bounded admission is enabled only after
success, saturation, shutdown, replay, and partial-submission tests pass.
Command execution is enabled only after process ownership, stale-run
reconciliation, durable completion, parent-loss behavior, and retryable
container shutdown tests pass.

Rollback is a code revert in reverse slice order. No durable data migration is
required. Persisted pending events remain compatible with the existing replay
path, existing `job_runs` rows remain readable, and no queue-only or
process-local state is treated as authoritative.

## Validation

- Focused pytest for Web resource initialization/closure, route contract parity,
  EventBus admission, per-handler idempotency, replay, saturation, shutdown, and
  partial submission, plus durable command completion and parent-loss cleanup.
- Temporary data roots and SQLite fixtures only; no live network or real-data
  write.
- Capacity smoke proving admitted work is bounded under a blocked handler and
  that status inspection remains bounded and read-only.
- `python -m compileall trade_py trade_web tests`, `./trade dev check
  --show-plan`, `./trade dev check`, and `git diff --check`.
- Mandatory six-role design review and strict design approval before production
  code; mandatory six-role implementation review before merge.
