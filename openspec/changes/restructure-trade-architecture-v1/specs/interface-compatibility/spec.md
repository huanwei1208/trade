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
pointers directly. The compatibility child SHALL derive its first baseline
from the actual FastAPI route registry plus representative golden requests and
responses. The audited application currently registers 72 routes with the
default-off or error Observatory capability surface, and 81 routes when the
complete Observatory data surface is enabled. The nine-route difference is an
intentional capability gate and SHALL have disabled, enabled and registration-
error snapshots. Two routes are SSE streams in every mode:
`GET /api/events/stream` with `after_id=0`, `limit=50` (maximum 500) and
`poll_seconds=2.0` (range 0.25 through 60), and
`GET /api/runtime/stream` with `scope="report"` and the same poll range.

The current OpenAPI generator is not an authoritative complete baseline because
schema generation fails while resolving the local `PredictRequest` forward
reference. The compatibility child SHALL retain `/predict` in the registry and
golden baseline, repair the schema-generation defect without changing route
behavior, then add an OpenAPI snapshot. A generator failure SHALL fail the
OpenAPI check explicitly; it SHALL NOT produce an empty snapshot, remove the
route or trigger a reduced route inventory.

#### Scenario: A route is extracted from the current FastAPI application

- **WHEN** an `/api/*` route moves behind an interface router or BFF
- **THEN** an OpenAPI/contract snapshot verifies the path, method, request
  fields, status codes, response/error fields and SSE behavior before the
  legacy implementation is retired

#### Scenario: OpenAPI generation fails before the compatibility baseline

- **WHEN** schema generation cannot resolve a request model such as the current
  local `PredictRequest` forward reference
- **THEN** the child records the generator failure, freezes the complete
  registered route/method/signature inventory and golden payloads, keeps
  `/predict` covered, and blocks route retirement until repaired OpenAPI
  generation produces a matching snapshot

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
`ErrorEnvelope`, `OperationReceipt` and `ProcessView` SHALL preserve distinct
`unknown`, `not_observed`, `unavailable`, `empty`, `partial`, `blocked`,
`quarantined`, `stale` and terminal-error states in CLI, HTTP and SSE snapshots.

#### Scenario: A retained route observes a blocked process

- **WHEN** a legacy HTTP route, CLI command or Web page queries an operation
  whose ProcessView is blocked, dead-lettered, expired or unavailable
- **THEN** the adapter returns the compatible status/payload plus a stable
  ErrorEnvelope reason and correlation/process link, and does not retry,
  repair, redrive or mutate the process while servicing the query

### Requirement: Interfaces SHALL expose bounded retention and recovery operations

Operations interfaces SHALL expose owner-managed, bounded `RetentionView`,
`GcDryRunReceipt` and `GcRunReceipt` query/receipt DTOs through compatible
`trade status`, `trade show` and Operations BFF surfaces. The view SHALL report
retention class, last/next evaluation, freshness/unknown state, bytes/items by
class, capacity forecast/at-risk state, legal hold, protected-reference reason,
candidate count, tombstone/archive recovery location and failed/suppressed
deletion reason. A query SHALL not run collection; an authorized command SHALL
return a receipt linked to the retention operation.

#### Scenario: An operator investigates retention-at-risk

- **WHEN** a compatible CLI or Operations page queries a retention class that
  exceeds its capacity forecast or is blocked by protected references
- **THEN** it receives a bounded RetentionView with explicit freshness and
  lineage/recovery links, and any dry-run or collection command returns an
  auditable receipt without deleting data during the query

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

### Requirement: BTC observation and analysis SHALL use one evidence identity

The BTC Observatory product surface SHALL remain an Interfaces BFF over
Datasets, Studies, Decision Support where applicable, and Platform status
queries; it SHALL NOT become a bounded context. The target workspace SHALL
compose Market, Quality, Research and Lineage views from one resolved immutable
snapshot identity and SHALL reject any panel whose DatasetSnapshotRef,
knowledge cut, revision policy or projection generation does not match that
selection. It SHALL preserve the current capability fail-closed gate, URL and
local-state restoration, decimal-string market values, granular route
compatibility and explicit unavailable states.

The BFF MAY perform permission checks, bounded parallel queries, DTO mapping,
response shaping and cache metadata. It SHALL NOT read owner tables or parquet,
call a provider, compute a formal metric, repair or publish data, run a Study,
create a DecisionCase or move a lifecycle pointer. Previously confirmed data
MAY remain visible while revalidating only when its immutable identity and
stale state remain visible.

Before the batched BTC BFF is selected, the child SHALL emit a BTC-specific
`CapacityEnvelope` and the cumulative `CombinedCapacityEnvelope` for the exact
deployment topology. Evidence SHALL cover four-panel cold and warm requests,
partial failure, a slow owner, concurrent clients, parallel-query/deadline
cancellation, scan files/bytes, result bytes, cache/coalescing behavior and peak
CPU/memory/file-descriptor/connection/worker usage. The combined run SHALL
include applicable Capture, replay, Dataset/Study query, Process/outbox and
existing SSE workloads and prove finite admission shedding and fair recovery.
An isolated or cumulative budget failure SHALL prevent BFF selection even when
functional and bounded-fan-out tests pass.

#### Scenario: Market and research panels resolve different snapshots

- **WHEN** a workspace response would combine a market panel and StudyResult
  whose pinned DatasetSnapshotRef or knowledge/revision identity differs from
  the selected workspace identity
- **THEN** the BFF or client contract rejects the mismatched panel with an
  explicit identity-conflict state and does not render the values as one
  coherent analysis

#### Scenario: One bounded panel is unavailable

- **WHEN** the selected snapshot is valid but a Quality, Research or Lineage
  query returns partial, stale, unavailable, quarantined or failed
- **THEN** the workspace preserves confirmed independent panels, renders the
  affected panel's typed state and evidence/recovery link, and performs no
  repair or mutation during the read

#### Scenario: The BTC BFF passes functional tests but exceeds combined capacity

- **WHEN** the workspace returns contract-valid panels in isolation but its
  cumulative topology exceeds a declared query, scan, runner-resource or
  recovery-fairness budget while Capture, replay or SSE load coexists
- **THEN** selection remains on the granular endpoints, the failed
  `CapacityEnvelope` or `CombinedCapacityEnvelope` is retained with the observed
  limit, and the UI child cannot treat functional parity as production readiness

#### Scenario: The BTC UI child is rolled back

- **WHEN** the batched workspace BFF or redesigned page violates a route,
  payload, identity, accessibility, responsive-layout or capacity golden
- **THEN** Interfaces selects the existing four-lens Observatory page and
  granular endpoints, preserving URL state and immutable evidence while the
  new adapter remains disabled
