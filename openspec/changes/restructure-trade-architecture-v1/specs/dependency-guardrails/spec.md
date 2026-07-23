## ADDED Requirements

### Requirement: Context imports SHALL follow the declared acyclic graph

The system SHALL enforce this graph: Capture MAY depend on Kernel and Platform
public contracts/ports; Datasets MAY depend on Kernel, Platform public
contracts/ports and Capture contracts; Studies MAY depend on Kernel, Platform
public contracts/ports and Datasets contracts; Decision Support MAY depend on
Kernel, Platform public contracts/ports, Datasets contracts and Studies
contracts; Processes MAY depend on all business contracts and Platform public
APIs; Interfaces MAY depend on contracts, approved use-case/query handles,
Processes and Platform public APIs; Platform SHALL NOT depend on business
Context implementations or contracts; Bootstrap alone MAY compose concrete
adapters, repositories, use cases, process managers and platform
implementations.

#### Scenario: A Study needs capture information

- **WHEN** a Studies use case needs provenance for a DatasetSnapshot input
- **THEN** it consumes the DatasetSnapshotRef and exposed Datasets contract
  fields rather than importing Capture implementation or querying Capture tables

#### Scenario: A context needs a technical service

- **WHEN** a context requires persistence, events, scheduling or native
  computation
- **THEN** it depends on its own port or a Platform public capability and does
  not import a concrete adapter from another context

#### Scenario: A context uses a Platform transaction capability

- **WHEN** a Context use case requires an outbox, read-only session, execution
  or native-compute capability
- **THEN** it imports only the Platform's framework-free public port/DTO and
  its own port adapter, while Platform imports no Context contract or
  implementation and Bootstrap supplies the concrete binding

### Requirement: Contracts and domain code SHALL not leak implementation types

Contracts SHALL expose immutable references, command/event/query DTOs and
capability interfaces only. They SHALL NOT expose ORM objects, DataFrames,
database connections, filesystem paths, concrete repositories or framework
objects. Domain SHALL depend on Kernel only; use cases SHALL NOT directly
import concrete adapters.

#### Scenario: A contract DTO is added

- **WHEN** a child change adds a cross-context contract type
- **THEN** architecture tests serialize and deserialize it, verify that it
  contains no forbidden implementation type and confirm that it can be consumed
  without importing the producer's domain or adapters

### Requirement: Database access SHALL have one logical context owner

Each business table and artifact family SHALL have one context owner. Other
contexts SHALL obtain data through contracts, events or projections. Global
`TradeDB` compatibility code and `db._conn` access SHALL be progressively
eliminated from new business paths, and a new cross-domain facade SHALL NOT be
introduced.

#### Scenario: A non-owner requires a read model

- **WHEN** a Process or interface needs data from another context
- **THEN** it uses a contract query or rebuildable projection and the
  architecture guard rejects direct owner-table SQL or private connection access

### Requirement: Platform SHALL remain free of business semantics

Platform SHALL provide execution, events, scheduling, persistence, settings and
backup mechanics only. It SHALL NOT contain BTC, Kline, Study,
Recommendation, Portfolio or other business aggregate vocabulary.

#### Scenario: A new platform execution capability is proposed

- **WHEN** a child change adds execution, retry, cancellation or resource
  controls
- **THEN** the public capability uses generic command/envelope/receipt terms
  and the business mapping remains in a context adapter or Process Manager

### Requirement: Native capabilities SHALL remain context-port adapters

Every C++/native capability SHALL be catalogued with one owning Context port,
typed input/output DTOs, ABI/version range, cancellation/error mapping and
differential-test owner. `_trade_native` or any future binding SHALL NOT open
SQLite, write artifacts, advance lifecycle pointers, compose application
services or initialize a runtime container. Domain and use-case modules SHALL
depend on their Context port rather than import a native extension.

#### Scenario: A Dataset computation is accelerated by the C++ engine

- **WHEN** a Datasets child change selects a C++ implementation for a declared
  computation port
- **THEN** Bootstrap injects the native adapter behind that port, the adapter
  returns typed values only, and C++/Python differential tests cover normal,
  cancellation and safe-failure cases without allowing native code to mutate
  context persistence or releases

### Requirement: Native binding linkage SHALL exclude persistence and lifecycle targets

The native binding build SHALL link a dedicated compute-only target containing
only catalogued capability sources. It SHALL NOT link storage, SQLite, Parquet
writer, artifact, release-pointer, CLI/runtime composition or orchestration
targets. CMake/source-path and exported-symbol deny checks SHALL enforce this
boundary before a native binding is enabled.

#### Scenario: A new native binding source is proposed

- **WHEN** a child change adds a source group or export to `_trade_native`
- **THEN** the build check rejects it if the group reaches storage, writer,
  persistence or lifecycle code, and the child maps the remaining compute API
  to one Context port with a differential fixture
