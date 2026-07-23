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
  Platform-vocabulary, and native-boundary rules for future `src/trade` source
  paths only.
- Add a versioned `architecture-baseline.toml` that records current Python
  package roots, schema-definition sources, table classifications, native
  binding facts, and compatibility-pointer facts.
- Validate the baseline against source text only; it will not open a database,
  inspect a parquet file, import an application module, or mutate a data root.
- Add focused architecture tests with temporary source trees and a current-tree
  baseline validation fixture.

There are no breaking user-facing CLI, HTTP, Web, SDK, notebook, database,
artifact, C++ ABI, or runtime behavior changes. The only public developer-tool
effect is that `trade dev check` reports a deterministic quality failure when a
changed future target module violates the approved architecture boundary.

## Capabilities

### New Capabilities

- `architecture-static-guardrails`: Source-only enforcement for future target
  module imports, contract/domain boundaries, table ownership, read-only
  interface behavior, and Platform business-vocabulary isolation.
- `architecture-baseline-inventory`: A versioned, auditable legacy inventory of
  package, schema-source, table, native-binding, and compatibility-pointer
  facts used to scope future migration changes.

### Modified Capabilities

- None.

## Impact

Affected implementation paths are the existing quality contributor registry,
one narrow architecture-check module, its focused pytest coverage, and the
new baseline file. `trade dev check` receives one additional read-only step
only when its changed scope includes the baseline, future `src/trade` code, or
the recorded native binding source.

Design-quality governance applies. The contract profile applies because the
developer quality command gains a stable failure mode and remediation path.
Persistent writes, schema work, point-in-time semantics, predictive behavior,
external-event ingestion, and runtime concurrency do not apply: this child
uses only repository source text and temporary test trees.
