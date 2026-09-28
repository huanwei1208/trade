# Python Package and Web Layout Design

## Decision Summary

Adopt a staged authority-transfer model:

1. keep the distribution name `trade-py`;
2. add the installed Python namespace `trade` under `src/trade`;
3. retain `trade_py` and `trade_web` as compatibility roots;
4. move only modules whose semantic owner and interface adapter have already
   been approved and implemented;
5. make every compatibility dependency point from legacy to target;
6. reserve `_trade_native` for the optional native extension and use it only
   behind Context-owned adapter Ports;
7. move the Vite workspace independently from the ASGI package;
8. retire bridges only in `tests-and-legacy-cleanup` after measured use and
   contract evidence satisfy the exit criteria.

The directory layout is an output of semantic migrations, not the mechanism
that creates ownership.

## Design Quality Brief

### Requirements and acceptance

The change succeeds only when source, editable and clean-wheel environments
resolve the declared legacy and target imports from reviewed origins; each
migrated logical module has one implementation authority; root/console, ASGI,
HTTP/SSE/capability, Web asset, SDK/notebook and native contracts pass their
focused matrices; and every slice can be reversed without undoing later
unrelated slices or rolling back database or business artifacts. Python/ASGI
reversal uses a newly verified compensating immutable deployment generation
when the historical predecessor does not contain later accepted slices. A
green checkout-only import is not acceptance, and no requirement authorizes
movement before its semantic owner child is implemented.

### Ownership and boundaries

Package/build configuration owns discovery and installed artifacts; the
architecture guard owns module-authority evidence; Contexts own business
behavior and repositories; Interfaces own CLI/HTTP/SDK adapters; Bootstrap owns
concrete runtime construction and shutdown; `web/` owns frontend source/build;
and `engine/` plus Context native adapters own optional C++ calculation. Legacy
roots contain explicit compatibility modules only after an authority transfer
and never become a second implementation owner.

### Data and state invariants

Runtime business data and durable data contracts remain untouched. Authority
generations are immutable, one logical module has one implementation owner,
compatibility dependencies point legacy-to-target only, optional native
unavailability remains explicit, unknown bridge use blocks retirement, and
rollback retains all databases and immutable business artifacts. Evidence uses
UTC timestamps and content-bound package/Web/native identities.

### Contracts and compatibility

Distribution `trade-py`, existing `trade_py` imports, root `./trade`, installed
`trade-py`, `trade_web:create_app`, reviewed backend imports, HTTP route and
OpenAPI state, payload/error/SSE/capability behavior, Web proxy/assets/deep
links, SDK/notebook semantics and component test runners remain compatible.
New `trade` and `_trade_native` names are additive until an owning slice passes
all source/editable/wheel or differential evidence.

### Failure and recovery

A missing wheel member, checkout-dependent origin, duplicate module owner,
unknown consumer, ASGI/reload/child import failure, route/SSE/asset mismatch,
native differential mismatch, notebook prohibited access or residual process
cannot advance module authority. Finite validation deadlines terminate owned
process groups and report timeout separately from assertion, contract, cleanup
and tool failures. Durable activation phases reconcile crashes before or after
selector commit and service spawn. Python/ASGI rollback publishes a new
compensating generation derived from the current accepted generation when
necessary; Web and an independently owned native capability may select their
retained prior reference through a new forward revision. Every path reruns its
focused matrix.

### Performance and capacity

One authority slice is limited to 50 production modules and 500 consumer
records, reuses one sorted tree index per content digest, never randomly
samples or silently truncates, and enforces finite process-tree workers, heavy
jobs, RSS, disk and admission wait. It does not claim cross-invocation
admission without a reviewed shared lease. Cold/warm startup records p50/p95,
RSS and module count; Web caches bind one selected root; current and synthetic
ten-times scans have explicit wall/RSS gates. Package, native and Web checks
retain finite deadlines and verified process-tree cleanup.

### Observability and operations

Reports expose package generation, wheel/member digest, module origins and
authority, duplicate/reverse/unclassified consumers, CLI parity, ASGI/reload/
child status, route/OpenAPI/SSE/capability parity, Web manifest/assets, native
availability/differential state, notebook clean-run state, bridge age/use and
early-stop reason. Selector generation/revision, activation phase,
reconciliation, shutdown escalation and residual counts are visible without
arguments or payloads. Migration, execution, startup health, failure, rollback
and operator action remain orthogonal; absent or overflowed bridge telemetry
blocks retirement.

### Validation strategy

Validation combines static dependency/authority guards; source, editable and
clean-wheel import/console checks; old/new import-order and side-effect tests;
ASGI/reload/child-process and complete HTTP compatibility fixtures; Vite
typecheck/unit/build/bundle/asset smokes; SDK/notebook clean-environment tests;
native absent/present plus C++/Python differential fixtures; collection mapping;
compileall; repository quality gates; strict design checking; and six-role
implementation review. All data fixtures are temporary and offline.

### Persistent-write safety

The only durable write surface is an explicit deployment control root owned by
the layout controller; service managers write only their fenced process
receipts, while Contexts, interfaces, bridges and status are read-only. A
per-scope lock and expected generation/revision CAS publish canonical selector
JSON using same-directory stage, fsync, atomic replace and directory fsync.
Operation ID makes lost responses idempotent, revisions never decrease, and
`prepared`, `selector_committed`, `start_intent_recorded`, `process_started`
and `verified` receipts support crash reconciliation. A stable
deployment-unit identity and invocation token make lost spawn responses
adoptable or safely tear-downable. Corrupt or ambiguous state is retained and
blocks mutation; rollback writes a higher revision selecting a verified
compensating or independent prior generation, and referenced evidence is not
collected.

### Alternatives and trade-offs

An atomic rename is shorter but couples 1,531 import bindings, dynamic patch
strings, wheel membership, ASGI reload, child processes, Web output and native
ABI into one rollback. Permanent legacy roots preserve mixed ownership, while
mirrored trees create duplicate modules and side effects. Staged authority
transfer adds temporary bridge maintenance and may require a new forward-built
deployment generation for non-LIFO reversal. It is the only option that
follows semantic owners, proves installed behavior and reverses one logical
slice without silently undoing later accepted slices.

### Rollout and rollback

This parent freezes prerequisites and consumers and implements only dual-root
packaging proof, source authority/index guards, schemas and read-only status.
A mandatory selector-control child precedes activation, and every native,
owner-module, SDK/notebook, ASGI, frontend-default and test-topology transfer
has its own frozen manifest and strict approval. No global switch activates all
roots. Each slice keeps the old implementation material available for a
compensating generation; independently selected Web and native capability
references retain their prior generation. Cleanup waits at least 30 days,
requires known zero supported use, and belongs to `tests-and-legacy-cleanup`.

## Current-State Audit

The audit was source-only. It read Git-tracked source, configuration and tests;
it did not open a database, parquet file, provider connection or real data root.

### Python distribution and import roots

`pyproject.toml:1-60` names the distribution `trade-py`, exposes only the
`trade-py = trade_py.cli.main:main` console script and discovers only
`trade_py*` and `scripts*`. Ruff considers `trade_py` and `trade_web`
first-party, while BasedPyright includes `trade_py`, `trade_web/backend` and
`tests` (`pyproject.toml:66-93`).

The tracked source inventory on 2026-07-27 is:

| Root | Tracked paths | Relevant detail |
|---|---:|---|
| `trade_py/` | 334 | 318 Python files |
| `trade_web/backend/` | 18 Python files | ASGI, BFF, runtime and capability code |
| `trade_web/frontend/` | 129 | React/Vite application and tool configuration |
| `tests/` | 94 paths | 91 Python files |
| `scripts/` | 4 | package marker, backup and two migrations |
| `research/` | 2 | paired BTC notebook files |
| `_bmad-output/` | 6 | historical planning material |
| `engine/` | 185 | C++, CMake, tests and vendor metadata |

A tracked-source scan finds 347 Python files containing `trade_py` import or
attribute references and 1,531 matching lines. These include dynamic imports,
`sys.modules` fixtures and string-valued `monkeypatch` targets, so ordinary
static import replacement is not a complete migration.

The root facade calls `python -m trade_py.cli.main` for help and all Python
domains (`trade:6-81`, `trade:175-220`). The CLI dynamically imports
`trade_py.cli.<domain>` (`trade_py/cli/main.py:90-92`). Direct execution also
rewrites `sys.path` based on the literal `/trade_py/cli` suffix
(`trade_py/cli/main.py:22-26`).

### Native namespace collision

`trade_py/__init__.py:6-20` imports `trade_py` while already initializing that
same package and treats the result as the C++ extension. CMake separately names
the nanobind target `trade_py` (`engine/cmake/python_bindings.cmake:11-22`).
The package and extension therefore compete for one import name, and the
current probe cannot prove that native code was loaded.

The engine binding source paths referenced by CMake are not tracked in this
worktree. That is an implementation blocker, not permission to invent or
regenerate bindings. The native slice must first reconcile the target sources,
the nanobind module initializer name, built artifact name and wheel contents.

### ASGI, Web assets and process imports

`trade_web/__init__.py` and `trade_web/backend/__init__.py` re-export
`create_app` and `InferenceService`. `trade_py/cli/web.py:148-155` starts
Uvicorn from the string `trade_web:create_app`, including reload mode. Runtime
commands spawn the string module
`trade_web.backend.runtime.command_child`
(`trade_web/backend/runtime/commands.py:277-294`). A source scan identifies 17
non-document files with `trade_web/backend` or `trade_web/frontend` path
dependencies.

The Web CLI computes the frontend root from its own location, may run `npm
build`, sets `TRADE_WEB_DIST`, and defaults to
`trade_web/frontend/dist` (`trade_py/cli/web.py:101-142`). The FastAPI factory
independently computes the same legacy default, mounts `/assets`, retains an
optional `/static` fallback and serves `index.html` for `/` and non-API SPA
paths (`trade_web/backend/app.py:1384-1403`, `trade_web/backend/app.py:3771-3779`).

The Vite project has local relative TypeScript project references and a build
that runs TypeScript, Vite and a bundle check
(`trade_web/frontend/package.json:6-17`). Its development server exposes the
existing `/api` and `/predict` proxy routes. Both point to port 8080
(`trade_web/frontend/vite.config.ts:9-15`). Moving it changes the tool working
directory and output location even if source code is unchanged.

### Runtime lifecycle coupling

The Web launcher installs a Ctrl+C watchdog, supplies Uvicorn's graceful
shutdown timeout and schedules forced termination when non-daemon threads
remain (`trade_py/cli/web.py:57-89`, `trade_py/cli/web.py:146-166`).
FastAPI lifespan owns `WebResourceContainer.start/stop`
(`trade_web/backend/app.py:191-214`). The container drains command admission,
EventBus admission, commands, bus and DB in order against a shared deadline
(`trade_web/backend/runtime/resources.py:188-360`).

This child does not alter those semantics. It prevents path movement from
creating a second lifecycle owner. Bootstrap migration remains owned by the
Platform/Bootstrap child, and the compatibility ASGI module delegates to that
single owner after it exists.

### Notebook, scripts and historical material

The BTC notebook searches parent directories for `trade_py` and mutates
`sys.path` before importing an internal Observatory SDK
(`research/notebooks/btc_h1_observatory.py:43-69`). This is not an installed SDK
contract and fails outside a repository checkout.

`scripts/backup.py` combines a Google Drive driver, snapshot behavior and
`TradeDB` access (`scripts/backup.py:1-24`). It is not a generic tool until its
Platform Backup and owner repository boundaries are separated.
`scripts/migrate_kline_consolidate.py` is a destructive data-layout migration
with direct Datasets/DB imports and parallel writes
(`scripts/migrate_kline_consolidate.py:1-31`). `scripts/migrate_paths.sh`
moves data directories, copies databases and instructs operators to delete old
roots (`scripts/migrate_paths.sh:1-48`). Neither migration is moved or invoked
by this child.

`_bmad-output` contains historical plans. The governed OpenSpec and actual code
remain authoritative; individual historical files require reference and
retention checks before removal.

### Tests and hidden consumers

Tests import both legacy roots, inject fake modules into `sys.modules`, patch
string module paths and assert lazy import sets. Web tests also import the
runtime child module by its current name. A passing test suite from the
repository root can therefore hide a broken wheel or a second module object.

The migration requires independent source, editable and clean-wheel
environments and explicit `sys.path`, `__spec__.origin`, module identity,
console, ASGI child-process and test-collection checks.

## Problems and Root Causes

1. **Filesystem location is used as composition metadata.** CLI, Web asset and
   notebook code derive behavior from `__file__` or repository search.
2. **Legacy names mix public contracts with implementation ownership.**
   `trade_py` contains domain, data, DB, execution, CLI and developer tooling;
   `trade_web/backend` mixes BFF, composition and runtime ownership.
3. **There is no module authority protocol.** Copying a module can create two
   registries, two singleton instances or import-order-dependent behavior.
4. **Packaging is tested mainly from the checkout.** Repository-root imports
   do not prove editable or wheel behavior.
5. **Native and Python names collide.** The extension cannot be independently
   identified or isolated behind a Port.
6. **Web backend and frontend moves have different failure surfaces.** Treating
   them as one rename couples ASGI reload/process imports with Node build output
   and static serving.
7. **Mixed directories cannot be assigned by name.** Current `analysis`,
   `evaluation`, `observatory`, `scripts` and backend files span owners.
8. **Compatibility retirement has no measured exit condition.** A target path
   existing is not proof that all imports, deployment commands or notebooks
   stopped using a legacy path.

## Alternatives Considered

### A. Atomic root rename

Rename `trade_py` to `src/trade`, move `trade_web/frontend` to `web`, rewrite
all imports and update configuration in one branch.

Benefits: shortest apparent transition and no long-lived shims.

Costs: combines package metadata, 1,531 import bindings, monkeypatch strings,
ASGI reload, process children, frontend output, docs and native ABI. A partial
failure has no narrow rollback. It also moves modules before Context ownership
exists. Rejected.

### B. Permanent legacy roots

Leave `trade_py` and `trade_web` as the architecture and apply only import
guards.

Benefits: minimum packaging risk.

Costs: preserves mixed ownership and native collision, prevents the selected
Context Cell layout, and leaves interfaces/runtime composition interleaved.
Rejected as the target; retained only as rollback during migration.

### C. Namespace aliasing or mirrored trees

Expose both roots by adding package paths, aliasing entries in `sys.modules` or
copying implementation files.

Benefits: low initial import churn.

Costs: import order determines class/module identity, reload can execute side
effects twice, resources can have two owners, and wheel membership is
ambiguous. Rejected.

### D. Staged authority transfer

Add target packaging, select one implementation authority per logical module,
make old modules one-way forwarders, preserve external surfaces, and retire
only after measured evidence.

Benefits: owner-aligned, reversible and independently testable. It supports
source/editable/wheel parity and separates Python, ASGI, frontend and native
risks.

Costs: temporary compatibility code and a longer transition. Selected because
these costs are bounded and observable.

## Selected Architecture

### Target physical structure

```text
src/trade/
├── kernel/
├── capture/
├── datasets/
├── studies/
├── decision_support/
├── processes/
├── platform/
├── interfaces/
└── bootstrap/

web/
engine/
tests/
tools/
examples/
docs/
openspec/
config/
deployment/
```

The target tree is populated only by the owning children. This child owns
package/layout transition mechanics and compatibility evidence, not business
module classification.

### Code dependency graph

```mermaid
flowchart TD
    ROOT["./trade and trade-py"] --> LEGACYCLI["trade_py.cli compatibility"]
    LEGACYCLI --> TARGETCLI["trade.interfaces.cli"]
    ASGIOLD["trade_web:create_app compatibility"] --> HTTP["trade.interfaces.http"]
    HTTP --> USECASES["Context use cases and contracts"]
    HTTP --> PROC["trade.processes"]
    HTTP --> STATUS["trade.platform public status APIs"]
    BOOT["trade.bootstrap"] --> HTTP
    BOOT --> USECASES
    BOOT --> PROC
    BOOT --> ADAPTERS["Context adapters"]
    ADAPTERS --> NATIVE["_trade_native"]
    LEGACYPKG["legacy trade_py module"] --> TARGETMOD["one target trade module"]

    TARGETCLI -. forbidden .-> LEGACYCLI
    TARGETMOD -. forbidden .-> LEGACYPKG
    USECASES -. forbidden .-> NATIVE
```

### Package and native ADR

| Decision | Selected value | Reason |
|---|---|---|
| Distribution | `trade-py` during compatibility window | avoids package-manager breakage |
| New import namespace | `trade` from `src/trade` | matches target architecture |
| Existing import namespace | `trade_py` retained as compatibility | 347 tracked Python consumers |
| Root command | `./trade` retained | stable user facade |
| Console command | `trade-py` retained | existing installed contract |
| Future additional console alias | deferred to `cli-http-sdk-compatibility` | avoid unreviewed public command |
| Native module | `_trade_native` | avoids package collision and signals private adapter API |
| ASGI compatibility | `trade_web:create_app` retained | preserves Uvicorn/deployment/reload string |
| Frontend target | `web/` | independent product workspace |
| Versioning | one distribution version plus compatibility manifest generation | avoids split-package skew |

No target `trade` package may extend its `__path__` into `trade_py`, and no
legacy package may use a broad module-level `__getattr__` or `sys.modules`
alias to conceal unresolved imports. Forwarders are explicit per module and
export.

### Module authority state machine

Each logical module has a migration record with:

```text
logical_module
source_module
target_module
semantic_owner
contract_generation
authority
compatibility_direction
consumer_inventory_ref
source_digest
target_digest
activation_plan_ref
migration_evidence_ref
bridge_coverage_ref
rollback_target
retirement_deadline
selector_scope
selector_revision
selector_fence
operation_id
state
```

```mermaid
stateDiagram-v2
    [*] --> inventoried
    inventoried --> prepared: owner and contracts approved
    prepared --> shadow_verified: target import and parity pass
    shadow_verified --> legacy_forwarding: old module delegates to target
    legacy_forwarding --> target_authoritative: all production callers select target
    target_authoritative --> retireable: usage and window gates pass
    shadow_verified --> prepared: parity failure
    legacy_forwarding --> shadow_verified: runtime or contract mismatch
    target_authoritative --> legacy_forwarding: rollback selector
    retireable --> [*]: cleanup child removes bridge
```

At every non-inventory state:

- exactly one implementation is authoritative;
- forwarders contain no mutable registry, singleton, handler registration,
  background worker, repository, provider call or duplicated side effect;
- importing old then new, new then old and both concurrently yields the same
  public object identity where identity is contractual;
- unsupported private imports fail explicitly instead of falling through to a
  second implementation;
- a migration record cannot advance when its consumer inventory is incomplete,
  stale or changed after validation;
- activation and rollback consume one immutable evidence generation rather than
  an uncorrelated set of successful command logs.

### Consumer inventory identity and freshness

`ConsumerInventoryRef` binds:

- repository commit and tree digest;
- scanner name, version and executable/source digest;
- included roots, explicit exclusions and selection-rules digest;
- UTC generation time and a 24-hour maximum activation age;
- production-module, consumer and unclassified-consumer counts;
- `complete`, `incomplete`, `tool_failed` or `over_budget` completeness state;
- sorted entry digest and full report digest.

Only `complete` is admissible. Any repository-tree, scanner, rules or scope
change invalidates the reference immediately; the UTC age bound is additional,
not a substitute for content identity. A failed scan is `tool_failed`, never an
empty inventory. More than 50 modules or 500 consumers is `over_budget` and
requires deterministic subdivision.

### Typed execution, migration and rollback state

Operational reports use independent axes:

```text
migration_state:
    inventoried | prepared | shadow_verified | legacy_forwarding |
    target_authoritative | retireable

execution_state:
    not_run | running | passed | failed | stopped

failure_class:
    none | unavailable_prerequisite | timeout | test_failure |
    contract_mismatch | tool_failure | capacity_refusal |
    process_cleanup_incomplete

rollback_state:
    not_required | ready | requested | running | succeeded |
    failed | unknown

startup_state:
    not_started | starting | started_healthy | started_degraded |
    failed | stopped

reconciliation_state:
    not_required | pending | adopted | absence_proved |
    fenced_teardown | required | failed

operator_action:
    none | wait | continue_validation | resume_reconciliation |
    retry_identical_invocation | repair_prerequisite | narrow_slice |
    execute_reviewed_rollback | investigate
```

Each report also carries the tool exit code when one exists, bounded failure
detail, `partial_evidence_ref`, active/prior generation identities, bounded
startup reason codes and degraded component identities. `retireable` is only a
migration state; `rolled_back` is represented by
`rollback_state=succeeded`; `started_degraded` means the process remains
available but is never reported healthy or fatal.

`reconciliation_state` is a closed read model, not an instruction to mutate
the selector or service manager:

| State | Required immutable evidence | Allowed reconciliation failure/action | Exit contribution |
|---|---|---|---|
| `not_required` | no unresolved phase/process/selector contradiction | no additional constraint; independent axes determine failure/action | none |
| `pending` | one internally consistent unfinished operation whose next recovery decision has not been recorded | `failure_class=none`, derived action `resume_reconciliation` | `1` |
| `adopted` | exactly one live deployment unit matches the durable intent, invocation token, generation, revision and fence | `failure_class=none`; reconciliation adds no operator action | none |
| `absence_proved` | a bounded service-manager receipt proves no matching deployment unit or descendant remains; any historical `process_started` is causally superseded by a terminal receipt for the same operation, token, generation, revision and fence | `failure_class=none`, derived action `retry_identical_invocation` | `1` |
| `fenced_teardown` | a teardown receipt binds the stale unit/fence, TERM/KILL outcome and zero residual process/thread counts | `failure_class=none`, `rollback_state=ready`, derived action `execute_reviewed_rollback` | `1` |
| `required` | valid evidence identifies a selector/process/fence contradiction, missed recovery deadline or ambiguous external result without claiming a recovery outcome | `failure_class` is `unavailable_prerequisite`, `timeout`, `contract_mismatch`, `tool_failure` or `process_cleanup_incomplete`; action is `repair_prerequisite` only for an unavailable prerequisite and otherwise `investigate` | `1` |
| `failed` | an immutable reconciliation-attempt receipt records a terminal unsuccessful outcome | the same non-`none` failure classes as `required`; action is `repair_prerequisite` only for an unavailable prerequisite and otherwise `investigate` | `1` |

`adopted` requires a matching `process_started` or `verified` phase receipt.
`absence_proved` rejects a matching live process and an unsuperseded
`process_started` receipt. It accepts a historical `process_started` only when
a causally later bounded terminal stop/absence receipt binds the exact same
operation, deployment unit, invocation token, generation, revision and fence
and proves zero live descendants.
`fenced_teardown` requires `startup_state=stopped`, a complete shutdown
receipt and zero residue; an incomplete cleanup is `required` or `failed`
instead. `required` and `failed` cannot be reported as `passed`,
`target_authoritative` or `retireable`. An invalid record, unknown enum,
missing required receipt or forbidden state product is not converted to
`required`: validation fails and `layout-status` exits `2`. None of the axes
can mask timeout, tool failure or contract mismatch. When reconciliation adds
no action, the independent execution, failure and rollback axes still select
their bounded action; contradictory action requirements are invalid rather
than resolved by undocumented precedence.

`LayoutStatusConstraintsV1` is the versioned, dependency-free legality and
derivation oracle. Every declared value is classified before aggregation:

| Axis | `healthy` values | `valid_attention` values |
|---|---|---|
| `migration_state` | `retireable` | `inventoried`, `prepared`, `shadow_verified`, `legacy_forwarding`, `target_authoritative` |
| `execution_state` | `passed` | `not_run`, `running`, `failed`, `stopped` |
| `failure_class` | `none` | every other declared failure class |
| `rollback_state` | `not_required`, `succeeded` | `ready`, `requested`, `running`, `failed`, `unknown` |
| `startup_state` | `started_healthy` | `not_started`, `starting`, `started_degraded`, `failed`, `stopped` |
| `reconciliation_state` | `not_required`, `adopted` | `pending`, `absence_proved`, `fenced_teardown`, `required`, `failed` |

An unknown value or a failed receipt/cross-axis predicate is `invalid`, not
attention. Reconciliation-specific allowed products are:

| Reconciliation | Allowed migration | Allowed execution | Allowed rollback | Allowed startup |
|---|---|---|---|---|
| `not_required` | any declared value subject to generic predicates | any declared value subject to generic predicates | any declared value subject to generic predicates | any declared value subject to generic predicates |
| `pending` | `inventoried`, `prepared`, `shadow_verified` | `not_run`, `running`, `stopped` | `not_required` | `not_started`, `starting`, `started_healthy`, `started_degraded`, `stopped` |
| `adopted` | `prepared`, `shadow_verified`, `legacy_forwarding`, `target_authoritative` | `running`, `passed` | `not_required` | `started_healthy`, `started_degraded` |
| `absence_proved` | `inventoried`, `prepared`, `shadow_verified` | `not_run`, `stopped` | `not_required` | `not_started`, `stopped` |
| `fenced_teardown` | `prepared`, `shadow_verified` | `stopped` | `ready` | `stopped` |
| `required`, `failed` | `inventoried`, `prepared`, `shadow_verified` | `failed`, `stopped` | `not_required`, `ready`, `requested`, `running`, `failed`, `unknown` | any declared value |

`pending`, `adopted`, `absence_proved` and `fenced_teardown` require
`failure_class=none`; `required` and `failed` require one of their listed
non-`none` failure classes. Generic predicates additionally require
`execution_state=passed` to use `failure_class=none`; a non-`none` failure
cannot coexist with `passed`; and `target_authoritative` or `retireable`
requires `execution_state=passed`, `failure_class=none`,
`rollback_state=not_required` and reconciliation `not_required` or `adopted`.
The oracle validates receipt predicates before classifying axes. A product of
declared values that satisfies these generic predicates and the row for its
reconciliation state is valid; the oracle has no additional implementation-
local allow/deny rules.

Exit aggregation is total and order-independent: any `invalid` result returns
`2`; otherwise any `valid_attention` value returns `1`; otherwise all values
are `healthy` and the result is `0`. `operator_action` is derived, never chosen
freely. The first matching row in this explicit priority table is the only
legal action:

1. reconciliation `required`/`failed`: `repair_prerequisite` for
   `unavailable_prerequisite`, otherwise `investigate`;
2. `fenced_teardown`: `execute_reviewed_rollback`;
3. `absence_proved`: `retry_identical_invocation`;
4. `pending`: `resume_reconciliation`;
5. `failure_class=unavailable_prerequisite`: `repair_prerequisite`;
6. `failure_class=capacity_refusal`: `narrow_slice`;
7. any other non-`none` failure, rollback `failed`/`unknown`, or startup
   `started_degraded`/`failed`/`stopped`: `investigate`;
8. rollback `ready`: `execute_reviewed_rollback`;
9. rollback `requested`/`running`, execution `running` or startup `starting`:
   `wait`;
10. any remaining attention value: `continue_validation`;
11. all-healthy: `none`.

A supplied action that differs from this derivation is invalid. The rollback
action refers only to the scope-specific reviewed `LayoutActivationPlanV1`;
it never means “select a historical generation.” For `python_deployment` with
later accepted slices, the reviewed rollback target must be a newly verified
current-composition successor. A historical predecessor target in that case
is an invalid product and returns `2`.

### Activation and selector contract

Every slice produces an immutable `LayoutActivationPlanV1` before cutover. It
names the logical migration slice, current and target deployment generation,
closed selector scope, exact selector mechanism, precedence, owner-adapter
activation and rollback command identities, immutable input refs, operator,
deadline and post-action checks. The plan also binds an `operation_id`,
expected selector revision, expected generation, current
composition-manifest digest, desired slice delta and the digest of every
command argv; it never embeds a shell string. After the plan digest is known,
`PreparedEvidenceRef` binds that plan, operation, inputs and intended target;
it is not embedded back into the plan and is not the final
`MigrationEvidenceRef`. Logical module and ASGI slices are not independent
runtime selectors. The closed selector scopes and mechanisms are:

| Scope | Selector and precedence | Atomic activation and rollback |
|---|---|---|
| `python_deployment` | exact immutable virtualenv or container generation containing the reviewed wheel, module-authority manifest and ASGI factory; no moving package specifier | build and verify a fresh generation, atomically switch and restart; rollback may select the exact predecessor only when no later accepted delta exists, otherwise it builds a fresh compensating generation from the current composition with only the failed module/ASGI delta reversed |
| Web assets | `--web-dist` > `TRADE_WEB_DIST` > reviewed generation default | select an immutable `WebBuildRef` directory before process start; rollback selects the retained prior directory and restarts without changing backend generation |
| typed native capability | only a finite Bootstrap-owned Context adapter capability selector with an exact `_trade_native` artifact; otherwise native is part of `python_deployment` | activate only the reviewed adapter/artifact pair; an independent capability may select its prior value, while a bundled artifact rollback uses a compensating Python generation |

`python_deployment`, `web_build` and an explicitly reviewed finite
`native_capability:<owner>` are the only scope classes; arbitrary strings are
rejected. In-place package replacement, a `latest` path, mutable symlink
without a generation compare-and-swap, and one flag switching all scopes are
forbidden.
An operator confirms the scope, expected current generation and expected
revision. The only mutating selector API is:

```text
CAS(
    scope,
    expected_generation,
    expected_revision,
    target_generation,
    operation_id,
    plan_digest,
    prepared_evidence_ref,
) -> SelectorRef(new_revision)
```

The operation is linearizable for one closed scope and allocates exactly
`new_revision = expected_revision + 1`. A stale generation or revision fails
without mutation. Repeating the same `operation_id` and input digest returns
the previously committed `SelectorRef`; reusing an operation ID with different
inputs is a conflict. Revisions never decrease or repeat. Rollback is a new
forward revision. For a non-LIFO Python/ASGI reversal it selects a newly built
compensating generation whose manifest proves that every later accepted slice
is unchanged and only the failed delta is reversed; selecting an arbitrary
historical full generation is forbidden. Every service-manager/startup reader
receives generation, revision, deployment-unit identity and invocation token
together and refuses to publish a start or verification receipt when its fence
is older than the current selector.

The post-action diagnostic must observe the requested generation, revision,
process receipt and evidence digest before the slice advances. These selector
rules govern deployment cutover. They do not change the current
local-development `trade web --build` and source-newer auto-build behavior in
this layout child; that behavior remains a compatibility contract until a
separate Web developer-workflow change versions it. Deployment activation never
uses that mutable local build path as `WebBuildRef` evidence.

### Deployment layout control store

The mutable selector is deployment control state, not a CI report. A mandatory
implementation child owns a policy-free `LayoutSelectorStore` port and the
first POSIX adapter under `tools/layout_control/`; application Contexts and
compatibility modules cannot write it. The store accepts only closed scope
identities and opaque generation/plan/evidence digests. It owns persistence,
journaling, CAS and retention mechanics only; it cannot import application
packages or interpret module, ASGI, Web, native or business policy.
Slice-specific planning, activation, verification and compensation belong to
typed owner adapters in deployment/package generation, Bootstrap/ASGI, Web
build deployment or the owning Context native adapter, and those adapters
depend on the store port, never the reverse. Mutation requires an explicitly
configured absolute deployment-state root outside the repository,
business-data root and package generation. There is no guessed production
default. The POSIX adapter is admissible only when every controller and service
manager for that scope uses the same filesystem with documented linearizable
`flock` and atomic-rename semantics; otherwise a later deployment-specific
adapter must provide the same contract.

The root contains bounded, versioned state:

```text
layout-control/v1/
├── selectors/<scope>.json
├── locks/<scope>.lock
├── operations/<scope>/<operation_id>/
│   ├── plan.json
│   └── receipts/<sequence>-<phase>.json
├── processes/<scope>/<revision>/<instance_id>.json
└── evidence/<digest>.json
```

`selectors/<scope>.json` is the sole current-selector authority and binds
scope, generation, monotonic revision/fence, operation ID, plan digest,
`PreparedEvidenceRef` and canonical payload digest. `plan.json`, phase
receipts, process receipts and final evidence are immutable and content/digest
checked.
Only the policy-free deployment layout controller writes selectors and
operation receipts; a typed service-manager adapter writes a bounded
start-intent/process-start/stop receipt for its own instance; `layout-status`
is read-only. Root/directories are owner-only
(`0700`), records are `0600`, symlinks/non-regular files and path traversal are
rejected, and IDs and JSON size are bounded before path construction.

Selector CAS takes one exclusive per-scope lock, validates the complete
predecessor, stages canonical JSON in the destination directory, flushes and
fsyncs the file, atomically replaces the selector, and fsyncs the directory.
Readers either hold the shared scope lock or read one atomic complete selector
and verify its digest. A malformed, oversized, missing-field, wrong-owner or
inconsistent predecessor blocks all mutation; no mtime, PID absence or age
causes automatic repair.

Current selectors are retained indefinitely. Operation, process and evidence
records are retained for at least the longer of 90 days, the declared rollback
support window and every referencing bridge's compatibility window. No record
referenced by the current selector, retained prior generation, unresolved
operation, rollback plan or bridge can be collected. Retention is a separate
audited operation; it never advances or repairs a selector.

### Activation phases and crash reconciliation

Each operation appends exactly ordered durable receipts:

```text
prepared -> selector_committed -> start_intent_recorded ->
process_started -> verified
```

`prepared` proves the target artifact and immutable plan. `selector_committed`
binds the returned revision. Before invoking a service manager,
`start_intent_recorded` durably binds one stable deployment-unit identity and
invocation token to operation, generation, revision/fence and exact owner
adapter command digest. `process_started` binds the admitted OS/service
instance to that identity. `verified` binds post-start contract evidence. A
failure or rollback appends a typed receipt; it never rewrites an earlier
phase. Only `verified` may advance module/root authority.

Recovery is idempotent by `operation_id`:

- a crash before selector CAS leaves `prepared` and may retry the same CAS;
- a lost CAS response returns the already committed revision for the same
  operation and digest;
- a crash after CAS but before intent records the stable intent before any
  service-manager call;
- a lost service-manager response reconciles the stable unit identity and
  invocation token: it adopts one matching live instance, proves absence
  before retrying the identical invocation, or performs verified fenced
  teardown before rollback; it never starts a second owner from receipt
  absence alone;
- a crash after process start revalidates the current fence and resumes
  verification;
- a running process, receipt or evidence generation that disagrees with the
  current selector is fenced, reported as `reconciliation_required` and never
  repaired by overwriting the selector;
- a missed deadline, corrupt predecessor or ambiguous external service-manager
  result halts automatic progress and requires an explicit operator decision.

Startup reconciliation runs before a mutable layout command accepts another
operation for that scope. Concurrent activation, activation-versus-rollback,
delayed-controller, lost-selector-response, crash immediately before spawn,
spawn-success/response-loss, crash after receipt persistence and
crash-at-every-phase fixtures must prove one selector winner, one live runtime
owner, monotonic revisions and no stale verified process. The mutable
`layout-selector-control-plane` child owns those transitions. This parent only
validates and reports the resulting closed `reconciliation_state`; reading
`pending`, `required` or `failed` never adopts, retries, tears down, repairs or
rewrites state.

### Package discovery and installation model

The package backend must include both root-layout compatibility packages and
`src/trade` without installing test, data, notebook, build or frontend roots.
The implementation chooses the smallest setuptools configuration that proves
this in an isolated build. This design does not prescribe a fabricated syntax
before the build backend is exercised.

The proof matrix is:

| Environment | Repository CWD | Installation | Required result |
|---|---|---|---|
| source smoke | repository root | project tooling | legacy and target imports resolve intentionally |
| editable | outside repository | editable wheel | same public modules and console behavior |
| wheel | fresh temp venv outside repository | built wheel only | exact member allowlist, imports and console behavior |
| wheel without optional native | outside repository | pure Python artifact | target imports work; native capability is explicitly unavailable |
| wheel with native | outside repository | supported native artifact | `_trade_native` imports; no `trade_py` collision |

The wheel test records `distribution.version`, `module.__spec__.origin`,
`module.__file__`, public export identity and console entry points. Any origin
inside the checkout in the clean-wheel case is failure.

## Bounded Context Definitions

This child does not redefine the parent Contexts. It enforces that physical
movement follows these approved semantic owners:

| Target root | Admitted content | Required prerequisite |
|---|---|---|
| `kernel` | framework-free stable primitives | `kernel-and-public-contracts` |
| `capture` | Capture owner cell | `capture-boundary` |
| `datasets` | Dataset product owner cell | formal PIT plus `dataset-product-boundary` |
| `studies` | Study owner cell | Dataset contracts plus `study-boundary` |
| `decision_support` | decision-support owner cell | `decision-support-boundary` |
| `processes` | cross-Context process managers | Platform and Context contracts |
| `platform` | business-neutral technical implementations | Platform foundation |
| `interfaces` | CLI/HTTP/SDK/events/schedules/import adapters and BFF | interface compatibility child |
| `bootstrap` | concrete composition and lifecycle | Platform/Bootstrap foundation |

`Observatory`, Today, Research and BTC workspaces remain product surfaces in
Interfaces/Web. They are not target Context packages.

## Aggregate and State-Machine Definitions

No business aggregate is introduced. The only state machine owned by this
change is `ModuleMigration` above, plus:

### Web root transition

```text
legacy_active
→ target_built
→ dual_path_verified
→ target_default
→ legacy_retireable
```

The `TRADE_WEB_DIST` explicit override has higher precedence than either
default throughout the transition. A default changes only after both roots
produce matching route/asset smoke evidence. The old root remains a fallback
for the compatibility window.

### ASGI transition

```text
trade_web_authoritative
→ target_factory_shadow_verified
→ trade_web_forwarding
→ target_factory_authoritative
→ trade_web_retireable
```

The legacy module string remains importable through reload and child process
spawn until cleanup. Only Bootstrap owns runtime construction and shutdown.

### Native transition

```text
unavailable_or_legacy_collision
→ _trade_native_built
→ adapter_differential_verified
→ legacy_probe_deprecated
→ legacy_probe_retireable
```

Native unavailability is explicit and never causes a domain/use-case fallback
to a different algorithm without owner policy.

## Immutable Reference Model

Layout migration evidence uses content digests but does not create business
Dataset or Study references.

`PackageGenerationRef` identifies:

- distribution name and version;
- Python ABI/platform tag;
- wheel SHA-256;
- sorted wheel member digest;
- compatibility manifest digest;
- optional native artifact name and digest.

`WebBuildRef` identifies:

- lockfile digest;
- Node and package-manager versions;
- source generation;
- build manifest digest;
- `index.html` digest;
- sorted asset path/digest set.

`ModuleAuthorityRef` identifies:

- logical, source and target module;
- owner child;
- contract generation;
- implementation source digest;
- `ConsumerInventoryRef`;
- activation-plan digest.

`PreparedEvidenceRef` identifies one immutable pre-cutover attempt:

- schema version, migration/slice/attempt and idempotent operation identities;
- source commit/tree, policy and approved OpenSpec artifact digests;
- activation-plan digest, current composition digest, immutable input refs and
  intended target generation;
- expected selector generation/revision/fence, stable deployment-unit
  identity, invocation token and exact owner-adapter command digests;
- preparation observation and canonical record digest.

It contains no selector-commit, process-start, verification or terminal
outcome that does not yet exist. The selector and operation phases retain this
ref or the operation identity; they never contain a placeholder for a future
final digest.

`MigrationEvidenceRef` identifies one complete activation or rollback proof:

- schema version, migration ID, slice ID, attempt ID and idempotent operation
  ID;
- source commit/tree, policy digest and approved OpenSpec artifact digest;
- `ConsumerInventoryRef`, `ModuleAuthorityRef` and applicable
  `PackageGenerationRef`/`WebBuildRef`/native artifact refs;
- activation-plan digest and selector generations/revisions/fences observed
  before and after;
- the exact `PreparedEvidenceRef` from which the attempt began;
- ordered `prepared`, `selector_committed`, `start_intent_recorded`,
  `process_started` and `verified` receipts, with stable deployment-unit and
  invocation-token identity plus reconciliation outcome;
- toolchain versions, ordered command identities and monotonic deadline policy;
- per-check typed execution/failure/rollback status and partial-evidence refs;
- bounded shutdown stage, TERM/KILL escalation, residual process/thread counts
  and forced-exit receipt, without argv, stack or user payload;
- UTC started/finished observations and sorted report-entry digest;
- final evidence-manifest digest.

Authority may advance only from one `passed` evidence manifest whose observed
post-selector equals the plan target. A rollback produces a new
`MigrationEvidenceRef` linked to the failed attempt, current composition and
compensation or independent prior target; it does not rewrite the failed
evidence. The final ref is written only after `verified` or a terminal
failure/rollback outcome and is then linked by the authority record; no
selector, plan or earlier receipt is overwritten to insert it.

`BridgeUseCoverageRef` identifies:

- bridge and generation identity;
- declared supported-consumer set digest;
- deployment population/scope digest;
- coverage start/end and UTC report time;
- source-scan and supported-facade observation digests;
- collector version, health and last successful observation;
- `complete`, `partial`, `unavailable` or `stale` coverage state;
- last observed supported use and report digest.

These references are test/deployment evidence. They contain no mutable
`latest`, arbitrary path or real data identity.

`LayoutSelectorRef` identifies:

- store schema and scope;
- immutable selected generation;
- monotonic revision/fence;
- operation ID, plan digest and `PreparedEvidenceRef`;
- predecessor generation/revision;
- canonical selector payload digest.

It is the only mutable deployment authority, but each published ref value and
all supporting operation receipts are immutable audit facts.

## Code Dependency Graph

The parent dependency graph remains authoritative. Additional transition
rules are:

```text
legacy compatibility module → target public module
target module               ↛ legacy implementation
target module               ↛ trade_web
domain/use_cases            ↛ _trade_native
Context adapter             → own Port + _trade_native (optional)
trade_web compatibility     → trade.interfaces.http / trade.bootstrap
web                          → HTTP contracts only
notebook                    → trade.interfaces.sdk only
```

The architecture guard must reject:

- target-to-legacy imports;
- broad `sys.modules` aliasing between roots;
- target package `__path__` extension into legacy roots;
- native imports outside approved adapter paths;
- runtime/bootstrap construction in compatibility forwarders;
- direct frontend source coupling from Contexts;
- moved modules without an authority record.

## Runtime Command and Event Graph

Directory movement does not change business runtime flow. Entry surfaces retain
their current contracts and delegate after their owning child is ready:

```mermaid
flowchart LR
    CLI["./trade / trade-py"] --> C["CLI compatibility"]
    C --> CU["Interface command/query adapter"]
    HTTP["trade_web:create_app"] --> HC["HTTP compatibility"]
    HC --> BFF["Interface BFF / handler"]
    SCHED["Scheduler adapter"] --> CMD["Command envelope"]
    EVENT["Event adapter"] --> PM["Process Manager"]
    CU --> CMD
    BFF --> CMD
    BFF --> Q["Owner queries"]
    CMD --> PM
```

No compatibility module orchestrates a workflow or opens a cross-Context
transaction.

## Process Manager Design

No Process Manager is created by this child. The package migration itself is a
developer/deployment operation represented by immutable validation evidence,
not a runtime business Process.

Existing `refresh_dataset`, `close_evidence_gap`, `propagate_revision` and
other runtime processes remain under their owning child changes. Moving their
files later must not change process IDs, idempotency identities, event names or
durable state.

## Database and Table Ownership

This child creates no business database table and runs no business migration.
The deployment selector/evidence root is a new isolated control-plane store
owned by deployment layout tooling, not Platform Persistence or a business
Context. Physical business-data co-location and ownership ledgers remain as
specified by the parent.

Compatibility modules may not query another Context's table to preserve an old
import. A module that still depends on `TradeDB` or `db._conn` is not
owner-ready and remains at its old path until its owner repository migration.

## Artifact Ownership

The child creates build/test reports plus explicitly configured deployment
control records:

| Artifact | Owner | Durable runtime authority |
|---|---|---|
| wheel and member manifest | package build/CI | no |
| compatibility manifest | architecture/package gate | no |
| Web build manifest/assets | Web build | deployable static artifact only |
| import/console/route goldens | contract tests | no |
| native differential report | owning Context adapter tests | no |
| layout selector | deployment layout controller | yes, one current ref per scope |
| operation/process receipts | controller/service manager | immutable audit/recovery facts |
| migration evidence | deployment layout controller | immutable activation authority evidence |

No market-data, model, research, decision or catalog artifact moves.

## Query and Command Separation

- Package and authority checks are read-only source/build queries.
- The Web BFF remains query composition only.
- CLI/HTTP command delegation remains owned by
  `cli-http-sdk-compatibility` and Process Managers.
- Notebook target code uses SDK queries and explicit import commands only.
- Package compatibility imports do not execute provider, DB repair, dataset
  publication, Study execution or lifecycle pointer mutation.

## Interface Compatibility

### CLI and console

Preserve:

- root `./trade`;
- installed `trade-py`;
- canonical and hidden compatibility domains;
- parser choices, defaults, help shape, stdout/stderr and exit status;
- `./trade dev` frozen/no-sync behavior;
- C++ configure/build/test/CLI paths.

The console target changes only after source/editable/wheel parity tests prove
the root facade and installed console resolve the same authoritative CLI.
Legacy `trade_py.cli` modules remain explicit compatibility adapters until each
command's owning interface migration is complete.

### HTTP and ASGI

Preserve:

- `trade_web:create_app` and `trade_web.backend` imports during the window;
- route path, method, parameter, status, header, body, error and SSE fixtures;
- capability-off, enabled and registration-error modes;
- Uvicorn factory and reload operation;
- runtime child module spawn;
- startup/shutdown order and force-exit behavior.

The compatibility factory contains no second resource container. It imports
and calls the one Bootstrap factory selected by the current generation.

### SDK and Notebook

The target SDK is installed under `trade.interfaces.sdk` (or a narrower
approved public import selected by the interface child). The notebook:

- never mutates `sys.path`;
- never searches the repository;
- never imports adapters/repositories;
- never reads parquet directly;
- resolves one immutable generation through SDK queries and pins its
  snapshot/run/release/artifact refs for the complete handle lifetime;
- runs from a clean working directory against temporary fixtures.

The current notebook stays unchanged until that SDK exists.

### Schedules, events and imports

Scheduler/event/import adapter strings and command DTOs are public compatibility
facts. Their files move only after Platform/Process/Capture owners exist and
contract fixtures cover old/new module names. A scheduler fixture must also
freeze schedule ID/topic, registration order, cadence, wall time, timezone or
explicit process-local clock, trading-session guard, DST behavior,
misfire/catch-up policy and injected-clock behavior. File imports continue to
become `RequestCapture(mode="import")`; layout movement cannot introduce a
direct Dataset build path.

## Web Page Compatibility

The Vite move changes no product design. Today, Observatory, Assurance/Data
Quality, Research, Symbol Workspace, Signals/Candidates, Actions, Trust, Data
Ops, Operations and Settings retain:

- client route/deep-link behavior;
- API/SSE URLs;
- capability gates;
- request/response mapping;
- loading, empty, unavailable and error states;
- responsive, accessibility and BTC canvas goldens owned by their UI changes.

```mermaid
flowchart TD
    Browser --> V["web/ Vite build"]
    V --> API["unchanged /api, /predict and SSE paths"]
    API --> Compat["trade_web ASGI compatibility"]
    Compat --> Factory["trade.interfaces.http + trade.bootstrap"]
    Factory --> Queries["Context/Process/Platform query handles"]
```

Vite movement is accepted only if both direct dev proxy and FastAPI static-host
smokes pass. The explicit `--web-dist`/`TRADE_WEB_DIST` override remains the
rollback and deployment escape hatch.

## SDK and Notebook Compatibility

SDK wire DTOs, immutable-ref serialization and errors are shared by CLI/HTTP
and notebook consumers. `SnapshotHandle` resolves a selector at most once and
pins one immutable snapshot plus run/release/artifact lineage for all subsequent
context, bars, findings and research queries. A concurrent release change
cannot mix generations: the handle returns the pinned generation or an
explicit stale/conflict error. Notebook parity compares snapshot identity,
quality state, lifecycle state, bars/findings and research metadata against the
old SDK on a temporary immutable fixture. It does not compare mutable
current/latest data.

## C++ Integration Boundary

`engine/` stays at the repository root. C++ remains a calculation adapter, not
a business Context.

Before `_trade_native` is enabled:

1. locate or restore the actual binding sources referenced by CMake;
2. make the nanobind initializer and target/output name agree;
3. build the module in isolation;
4. install it into a clean environment;
5. prove that importing `trade` and `trade_py` does not import native code;
6. prove only approved `*/adapters/native/` modules import `_trade_native`;
7. run C++/Python differential fixtures for every exposed operation;
8. make missing/unsupported native capability explicit.

The old self-import probe may become a deprecation adapter only after clean
native proof. No domain or use case imports `_trade_native`.

## Directory Target and Per-Path Disposition

| Current path | Target | Gate before movement | Rollback |
|---|---|---|---|
| `trade_py/<owner-ready module>` | `src/trade/<context cell>` | owner child implemented; authority and import parity | restore old authority; keep target unused |
| `trade_py/cli` | `src/trade/interfaces/cli` plus `trade_py/cli` compat | interface baseline and command delegation | select legacy CLI modules |
| `trade_py/db` | owner repositories/adapters, Platform primitives only | per-table migration and DB-owner proof | retain legacy repository bridge |
| `trade_py/bus` | Platform events/scheduling plus owner handlers | Platform/process child | retain legacy EventBus selector |
| `trade_web/backend` | Interfaces HTTP/BFF plus Bootstrap and owner adapters | interface and Bootstrap children | keep `trade_web` authoritative |
| `trade_web/frontend` | `web/` | build/test/asset parity | point default and npm root back |
| `research/notebooks` | `examples/notebooks` | installed SDK and clean run | retain old notebook path |
| `scripts/backup.py` | Platform backup adapter/tool after split | backup owner contract | retain script and CLI import |
| `scripts/migrate_kline_consolidate.py` | owner migration tooling or archived docs | Dataset migration reconciliation evidence | do not move/run/delete |
| `scripts/migrate_paths.sh` | archived migration evidence or delete in cleanup | usage/reference/retention and safety review | retain inert script |
| `_bmad-output/*` | governed docs extraction or deletion | source-link and retained-decision ledger | restore file from Git |
| `tests/*` | gradual category/component ownership | production path stable first | keep existing collection path |
| `engine/` | unchanged root; adapter consumption from Contexts | native Port and differential tests | disable optional native adapter |

## File-by-File Classification Method

Every candidate file is classified by:

1. public imports, dynamic import strings and entrypoint consumers;
2. state/aggregate transitions it performs;
3. tables, artifact paths and transaction primitives it reads/writes;
4. provider, framework and native dependencies;
5. commands/events/queries it accepts or emits;
6. runtime resources and side effects created at import or call time;
7. semantic owner under the parent architecture;
8. target cell (`contracts`, `domain`, `use_cases`, `ports`, `adapters`);
9. compatibility obligation and retirement condition;
10. focused tests, failure states and rollback selector.
11. clock source/timezone and source, publication, observed, knowledge and
    partition-time semantics where event/news/schedule behavior exists;
12. lateness/finality, replay range and idempotency identity for event-like
    inputs.
13. plugin entry-point, MCP transport and remote-worker protocol ownership,
    capability/version state, registration identity and optional dependency
    direction where future interfaces exist.

Names alone are not evidence. Files with multiple owners are split by behavior
in their owning child; they are never copied whole into a target Context.
Scheduler, news, sentiment and external-event files remain `blocked` until
their owning child freezes these temporal semantics in a typed per-path
manifest. Plugin, MCP and remote-worker code remains absent or blocked until
`optional-interface-extension-boundary` freezes its Interface/Platform
contracts.

## Requirements and Acceptance

### Observable success criteria

1. Source, editable and clean-wheel environments import all declared legacy and
   target modules from expected origins.
2. Each migrated logical module has exactly one implementation authority and no
   duplicate import-time side effect.
3. `./trade` and `trade-py` retain command/help/exit parity.
4. `trade_web:create_app`, Uvicorn reload and runtime child process imports
   remain usable through the compatibility window.
5. Route/OpenAPI/error/SSE/capability fixtures remain compatible.
6. `web/` produces a valid manifest and assets; dev proxy and FastAPI-hosted SPA
   deep links work.
7. Notebook/SDK execution works outside the repository without `sys.path`
   mutation.
8. `_trade_native` is optional, isolated and differentially tested.
9. No moved file lacks a semantic owner or explicit tool/example/docs
   disposition.
10. Every slice can be reversed without database or artifact rollback and,
    for non-LIFO Python/ASGI reversal, without removing later accepted slices.
11. Selector revisions are monotonic and fenced, every activation is
    crash-recoverable by operation ID, and stale process receipts cannot
    verify a generation.
12. Compatibility startup/import, discovery, Web-build and validation-resource
    budgets pass against committed baselines.

### Non-goals and blocked acceptance

No acceptance criterion authorizes moving a business file before its owner
child is implemented. Passing import tests does not prove ownership. A clean
wheel that omits expected modules, contains duplicate implementation paths or
depends on repository CWD fails the change.

## Ownership and Boundaries

| Concern | Owner | Non-owner behavior |
|---|---|---|
| package discovery/version | package/build configuration | Contexts do not inspect checkout layout |
| module authority manifest/guard | architecture developer tooling | compatibility modules consume explicit records |
| selector persistence and operation journal mechanics | policy-free deployment layout controller | typed owner adapters depend on its finite-scope port; it imports no application policy |
| slice activation/verification/compensation | package deployment, Bootstrap/ASGI, Web deployment or Context native owner adapter | store/controller does not interpret module, HTTP, Web, native or business semantics |
| service start intent and process receipt | deployment service manager | controller validates stable unit/token/fence; application business code does not write it |
| business behavior | owning Context cell | package change does not rewrite semantics |
| CLI/HTTP/SDK adapters | Interfaces | Contexts expose contracts/use cases/queries |
| runtime construction/shutdown | Bootstrap with Platform primitives | CLI/ASGI compatibility delegates once |
| Web product source/build | `web/` | backend serves immutable build output |
| native implementation | `engine/` plus Context native adapter | domain/use cases depend on Port |
| compatibility bridge | legacy root, narrowly scoped | no new business behavior |
| bridge retirement | `tests-and-legacy-cleanup` | this child records criteria only |

## Data and State Invariants

- No runtime business data or schema changes.
- A module authority generation is immutable once validated.
- One logical module maps to exactly one implementation authority per
  generation.
- Compatibility direction is legacy to target only.
- Package, Web and native evidence binds exact content and environment.
- Selector revision/fence is strictly monotonic per scope; rollback never
  decrements it.
- One operation ID identifies one immutable plan/input digest and can be
  retried without a second transition.
- Only a process receipt matching the current scope, generation and revision
  can be verified.
- An unavailable optional native module is not represented as available.
- A missing Web build yields the existing explicit fallback/API behavior, not a
  fabricated healthy UI.
- Unknown legacy usage blocks retirement.
- Rollback never deletes immutable market/research/decision artifacts.
- All timestamps in evidence are UTC; monotonic time bounds local subprocess
  waits.

## Contracts and Compatibility

Compatibility matrices are generated from the parent baseline plus this
child's path consumers. Exact preserved contracts include distribution name,
legacy imports, root/console commands, ASGI module, HTTP registry, OpenAPI
status (including known failures), payload/error/SSE goldens, capability modes,
Web asset URLs, SDK values, CMake/native import name transition and test
collection.

Forwarders preserve public object semantics but are not required to preserve
private implementation filenames. Any consumer depending on a private module
must be inventoried and migrated explicitly; it cannot be hidden through broad
fallback imports.

## Failure and Recovery

| Failure | Required state | Recovery |
|---|---|---|
| target package omitted from wheel | no authority advance | revert package discovery and fix build |
| source/editable/wheel origin differs | `prepared` | reject checkout-dependent proof |
| duplicate module/registry/handler | no forwarding | remove duplicate; retain old authority |
| unknown private import consumer | no retirement | add consumer and owner migration |
| ASGI factory/reload import failure | legacy ASGI remains selected | restore old module string/default |
| runtime child cannot import | old process module retained | revert child module selector |
| route/OpenAPI/SSE mismatch | no ASGI cutover | retain legacy factory |
| Vite build or asset mismatch | legacy Web root/default | restore npm root and dist default |
| native build/source mismatch | native unavailable | disable adapter; retain Python path |
| notebook clean run failure | old notebook remains | do not move/remove path logic yet |
| shutdown/lifecycle mismatch | no Bootstrap forwarding | restore legacy owner and rerun runtime tests |
| crash before selector commit | prior selector remains authoritative | retry the same operation ID |
| crash after selector commit | current selector remains authoritative but unverified | reconcile phase/receipt, resume exact plan or issue forward-revision rollback |
| stale controller/process fence | no verification or overwrite | stop, report conflict and require fresh plan |
| corrupt selector/operation record | all mutation stopped | preserve state and investigate; never auto-repair |
| migration interrupted before authority verification | selector may have changed but module authority does not advance | recover from durable phases and retain incomplete evidence |

No exception is classified as a successful migration or killed compatibility
requirement. Tool failures and contract mismatches are reported separately.

## Performance and Capacity

This is not a throughput redesign. The migration guard and validation are
bounded:

- operate on Git-tracked source, not data/build/vendor trees;
- cap one authority slice to 50 production modules and 500 consumer records;
- build one immutable shared tree index per repository tree/scanner/rules digest
  and derive deterministic owner/module partitions from that index;
- process deterministic sorted paths; partition overflow fails with exact
  ownership groups rather than arbitrary file chunks;
- build one wheel per Python ABI/platform validation job;
- allow at most two isolated install environments concurrently;
- schedule at most two heavy build/browser/native jobs and
  `min(4, max(1, floor(available_cpu / 2)))` ordinary validation workers
  within one validation process tree; refuse after a two-minute queue deadline
  instead of oversubscribing. Cross-invocation/host-global admission requires
  a separately reviewed shared lease and is not claimed by this parent;
- cap aggregate validation RSS at the lower of 75% of detected runner memory
  and 8 GiB, and temporary output at 10 GiB; capacity refusal retains partial
  evidence and runs cleanup;
- bound every subprocess and terminate its process group on timeout;
- compare Web asset manifests by path/digest without loading all assets into
  memory;
- use a 5-minute per packaging smoke, 10-minute native build smoke and
  15-minute Web build/test smoke unless repository baseline evidence justifies
  a reviewed change;
- at 10x current module count, the shared-index benchmark must scan once, use
  no more than 10x baseline wall time plus 5 seconds and no more than 3x
  baseline peak RSS plus 64 MiB; individual over-50/500 authority partitions
  still fail closed into smaller slices.

Before a compatibility slice, one committed baseline JSON is produced on the
same runner image, Python build and dependency lock. Cold cases run in 15 fresh
processes; warm callable cases run 30 times after five discarded warmups. The
matrix covers root and installed CLI help, one selected-domain help,
`import trade_web`, `import trade`, and factory construction without lifespan
or business-data access. It records p50/p95 monotonic duration, peak RSS and
sorted imported-module count. A candidate fails when:

- p95 exceeds the greater of 120% of baseline or baseline plus 50 ms;
- peak RSS exceeds the greater of 115% of baseline or baseline plus 16 MiB;
- imported-module count exceeds the greater of 110% of baseline or baseline
  plus 10 modules; or
- any one-hop bridge causes a second implementation import or the cumulative
  bridge count/cost is absent from evidence.

Thresholds may change only in the concrete digest-bound child with measured
variance and reviewer approval; a noisy result is retried as a complete matrix,
never by dropping a failed sample.

For Web development compatibility, root precedence selects exactly one source
root before recursive stat or build checks. A build cache key binds selected
root identity, lockfile, package manager/Node/Vite versions and sorted source
digest; it never combines legacy and target roots. Cache records are immutable,
retain at most three generations and 2 GiB, and use LRU eviction only for
unselected/unreferenced builds. The no-change launcher check must remain within
the greater of 120% of baseline or baseline plus 500 ms; cold build remains
within 15 minutes; incremental build must remain within the greater of 125% of
baseline or baseline plus 5 seconds. Cache-key, invalidation, no-change, cold,
incremental and stale-output fixtures are gates for the Web child.

## Observability and Operations

The package/build authority guard owns immutable evidence-manifest generation.
Owner Interface adapters expose bounded compatibility-use observations only at
already-owned CLI, ASGI, SDK, scheduler, event and import facades; compatibility
module import itself performs no network, file or metric I/O. The deployment
observability adapter is not currently repository-grounded. Therefore dynamic
bridge coverage is initially `unavailable`, and retirement remains blocked.
The mandatory `layout-bridge-observability` prerequisite child must name the
actual producer module, nonblocking queue/exporter, collector, deployment
population source, retention owner and read adapter before any observation can
be classified `complete`. The cleanup child consumes `BridgeUseCoverageRef`; it
does not infer zero from missing observations.

That prerequisite uses closed consumer classes
`cli|http|sdk|scheduler|event|import` and outcomes
`used|delegation_failed|unsupported`; arbitrary values are rejected. It
aggregates at least one minute locally, retains no arguments or payloads,
permits at most 512 active bridges, eight retained generations and 20,000
active series, limits each process to 1,000 observation increments per second,
and retains aggregate evidence for at least 90 days. Any overflow, drop,
unknown class, missing interval or unhealthy collector increments a bounded
overflow counter, changes coverage to `partial`, and blocks retirement without
blocking the request/import path.

No new business database, artifact catalog or shared runtime facade is used for
these records. If a deployment has no approved observability adapter, bridge
coverage is `unavailable` and retirement is blocked. Supported consumers that
cannot be observed dynamically remain in the explicit consumer inventory until
their removal is source/deployment-proven.

The additive read-only command `./trade dev layout-status [--json]` reads only
the selected deployment evidence files and source manifests. It performs no
provider, DB, parquet, repair, build, activation or rollback operation. Human
and JSON output expose:

- at most 32 explicitly referenced regular records, with reference depth at
  most eight, each canonical JSON record at most 256 KiB and aggregate input
  at most 4 MiB;
- a five-second monotonic read/validation deadline. The command never walks a
  directory, scans repository history, enumerates `/proc`/service-manager
  state, follows symlinks or probes live processes. Any limit breach is an
  invalid/unavailable tool result with exit `2`;

- package generation, wheel digest and member count;
- legacy/target module origins and selected authority;
- source commit/tree, inventory scanner/rules identities, completeness and age;
- migration evidence and activation-plan digests;
- missing, duplicate, reverse dependency and unclassified consumers;
- root/console command parity;
- ASGI/reload/child import status;
- route/OpenAPI/SSE/capability parity;
- Web build manifest and missing asset count;
- native capability/build/differential state;
- notebook clean-run state;
- compatibility bridge owner, population coverage, age, last observed use and
  deadline;
- independent migration, execution, failure and rollback states;
- selector revision/fence, activation phase and reconciliation state;
- shutdown stage, signal escalation, residual process/thread counts and
  forced-exit receipt;
- tool exit code, operator action and partial-evidence ref;
- whether validation or rollout stopped early and why.

JSON uses `LayoutStatusConstraintsV1` and stable exit semantics: unknown
values, forbidden state products, failed receipt predicates, a mismatched
derived action or unavailable/over-budget input return `2`; otherwise any
`valid_attention` value returns `1`; otherwise every value is `healthy` and
the report returns `0`. `adopted` can therefore return `0` only when every
other axis is healthy and internally consistent. Human and JSON output carry
the same enum values, uniquely derived action and exit result. Empty inventory
is success only when a complete report binds an explicitly empty expected set.

## Validation Strategy

### Architecture and package

- static dependency and module-authority guards;
- deployment selector store schema, permission, atomicity, fencing,
  idempotency, corruption and retention tests in a temporary explicit root;
- source/editable/clean-wheel imports;
- wheel member allowlist and origin checks;
- old/new import-order and concurrency fixtures;
- no import-time DB/provider/thread/native side effects;
- console/root command snapshots.

### HTTP and Web

- ASGI factory/reload and runtime child subprocess smoke;
- parent death before and after child spawn, descendants that ignore TERM,
  process-group KILL escalation, reload-supervisor teardown, cleanup-failure
  classification and zero residual PID fixtures;
- complete route registry and OpenAPI failure/success baseline;
- payload/error/SSE/capability goldens;
- Vite typecheck, unit, build and bundle checks;
- unique-root build-cache key/invalidation and no-change/cold/incremental
  performance gates;
- manifest/asset/root/SPA deep-link smoke;
- Playwright desktop/mobile checks remain owned by product UI changes.

### SDK, notebook and native

- clean installed SDK/notebook run using temporary immutable fixtures;
- a release-race fixture proving one pinned snapshot/run/release/artifact
  generation across context, bars, findings and research queries or an explicit
  stale/conflict failure;
- semantic old/new assertions for snapshot ID, run/release lineage, artifact
  hashes, knowledge mode/cut, revision policy, quality and lifecycle state in
  addition to shape goldens;
- prohibited repo scan/path/adapters checks with an explicitly injected
  temporary root; unset roots and DB/parquet/socket/provider access outside it
  fail before open;
- native absent/present import tests;
- CMake build/ctest and Context-owned C++/Python differential fixtures.

### Repository and delivery

- existing test collection count before/after every test-layout slice;
- scheduler temporal registration and event/news classification guards before
  those files can move;
- startup/import/RSS/module-count, shared-index current/10x and global-resource
  contention performance checks;
- `python -m compileall` for both package roots and tests;
- `./trade dev check --show-plan`, `./trade dev check`;
- focused frontend and C++ checks as applicable;
- `git diff --check`, clean artifact review and six-role implementation review.

Tests never access real data or the network.

## Testing Strategy

The eventual target test structure is:

```text
tests/
├── unit/
├── integration/
├── contract/
├── architecture/
├── golden/
├── e2e/
└── fixtures/
```

Reclassification is separate from production movement. Existing pytest node IDs
and collection remain stable until a dedicated test slice records old/new
mapping. Python, frontend and C++ tests stay with their appropriate component;
the target tree does not force all tests into one runner.

Required package/layout fixtures include:

- import dependency guard;
- module authority and duplicate side-effect fixture;
- CLI compatibility snapshot;
- OpenAPI and Web BFF contract snapshot;
- ASGI reload/child process fixture;
- Web manifest/asset/deep-link fixture;
- SDK/notebook clean-environment fixture;
- native absent/present and differential fixture;
- migration generation rollback fixture;
- bridge usage/retirement guard.

## Persistent-write safety

The only new durable write surface is the explicit deployment layout control
store. Policy-free `tools/layout_control` is the sole selector/operation writer
and owns no module, ASGI, Web, native or business policy; typed owner adapters
call its finite-scope port. The deployment service manager writes only its own
fenced start-intent/process receipts. Context, Interface, compatibility and
read-only status code cannot write this root. Every attempt is keyed by scope
plus operation ID and immutable plan digest.

Per-scope locks serialize complete predecessor validation and selector CAS.
Canonical bounded JSON is staged in the destination directory, flushed,
fsynced, atomically replaced and followed by directory fsync. Immutable
receipts use create-exclusive names and content-digest verification. A reader
observes one predecessor or successor selector and validates its digest and
revision; it cannot observe partial JSON.

Crash windows and reconciliation are specified by the durable activation
phases above. Corrupt, symlinked, oversized, inconsistent or ambiguous
predecessor state is preserved and blocks mutation. A partial operation never
advances module authority, and rollback allocates a new revision instead of
rewinding or deleting audit history. Temporary-root tests inject failure before
and after every write/sync/replace/restart/verification boundary and verify
selector digest, monotonic revision, process fencing and retained receipts.

The control root contains no business data and requires an explicit absolute
path. Backup verification copies the bounded selector/operation/evidence tree
to a temporary root, verifies every canonical digest and reference, and proves
that the current and retained prior generation can be diagnosed. Code rollback
does not delete or decrement durable selector state; decommission is a separate
reviewed deployment operation after all selectors and bridge references retire.

## Migration Phases

### Phase 0: prerequisites and frozen evidence

Consume the merged architecture baseline, approved package ADR and completed
owner/interface/Bootstrap prerequisites. Refresh consumer inventory. No move.

Exit: all candidate modules name an implemented owner and compatibility
contract; otherwise remain legacy.

### Phase 1: package discovery and authority guard

Prove dual-root source/editable/wheel installation and add deterministic
authority/forbidden-dependency checks, evidence schemas, shared tree index and
read-only diagnostics. Preserve all entrypoints. This phase neither writes a
deployment selector nor changes module/root authority.

Exit: wheel/member/origin/console matrix passes with no target business move.

### Phase 2: layout control-plane child

Implement the deployment selector store, linearizable revision-fenced CAS,
activation journal, service-manager process receipts, recovery reconciler,
retention and explicit operator commands under a separately reviewed child.

Exit: temporary deployment roots prove concurrent CAS, lost response, crash at
each phase, stale-process fencing, corrupt-state refusal, forward-revision
rollback and read-only status. No business slice is activated by this proof.

### Phase 3: native namespace isolation

Reconcile binding sources, build `_trade_native`, add adapter-only guard and
differential tests through its mandatory concrete child. Keep native optional.

Exit: no package collision; absent/present states explicit.

### Phase 4: owner-ready Python modules

For each bounded owner slice, first create a strict-approved child containing
its exact manifest, prerequisite SHAs, inventory, authority record, selectors,
rollback commands and focused topology. Then move that slice into `src/trade`,
update target-internal imports, replace old modules with explicit forwarders
and verify module authority.

Exit: one implementation authority, legacy snapshots pass, rollback tested.

### Phase 5: SDK and notebook

Expose the approved installed SDK and move the paired notebook to
`examples/notebooks` only after a clean external run, a pinned-generation race
test and semantic lineage parity.

Exit: no `sys.path`, repo scan, direct parquet, repository or adapter import.

### Phase 6: ASGI/backend

Through its mandatory concrete child, move only already-extracted HTTP/BFF and
Bootstrap components. Retain `trade_web:create_app` and runtime child
compatibility modules.

Exit: complete HTTP/ASGI/reload/lifecycle parity and one runtime owner.

### Phase 7: frontend

Through an independent child, move the Vite workspace to `web/`, update
tooling/default discovery and retain explicit old-root rollback. Default-root
activation is digest-bound independently from the physical move.

Exit: typecheck/unit/build/bundle/assets/dev proxy/FastAPI host pass.

### Phase 8: tools/examples/tests

Classify root scripts individually and migrate test categories without changing
business behavior or collection silently. Each topology mutation uses a
concrete child. Extract governed historical facts.

Exit: all moved paths have a non-cosmetic disposition.

### Phase 9: retirement

Owned by `tests-and-legacy-cleanup`. Remove a bridge only after its minimum
30-day compatibility window, zero observed supported use for the full window,
complete consumer scan, release-note/deprecation evidence and rollback drill.

## Observability

Package and layout rollout uses `MigrationEvidenceRef` and
`BridgeUseCoverageRef`, not runtime business metrics. Facade observations are
bounded to bridge/generation, supported-consumer class and outcome; they exclude
user data, command arguments, credentials, paths and stack traces. They use no
blocking external call on request or import paths. Collector health and
deployment-population coverage are part of the report. Any missing interval,
unknown deployment, failed collector or stale report produces non-complete
coverage and blocks retirement.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| duplicate module objects or singleton owners | P0 | explicit authority records and import-order/process tests |
| source checkout hides broken wheel | P0 | clean-wheel environment outside repository |
| concurrent selector writers or delayed controller | P0 | revision-fenced linearizable CAS and stale-reader refusal |
| crash between selector, restart and evidence | P0 | durable operation phases and startup reconciliation |
| corrupt selector or ambiguous process generation | P0 | fail closed, preserve state, explicit operator decision |
| ASGI reload/child string breaks | P0 | retain legacy strings and process smoke |
| second Bootstrap/shutdown owner | P0 | compatibility factory delegates only; lifecycle tests |
| native initializer/output mismatch | P0 | reconcile source/target/output before enablement |
| owner-unready file moved by directory | P0 | prerequisite and file classification gates |
| route/SSE/capability regression | P0 | complete frozen interface baseline and goldens |
| frontend built but assets not served | P1 | manifest, path, SPA and FastAPI host smoke |
| string monkeypatch/dynamic consumer missed | P1 | source inventory plus runtime import tests |
| old script accidentally executed after movement | P1 | no movement until owner/safety classification |
| SDK handle mixes moving generations | P1 | pin one immutable generation and race-test semantic lineage |
| compatibility degrades startup/CI cost | P1 | enforce p95/RSS/module/index/build/resource budgets |
| schedule/news time semantics drift | P1 | temporal classification and owner prerequisite before movement |
| telemetry cardinality or collector gap hides use | P1 | closed bounds; overflow/absence blocks retirement |
| bridge never retired | P2 | age/use/owner/deadline report and cleanup child |
| historical document removed prematurely | P2 | reference/provenance/retention ledger |

## Rollback

Rollback is generation-based and per logical slice:

1. stop advancing the affected migration record;
2. recover the operation journal and current selector generation/revision;
   if state is unambiguous, create a new rollback operation and execute the
   exact `LayoutActivationPlanV1` rollback for only the affected scope;
3. for a Python/ASGI slice, compare its predecessor composition to the current
   accepted composition. If later slices exist, build and validate a new
   immutable compensation generation from current with only the failed slice
   delta reversed; selecting a historical generation that removes later slices
   is forbidden;
4. restore a legacy forwarder as implementation only inside that reviewed
   compensation when it was the failed slice's prior authority. For Web select
   the prior `WebBuildRef`; for an independently selected typed native
   capability select its prior value; a native artifact bundled in Python uses
   compensation. Every rollback CAS increments revision and fences the failed
   generation;
5. restart the affected process generation and run `./trade dev layout-status
   --json` plus the scope-specific contract checks;
6. require observed selector generation/revision, process receipt, authority
   and digest to equal the rollback target; otherwise mark
   `rollback_state=failed`, halt rollout and escalate P0;
7. retain failed target files and both evidence manifests for diagnosis or
   revert the isolated commit;
8. do not alter databases or immutable business artifacts.

Rollback triggers include any duplicate owner, import-origin mismatch,
entrypoint/route/SSE/asset contract regression, lifecycle residue, native
differential mismatch or unknown consumer discovered after cutover.
The rollback matrix includes a non-LIFO fixture: after slices A, B and ASGI are
accepted in successive Python generations, reverting A produces a new
generation that preserves B and ASGI byte-for-byte and contract-for-contract.

## Child OpenSpec Changes

This change is already a child of `restructure-trade-architecture-v1`. Its
implementation consumes, rather than duplicates:

1. `architecture-guardrails-and-baselines`;
2. `kernel-and-public-contracts` package proof;
3. `platform-persistence-events-and-bootstrap-foundation`;
4. implemented Context owner changes;
5. `process-manager-boundary`;
6. `cli-http-sdk-compatibility`;
7. `btc-observation-analysis-ui-v1`.

This parent implementation is limited to additive package discovery proof,
read-only evidence vocabulary and validators, deterministic source
inventory/authority guards and read-only status. It may define immutable refs,
closed report axes and parser validation required by those readers. It may not
implement or semantically own selector CAS, mutable operation journals,
start-intent/service-manager protocols, reconciliation transitions, retention
commands or slice-specific activation/compensation plans. Those mutation
contracts are versioned only by `layout-selector-control-plane`. The following
ordered implementation children are mandatory, not conditional on PR size:

1. `layout-selector-control-plane`;
2. `native-module-isolation`;
3. one `owner-<name>-python-layout-slice` per bounded owner transfer;
4. `sdk-notebook-layout-compatibility`;
5. `http-bootstrap-layout-compatibility`;
6. `web-workspace-physical-layout`;
7. `web-workspace-default-activation`;
8. one `tool-example-test-layout-<scope>` per bounded topology mutation;
9. `optional-interface-extension-boundary` before plugin, MCP or remote-worker
   code or dependencies are admitted;
10. `layout-bridge-observability` before dynamic coverage may be complete.

Each child freezes its exact files/exports, source and prerequisite SHAs,
consumer/tree index, authority and deployment refs, selector revisions,
activation/rollback argv, performance baseline, focused tests and rollback
topology before code. It runs its own six-role review and strict approval. The
native, ASGI, frontend-default and test-topology children may not be folded
into an owner slice.

Final bridge removal stays in `tests-and-legacy-cleanup`.

## Rollout and Rollback

Rollout is off by default for each module/root until its shadow evidence passes.
There is no global flag that switches every package at once. Python modules and
ASGI share one immutable deployment selector; Web build and explicitly
reviewed typed native capability selectors remain independent. Logical
Python/ASGI slices are independently reversible through a new compensating
deployment generation, not by pretending they have independent runtime
selectors. Deployment first creates `LayoutActivationPlanV1` and a `prepared`
evidence ref in that acyclic order, verifies a canary/temporary immutable
generation, confirms expected selector generation and revision, commits one
revision-fenced CAS, records a durable start intent and matching process start,
verifies the post-start contracts, then creates the terminal
`MigrationEvidenceRef`, observes compatibility and only later permits cleanup.
A crash resumes by operation ID and deployment-unit identity before another
mutation is admitted.

The old root remains installed and importable for at least 30 days after target
authority for that contract, unless a later reviewed public-contract policy
sets a longer window. A LIFO failure may restore the exact predecessor; a
non-LIFO failure builds a compensating successor preserving later accepted
slices. No big-bang reverse import rewrite is required.

