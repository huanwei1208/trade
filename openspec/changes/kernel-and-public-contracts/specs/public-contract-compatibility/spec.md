## ADDED Requirements

### Requirement: Public contract serialization SHALL be deterministic, exact and bounded

Each public wire DTO SHALL declare schema name and positive integer schema
version. Canonical JSON SHALL use UTF-8, sorted keys, compact separators,
finite values, UTC `Z` instants and explicit enum strings. Version 1 decoders
SHALL accept exactly version 1 and the exact declared field set. Unknown fields,
unknown versions, excessive depth/items/string/bytes or unregistered owner
payloads SHALL fail before object construction or digest calculation.

Version 1 SHALL limit an encoded envelope to 64 KiB, nesting to 8, a string to
2 KiB, a collection to 100 items, actor scopes to 32, delegation hops to 8,
process history to 50, and each safe error message or hint to 1 KiB.

#### Scenario: The same DTO is serialized twice
- **WHEN** code, contract version and values are identical
- **THEN** canonical bytes and digest are identical across source, editable-install and wheel-install environments

#### Scenario: A producer sends an additive unknown field
- **WHEN** a version 1 consumer receives a field absent from the exact version 1 schema
- **THEN** it rejects the payload and requires explicit version negotiation rather than silently discarding the field

#### Scenario: A payload exceeds a limit
- **WHEN** a payload exceeds any byte, depth, string, collection or history bound
- **THEN** decoding fails with a bounded structural error and no partial object is returned

### Requirement: Source, editable and wheel installations SHALL expose compatible packages

Implementation SHALL prove an additive package-discovery configuration that
keeps distribution `trade-py`, the root `./trade` facade, `trade-py` console
entry and installed `trade_py` imports while adding installed `trade` contract
imports. The proof SHALL cover source tree, editable install and a clean wheel
installation. A root shim, symlink or test/notebook `sys.path` mutation SHALL
NOT be used.

#### Scenario: Dual-root packaging cannot be proven
- **WHEN** the current build backend cannot produce both installed packages without broader migration or import ambiguity
- **THEN** this child stops before contract implementation and promotes the package-transition ADR rather than shipping source-only imports

#### Scenario: A wheel is installed in a clean environment
- **WHEN** the built wheel is installed without the repository working directory on `sys.path`
- **THEN** both legacy `trade_py` compatibility imports and new `trade` contract imports succeed while the console entry remains unchanged

### Requirement: Legacy mappings SHALL be explicit, one-way and conservative

Each compatibility mapper SHALL name source owner/version, target schema
version, lossiness, snapshot, retirement condition and refusal behavior. The
legacy layer MAY import target contracts; Kernel, Platform contracts and
Processes contracts SHALL NOT import `trade_py` or `trade_web`. Mappers SHALL
be pure and SHALL NOT call repository mutation APIs or SQL mutation
primitives, access `db._conn`, call providers, move pointers, signal processes
or repair state.

#### Scenario: A legacy value is lossy
- **WHEN** a legacy event, artifact, error or status contains fields that are unsafe or have no target semantics
- **THEN** the mapper records the loss, excludes those fields and never broadens authority or certainty

#### Scenario: A target package is imported
- **WHEN** tests import all public target modules in a clean interpreter
- **THEN** no legacy implementation, Web, database, provider, pandas or native module is imported as a side effect

### Requirement: Current mutation and status surfaces SHALL retain snapshots until owning migration

This child SHALL preserve current EventBus admission behavior, `job_runs`
status rows, `/api/run` routes/status/headers/payloads, CLI event/run output and
exit behavior, Observatory errors/artifacts, SSE, database schema, artifact
layout and shutdown exceptions. New DTOs or mappers SHALL NOT reroute a current
interface. A later owning child SHALL provide a mutation ledger, old/new
snapshot parity and rollback before delegation.

#### Scenario: Web run is accepted
- **WHEN** the existing `/api/run` route accepts a command
- **THEN** its current 200 payload including accepted, target, limit, PID, run ID and running status remains byte/field compatible while any target receipt exists only in mapper tests

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
