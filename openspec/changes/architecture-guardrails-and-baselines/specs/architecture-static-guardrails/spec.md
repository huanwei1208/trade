## ADDED Requirements

### Requirement: Future target modules SHALL enforce the approved dependency graph

The quality gate SHALL parse changed Python modules under the declared
`src/trade` target root without importing them. It SHALL enforce the approved
Context, Processes, Interfaces, Platform, Bootstrap, Kernel, and Context-Cell
dependency graph. The guard SHALL not require legacy `trade_py` modules to
conform before their individual migration child introduces a target module.
The baseline SHALL separately declare `target_source_root` and
`target_import_root`; AST import resolution SHALL use those declarations
rather than deriving an import name from a filesystem path.

#### Scenario: A Dataset use case consumes Capture provenance

- **WHEN** `src/trade/datasets/use_cases/` needs Capture data
- **THEN** it imports only `trade.capture.contracts` plus its permitted Kernel,
  Platform public-contract, own-domain, own-port, and own-contract
  dependencies

#### Scenario: A Study imports Capture implementation

- **WHEN** a changed Study target module imports `trade.capture.adapters` or
  another Context implementation module
- **THEN** the architecture quality step fails with the path, line, and
  `dependency.context_implementation` remediation

#### Scenario: A target module uses the filesystem root as an import root

- **WHEN** a changed target module imports `src.trade.capture.contracts` or
  another `src.trade.*` path
- **THEN** the architecture quality step fails with
  `dependency.invalid_target_import_root` and requires the declared
  `trade.*` import namespace

#### Scenario: Bootstrap composes concrete adapters

- **WHEN** a changed Bootstrap target module imports a Context adapter,
  repository, use case, Process manager, or Platform implementation
- **THEN** the architecture quality step accepts the import because Bootstrap
  is the sole target composition root

#### Scenario: A Context uses a Platform capability

- **WHEN** a changed target Context use case needs command execution, outbox,
  scheduling, persistence, or process capability
- **THEN** it imports only the declared framework-free `trade.platform.contracts`
  or `trade.platform.api` public namespace and does not import
  `trade.platform.adapters` or another concrete Platform implementation

#### Scenario: A target module imports a legacy implementation

- **WHEN** a changed target module outside the explicitly approved bootstrap
  compatibility bridge imports `trade_py` or `trade_web`
- **THEN** the architecture quality step fails with
  `dependency.legacy_namespace` and requires an approved Context contract,
  port, or the named compatibility bridge

### Requirement: Legacy, dynamic execution, and process-spawn paths SHALL be fail-closed

The architecture quality step SHALL reject target imports from `trade_py` and
`trade_web`, dynamic Python module imports, file-based module loaders, and
direct native-library loaders. It SHALL also reject target direct process
creation, shell execution, and process pools. The only legacy exception SHALL
be a baseline-declared Platform persistence adapter imported only by
`trade.bootstrap`; that adapter may expose one
`LegacySchemaBootstrapAdapter` and import only the specifically declared legacy
schema-bootstrap symbols. Its baseline declaration SHALL name the physical
adapter path, allowlisted symbols, owning Platform-foundation child, and
removal condition. The guard SHALL reject an undeclared exception and SHALL
not authorize a Context, Interface, or Process module to use the bridge.

Future plugin, worker, or remote execution support SHALL first introduce an
approved manifest, capability contract, static allowlist, and serialized
Platform command/envelope boundary in its own child change. The guard SHALL
not allow a source-controlled executable name, module path, importlib call,
`__import__`, `importlib.util` loader, `runpy`, `exec`, `eval`, `compile`,
`zipimport`, `ctypes`, `cffi`, `subprocess`, `os.system`, `os.exec*`,
`asyncio.create_subprocess_*`, `multiprocessing`, or
`concurrent.futures.ProcessPoolExecutor` as an implicit extension point.

#### Scenario: A Capture use case dynamically loads legacy ingestion

- **WHEN** a changed Capture use case calls `importlib.import_module`,
  `__import__`, an `importlib.util` loader, `runpy`, `exec`, `eval`, `compile`,
  `zipimport`, `ctypes`, or `cffi`
- **THEN** the architecture quality step fails with
  `dependency.dynamic_loading` and requires a declared port implemented by an
  approved adapter

#### Scenario: A target module directly creates a worker process

- **WHEN** a changed target module calls `subprocess.Popen` or `run`,
  `os.system`, an `os.exec*` function, `asyncio.create_subprocess_exec` or
  `create_subprocess_shell`, `multiprocessing.Process`, or
  `ProcessPoolExecutor`
- **THEN** the architecture quality step fails with
  `execution.direct_process_creation` and requires a future approved Platform
  execution adapter with a manifest, allowlist, and serialized command
  envelope

#### Scenario: Platform uses the declared legacy bootstrap bridge

- **WHEN** the later Platform-foundation child adds the exact
  baseline-declared Platform persistence adapter path and its approved legacy
  symbol allowlist, and `trade.bootstrap` imports its public bridge
- **THEN** the architecture quality step accepts only that Bootstrap-to-Platform
  bridge and continues to reject every other target `trade_py` or `trade_web`
  import

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

### Requirement: Future target persistence and artifact access SHALL preserve Context ownership

The quality gate SHALL reject direct `trade_py.db` imports, `sqlite3`,
`duckdb`, SQLAlchemy or equivalent database-client imports, private connection
attributes, and SQL literals in target Context modules outside their future
approved persistence adapter. It SHALL reject database-client imports, private
connection access, SQL literals, direct filesystem artifact readers, and
DataFrame/columnar readers from target Interfaces. Target Context code SHALL
also reject direct artifact client calls, including `open`, `Path.read_*`,
`pandas.read_*`, `pyarrow`, `polars`, `duckdb.read_*`, or equivalent direct
Parquet/SQLite/manifest/pointer/receipt access, unless an owning child adds a
named approved adapter capability and focused boundary fixture. The guard SHALL
treat an unclassified or deferred table or artifact family as unavailable to a
new target owner until a later approved child resolves its classification.

#### Scenario: A Context adapter reaches a declared candidate table

- **WHEN** an approved later Context child introduces a persistence adapter for a
  baseline table classified to that Context
- **THEN** its child design and focused repository fixture can extend the
  baseline and architecture guard without allowing another Context or an
  Interface direct access

#### Scenario: A target adapter bypasses its persistence port

- **WHEN** a changed target Context adapter imports `duckdb`, SQLAlchemy, or
  another unapproved database API, or directly opens a Parquet, SQLite,
  manifest, pointer, or receipt artifact
- **THEN** the architecture quality step fails with
  `persistence.unapproved_client` or `artifacts.direct_access` and requires a
  named owner adapter/port approved by its owning child

#### Scenario: An Interface queries a business table

- **WHEN** a changed target HTTP, CLI, SDK, event, schedule, or import adapter
  contains direct SQL, accesses `_conn`, opens a database client, or reads a
  business artifact directly
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

### Requirement: Target persistence adapters SHALL have an explicit table authorization

The baseline SHALL record each known logical table with its current owner,
one-or-more source provenance facts, `target_context` or `deferred` state, and
an empty or explicit approved target persistence-adapter scope. A
`candidate` or `deferred` classification SHALL be audit-only and SHALL NOT
authorize any target adapter. Only an explicit `approved_binding`, added by
the owning implementation child with a named Context and adapter scope, may
authorize SQL access to a declared table.

For literal SQL in target code, the architecture quality step SHALL extract
referenced table names and fail closed for an unknown, deferred, candidate-only,
or foreign-owned table. SQL is permitted only within the authorized target
persistence-adapter scope. Dynamic SQL remains prohibited in this first guard
unless a later child adds a reviewed parser/allowlist and corresponding tests.

#### Scenario: A non-owner persistence adapter queries a declared table

- **WHEN** a target Studies persistence adapter contains a literal query for a
  Dataset table whose approved binding belongs to Datasets
- **THEN** the architecture quality step fails with
  `database.foreign_table_owner` and identifies the table and required Context

#### Scenario: An owning adapter receives explicit approval

- **WHEN** an owning Context child adds a baseline `approved_binding` for its
  named persistence adapter after its owner, compatibility, and boundary tests
  pass
- **THEN** that adapter's literal SQL for the named table is accepted while all
  other target scopes remain blocked

### Requirement: Architecture results SHALL be bounded, deterministic, and complete for their declared scope

The contributor SHALL validate the baseline in one deterministic step and
validate target source in explicit `batched_paths()` batches with deterministic
batch identifiers. It SHALL impose a 1 MiB per-source cap, at most 128 target
files and 8 MiB aggregate source bytes per batch, at most 512 target files and
32 MiB aggregate target source bytes per architecture-selected scope, and an
explicit `architecture.scope_budget_exceeded` quality failure before it drops
or parses excess work. These declared limits are independent of the existing
65,536-byte argv limit and the four-light-worker executor bound. It SHALL
report at most 64 findings per envelope, an explicit omitted count, a 30 second
timeout, and a 32 KiB output limit. The serialized envelope SHALL reserve at
least 1 KiB for mandatory metadata and counts, bound every displayed
path/message/remediation field by bytes before JSON encoding, and degrade to a
valid count-only truncated envelope rather than exceed the output limit.
Diagnostics SHALL have a stable ordering by path/line/rule/message and be
emitted in the declared structured-output schema as well as human-readable
form.

The architecture structured-output contract SHALL be
`trade.architecture.guard.v1`. Every baseline and target step SHALL emit one
JSON object with required fields `schema_version`, `status`, `scope`,
`partial_scope`, `findings`, `counts`, `emitted_count`, and `omitted_count`.
`status` SHALL be `pass`, `fail`, or `invalid`; `scope` SHALL identify
`baseline` or the sorted target batch identity; `partial_scope` SHALL state
whether canonical filtering excluded an architecture-sensitive delta.
`counts` SHALL contain non-negative `error`, `warning`, and `total` integers
consistent with the ordered `findings` plus `omitted_count`. Each emitted
finding SHALL contain `rule_id`, repository-relative `path`, positive `line`,
bounded `message`, and bounded `remediation`. JSON and human text SHALL derive
from the same ordered finding set. Unknown schema versions, missing required
fields, invalid counts, unsafe paths, invalid status, or an output overflow
SHALL be an infrastructure failure, never an architecture pass.

The contributor SHALL trigger for every baseline-declared evidence source and
for its guard, parser, contributor, and registry integration paths. Rename or
delete of an evidence source SHALL trigger validation and fail until the
baseline is updated. The shared `ScopeSelection` contract SHALL preserve the
canonical unfiltered modified, added, deleted, renamed-from, renamed-to, and
untracked delta sets plus normalized requested filters before it creates the
filtered execution fields. The planner SHALL pass that metadata unchanged to
contributors and create `architecture.partial_scope` when the canonical
unfiltered delta contains a baseline, target, guard, contributor, registry,
native, or interface-baseline trigger excluded by `--path`. The contributor
SHALL NOT rediscover Git state. The rule SHALL cover modified files, both rename
endpoints, deletion, and untracked files. Existing global scope-discovery and
full-fingerprint costs are outside this child and SHALL have the named
quality-platform follow-up `quality-scope-capacity-baseline`, owned by
developer-experience/quality-platform, before repository-wide target adoption.
Its exit criteria are a representative repository measurement, bounded
full-fingerprint byte/path work, and a documented budget/fail-safe policy; this
child shall add no additional full-tree scan.

#### Scenario: A large target delta needs multiple subprocess batches

- **WHEN** changed target filenames exceed the configured argv budget but each
  batch and the aggregate architecture scope remain inside their declared
  file/source-byte budgets
- **THEN** the contributor emits one baseline step and ordered target batches
  using `batched_paths()` and deterministic batch IDs without dropping a file

#### Scenario: Target source work exceeds a budget

- **WHEN** changed target source exceeds the per-file, per-batch, or total
  architecture file/source-byte limit
- **THEN** planning emits `architecture.scope_budget_exceeded`, does not create
  a partial target acceptance, and tells the owner to reduce the change or
  obtain a separately reviewed capacity change

#### Scenario: A filtered scope omits a renamed architecture source

- **WHEN** `--path` excludes an architecture-sensitive modified file, deleted
  file, rename source, rename target, or untracked source recorded in the
  canonical unfiltered delta metadata
- **THEN** planning emits `architecture.partial_scope` before target execution
  and no contributor independently scans Git history

#### Scenario: A worst-case finding report is truncated

- **WHEN** a target batch produces more findings or longer fields than fit in
  the architecture output envelope
- **THEN** it emits valid `trade.architecture.guard.v1` JSON with consistent
  counts, `emitted_count`, and `omitted_count`, and the executor never receives
  more than the declared output limit

#### Scenario: An audited evidence source is renamed

- **WHEN** a baseline-declared DDL, artifact, pointer, receipt, Capture fact,
  native fact, interface-baseline fact, guard, contributor, or registry source
  is renamed or deleted
- **THEN** the architecture step runs and fails until the reviewed baseline
  declares its new source fact or removes the obsolete fact
