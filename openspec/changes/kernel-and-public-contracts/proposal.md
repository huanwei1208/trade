## Why

The approved `restructure-trade-architecture-v1` migration cannot establish
Platform, Processes, Context, SDK, CLI, or HTTP boundaries while identifiers,
operation states, errors, actor provenance, and immutable references remain
implicit dictionaries or owner-specific legacy objects. Current code exposes
incompatible facts: EventBus events carry a live `bus` back-reference,
`OperationResult` and `job_runs` use open string statuses, Observatory
`ArtifactRef` exposes a filesystem path, and `/api/run` has a separate
admission/error shape.

This child creates the smallest framework-free contract substrate before any
runtime route or repository is migrated. It also closes a reliability gap made
visible by current shutdown code: a public deadline is not bounded if cleanup
later performs an unbounded thread join, and an observation timeout must not be
reported as successful cancellation.

## What Changes

- Add only the justified target Kernel primitives under `src/trade/kernel`:
  opaque identifiers, UTC instants/deadlines, content digests, bounded contract
  errors/results, envelope metadata, and immutable reference identity.
- Add framework-free Platform public DTOs for trusted `ActorContext`,
  `OperationReceipt`, versioned `ErrorEnvelope`, cancellation/control results,
  and a truthful bounded `ShutdownReceipt`.
- Add a framework-free Processes `ProcessView` contract with a closed state
  taxonomy, bounded transition history, deadlines, retry/compensation state,
  dead-letter visibility, and authorized recovery actions.
- Define owner-specific immutable-reference construction rules without
  prematurely publishing formal DatasetSnapshot, revision, Capture, or Study
  contracts. Those concrete references remain owned by their later Context
  children.
- Define deterministic, bounded JSON serialization and schema-version
  negotiation. Public DTOs contain no FastAPI/Pydantic/ORM/DataFrame,
  connection, filesystem path, live exception, callback, or service object.
- Define an explicit legacy compatibility mapping inventory for current
  EventBus admission, `job_runs`, Web `/api/run`, data-operation,
  Observatory error/artifact, CLI wait, and runtime shutdown surfaces. This
  child adds mappers and snapshot fixtures only; it does not reroute a CLI,
  HTTP route, scheduler, event handler, or runtime owner.
- Require every synchronous wait/cancel/shutdown contract to have a finite
  deadline, distinguish caller observation timeout from owner deadline, report
  residual work, and avoid an unbounded join after the declared deadline.
- Add contract, round-trip, forbidden-import, actor-provenance, status-mapping,
  size/depth-budget, legacy-snapshot, and bounded-control fixtures.
- Apply the `public_contract` and `runtime_concurrency` design-quality profiles,
  six-role digest-bound review, and current-date strict approval before code.

There are no breaking user-facing changes in this child. Existing CLI names,
HTTP paths/status/payloads, SSE behavior, database rows, artifacts, EventBus
topics, C++ ABI, long-wait defaults, and process behavior remain unchanged.

## Capabilities

### New Capabilities

- `kernel-primitives`: Minimal framework-free identity, time, digest, result,
  envelope, and immutable-reference primitives with deterministic validation.
- `operation-control-contracts`: Trusted actor, operation, process,
  error, cancellation, and shutdown DTOs with closed truthful state machines.
- `immutable-reference-policy`: Owner-preserving rules for versioned immutable
  references and policy identities without paths, moving aliases, or live data.
- `public-contract-compatibility`: Versioned serialization, legacy mapping,
  bounded wait/control semantics, and compatibility evidence for existing
  interfaces.

### Modified Capabilities

- None.

## Impact

The later implementation is limited to new `src/trade/kernel`,
`src/trade/platform/contracts`, `src/trade/processes/contracts`, and narrow
compatibility/contract-test paths, plus the minimum additive package discovery
needed to import those modules. It does not create Platform implementations,
Process Managers, Context repositories, business DTOs, database tables,
outbox delivery, provider access, Web routing, native bindings, or a global
`common`, `shared`, `utils`, `services`, or DTO facade.

Current contract owners remain authoritative during the compatibility window:
`trade_py.bus`, `trade_py.data.operations`, `trade_py.observatory`,
`trade_web.backend.runtime`, `trade_web.backend.app`, and `TradeDB.job_runs`.
New contract adapters may observe and map those shapes but may not write their
tables, repair state, or claim cancellation without durable evidence.

No real data, database, parquet, manifest, pointer, provider, or network access
is required. Tests use in-memory values and temporary roots. Rollback removes
the new unused contract package and fixtures or stops new consumers while all
legacy imports and payload paths remain intact.
