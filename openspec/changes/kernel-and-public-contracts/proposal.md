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

- Add only the parent-approved six target Kernel modules under
  `src/trade/kernel`: opaque identifiers, UTC instants/deadlines, content
  digests, bounded contract errors/results and envelope metadata. Formal
  immutable and policy reference DTOs remain in their owning Context contracts.
- Add framework-free Platform public DTOs for trusted `ActorContext`,
  `OperationReceipt`, versioned `ErrorEnvelope`, cancellation/control results,
  and a truthful bounded `ShutdownReceipt`.
- Separate historical replay attribution from current execution authority
  through a finite `ReplayAdmissionV1`. Direct replay is resolve-only, performs
  one owner-local lookup/audit transaction, commits a request-causal audit
  before returning an unchanged historical receipt, and fails closed on
  binding conflict, missing operation or audit unavailability without retry or
  background continuation.
- Add a framework-free Processes `ProcessView` contract with a closed state
  taxonomy, bounded transition history, deadlines, retry/compensation state,
  dead-letter visibility, and owner-scoped recovery descriptors.
- Define owner-specific immutable-reference construction rules without
  prematurely publishing formal DatasetSnapshot, revision, Capture, or Study
  contracts. Those concrete references remain owned by their later Context
  children.
- Define deterministic, bounded JSON serialization and schema-version
  negotiation with a pre-materialization lexical/structural scan for bytes,
  duplicate keys, depth, string/integer tokens, aggregate nodes and
  per-container limits. Version 1 also freezes exact Unicode preservation,
  escaping, solidus and key-order bytes so equivalent encoder choices cannot
  change fingerprints. Public DTOs contain no
  FastAPI/Pydantic/ORM/DataFrame, connection, filesystem path, live exception,
  callback, or service object.
- Define versioned, domain-separated keyed public fingerprints for command and
  idempotency identity, exact zero/one/multi-match admission, command-conflict
  rejection, generation-serialized rotation, three-attempt contention bounds
  and exact size-bounded auditable refusal outcomes so receipts and refusal
  evidence do not expose raw values or enumerable unkeyed hashes.
- Define Platform codec descriptors and registry invariants; the later Platform
  foundation child implements static Bootstrap assembly. Codecs validate one
  owner/schema/purpose shape but grant no authority or external-content rights;
  cross-Context provider/news/L2/stream content must first become a
  Capture-owned immutable artifact reference.
- Make admission envelopes explicitly local-only and give
  `trade.platform.contracts.messages` one authority-free binary
  `DurableEnvelopeProjectionV1` identity. Replay hashes those exact framed
  bytes; one owner-codec encode yields the typed DTO/byte equality product,
  retained descriptors are proven by Platform-owned bounded 16-shard
  accounting plus one fenced authoritative generation/count/digest snapshot
  rather than startup row scans, global hot counters, whole-manifest rewrites
  or cross-owner transactions, and projection/registry failures use closed
  safe caller/readiness products plus an authorized bounded operator
  cause/action taxonomy.
- Freeze the exact public DTO field correction: receipt actors become unverified
  attribution; only ControlReceipt, ShutdownReceipt and ProcessView retain UTC
  deadline evidence; OperationReceipt remains deadline-free and uses an
  internal immutable Platform admission-deadline contract. ShutdownReceipt can
  link only an exact accepted shutdown control and reports linkage corruption
  through one unavailable query product plus an idempotent integrity
  observation whose fenced claim allows at most one external call and whose
  crash-ambiguous result is explicitly `delivery_outcome_unknown`.
- Define owner-local operation and process admission-deadline facts plus
  process-local monotonic-clock-domain bindings. A live same-domain retry uses
  the original budget; restart or binding loss fails closed and cannot rebuild
  time from UTC evidence. Recovery must fence/terminalize the old owner or
  create a new causally linked identity.
- Make Platform command ingress the sole future owner of command-admission
  idempotency claims, operation identity and the complete `OperationReceipt`
  lifecycle. Processes separately owns `ProcessStartKeyV1`/inbox claims,
  Process Manager workflow state and `ProcessView`; linkage uses an opaque ID
  and never a shared transaction, secret or dual-writer receipt. All
  codec-dependent durable projection bytes and retention identities remain
  Platform-owned; Processes persists only projection-independent handoff facts,
  immutable references and opaque Platform links.
- Define an explicit legacy compatibility mapping inventory for current
  EventBus admission, `job_runs`, Web `/api/run`, Observatory error/artifact,
  CLI wait, and runtime shutdown surfaces. Data Operations remains an explicitly
  inventoried legacy-only owner with no canonical mapper in this child because
  its open status/evidence dictionaries require the later Dataset/interface
  owner decision. This child adds only the four named owner-specific mappers and
  snapshot fixtures; it creates no global mapper facade and does not reroute a
  CLI, HTTP route, scheduler, event handler, or runtime owner.
- Preserve mixed EventBus handler admission facts and map current `/api/run`
  acceptance only as a legacy observation; no mapper fabricates trusted actor,
  fingerprints or a formal operation receipt from `run_id`. The EventBus
  observation omits legacy `created_at`: current persistence writes naive local
  time, live objects use an independent UTC clock, and replay may relabel or
  synthesize an instant, so none is safe canonical temporal evidence.
- Preserve legacy `job_runs` naive time strings only as bounded unproven
  observations. No mapper creates `UtcInstant` or calls a row current without
  separately supplied row-bound owner-generation/liveness evidence.
- Require every synchronous wait/cancel/shutdown contract to have a finite
  deadline, distinguish caller observation timeout from owner deadline, report
  closed residual ownership, fence stale writers, support crash takeover, and
  avoid an unbounded join after the declared deadline.
- Make `runtime-owner-shutdown-and-recovery-hardening-v1` a hard gate before
  current EventBus/Web/FastAPI/CLI runtime adoption. It must cover the audited
  terminal-persistence retry, monotonic wait, concurrent stop, startup cleanup,
  executor tail, generation takeover and real signal-to-process-tree-reap paths
  while preserving existing interface snapshots.
- Add contract, round-trip, forbidden-import, actor-provenance, status-mapping,
  size/depth-budget, legacy-snapshot, and bounded-control fixtures.
- Extend the existing architecture guard for the six-module Kernel,
  Platform-not-to-Processes, target-not-to-legacy, owner-specific compatibility
  imports and no aggregate re-export. The four compatibility modules are
  test-only leaf adapters in this child: until the shutdown/recovery child is
  approved, every non-test `trade_py`/`trade_web` module is forbidden both from
  importing new control/operation contracts and from importing a compatibility
  mapper that returns them. Direct, relative, aliased, dynamic-literal and
  package re-export paths from EventBus, CLI, FastAPI lifespan,
  `RuntimeCommandRunner`, `WebResourceContainer` and every other legacy runtime
  module are rejected.
- Apply the `public_contract` and `runtime_concurrency` design-quality profiles,
  six-role digest-bound review, and current-date strict approval before code.

There are no breaking user-facing changes in this child. Existing CLI names,
HTTP paths/status/payloads, SSE behavior, database rows, artifacts, EventBus
topics, C++ ABI, long-wait defaults, and process behavior remain unchanged.

## Capabilities

### New Capabilities

- `kernel-primitives`: Minimal framework-free identity, time, digest, error,
  result and envelope primitives with deterministic validation; typed
  owner-codec descriptors and static registration remain Platform/Bootstrap
  responsibilities.
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

The later implementation is limited to the six approved `src/trade/kernel`
modules, `src/trade/platform/contracts`, `src/trade/processes/contracts`, and narrow
owner-specific compatibility/contract-test paths, plus the minimum explicit
additive package discovery needed to import those modules. The package proof
builds one wheel, verifies an exact source-derived Python member/byte inventory
plus exactly `METADATA`, `WHEEL`, `entry_points.txt`, `top_level.txt` and
`RECORD` in its single dist-info family, and installs that exact artifact
offline/no-deps; failure promotes the later package-layout ADR rather than
adding a shim. It does not create Platform
implementations, Process Managers, Context repositories, business DTOs,
database tables, outbox delivery, provider access, Web routing, native bindings,
or a global `common`, `shared`, `utils`, `services`, or DTO facade.
It also includes the narrow target-graph rules in
`trade_py/devtools/architecture_guard.py` and their architecture fixtures; it
does not implement Bootstrap registry assembly.

Current contract owners remain authoritative during the compatibility window:
`trade_py.bus`, `trade_py.data.operations`, `trade_py.observatory`,
`trade_web.backend.runtime`, `trade_web.backend.app`, and `TradeDB.job_runs`.
New contract adapters may observe and map those shapes but may not write their
tables, repair state, or claim cancellation without durable evidence.
Existence of the DTOs does not authorize runtime adoption before the named
shutdown/recovery hardening child passes strict approval and implementation
review.

No real data, database, parquet, manifest, pointer, provider, or network access
is required. Tests use in-memory values and temporary roots. Rollback removes
the new unused contract package and fixtures or stops new consumers while all
legacy imports and payload paths remain intact.
