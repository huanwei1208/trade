## Context

`restructure-trade-architecture-v1` is strictly approved as a design-only
parent. Its first implementation prerequisite is a guard that protects
future target modules before any extraction starts. The current repository has
not yet adopted `src/trade`: Python behavior remains under `trade_py/`, Web
behavior under `trade_web/backend/`, and the central `TradeDB` constructor and
DDL sources define many current tables. Direct `TradeDB` imports remain in
CLI, jobs, and Web runtime code. These facts are intentionally not treated as
the target architecture.

The audit also found a native-binding collision risk: `engine/cmake/python_bindings.cmake`
defines a module named `trade_py`, while `trade_py/__init__.py` attempts to
import that name as its C++ probe. The BTC store retains a verified
compatibility pointer at `market/crypto/btc_current.json` alongside
`market/crypto/btc.parquet`. Both are current compatibility facts, not a
license to create further unowned pointers.

The source audit also identifies warehouse Parquet families in
`trade_py/data/warehouse/materialize.py`, Crypto ADS pointer and completion
receipt conventions in `trade_py/data/warehouse/crypto_store.py`, and the
Kline reconciliation `current.json` convention in
`trade_py/data/operations/checks.py`. These are migration inputs, not
artifacts inspected by this child. Capture migration inputs are likewise
source-only: `RawRecord` has one `published_at` field, while RSS, GDELT, and
warehouse RSS paths substitute collector/fetch time when provider publication
time is unavailable. Archive and date-only feeds infer noon timestamps;
GDELT streaming re-fetches a provider while reading/writing local state, and
WAL recovery has a distinct legacy meaning. Semantic quarantine also occurs in
the warehouse transformation rather than at transport admission. RSS catalogs
can be selected through environment overrides, while rights-policy evidence is
not currently present. The Capture child, not this guard, owns the correction.

The audit found further independent persistence and projection declarations
outside the initial central schema sources: `trade_py/intelligence/schema.py`
defines `feed_scores` and `source_configs`, while
`trade_py/observatory/catalog/store.py` defines the rebuildable
`catalog.sqlite` projection, `generation.json` pointer, and `catalog_meta`,
`runs`, and `releases` tables. Warehouse materialization writes
`ads_warehouse_validation_report` even though that table is not in the
hand-maintained required-table list. The source-only baseline must inventory
these facts by source producer without treating them as ownership approval.

The parent migration matrix assigns this first child bounded CLI, HTTP, OpenAPI,
and SSE baselines. The audit identifies the root `trade` facade and
`trade_py/cli/main.py` domain registry, `trade_web/backend/app.py`,
`trade_web/backend/runtime/router.py`, Observatory routers, and existing
CLI/Web contract tests as the source evidence. This child records those
surfaces only; the later `cli-http-sdk-compatibility` child remains responsible
for behavior snapshots, adapter delegation, and retirement decisions.

This child is Non-trivial because it changes the repository-wide developer
quality path and sets future architecture enforcement across tooling, tests,
and new target module roots. It performs no runtime/domain implementation,
module move, external request, database open, artifact read, artifact write,
or ownership transition.

## Goals / Non-Goals

**Goals:**

- Make the parent design's prospective dependency rules executable for new
  `src/trade` Python files without first repairing the entire legacy tree.
- Detect forbidden concrete Context imports, invalid internal Cell direction,
  contract type leakage, private database or artifact-client escape, direct
  interface SQL, Platform business vocabulary, legacy namespace, dynamic
  execution, process-spawn escapes, unauthorized table access, and native
  imports outside a Context `adapters/native` boundary.
- Record auditable current facts for Python package roots, schema-definition
  sources, physical table classifications, independent projection declarations,
  warehouse artifacts, pointers, receipts, Capture migration risks,
  CLI/HTTP/OpenAPI/SSE source surfaces, C++ binding targets, and the BTC
  compatibility pointer.
- Keep guard execution deterministic, offline, bounded, and free of runtime
  imports or data-root access.
- Give later child changes a stable baseline and a small prerequisite rather
  than authorizing a broad directory move.
- Extend shared quality scope metadata once so filtered architecture checks can
  fail closed from canonical delta facts without a second Git discovery path.

**Non-Goals:**

- Moving `trade_py/` to `src/trade/`, extracting any Context, adding Kernel
  types, changing CLI/HTTP/Web behavior, or changing import paths.
- Replacing `TradeDB`, editing existing DDL, opening a SQLite
  database, reading parquet/raw artifacts, or assigning final ownership to
  deferred KG, causal, factor, or legacy recommendation records.
- Implementing Capture clocks, SourceManifest rights, provider-free replay,
  quality/quarantine semantics, a plugin system, a remote worker, or a native
  binding. This child records source facts and prohibits ungoverned loading;
  their implementation remains separately governed.
- Changing CLI/HTTP/Web/SDK/Notebook behavior, generating a behavior snapshot,
  adding an interface compatibility adapter, or delegating an existing route.
  This child records source-level interface inventory only.
- Building a generalized lint framework, adding a third-party dependency, or
  enforcing current `trade_py` imports as if legacy code already met the
  target graph.
- Enabling, renaming, or linking a native Python extension.

## Design Quality Brief

### Requirements and acceptance

The existing `trade dev check` contributor mechanism gains one architecture
step when the changed scope contains `architecture-baseline.toml`, an
`src/trade/**/*.py` target module, any baseline-declared source fact, the
guard/parser/contributor/registry integration, or the reviewed native binding
definition, or a baseline-declared interface source. Rename and delete events
are triggers. The step parses only selected Python source text and named
repository source files. It produces `trade.architecture.guard.v1` structured
diagnostics with stable path, line, rule, remediation, ordered findings, counts,
scope identity, and partial-scope state; it never imports the inspected package.

Acceptance requires that a compliant target module passes, each prohibited
relationship has a focused failing fixture, baseline source/table/pointer
claims match the current repository text, and a normal legacy-only changed
scope remains unaffected. The step must be represented as a quality failure,
not a skip or a warning, when a target rule is violated.

`--path` is a partial development selector, not a release-acceptance shortcut.
`ScopeSelection` retains normalized requested filters and canonical unfiltered
modified, added, deleted, rename-source, rename-target, and untracked delta
metadata before deriving its existing filtered execution fields. The planner,
not a contributor, compares architecture triggers against that metadata. If
filters exclude an architecture-sensitive changed source, planning fails closed
as `architecture.partial_scope`, including rename endpoints and deleted or
untracked sources. A complete selected scope contains one baseline validation
step and all deterministic target-source batches.

### Ownership and boundaries

`trade_py/devtools/architecture_guard.py` owns parsing, validation, bounded
diagnostic-envelope formatting, and baseline fact semantics for this child.
`trade_py/devtools/quality/models.py` and `scope.py` own the additive canonical
unfiltered delta/filter contract; `planner.py` owns conversion of excluded
architecture-sensitive delta facts into a fail-closed plan issue. The future
`trade_py/devtools/quality/contributors/architecture.py` receives that canonical
selection and only constructs bounded subprocess steps; it must not rediscover
Git state. The existing quality registry owns contributor registration.
`architecture-baseline.toml` is the authoritative declaration of audited source
facts. It separately freezes `target_source_root = "src/trade"` and
`target_import_root = "trade"`; the guard uses the latter for absolute and
relative import resolution without requiring target-package installation.
`tests/test_architecture_guard.py`, `tests/test_architecture_contributor.py`,
and focused scope/planner extensions own target-fixture coverage; no fixture
opens the application or a data root.

The guard has a deliberately narrow prospective boundary. It applies to
`src/trade` once a later child creates that root. It does not validate all
legacy `trade_py` dependencies. A later extraction must add its own target file
and satisfy this guard before it becomes a new architectural dependency.

### Data and state invariants

The baseline is source metadata, not a runtime catalog, a schema authority, or
an ownership-transfer mechanism. Each logical table records a current owner,
one-or-more source facts with `bootstrap`, `migration`, `alter`, or
`data_transform` role, an audit-only `candidate` or `deferred` classification,
semantic kind, target Context/defer reason, and required child. Neither
`candidate` nor `deferred` authorizes persistence access. Only a later
implementation child may add an explicit `approved_binding` that names one
Context and one persistence-adapter scope after proving writer, reader,
transaction, compatibility, and owner behavior.

The checker reads UTF-8 text using repository-relative paths beneath the
worktree and rejects malformed TOML, missing sources, unsafe relative paths,
duplicate declarations, and source facts that no longer match their declared
literal. It does not load modules, initialize `TradeDB`, read an artifact
directory, or accept arbitrary paths outside the repository. The focused
source-only fixture permits reads only of the baseline and declared source
evidence files; it denies `sqlite3.connect`, `duckdb.connect`,
`pandas.read_parquet`, all reads of in-repository `data/**`, `warehouse/**`,
`market/**`, SQLite, Parquet, manifest, pointer, and receipt sentinels, and
all out-of-repository paths.

### Contracts and compatibility

The user-facing `trade` command, existing CLI command names, HTTP routes,
OpenAPI output, SSE semantics, Web payloads, SDK imports, notebook behavior,
table readers, BTC pointer format, and C++ ABI remain unchanged. The bounded
baseline records where these CLI/HTTP/OpenAPI/SSE contracts are defined and
tested, but it does not snapshot or alter their behavior. The developer-facing
`trade dev check` contract gains stable scope metadata, a partial-scope refusal,
and a versioned architecture diagnostic envelope only for in-scope changes.
Its diagnostics identify a rule ID, source location, and the approved
remediation direction; repository consumers can continue to use legacy import
paths until their individual compatibility child supplies a replacement.

The architecture baseline records, rather than replaces, the `trade_py`
package discovery and the `trade_py` CMake binding target. It reserves
`_trade_native` as the future native name but does not claim that the binding
exists. The later package-layout child owns the actual transition and must
prove source, editable, and wheel compatibility.

All target business Contexts can import only `trade.platform.contracts` or
`trade.platform.api`, never a concrete Platform adapter. Bootstrap is the
only normal composition root for concrete adapters. The sole future legacy
exception is a specifically declared Platform persistence adapter, imported
only by `trade.bootstrap`, which exposes
`LegacySchemaBootstrapAdapter` through a narrow schema-bootstrap allowlist and
removal condition. Every other target `trade_py.*` or `trade_web.*` import is
denied.

### Failure and recovery

Malformed source, unsupported relative import, malformed or oversized
diagnostic envelope, malformed baseline, unlisted target Cell, missing baseline
evidence, exceeded scope budget, partial scope, or a prohibited dependency is a
fail-closed architecture result. A quality check failure has no side effect:
the source tree and local data remain unchanged. A developer corrects the
target module or updates the baseline through a reviewed child change. The
guard does not automatically rewrite imports, infer table ownership, or
silently ignore an unknown file.

The implementation supplies a concise developer runbook keyed by
`architecture.*`, `dependency.*`, `persistence.*`, `artifacts.*`, and
`execution.*` rule IDs. It states the matching `trade dev check --show-plan`
and JSON-report commands, the expected owner, and the corrective action for a
stale baseline, rename/delete, partial scope, scope budget, timeout, invalid
envelope, or source rule violation. The runbook is developer tooling
documentation, not an application operations system.

Rollback removes the contributor, guard, baseline, and focused tests together.
Because the child does not alter runtime behavior, database content, artifact
content, or interface payloads, the previous quality plan remains usable
immediately. A bad baseline fact is corrected in a small documentation/tooling
commit before any owner migration consumes it.

### Performance and capacity

The contributor runs only for its explicit scope triggers. The checker walks
the selected target Python files once, parses each with the standard-library
AST, and reads only the finite set of baseline-declared source files. It has a
finite subprocess timeout and output limit through the existing quality-step
model. No network access, package installation, database scan, artifact hash,
or recursive full-repository AST scan is permitted.

The first target scope is expected to be small because Context children add
bounded modules incrementally. The contributor explicitly uses
`batched_paths()` and deterministic batch identifiers: exactly one baseline
step plus target batches within the configured argv budget. Independent of that
argv limit, the guard refuses a source over 1 MiB, a target batch over 128 files
or 8 MiB aggregate source, and a selected architecture target scope over 512
files or 32 MiB aggregate source. It reports an explicit budget failure rather
than silently dropping work. The existing executor runs at most four light
steps concurrently; four maximum-size target batches are therefore bounded to
32 MiB source input at once. A 30-second step timeout, 64 emitted findings,
bounded fields, reserved metadata space, count-only truncation fallback, and
32 KiB serialized envelope prevent an oversized structured report. Baseline
validation is linear in its declared evidence entries and is exercised from a
temporary fixture repository.

Existing scope discovery and before/after full-worktree fingerprinting remain
an owned quality-platform performance debt. The child records the named
`quality-scope-capacity-baseline` follow-up, owned by
developer-experience/quality-platform, with measured representative scope,
bounded byte/path work, and a documented fail-safe exit criterion before
repository-wide target adoption. This child does not add another full-tree
walk.

### Observability and operations

Every `trade.architecture.guard.v1` JSON envelope has required
`schema_version`, `status`, `scope`, `partial_scope`, `findings`, `counts`,
`emitted_count`, and `omitted_count` fields. `status` is `pass`, `fail`, or
`invalid`; `scope` identifies the baseline or deterministic target batch; and
counts are consistent with emitted plus omitted findings. Each finding contains
`rule_id`, repository-relative `path`, positive `line`, bounded `message`, and
bounded `remediation`. JSON and terminal detail derive from the same ordered
finding set. An unrecognized schema, missing/unsafe field, inconsistent count,
or overflow is an infrastructure result rather than a pass.

Each failure reports a deterministic rule name such as
`dependency.context_implementation`, `cell.use_case_adapter`,
`contracts.implementation_type`, `database.owner_escape`,
`database.foreign_table_owner`, `persistence.unapproved_client`,
`artifacts.direct_access`, `interfaces.direct_sql`,
`dependency.legacy_namespace`, `dependency.dynamic_loading`,
`execution.direct_process_creation`, `platform.business_vocabulary`, or
`native.boundary`. Diagnostics include the repository-relative path and source
line where the offending import, annotation, attribute, SQL literal, direct
artifact client, dynamic loader, process spawn, or vocabulary occurs. They sort
by path, line, rule, and message; truncation reports the emitted and omitted
counts rather than hiding findings.

`trade dev check --show-plan` shows the architecture step when triggered. A
clean legacy-only implementation change does not silently receive an unrelated
new full-tree audit. The baseline itself is format-checked by the current
shared TOML parser and its semantic source claims are checked by the
architecture step whenever it changes.

### Validation strategy

Focused pytest uses temporary repositories and source files to prove the
allowed Context graph and each forbidden rule. It covers absolute and relative
imports under the declared `trade` import root, rejection of `src.trade.*`,
Platform public API versus concrete adapter imports, the exact Bootstrap-to-
Platform legacy schema bridge, legacy namespace imports, dynamic Python/file/
native loaders, direct process creation and process pools, own-Cell direction,
contract annotation leakage, Context/Interface database and artifact-client
access, table owner and approved-binding decisions, Platform terminology, native
import placement, malformed baseline, multi-source table provenance, independent
intelligence/projection declarations, producer-derived warehouse artifacts,
missing/deleted source evidence, precise Capture migration facts, source-only
CLI/HTTP/OpenAPI/SSE facts, duplicate declarations, negative-I/O enforcement,
and the current-tree legacy baseline.

Contributor, scope, and planner tests assert triggering for target, baseline,
every declared evidence path, guard/parser/contributor/registry integration,
native binding, and interface source changes; they assert that a legacy-only
scope adds no architecture step. They prove modified/deleted/renamed/untracked
partial-scope failures using canonical preserved metadata; argv, file-count,
per-file, batch-byte, total-scope, and four-worker wave budgets; deterministic
batch IDs; timeout/output settings; valid worst-case structured truncation;
invalid-envelope rejection; and check mode with no mutation step. The final
implementation runs the focused tests, shared Python compile validation,
`uv run ./trade dev check --show-plan`, `uv run ./trade dev check`, and
`git diff --check`. No C++ build, frontend build, API smoke, or live-data
validation is required because no component behavior changes.

### Alternatives and trade-offs

**Enforce the full current `trade_py` tree immediately:** rejected because the
audit already shows direct facade imports across many legacy paths. Treating
those facts as immediate failures would force a broad rewrite and obscure the
incremental owner migration required by the parent design.

**Use a third-party import linter:** rejected for this first slice because the
needed checks include Cell direction, AST annotation leakage, source-declared
table facts, pointer evidence, and native boundary policy. A small
standard-library implementation keeps the policy local, deterministic, and
testable without expanding packaging risk.

**Store the inventory in comments or a Markdown table:** rejected because
later child tooling needs parseable source locations and classifications. TOML
keeps the baseline versioned and machine-verifiable while the parent OpenSpec
continues to explain target ownership.

**Make the baseline final ownership authority:** rejected because several
legacy records require row-level analysis. `candidate` and `deferred` are both
audit-only; an owning Context child must prove its authoritative writer,
readers, transaction boundary, compatibility plan, and named persistence
adapter before adding an explicit `approved_binding`.

### Rollout and rollback

1. Add and approve this child design before code implementation.
2. Add the baseline parser/validator and fixture tests without registering it.
3. Register the contributor and verify changed-scope plan behavior.
4. Commit the baseline/guard unit, then run the focused and unified quality
   gates.
5. Run the six-role implementation review against the frozen diff and resolve
   P0 findings before push/PR.

The guard is prospective: later children create `src/trade` modules only after
their approved designs name an owner and compatibility bridge. A failing
transition is rolled back by retaining the legacy path and removing the new
target module from the child branch; this guard itself has no runtime state to
restore.

## Decisions

### Use an AST guard with a declarative scope

`architecture-baseline.toml` declares distinct `target_source_root` and
`target_import_root`, approved Context names, legacy source facts, table
provenance and approval state, warehouse/pointer/receipt/Capture facts,
CLI/HTTP/OpenAPI/SSE source facts, and native facts. The checker parses source
via `ast.parse`, resolves absolute and relative imports under the declared
import root, and applies the parent dependency graph only under the declared
target root. It rejects `src.trade.*` as a filesystem-path import rather than
mistaking it for a Context namespace. This catches the relationships that
matter at the time a new Context file is introduced without importing code or
relying on fragile text-only import searches.

The allowed graph is:

```text
kernel -> kernel
capture -> kernel, platform.contracts/api
datasets -> kernel, platform.contracts/api, capture.contracts
studies -> kernel, platform.contracts/api, datasets.contracts
decision_support -> kernel, platform.contracts/api, datasets.contracts, studies.contracts
processes -> kernel, platform.contracts/api, all business contracts
interfaces -> kernel, platform.contracts/api, processes, context contracts/use_cases
bootstrap -> all target modules
platform -> kernel, platform contracts/api
```

Within a Context Cell, `contracts` and `domain` only receive Kernel and own
types under their approved rule; `ports` receives own domain/contracts;
`use_cases` receives own domain/ports/contracts plus upstream contracts; and
`adapters` receives own ports/domain/contracts plus external libraries. A
Context or Interface file cannot directly import unapproved database or
artifact clients, legacy namespaces, or access private connection attributes. A
Context may access literal SQL only within a baseline-authorized persistence
adapter for its approved table. A target Platform file cannot contain declared
business aggregate vocabulary. A native extension is importable only from a
Context `adapters/native` module. Dynamic module/file/native loading, direct
process creation, shell execution, and process pools are forbidden until a
later separately approved plugin/worker or Platform execution contract.

### Validate baseline facts, not final Context ownership

The initial baseline uses the observed DDL locations in
`trade_py/db/trade_db.py`, `trade_py/db/migrations.py`,
`trade_py/db/pipeline_db.py`, and `trade_py/intelligence/schema.py`; it also
records the Observatory catalog projection declarations in
`trade_py/observatory/catalog/store.py`. It records one-or-more provenance
facts for each logical table and names current code owners plus target
classification. Warehouse artifact entries are derived from every
`write_table` and `upsert_table` producer in
`trade_py/data/warehouse/materialize.py`, including the validation report, and
every other first-party production call statically resolving to
`WarehouseLayout.write_table` or `WarehouseLayout.upsert_table`. This includes
the standalone CLI fetch producers in `trade_py/cli/data.py` for
`dim.dim_data_source` and `ods.ods_fetch_attempt`; test fixtures are excluded
because they do not produce repository artifacts. The classification is
intentionally `candidate` for obvious families and `deferred` where the parent
design requires later file/row analysis. Both are non-authorizing. This avoids
making the guard another global database facade or pretending exact future table
names already exist.

`BtcRunStore.current_path`, `compatibility_path`, and
`engine/cmake/python_bindings.cmake` are pinned as source facts, alongside
warehouse layout/materialization, Crypto ADS pointer/receipt, Kline
reconciliation, precise Capture time/catalog/replay/quarantine facts, and root
CLI/FastAPI/OpenAPI/SSE sources. This informs future Capture, Datasets,
interface, and package changes of known compatibility and recovery edges while
making no production change to those edges.

The one future legacy schema bridge is deliberately placed at
`trade.platform.persistence.adapters.legacy_schema_bootstrap`.
`LegacySchemaBootstrapAdapter` is an implementation in that Platform adapter;
only `trade.bootstrap` may import it. The baseline declaration must name the
adapter path and every legacy schema-bootstrap symbol it imports, and no
business Context, Process, or Interface may import it. This preserves the
parent's Bootstrap-only composition rule and avoids an ambiguous
`trade.bootstrap.compat` ownership boundary.

### Integrate through the existing quality contributor seam

The existing `DesignQualityContributor` shows the project convention for
scope-aware quality checks. A sibling `ArchitectureContributor` supplies one
baseline check plus explicitly batched read-only target checks; normal provider
ownership remains unchanged. The contributor never invokes the guard in fix
mode and never makes the architecture checker a catch-all quality provider.
Before contributor planning, the additive `ScopeSelection` fields preserve
canonical unfiltered delta/filter facts. The shared planner computes
`architecture.partial_scope` as an ordinary failed plan issue, allowing the
existing runner and JSON/text reports to expose it consistently while
independent checks remain observable. This preserves the quality runner's
source-protection guarantee and avoids duplicate Git traversal.

## Risks / Trade-offs

- **Rule false positives from partial Context layouts** -> The checker applies
  only when a file has a declared target Context and Cell path. Unknown target
  layouts fail with an explicit rule rather than being guessed; each child
  introduces files in the canonical Cell shape.
- **Legacy baseline becomes stale** -> The baseline validates source literals
  and source paths on every evidence/native/target/guard-triggered run,
  including rename/deletion; a child must update it in the same reviewed change
  when audited facts legitimately move.
- **A source-text rule cannot prove runtime ownership** -> The guard blocks
  direct architectural bypasses and fail-closes unknown table/artifact,
  dynamic-loading, and process-spawn paths, but does not claim dynamic behavior
  proof. Later Context and Platform children retain focused
  integration/contract fixtures and six-role review obligations.
- **Direct SQL detection has lexical limits** -> It is intentionally scoped to
  target Interfaces and Context paths. Literal SQL is allowed only in an
  explicit `approved_binding`; dynamic SQL needs a later parser/allowlist
  design and cannot bypass the first guard.
- **Guard volume or noisy diagnostics** -> Per-file, per-batch, total-scope,
  and concurrent-wave source-byte budgets; argv limits; timeout; versioned
  bounded envelope; stable sort; and explicit count-only truncation make
  failures predictable. Existing quality scope/fingerprint costs remain
  separately tracked through `quality-scope-capacity-baseline` and are not
  worsened by this child.
- **Source-only baseline reads data by accident** -> The validator allowlists
  only its baseline/evidence source files in a temporary fixture and explicitly
  denies in-repository data/artifact sentinels as well as external paths. A
  source fact cannot justify physical artifact inspection.
- **First-child interface scope expands into a compatibility migration** ->
  This child inventories definition/test sources only. It does not generate
  behavioral snapshots, delegate a route, or alter a response form; those remain
  exit criteria of `cli-http-sdk-compatibility`.
- **Native boundary policy precedes a real binding** -> The baseline records
  the current collision and prohibits future direct imports; the package/native
  child will add CMake linkage and differential checks before enabling a
  binding.

## Migration Plan

The implementation is additive and order-preserving:

1. Add the baseline and parser tests while all application paths remain in
   their current locations.
2. Add the additive shared scope/model/planner metadata and focused
   modified/delete/rename/untracked filtered-scope tests.
3. Add the scoped guard and contributor registration, with tests that prove
   no legacy-only source is newly audited.
4. Freeze the baseline as the first architecture migration input.
5. Require `kernel-and-public-contracts` to introduce any first `src/trade`
   paths under this guard.

Rollback removes the guard components and baseline declaration, leaving source,
database, artifact, native, and interface behavior untouched. If needed, the
additive scope metadata and planner architecture-only plan issue are removed in
the same isolated rollback, restoring the prior filtered selection behavior.
Later child rollbacks retain legacy modules and update/restore baseline source
facts before attempting another extraction.

## Open Questions

- The final mapping for KG, causal, factor, and historical recommendation
  records remains deferred to their owning Dataset, Study, or Decision Support
  child; no ambiguity is resolved by this guard.
- The package-layout child must decide the exact distribution/console bridge
  and whether `_trade_native` is a separately installed extension before CMake
  linkage changes are designed.
