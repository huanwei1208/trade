## ADDED Requirements

### Requirement: Public contract serialization SHALL be deterministic, exact and bounded

Each public JSON wire DTO SHALL declare schema name and positive integer schema
version. Canonical JSON SHALL use UTF-8, sorted keys, compact separators,
finite values, explicit enum strings and UTC instants in the sole form
`YYYY-MM-DDTHH:MM:SS.ffffffZ`. The instant form SHALL use a four-digit year
from `0001` through `9999`, seconds from `00` through `59`, exactly six
fractional-second digits and literal `Z`; version 1 SHALL reject offset
spellings, omitted or variable fractional precision, precision beyond
microseconds and leap seconds rather than normalizing or rounding them.
Version 1 decoders SHALL accept exactly version 1 and the exact declared field
set. Unknown fields, unknown versions, excessive depth/items/string/bytes or
unregistered owner payloads SHALL fail before object construction or digest
calculation.

`Deadline` values containing process-local monotonic expiry SHALL NOT be
serialized. Public receipt/view fields named `deadline` SHALL encode exactly
one canonical `UtcInstant` containing declared wall-clock expiry evidence; a
decoder SHALL NOT construct a local `Deadline` from that value. Floating-point
numbers, `monotonic_expires_at`, receipt-finalization reserves and other
process-clock state SHALL be forbidden on the v1 wire.

`CommandEnvelope` and `QueryEnvelope` SHALL be admission-local composites, not
public wire DTOs. Generic serialization and owner codecs SHALL reject either
whole object. Only the exact `DurableEnvelopeProjectionV1` SHALL have a durable
codec. That projection SHALL contain the complete `EnvelopeMeta`, complete
`OwnerCodecDescriptor` identity/policy and exact canonical payload bytes under
the framing defined by `kernel-primitives`; it SHALL contain no `ActorContext`,
`Deadline`, remaining time or attempt state. Decoding it SHALL yield an inert
projection and SHALL create neither executable authority nor a local budget.
It is the explicit non-JSON exception to this requirement: its fixed domain
plus projection version identify the schema, it has no per-object
`schema_name`, and the exact framed binary encoding is its sole public/durable
representation. No second JSON projection codec is permitted.

Any `ActorContext` encoded inside an operation, control or shutdown receipt
SHALL have `assurance=unverified` and SHALL be attribution only. Encoding a
verified receipt actor or decoding receipt attribution into executable
authority SHALL fail closed. Verified current authority remains ingress-local
and requires separate trusted evidence.

Version 1 canonical output SHALL sort object keys by decoded Unicode
scalar-value sequence, preserve decoded scalar sequences without Unicode
normalization, encode non-ASCII scalars directly as UTF-8 and reject lone
surrogates. It SHALL never escape `/`; SHALL encode quotation mark and reverse
solidus as `\"` and `\\`; SHALL use only `\b`, `\t`, `\n`, `\f`, `\r` for
those controls and lower-case `\u00xx` for every other U+0000-U+001F control;
and SHALL use no other `\u` escape. Input MAY use any grammar-valid equivalent
escape, but duplicate-key checks and ordering SHALL operate on decoded scalar
sequences and canonical re-encoding SHALL emit only the spelling above.

Version 1 SHALL limit raw UTF-8 input before parsing and canonical output each
to 65,536 bytes; one string/key to 2,048 UTF-8 bytes; every container to 100
items/members; aggregate array items plus object members to 1,024; total value
nodes to 2,048; nested-container depth to 8; actor scopes to 32; delegation hops
to 8; process history to 50; recovery descriptors to 16; and each safe error
message/hint to 1,024 UTF-8 bytes. Integer tokens SHALL be canonical
non-negative decimal `0` or `[1-9][0-9]{0,18}` before field-specific limits.

Before JSON materialization, a deterministic single-pass lexical/structural
scanner SHALL validate strict UTF-8/JSON grammar and enforce BOM, duplicate-key,
surrogate, float/non-finite, depth, decoded string/key, integer-token,
per-container, aggregate-member and value-node limits. Only accepted input MAY
reach the JSON decoder. A bounded `parse_int` hook SHALL repeat the 19-digit
limit before integer construction. Root scalar depth is zero, root container
depth is one, and each nested container increments depth by one. A value node
is the root or an object value/array element; keys consume string/member budgets
but are not extra value nodes. Post-materialization traversal SHALL use a
bounded explicit worklist rather than unbounded recursion. Python 3.10 and the
highest supported version SHALL emit the same structural error for the reviewed
deep, integer and duplicate-key fixtures.

#### Scenario: The same DTO is serialized twice
- **WHEN** code, contract version and values are identical
- **THEN** canonical bytes and digest are identical across source, editable-install and wheel-install environments

#### Scenario: Equivalent JSON spellings are decoded
- **WHEN** CJK, composed/decomposed combining sequences, controls, solidus, reverse solidus, quotation marks or escape-equivalent object keys are decoded and re-encoded
- **THEN** one golden canonical byte sequence is emitted, composed and decomposed scalar sequences remain distinct, and decoded duplicate keys are rejected

#### Scenario: An instant uses a non-canonical UTC spelling
- **WHEN** an otherwise equivalent instant uses `+00:00`, no fractional seconds, a non-six-digit fraction, more than microsecond precision or a leap second
- **THEN** version 1 rejects it before DTO construction or fingerprint calculation rather than normalizing it to another canonical identity

#### Scenario: A producer sends an additive unknown field
- **WHEN** a version 1 consumer receives a field absent from the exact version 1 schema
- **THEN** it rejects the payload and requires explicit version negotiation rather than silently discarding the field

#### Scenario: A public receipt carries process-local clock state
- **WHEN** a receipt or view includes a monotonic float, `monotonic_expires_at`, a composite Deadline or a receipt-finalization reserve
- **THEN** version 1 decoding rejects it and accepts only the declared UTC deadline evidence field

#### Scenario: An admission-local envelope is passed to a public serializer
- **WHEN** a caller attempts to encode a whole CommandEnvelope or QueryEnvelope
- **THEN** the serializer rejects it and requires the authority-free DurableEnvelopeProjectionV1

#### Scenario: A durable envelope projection is decoded
- **WHEN** a public decoder accepts exact projected metadata, descriptor identity and canonical payload bytes
- **THEN** it returns no verified actor or local Deadline and trusted ingress must separately establish both before execution

#### Scenario: A public receipt claims verified actor assurance
- **WHEN** an operation, control or shutdown receipt encodes `actor` or `initiator` with verified assurance
- **THEN** version 1 decoding rejects the receipt rather than recreating mutation authority from durable bytes

#### Scenario: A payload exceeds a limit
- **WHEN** a payload exceeds any byte, depth, string, collection or history bound
- **THEN** decoding fails with a bounded structural error and no partial object is returned

#### Scenario: Input expands or aliases during parsing
- **WHEN** raw input is 65,537 bytes, repeats an object key, contains an invalid surrogate or exceeds the aggregate node/member budget while each local container is valid
- **THEN** decoding fails deterministically before DTO construction or fingerprint calculation

#### Scenario: Parser materialization would amplify input
- **WHEN** a payload contains depth 9, depth 1,500 or a within-byte-budget overlong integer token
- **THEN** the pre-materialization scanner rejects it with the same bounded structural error on Python 3.10 and the highest supported version, without `RecursionError` or large-integer construction

### Requirement: Source, editable and wheel installations SHALL expose compatible packages

Implementation SHALL prove an additive package-discovery configuration that
keeps distribution `trade-py`, the root `./trade` facade, `trade-py` console
entry and installed `trade_py` imports while adding installed `trade` contract
imports. The proof SHALL cover source tree, editable install and a clean wheel
installation. A root shim, symlink or test/notebook `sys.path` mutation SHALL
NOT be used.

The proof SHALL build one wheel, inspect that artifact's members and install
the same artifact into an isolated temporary environment with dependency
installation disabled and network access denied. The clean-wheel interpreter
SHALL run outside the repository cwd. Source/editable checks SHALL reuse the
locked development environment and SHALL NOT reinstall the full dependency
graph per mode. This additive proof SHALL NOT move legacy packages or replace
the later canonical package-layout child.

The normalized wheel member inventory SHALL equal the source-derived set of
discovered `trade_py`, `scripts` and `src/trade` Python package members plus the
single expected `trade_py-*.dist-info` family. That family SHALL contain exactly
the normalized basenames `METADATA`, `WHEEL`, `entry_points.txt`,
`top_level.txt` and `RECORD`; no license subdirectory or additional metadata
member is admitted by version 1. The proof SHALL record member count and
compressed/uncompressed bytes and SHALL reject every test, repository data,
frontend, engine, generated, vendor, cache, undeclared package-data or
unexpected top-level package member. The exact source-derived allowlist and
byte totals are the deterministic artifact budget. Every packaged Python member
SHALL byte-equal its source. If `S` is the sum of source Python member bytes,
each of the five dist-info members SHALL be at most 65,536 bytes and the family
at most 262,144 uncompressed bytes in aggregate; total uncompressed wheel
members SHALL be at most `S + 262,144`, and the wheel file SHALL be at most
`S + 524,288` bytes. A broad wildcard, an absolute budget unrelated to source,
or a wall-clock-only threshold SHALL NOT substitute for these checks.

#### Scenario: Dual-root packaging cannot be proven
- **WHEN** the current build backend cannot produce both installed packages without broader migration or import ambiguity
- **THEN** this child stops before contract implementation and promotes the package-transition ADR rather than shipping source-only imports

#### Scenario: A wheel is installed in a clean environment
- **WHEN** the built wheel is installed without the repository working directory on `sys.path`
- **THEN** `--no-deps` offline installation succeeds, wheel members include both intended package roots, legacy `trade_py` compatibility imports and new `trade` contract imports succeed, and the console entry remains unchanged

### Requirement: Legacy mappings SHALL be explicit, one-way and conservative

Each compatibility mapper SHALL name source owner/version, target schema
version, lossiness, snapshot, retirement condition and refusal behavior. The
legacy layer MAY import target contracts; Kernel, Platform contracts and
Processes contracts SHALL NOT import `trade_py` or `trade_web`. Mappers SHALL
be pure and SHALL NOT call repository mutation APIs or SQL mutation
primitives, access `db._conn`, call providers, move pointers, signal processes
or repair state.

Mappers SHALL be split by legacy owner (`bus_contracts`,
`job_run_contracts`, `observatory_contracts`, `runtime_contracts`). No
`public_contracts` aggregate facade, package-level mapper re-export or
cross-owner mapper import SHALL be introduced.

The reviewed outcome matrix SHALL be exhaustive. EventBus `accepted`,
`saturated`, `shutting_down` and `submission_failed` all retain the durable
legacy event identity while describing handler-admission facts; none proves
handler/process completion. Web command `saturated` and pre-persistence
`stopping` have no operation receipt; `persistence_failed` has no durable
operation ID; post-persistence `stopping` and `spawn_failed` may carry a legacy
`run_id` but require separately observed job-row evidence for a target terminal
state. Outcome spelling, process exit, PID or exception text alone SHALL NOT
prove cancellation or completion.

The EventBus mapper SHALL retain total, accepted, saturated, shutting-down and
submission-failed handler counts plus a deterministic latest-at-most-50
bounded summary with returned/omitted metadata. A mixed handler set SHALL remain
explicitly mixed and SHALL NOT be flattened to the aggregate precedence value.
If the target schema cannot preserve these facts, the canonical mapping SHALL
be refused while the unchanged legacy result remains available.
The canonical EventBus observation SHALL omit legacy `created_at` entirely.
Current persistence emits naive local text, the live event independently uses a
UTC clock, and replay may relabel naive text as UTC or substitute the replay
clock for malformed/missing input. The mapper SHALL NOT preserve a raw time
token, construct `UtcInstant`, use a fallback `now`, or interpret any legacy
event time as provider publication, observed, received, available or envelope
creation time. The unchanged legacy value remains available to its owner.
Because the current legacy result materializes one value per handler and has no
registration cardinality contract, canonical mapping SHALL accept at most 1,024
source handler results. At 1,025 or more it SHALL refuse before allocating a
second proportional DTO collection and SHALL leave the legacy result unchanged.

Current `/api/run` accepted output SHALL map only to an owner-local legacy run
admission observation. A durable `run_id` alone SHALL NOT fabricate a formal
`OperationReceipt`: trusted actor, correlation/causation and versioned command/
idempotency fingerprints must come from the same future admission boundary.

`LegacyJobRunObservation` SHALL preserve each naive legacy time only as an
optional bounded raw ASCII token with `time_provenance = unproven`, unless an
owner reader supplies independent offset/timezone evidence bound to the same
row and owner generation. A mapper SHALL NOT assume UTC, local/host timezone or
DST fold/gap and SHALL NOT construct `UtcInstant` from a naive token. A running
row SHALL be current only when separate evidence binds row ID, owner instance,
fence generation, observed-at instant and unexpired liveness/reconciliation.
Missing, mismatched or stale evidence SHALL be unknown/owner-lost.

Data Operations SHALL remain an explicitly inventoried legacy-only surface in
this child. Its open `OperationResult`/`StepResult` status strings and arbitrary
evidence dictionaries SHALL retain their existing CLI/JSON snapshots, but no
canonical mapper SHALL be created. The later Dataset/interface owners SHALL
define source version, target schema, lossiness, refusal and retirement before
mapping is admitted.

#### Scenario: A legacy value is lossy
- **WHEN** a legacy event, artifact, error or status contains fields that are unsafe or have no target semantics
- **THEN** the mapper records the loss, excludes those fields and never broadens authority or certainty

#### Scenario: A target package is imported
- **WHEN** tests import all public target modules in a clean interpreter
- **THEN** no legacy implementation, Web, database, provider, pandas or native module is imported as a side effect

#### Scenario: A compatibility package is imported
- **WHEN** an owner mapper or its package is imported
- **THEN** only that owner mapper's reviewed target dependencies are visible and no aggregate mapper facade is exported

#### Scenario: The Web runner stops at different admission stages
- **WHEN** two `stopping` results differ because one has no `run_id` and one has a durably created `run_id`
- **THEN** the mapper produces no receipt for the first and requires separately observed durable state for the second rather than treating both as cancelled

#### Scenario: Event handlers have mixed admission outcomes
- **WHEN** one durable event has accepted, saturated and submission-failed handler results
- **THEN** the canonical observation retains each count and bounded summary or refuses mapping; it does not report all handlers as the aggregate precedence outcome

#### Scenario: One event is observed live and replayed
- **WHEN** the same legacy event identity carries an independent live UTC value, naive local database text, force-labelled replay time, malformed or missing time, or a DST fold/gap value
- **THEN** every canonical observation omits event time and no fallback clock or temporal semantic is fabricated

#### Scenario: Event handler cardinality is unbounded
- **WHEN** a legacy publish result contains 1,025 or a 10x-over-limit number of handler results
- **THEN** canonical mapping is refused before a proportional target collection is allocated and the unchanged legacy result remains available

#### Scenario: A legacy job row has a naive timestamp
- **WHEN** `CURRENT_TIMESTAMP`, `datetime('now', 'localtime')`, malformed, mixed-origin, DST-gap or DST-overlap text lacks independently bound timezone evidence
- **THEN** the mapper preserves at most a bounded unproven token, emits no UtcInstant and cannot use that time to declare the row current

#### Scenario: Data Operations is observed
- **WHEN** an `OperationResult` contains open status strings or arbitrary evidence
- **THEN** its current legacy snapshot remains available and canonical mapping is refused until an owning child defines a closed contract

### Requirement: Current mutation and status surfaces SHALL retain snapshots until owning migration

This child SHALL preserve current EventBus admission behavior, `job_runs`
status rows, `/api/run` routes/status/headers/payloads, CLI event/run output and
exit behavior, Observatory errors/artifacts, SSE, database schema, artifact
layout and shutdown exceptions. New DTOs or mappers SHALL NOT reroute a current
interface. A later owning child SHALL provide a mutation ledger, old/new
snapshot parity and rollback before delegation.

#### Scenario: Web run is accepted
- **WHEN** the existing `/api/run` route accepts a command
- **THEN** its current 200 payload including accepted, target, limit, PID, run ID and running status remains byte/field compatible while the mapper yields only a legacy admission observation and no fabricated formal receipt

#### Scenario: Web run is saturated
- **WHEN** current command admission returns saturated
- **THEN** the existing 503 body and `Retry-After` header remain compatible and the canonical mapper does not advise duplicate work

#### Scenario: CLI event observation times out
- **WHEN** the admitted event does not settle within the configured legacy wait
- **THEN** existing output and exit behavior remain unchanged in this child while the canonical mapping records accepted command plus not-observed completion, not completed success

### Requirement: Compatibility shall not invent formal owner facts

Compatibility mapping SHALL NOT convert a legacy path-bearing artifact into a
formal Capture/Dataset reference, convert a job run into a Process Manager
record, infer trusted actor from payload, infer cancellation from process exit,
infer availability from an empty list, or infer error safety from free-form
exception text.

#### Scenario: A legacy terminated row lacks intent evidence
- **WHEN** only status `terminated` and a process exit are available
- **THEN** the mapper preserves the legacy value and produces conservative failed/unknown target observation without claiming actor-authorized cancellation

#### Scenario: A runtime shutdown error is free-form
- **WHEN** an existing exception says shutdown is incomplete but exposes no structured residual counts
- **THEN** the mapper emits a safe incomplete/unknown receipt or error and does not parse text into fabricated ownership evidence

#### Scenario: A legacy artifact has a path and digest
- **WHEN** Observatory supplies a relative path-bearing artifact, including traversal/absolute paths or a one-byte digest mismatch fixture
- **THEN** mapping yields only a closed `LegacyArtifactObservation` resolution/verification state and never existence, authorization, publication, quality, PIT or formal-reference proof

### Requirement: Public wait and control compatibility SHALL expose finite observation

New SDK and future Interface consumers SHALL observe operations through finite
receipt/process queries rather than holding a CLI, Web router, scheduler or
event handler for the full business workflow. Legacy synchronous waits may
remain only behind documented compatibility adapters until their owning
interface child migrates them. They SHALL NOT become defaults for new APIs.

#### Scenario: A new interface submits long-running work
- **WHEN** the command is durably accepted
- **THEN** the interface returns an OperationReceipt promptly and offers a finite ProcessView observation path instead of synchronously owning the whole workflow

#### Scenario: A non-returning worker exceeds observation deadline
- **WHEN** a worker or review task does not produce a newer state before the caller deadline
- **THEN** the caller receives not-observed/unavailable state and retains a correlation/operation/process link; the worker does not retain the caller indefinitely

### Requirement: Runtime contract adoption SHALL be separately hardened

This child SHALL NOT reroute EventBus, Web resources, RuntimeCommandRunner,
FastAPI lifespan, CLI or HTTP behavior through the new shutdown/control
contracts. Adoption SHALL require the independently reviewed
`runtime-owner-shutdown-and-recovery-hardening-v1` child. That child SHALL
preserve current CLI output/exit and HTTP payload/status snapshots while proving
bounded terminal-persistence retry, monotonic observation, concurrent stop,
startup cleanup, executor tail, owner-generation takeover and real Uvicorn
signal-to-process-tree reap.

Until that adoption gate passes, the architecture guard SHALL forbid imports
of `trade.platform.contracts` or `trade.processes.contracts` from every legacy
`trade_py`/`trade_web` runtime module. Within legacy source, only the exact four
compatibility modules `bus_contracts`, `job_run_contracts`,
`observatory_contracts` and `runtime_contracts` MAY have an outbound dependency
on those target contracts. Those four modules SHALL be leaf adapters with no
inbound imports from non-test `trade_py` or `trade_web` production modules. The guard
SHALL reject direct, relative, aliased, literal dynamic-import and package
re-export paths from EventBus, CLI, FastAPI lifespan, `RuntimeCommandRunner`,
`WebResourceContainer` and every other non-test legacy module to either target
contracts or a compatibility adapter. In those protected production roots, any
computed `importlib.import_module`, computed `__import__`, module `__getattr__`
dynamic re-export or equivalent import target that the guard cannot resolve
statically SHALL fail closed unless the exact importing file, call site and
finite target set are present in a reviewed allowlist. Existing resolved legacy
CLI domain loading MAY be allowlisted only to the finite `trade_py.cli` domain
set; it SHALL never admit `trade.*`, `trade_py.compat.*` or a target assembled
from caller text. Only focused contract tests are admitted consumers before
hardening. The hardening/adoption child MAY revise these allowlists only after
its own strict approval and fixtures pass.

#### Scenario: Contract DTOs exist before runtime hardening
- **WHEN** this child has shipped but the named runtime hardening child has not passed its gates
- **THEN** current runtime code remains on its compatibility path and architecture guards reject premature adoption

#### Scenario: A runtime imports a compatibility adapter indirectly
- **WHEN** EventBus, CLI, FastAPI lifespan, RuntimeCommandRunner or WebResourceContainer imports or re-exports one of the four leaf adapters instead of importing target contracts directly
- **THEN** the architecture guard rejects that inbound production edge before the runtime-hardening gate passes

#### Scenario: A protected runtime computes an import target
- **WHEN** a non-test legacy production module builds an `import_module`, `__import__` or module `__getattr__` target that is not statically resolved to a reviewed finite legacy-only allowlist
- **THEN** the architecture guard rejects the unresolved import/re-export rather than assuming it cannot reach target contracts or a compatibility adapter
