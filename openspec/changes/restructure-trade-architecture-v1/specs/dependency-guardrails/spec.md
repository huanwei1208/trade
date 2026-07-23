## ADDED Requirements

### Requirement: Context imports SHALL follow the declared acyclic graph

The system SHALL enforce this graph: Capture MAY depend on Kernel; Datasets MAY
depend on Kernel and Capture contracts; Studies MAY depend on Kernel and
Datasets contracts; Decision Support MAY depend on Kernel, Datasets contracts
and Studies contracts; Processes MAY depend on all business contracts and
Platform public APIs; Interfaces MAY depend on contracts, approved
use-case/query handles, Processes and Platform public APIs; Bootstrap alone MAY
compose concrete adapters, repositories, use cases, process managers and
platform implementations.

#### Scenario: A Study needs capture information

- **WHEN** a Studies use case needs provenance for a DatasetSnapshot input
- **THEN** it consumes the DatasetSnapshotRef and exposed Datasets contract
  fields rather than importing Capture implementation or querying Capture tables

#### Scenario: A context needs a technical service

- **WHEN** a context requires persistence, events, scheduling or native
  computation
- **THEN** it depends on its own port or a Platform public capability and does
  not import a concrete adapter from another context

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
