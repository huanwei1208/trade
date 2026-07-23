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

### Requirement: Interface errors and process views SHALL remain operable

CLI, HTTP and SSE compatibility adapters SHALL map context and Platform failure
states to a versioned `ErrorEnvelope` with stable reason code, correlation ID,
safe retry/recovery hint and compatibility status/exit mapping. Interfaces
SHALL provide bounded ProcessView list/detail and recovery-link queries through
the owning Processes/Platform query APIs. Legacy error shapes remain available
until their snapshot and retirement conditions pass; adapters SHALL NOT expose
raw exception text, credentials, artifact bytes or private table state.

#### Scenario: A retained route observes a blocked process

- **WHEN** a legacy HTTP route, CLI command or Web page queries an operation
  whose ProcessView is blocked, dead-lettered, expired or unavailable
- **THEN** the adapter returns the compatible status/payload plus a stable
  ErrorEnvelope reason and correlation/process link, and does not retry,
  repair, redrive or mutate the process while servicing the query

### Requirement: BFF and SSE fan-out SHALL have finite client budgets

Each BFF route SHALL declare parallel-query, deadline, pagination and
cache/coalescing policy. SSE SHALL declare maximum concurrent connections per
instance and identity, shared dispatcher/hub ownership, per-client item and
byte queues, heartbeat, idle timeout, slow-client disconnect and cursor
retention/resync behavior. A BFF or SSE adapter SHALL use a bounded shared
fan-out path from durable delivery/projection state; it SHALL NOT start a
database poller or unbounded queue for every connected client.

#### Scenario: A slow SSE client falls behind retention

- **WHEN** a client exceeds its queue budget or asks for a cursor older than
  the retained event/projection window
- **THEN** the adapter disconnects or returns an explicit resync-required
  response with a stable reason, records safe capacity telemetry, and does not
  allow that client to accumulate unbounded memory or block other consumers

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
