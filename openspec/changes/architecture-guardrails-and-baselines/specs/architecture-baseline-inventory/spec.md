## ADDED Requirements

### Requirement: The legacy architecture baseline SHALL be source-verified and non-authoritative

The repository SHALL maintain a versioned architecture baseline that records
current package roots, independently declared target source/import roots,
schema-definition sources, physical table classifications, artifact/pointer/
receipt facts, Capture migration facts, native binding facts, source-derived
CLI/HTTP/OpenAPI/SSE compatibility facts, and compatibility-pointer facts. The
quality gate SHALL validate each entry against source text only. The baseline
SHALL not initialize an application, open a database, read an artifact, or
claim final runtime ownership.

Every table declaration SHALL record a logical table name, current owner,
one-or-more provenance records, and a classification. A provenance record
SHALL name a repository source, an exact source literal, and one of
`bootstrap`, `migration`, `alter`, or `data_transform`; a single bootstrap DDL
location SHALL not be treated as complete physical-schema evidence. A
classification SHALL carry a semantic kind, target Context or `deferred`,
reason, required owning child, and explicit activation state. `candidate` and
`deferred` are audit-only classifications and SHALL never authorize target
persistence access. Only a later, separately reviewed `approved_binding` with
one target Context and a named persistence-adapter scope authorizes a literal
SQL table reference.

#### Scenario: A baseline table source changes

- **WHEN** a child moves or rewrites a source-defined table declaration
- **THEN** the baseline validation fails until that child updates the declared
  provenance fact or facts, classification, compatibility note, and focused
  migration evidence in the same reviewed change

#### Scenario: A table requires further classification

- **WHEN** the current source inventory identifies a KG, causal, factor, or
  historical recommendation record whose target Context is not yet proven
- **THEN** the baseline marks it `deferred`, records its reason and required
  owning child, and no target module treats the declaration as authority to
  read or write that record

#### Scenario: A candidate table lacks an approved binding

- **WHEN** a baseline entry names Datasets as a candidate target Context but
  does not contain an explicit approved persistence-adapter binding
- **THEN** a target Datasets adapter cannot query that table; the guard fails
  closed until its owning child adds the approved binding and focused owner,
  transaction, reader, and compatibility evidence

#### Scenario: Historical DDL has two provenance roles

- **WHEN** a logical record is created by bootstrap SQL and later has a
  `migration` or `alter` provenance source
- **THEN** the baseline records both provenance facts with their distinct roles
  and does not claim either source alone describes the complete physical schema

#### Scenario: An independent schema or projection declaration is encountered

- **WHEN** current source declares `feed_scores`, `source_configs`,
  `catalog_meta`, `runs`, `releases`, `catalog.sqlite`, or `generation.json`
  outside the central TradeDB schema paths
- **THEN** the baseline records the exact source literal, current owner,
  projection or authoritative role, candidate/deferred target classification,
  and required child without treating the record as an approved persistence
  binding

### Requirement: Source-only artifact, pointer, receipt, and Capture-risk facts SHALL be complete enough to govern later children

The baseline SHALL record known source-defined warehouse Parquet artifact
families, the Crypto ADS current pointer and completion-receipt convention, the
BTC compatibility pointer, and the Kline reconciliation `current.json` fact.
It SHALL record each fact's repository source, exact literal, current code
owner, compatibility or recovery role, candidate target Context or deferred
state, and required owning child. These are source-only migration inputs, not
runtime artifact inspection or release authorization.

The baseline SHALL also record the current Capture-risk facts for the legacy
`RawRecord` temporal model and every known RSS, GDELT, warehouse, archive, and
date-only publication-time fallback. Every Capture-risk record SHALL state its
repository source, exact literal, risk kind, current behavior, required child,
and required migration proof. Required risk kinds include provider timestamp
absence/substitution, date-only inferred precision, catalog/environment
override and absent rights-policy evidence, provider-refetch versus local
artifact replay versus WAL recovery, and transport/integrity failure versus
downstream semantic quarantine. `capture-boundary` SHALL treat those
declarations as mandatory inputs and prove independent
provider/observed/received/available/revision/finality clocks, SourceManifest
rights enforcement, provider-free replay, and the Capture transport-versus-
Datasets semantic quarantine split before migrating a news or NLP adapter.

The warehouse artifact inventory SHALL be producer-driven. Its only canonical
writer targets are the module-level functions
`trade_py.data.warehouse.io.write_table` and
`trade_py.data.warehouse.io.upsert_table`, each of which accepts a
`WarehouseLayout` value as its first `layout` argument. The source-only
resolver SHALL recognize direct and module imports, local aliases, and the
`trade_py.data.warehouse` package re-exports of those functions; it SHALL NOT
invent nonexistent `WarehouseLayout` instance methods. A call counts as a
producer when its callee resolves to one canonical writer and its first
argument is a statically known `WarehouseLayout` binding. A nonliteral
layer/table, unresolved warehouse-writer import, or unresolved layout binding
in a candidate call SHALL fail closed with a producer-discovery finding rather
than be omitted from the inventory.

The initial inventory pass SHALL parse the complete, bounded universe of Git
tracked first-party production Python sources below `trade_py/`. It excludes
test-only paths and files, generated, vendor, cache, non-source data assets,
and artifact paths; production modules such as `trade_py/data/**.py` remain in
scope. It never imports code or reads a database or artifact. This is the sole
narrow exception to the rule against recursive full-repository AST scanning: it
is limited to the declared `trade_py/` production universe, at most 512 files
and 32 MiB aggregate source, and one source file may not exceed 1 MiB. The
validator SHALL emit `architecture.producer_discovery_budget_exceeded` and fail
without an incomplete inventory if any limit is exceeded. The current source
measurement of 304 files and 2,967,859 bytes is capacity evidence, not an
authorization to raise the limits.

After the initial inventory, every modified, added, renamed, or untracked
production Python file receives the same bounded AST import/call prefilter
before the planner classifies the delta as legacy-only. A detected canonical
writer, a changed or deleted declared producer source, or an unresolved
warehouse-writer import forces baseline validation. The validator fails until
the baseline declares every discovered producer; it does not accept a
hand-maintained required-table list or one materialization module as proof of
completeness. Test fixtures are not production artifact producers. Each
declaration SHALL name the producer source, exact call literal, layer, table,
path role, and target/deferred classification. This includes
`ads_warehouse_validation_report` where the producer exists even when a
validation-required table list omits it, and the CLI fetch producers
`dim.dim_data_source` and `ods.ods_fetch_attempt`.

#### Scenario: A production warehouse writer is outside the materializer

- **WHEN** `trade_py/cli/data.py` resolves a call imported from
  `trade_py.data.warehouse.write_table` for `dim.dim_data_source` or a call
  imported from `trade_py.data.warehouse.upsert_table` for
  `ods.ods_fetch_attempt`
- **THEN** the baseline declares both producer facts and validation fails for an
  undeclared production writer even when `_REQUIRED_TABLES` or
  `materialize.py` does not list it

#### Scenario: An alias or package re-export invokes a canonical writer

- **WHEN** a production source aliases a direct/module import or imports
  `write_table` or `upsert_table` through the `trade_py.data.warehouse`
  package re-export
- **THEN** the resolver records the canonical `io` function target and requires
  a declaration for each literal producer call instead of treating the alias or
  re-export as a different writer

#### Scenario: A changed producer is not already in the baseline

- **WHEN** a changed or untracked production Python file contains a call that
  resolves to a canonical warehouse writer
- **THEN** its bounded prefilter prevents a legacy-only plan, baseline
  validation runs, and an undeclared producer fails closed until the inventory
  declaration is added

#### Scenario: A declared producer source is renamed or deleted

- **WHEN** a child renames or deletes a source named by a warehouse producer
  declaration
- **THEN** the baseline contributor runs from canonical rename/delete metadata
  and fails until the declaration is updated or removed with the corresponding
  producer inventory evidence

#### Scenario: Test-only calls do not create artifact declarations

- **WHEN** a test fixture calls either canonical warehouse writer
- **THEN** the production-universe filter excludes that source and validation
  does not require an artifact declaration for the fixture

#### Scenario: A declared pointer or receipt source is changed

- **WHEN** a child renames, deletes, or rewrites the code declaration of a
  recorded artifact, pointer, receipt, or Capture-risk fact
- **THEN** the architecture contributor runs and fails until the baseline
  declaration and the owning child's migration evidence are updated together

#### Scenario: Baseline validation runs in a no-I/O fixture

- **WHEN** the baseline validator runs in its focused negative-I/O fixture
- **THEN** the fixture permits reads only of the baseline, declared
  repository source-evidence files, and the bounded production-Python
  discovery universe, and patched `sqlite3.connect`,
  `duckdb.connect`, `pandas.read_parquet`, generic `open`/`Path.read_*` for
  in-repository `data/**`, `warehouse/**`, `market/**`, SQLite, Parquet,
  manifest, pointer, and receipt sentinels, and every out-of-repository path
  fail the test if the validator attempts to use them

#### Scenario: A source-only Capture fact changes

- **WHEN** a child changes a provider-time fallback, date-only precision rule,
  catalog/environment override, replay/WAL behavior, or semantic quarantine
  source literal
- **THEN** baseline validation fails until the record's risk kind, current
  behavior, required child, and required migration proof are updated in the
  same reviewed change

### Requirement: Compatibility and native baseline facts SHALL remain explicit

The baseline SHALL record the current root `trade` command facade, canonical
and retained hidden/deprecated CLI domains, FastAPI application/router source
roots, generated OpenAPI source, SSE route/media-type sources, and existing
CLI/HTTP/OpenAPI/SSE contract-test sources as source facts. Each interface
record SHALL name the source, exact literal, surface kind, current behavior,
compatibility owner, and the later `cli-http-sdk-compatibility` child required
to create snapshot parity and retire the old path. This child is a bounded
source-only interface baseline inventory: it SHALL NOT delegate routes, alter
payloads, generate a runtime snapshot, or implement compatibility adapters.

The baseline SHALL also record the current BTC compatibility pointer and C++
Python binding target as source facts. A later Dataset, package-layout, or
native child SHALL retain the legacy fact until it passes its own compatibility,
native-boundary, and rollback criteria.

#### Scenario: An interface evidence source changes

- **WHEN** a child renames, deletes, or changes the source declaration of a
  canonical CLI domain, FastAPI route/router, OpenAPI creation path, SSE media
  type, or its existing contract-test source
- **THEN** the architecture baseline contributor runs and fails until the
  source-only inventory and the owning interface child evidence are updated

#### Scenario: A later interface child delegates a route

- **WHEN** `cli-http-sdk-compatibility` moves a CLI, HTTP, OpenAPI, or SSE
  surface behind a compatibility adapter
- **THEN** it consumes this inventory, creates the required snapshot and
  behavior evidence, and preserves the current public contract before the
  source-only record can be retired

#### Scenario: A package transition proposes a native rename

- **WHEN** a package-layout child replaces the `trade_py` native binding target
- **THEN** it updates the baseline only after source/editable/wheel and
  C++/Python differential evidence proves the `_trade_native` boundary and
  retains a compatible rollback path

#### Scenario: A Dataset release replaces the BTC pointer

- **WHEN** a Dataset migration proposes a replacement for the recorded BTC
  compatibility pointer
- **THEN** it preserves the current pointer as a compatibility reader or
  rollback source until dual-read comparison or a readiness-gated switch has
  passed
