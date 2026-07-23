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
  contract type leakage, private database escape, direct interface SQL,
  Platform business vocabulary, and native imports outside a Context
  `adapters/native` boundary.
- Record auditable current facts for Python package roots, schema-definition
  sources, physical table classifications, C++ binding targets, and the BTC
  compatibility pointer.
- Keep guard execution deterministic, offline, bounded, and free of runtime
  imports or data-root access.
- Give later child changes a stable baseline and a small prerequisite rather
  than authorizing a broad directory move.

**Non-Goals:**

- Moving `trade_py/` to `src/trade/`, extracting any Context, adding Kernel
  types, changing CLI/HTTP/Web behavior, or changing import paths.
- Replacing `TradeDB`, editing existing DDL, opening a SQLite
  database, reading parquet/raw artifacts, or assigning final ownership to
  deferred KG, causal, factor, or legacy recommendation records.
- Building a generalized lint framework, adding a third-party dependency, or
  enforcing current `trade_py` imports as if legacy code already met the
  target graph.
- Enabling, renaming, or linking a native Python extension.

## Design Quality Brief

### Requirements and acceptance

The existing `trade dev check` contributor mechanism gains one architecture
step when the changed scope contains `architecture-baseline.toml`, an
`src/trade/**/*.py` target module, or the reviewed native binding definition.
The step parses only selected Python source text and named repository source
files. It produces path, line, rule, and remediation diagnostics; it never
imports the inspected package.

Acceptance requires that a compliant target module passes, each prohibited
relationship has a focused failing fixture, baseline source/table/pointer
claims match the current repository text, and a normal legacy-only changed
scope remains unaffected. The step must be represented as a quality failure,
not a skip or a warning, when a target rule is violated.

### Ownership and boundaries

`trade_py/devtools/architecture_guard.py` owns parsing, validation, and
diagnostic formatting for this child. `trade_py/devtools/quality/contributors/architecture.py`
only decides whether the changed scope requires the guard and constructs a
bounded subprocess step. The existing quality registry owns contributor
registration. `architecture-baseline.toml` is the authoritative declaration of
audited legacy facts. `tests/test_architecture_guard.py` owns target-fixture
coverage; it does not open the application or a data root.

The guard has a deliberately narrow prospective boundary. It applies to
`src/trade` once a later child creates that root. It does not validate all
legacy `trade_py` dependencies. A later extraction must add its own target file
and satisfy this guard before it becomes a new architectural dependency.

### Data and state invariants

The baseline is source metadata, not a runtime catalog, a schema authority, or
an ownership-transfer mechanism. Every recorded table must point to one audited DDL
source and receive a `candidate` or `deferred` target classification. A
`deferred` classification forbids a new target repository from claiming direct
access until its owning child resolves the classification.

The checker reads UTF-8 text using repository-relative paths beneath the
worktree and rejects malformed TOML, missing sources, unsafe relative paths,
duplicate declarations, and source facts that no longer match their declared
literal. It does not load modules, initialize `TradeDB`, read an artifact
directory, or accept arbitrary paths outside the repository.

### Contracts and compatibility

The user-facing `trade` command, existing CLI command names, HTTP routes,
Web payloads, SDK imports, notebook behavior, table readers, BTC pointer
format, and C++ ABI remain unchanged. The developer-facing `trade dev check`
contract gains a stable architecture step only for in-scope changes. Its
diagnostics identify a rule ID, source location, and the approved remediation
direction; repository consumers can continue to use legacy import paths until
their individual compatibility child supplies a replacement.

The architecture baseline records, rather than replaces, the `trade_py`
package discovery and the `trade_py` CMake binding target. It reserves
`_trade_native` as the future native name but does not claim that the binding
exists. The later package-layout child owns the actual transition and must
prove source, editable, and wheel compatibility.

### Failure and recovery

Malformed source, unsupported relative import, malformed baseline, unlisted
target Cell, missing baseline evidence, or a prohibited dependency is a
fail-closed architecture result. A quality check failure has no side effect:
the source tree and local data remain unchanged. A developer corrects the
target module or updates the baseline through a reviewed child change. The
guard does not automatically rewrite imports, infer table ownership, or
silently ignore an unknown file.

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
bounded modules incrementally. If a later change introduces a large batch, the
same existing quality argv batching and output limits apply. Baseline validation
is linear in its declared source/table/pointer entries and is exercised from a
temporary fixture repository.

### Observability and operations

Each failure reports a deterministic rule name such as
`dependency.context_implementation`, `cell.use_case_adapter`,
`contracts.implementation_type`, `database.owner_escape`,
`interfaces.direct_sql`, `platform.business_vocabulary`, or
`native.boundary`. Diagnostics include the repository-relative path and source
line where the offending import, annotation, attribute, SQL literal, or
vocabulary occurs.

`trade dev check --show-plan` shows the architecture step when triggered. A
clean legacy-only implementation change does not silently receive an unrelated
new full-tree audit. The baseline itself is format-checked by the current
shared TOML parser and its semantic source claims are checked by the
architecture step whenever it changes.

### Validation strategy

Focused pytest uses temporary repositories and source files to prove the
allowed Context graph and each forbidden rule. It covers absolute and relative
imports, own-Cell direction, contract annotation leakage, Context/Interface
database access, Platform terminology, native import placement, malformed
baseline, missing source evidence, duplicate table declaration, and the
current-tree legacy baseline.

Contributor tests assert triggering only for a target source, baseline file,
or native binding source and assert that a legacy-only scope adds no
architecture step. The final implementation runs the focused tests, shared
Python compile validation, `uv run ./trade dev check --show-plan`,
`uv run ./trade dev check`, and `git diff --check`. No C++ build, frontend
build, API smoke, or live-data validation is required because no component
behavior changes.

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
legacy records require row-level analysis. The baseline distinguishes
`candidate` from `deferred`; an owning Context child must prove its authoritative
writer, readers, transaction boundary, and compatibility plan before changing
runtime ownership.

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

`architecture-baseline.toml` declares the target root, the target package,
approved Context names, legacy source facts, and native/pointer facts. The
checker parses source via `ast.parse`, resolves absolute and relative imports,
and applies the parent dependency graph only under the declared target root.
This catches the relationships that matter at the time a new Context file is
introduced without importing code or relying on fragile text-only import
searches.

The allowed graph is:

```text
kernel -> kernel
capture -> kernel, platform
datasets -> kernel, platform, capture.contracts
studies -> kernel, platform, datasets.contracts
decision_support -> kernel, platform, datasets.contracts, studies.contracts
processes -> kernel, platform, all business contracts
interfaces -> kernel, platform, processes, context contracts/use_cases
bootstrap -> all target modules
platform -> kernel, platform
```

Within a Context Cell, `contracts` and `domain` only receive Kernel and own
types under their approved rule; `ports` receives own domain/contracts;
`use_cases` receives own domain/ports/contracts plus upstream contracts; and
`adapters` receives own ports/domain/contracts plus external libraries. A
Context or Interface file cannot directly import `sqlite3`, `trade_py.db`, or
access private connection attributes. A target Platform file cannot contain
declared business aggregate vocabulary. A native extension is importable only
from a Context `adapters/native` module.

### Validate baseline facts, not final Context ownership

The initial baseline uses the observed DDL locations in
`trade_py/db/trade_db.py`, `trade_py/db/migrations.py`, and
`trade_py/db/pipeline_db.py`; it names current code owners and a target
classification. The classification is intentionally `candidate` for obvious
families and `deferred` where the parent design requires later file/row
analysis. This avoids making the guard another global database facade or
pretending exact future table names already exist.

`BtcRunStore.current_path`, `compatibility_path`, and
`engine/cmake/python_bindings.cmake` are pinned as source facts. This informs
future Datasets/package changes of a known compatibility edge while making no
production change to that edge.

### Integrate through the existing quality contributor seam

The existing `DesignQualityContributor` shows the project convention for
scope-aware quality checks. A sibling `ArchitectureContributor` supplies a
single read-only `CheckStep`; normal provider ownership remains unchanged.
The contributor never invokes the guard in fix mode and never makes the
architecture checker a catch-all quality provider. This preserves the quality
runner's source-protection guarantee.

## Risks / Trade-offs

- **Rule false positives from partial Context layouts** -> The checker applies
  only when a file has a declared target Context and Cell path. Unknown target
  layouts fail with an explicit rule rather than being guessed; each child
  introduces files in the canonical Cell shape.
- **Legacy baseline becomes stale** -> The baseline validates source literals
  and source paths on every baseline/native/target-triggered run; a child must
  update it in the same reviewed change when audited facts legitimately move.
- **A source-text rule cannot prove runtime ownership** -> The guard blocks
  obvious architectural bypasses but does not claim dynamic behavior proof.
  Later Context and Platform children retain focused integration/contract
  fixtures and six-role review obligations.
- **Direct SQL detection has lexical limits** -> It is intentionally scoped to
  target Interfaces and Context paths. Later repository implementations may
  own SQL in an approved adapter without reducing the rule for Interfaces.
- **Native boundary policy precedes a real binding** -> The baseline records
  the current collision and prohibits future direct imports; the package/native
  child will add CMake linkage and differential checks before enabling a
  binding.

## Migration Plan

The implementation is additive and order-preserving:

1. Add the baseline and parser tests while all application paths remain in
   their current locations.
2. Add the scoped guard and contributor registration, with tests that prove
   no legacy-only source is newly audited.
3. Freeze the baseline as the first architecture migration input.
4. Require `kernel-and-public-contracts` to introduce any first `src/trade`
   paths under this guard.

Rollback removes the guard components and baseline declaration, leaving source,
database, artifact, native, and interface behavior untouched. Later child
rollbacks retain legacy modules and update/restore baseline source facts before
attempting another extraction.

## Open Questions

- The final mapping for KG, causal, factor, and historical recommendation
  records remains deferred to their owning Dataset, Study, or Decision Support
  child; no ambiguity is resolved by this guard.
- The package-layout child must decide the exact distribution/console bridge
  and whether `_trade_native` is a separately installed extension before CMake
  linkage changes are designed.
