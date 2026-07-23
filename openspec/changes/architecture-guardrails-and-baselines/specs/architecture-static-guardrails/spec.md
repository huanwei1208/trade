## ADDED Requirements

### Requirement: Future target modules SHALL enforce the approved dependency graph

The quality gate SHALL parse changed Python modules under the declared
`src/trade` target root without importing them. It SHALL enforce the approved
Context, Processes, Interfaces, Platform, Bootstrap, Kernel, and Context-Cell
dependency graph. The guard SHALL not require legacy `trade_py` modules to
conform before their individual migration child introduces a target module.

#### Scenario: A Dataset use case consumes Capture provenance

- **WHEN** `src/trade/datasets/use_cases/` needs Capture data
- **THEN** it imports only `src.trade.capture.contracts` plus its permitted
  Kernel, Platform, own-domain, own-port, and own-contract dependencies

#### Scenario: A Study imports Capture implementation

- **WHEN** a changed Study target module imports `src.trade.capture.adapters`
  or another Context implementation module
- **THEN** the architecture quality step fails with the path, line, and
  `dependency.context_implementation` remediation

#### Scenario: Bootstrap composes concrete adapters

- **WHEN** a changed Bootstrap target module imports a Context adapter,
  repository, use case, Process manager, or Platform implementation
- **THEN** the architecture quality step accepts the import because Bootstrap
  is the sole target composition root

### Requirement: Target Context Cells SHALL not leak implementation boundaries

The architecture quality step SHALL reject a changed target Context Cell that
violates the approved internal direction. It SHALL reject concrete adapter
imports from use cases, ports/adapters/use-case imports from domain, producer
domain/adapter imports from contracts, and framework/ORM/DataFrame/connection/
filesystem implementation types exposed by contracts.

#### Scenario: A contract introduces an immutable reference

- **WHEN** a changed Context contract declares a standard-library immutable DTO
  or a Kernel reference without importing a producer domain or adapter
- **THEN** the architecture quality step accepts it

#### Scenario: A contract exposes a database connection

- **WHEN** a changed Context contract imports `sqlite3`, `pandas`, `Path`, a
  concrete repository, or a producer internal domain/adapters module
- **THEN** the architecture quality step fails with
  `contracts.implementation_type` and the offending source location

#### Scenario: A use case bypasses its port

- **WHEN** a changed use-case module imports an own or upstream concrete
  adapter
- **THEN** the architecture quality step fails with `cell.use_case_adapter`
  rather than accepting a direct implementation dependency

### Requirement: Future target database access SHALL preserve Context ownership

The quality gate SHALL reject direct `trade_py.db` imports, `sqlite3` imports,
private connection attributes, and SQL literals in target Context modules
outside their future approved persistence adapter. It SHALL reject database
imports, private connection access, and SQL literals from target Interfaces.
The guard SHALL treat an unclassified or deferred table as unavailable to a
new target owner until a later approved child resolves its classification.

#### Scenario: A Context adapter reaches a declared candidate table

- **WHEN** an approved later Context child introduces a persistence adapter for a
  baseline table classified to that Context
- **THEN** its child design and focused repository fixture can extend the
  baseline and architecture guard without allowing another Context or an
  Interface direct access

#### Scenario: An Interface queries a business table

- **WHEN** a changed target HTTP, CLI, SDK, event, schedule, or import adapter
  contains direct SQL or accesses `_conn`
- **THEN** the architecture quality step fails with
  `interfaces.direct_database_access` and requires a query/use-case contract

### Requirement: Platform and native target boundaries SHALL remain technical

The quality gate SHALL reject declared business aggregate vocabulary from
target Platform source and SHALL allow a native extension import only from a
Context `adapters/native` module. It SHALL record but not enable the current
`trade_py` CMake binding target, reserving `_trade_native` for a later
package/native migration decision.

#### Scenario: Platform adds generic retry behavior

- **WHEN** a changed target Platform module uses generic command, envelope,
  receipt, scheduling, persistence, or execution terminology
- **THEN** the architecture quality step accepts it without requiring a
  business Context dependency

#### Scenario: A Study use case imports a native extension

- **WHEN** a changed Study use-case module imports `_trade_native` or
  `trade_py`
- **THEN** the architecture quality step fails with `native.boundary` and
  requires a Context port plus an `adapters/native` implementation
