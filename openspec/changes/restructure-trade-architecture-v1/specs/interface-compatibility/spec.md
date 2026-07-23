## ADDED Requirements

### Requirement: Existing CLI contracts SHALL remain stable through compatibility adapters

The system SHALL keep the root `trade` facade and canonical CLI domains `run`,
`status`, `data`, `show`, `research`, `kg`, `observatory`, `config`, `event`,
`backup`, `start`, `web` and `dev` usable throughout migration. Existing hidden
or deprecated aliases SHALL keep their documented parse, output and exit-code
behavior until their individual retirement condition is met.

#### Scenario: Internal studies capability replaces a research implementation

- **WHEN** a `trade research` subcommand is routed to Studies use cases
- **THEN** the external command name, supported legacy arguments, output shape
  and documented deprecation behavior remain compatible while the adapter
  records the resolved immutable input/output references

#### Scenario: A legacy alias reaches its retirement boundary

- **WHEN** a child change proposes removal of one CLI alias
- **THEN** it provides usage evidence, a published successor, CLI snapshot
  parity, migration documentation and the compatibility-window completion
  record; a structural directory move alone is insufficient

### Requirement: HTTP, SSE and Web page surfaces SHALL be contract-compatible

`interfaces/http/compat` SHALL preserve existing route paths, methods,
query/path/body fields, defaults, status codes, response payloads, error
shapes, capability gates and SSE semantics while translating legacy transport
forms to Context query/use-case contracts. BFF routes SHALL compose read-only
query handles and SHALL NOT access business tables, providers or lifecycle
pointers directly.

#### Scenario: A route is extracted from the current FastAPI application

- **WHEN** an `/api/*` route moves behind an interface router or BFF
- **THEN** an OpenAPI/contract snapshot verifies the path, method, request
  fields, status codes, response/error fields and SSE behavior before the
  legacy implementation is retired

#### Scenario: A page queries unavailable data

- **WHEN** Today, Observatory, Assurance, Research, Symbol Workspace,
  Candidates, Actions, Trust, Data Ops, Operations or Settings receives an
  unavailable, partial, stale or quarantined query result
- **THEN** its BFF returns an explicit typed state and does not fetch, repair,
  publish, run a study or change data lifecycle during the query

### Requirement: SDK, notebooks and imports SHALL use shared contracts

SDK, CLI, HTTP, Web and notebooks SHALL share approved query/use-case DTOs.
Notebooks SHALL NOT mutate `sys.path`, scan repository layout, read formal
parquet directly, import adapters or call repositories. Every external file
import SHALL become `RequestCapture(mode="import")`.

#### Scenario: A notebook imports a local file

- **WHEN** a notebook user submits a file for formal analysis
- **THEN** the SDK creates a Capture request with declared source identity and
  digest, receives a CaptureArtifactRef and uses a Dataset build before any
  formal DatasetSnapshot or Study can consume the content

#### Scenario: A legacy direct notebook path is encountered

- **WHEN** migration detects a notebook that modifies `sys.path` or reads an
  internal artifact directly
- **THEN** the child change introduces an SDK-compatible adapter and contract
  fixture before removing the internal access path
