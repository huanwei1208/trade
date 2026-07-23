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

The warehouse artifact inventory SHALL be producer-driven: it SHALL derive its
declared layer/table/path facts from every current `write_table` and
`upsert_table` call rather than only a hand-maintained required-table list.
Each declaration SHALL name the materialization source, exact producer literal,
layer, table, path role, and target/deferred classification. This includes
`ads_warehouse_validation_report` where the producer exists even when a
validation-required table list omits it.

#### Scenario: A declared pointer or receipt source is changed

- **WHEN** a child renames, deletes, or rewrites the code declaration of a
  recorded artifact, pointer, receipt, or Capture-risk fact
- **THEN** the architecture contributor runs and fails until the baseline
  declaration and the owning child's migration evidence are updated together

#### Scenario: Baseline validation runs in a no-I/O fixture

- **WHEN** the baseline validator runs in its focused negative-I/O fixture
- **THEN** the fixture permits reads only of the baseline and declared
  repository source-evidence files, and patched `sqlite3.connect`,
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
