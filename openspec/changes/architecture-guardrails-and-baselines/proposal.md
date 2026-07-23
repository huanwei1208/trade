## Why

The approved `restructure-trade-architecture-v1` design cannot be implemented
incrementally unless new target modules are prevented from recreating the
current cross-domain import and database-access patterns. Current code facts
include a central `TradeDB` schema facade, direct legacy imports from CLI/Web
surfaces, a legacy C++ module named `trade_py`, and a BTC compatibility pointer.

This child establishes a small, source-only safety net before any Kernel,
Platform, Context, package-layout, or schema work starts. It records the
audited legacy facts without treating them as target conformance, so later
children can replace one owner at a time with evidence and rollback.

## What Changes

- Add a standard-library AST architecture guard to the existing read-only
  `trade dev check` contributor pipeline.
- Enforce declared dependency, contract-leakage, direct database-access,
  direct artifact-client, Platform-vocabulary, legacy-bridge, dynamic-loading,
  direct-process-creation, table-owner, and native-boundary rules for future
  `src/trade` source paths only.
- Add a versioned `architecture-baseline.toml` that records current Python
  package roots, multi-source schema provenance, table classifications,
  warehouse artifact/pointer/receipt facts, Capture migration facts, native
  binding facts, source-derived CLI/HTTP/OpenAPI/SSE compatibility facts, and
  compatibility-pointer facts.
- Validate the baseline against source text only; it will not open a database,
  inspect a parquet file, import an application module, or mutate a data root.
- Add focused architecture tests with temporary source trees and a current-tree
  baseline validation fixture. The fixtures deny database/parquet connections,
  direct in-repository data/artifact reads, and out-of-repository reads while
  the checker runs.
- Extend the shared quality-scope contract additively so the planner preserves
  canonical unfiltered delta, rename, and requested-filter metadata. The
  architecture contributor uses that metadata, rather than rediscovering Git
  state, to emit a fail-closed `architecture.partial_scope` quality result.

There are no breaking user-facing CLI, HTTP, Web, SDK, notebook, database,
artifact, C++ ABI, or runtime behavior changes. The only public developer-tool
effect is that `trade dev check` reports a deterministic quality failure when a
changed future target module violates the approved architecture boundary.

The target filesystem and import namespaces are independently frozen for this
guard: `target_source_root = "src/trade"` and `target_import_root = "trade"`.
The AST checker does not import that package; the package-layout child remains
responsible for distribution metadata and console-entry compatibility.

## Capabilities

### New Capabilities

- `architecture-static-guardrails`: Source-only enforcement for future target
  module imports, contract/domain boundaries, table ownership, read-only
  interface behavior, Platform business-vocabulary isolation, legacy escape
  prevention, and native loading boundaries.
- `architecture-baseline-inventory`: A versioned, auditable legacy inventory of
  package, schema-source, table, artifact, receipt, pointer, Capture-risk,
  native-binding, and compatibility facts used to scope future migration
  changes.

### Modified Capabilities

- None.

## Impact

Affected implementation paths are the shared quality scope/model/planner
contract, existing quality contributor registry, one narrow architecture-check
module, its focused pytest coverage, and the new baseline file. `trade dev
check` receives one additional read-only step only when its changed scope
includes the baseline, future `src/trade` code, or any baseline-declared
evidence source, guard implementation source, contributor integration source,
recorded native binding source, or interface-baseline source. A filtered
`--path` run fails closed when canonical unfiltered metadata shows that it
excluded an architecture-sensitive delta, so it cannot be reported as full
architecture acceptance.

Design-quality governance applies. The contract profile applies because the
developer quality command gains stable scope metadata, a bounded architecture
diagnostic envelope, failure modes, and remediation paths. Developer-tool
concurrency applies because the existing executor can run independent target
batches under its bounded light-worker pool; application runtime concurrency
does not change. Persistent writes, schema work, point-in-time semantics,
predictive behavior, and external-event ingestion do not apply: this child
uses only repository source text and temporary test trees.
