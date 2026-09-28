## Why

The target architecture in `restructure-trade-architecture-v1` uses an
installed `src/trade` package and a top-level `web/` workspace, but the current
repository is still bound to its legacy locations:

- `pyproject.toml` discovers only `trade_py*` and `scripts*`, publishes the
  `trade-py` console entry from `trade_py.cli.main`, and configures Ruff and
  BasedPyright around the legacy roots.
- The root `./trade` facade invokes `trade_py.cli.main`; that CLI dynamically
  imports `trade_py.cli.<domain>`.
- There are 334 tracked paths under `trade_py` (318 Python files). A source
  scan finds 347 Python files with `trade_py` import or attribute bindings and
  1,531 matching import/attribute lines. Tests also bind module names through
  `sys.modules` and string-based `monkeypatch` targets.
- `trade_web/backend` is the ASGI package and runtime composition area, while
  `trade_web/frontend` is the Vite build root. The Web launcher derives both
  source and `dist` locations from its own legacy filesystem path, and Uvicorn
  imports `trade_web:create_app`.
- The CMake Python target is named `trade_py`, which collides with the Python
  package namespace and makes `trade_py.__init__` probe itself instead of an
  independently named native module.
- The tracked BTC notebook mutates `sys.path`; root scripts mix backup,
  destructive migration and package roles; historical `_bmad-output` material
  is not an implementation authority.

A directory rename or global import rewrite would combine package, runtime,
Web asset, native ABI and test changes into one irreversible cutover. It would
also move unresolved mixed-domain modules before their semantic owners exist.
This child therefore defines and implements a staged compatibility transition:
one authoritative module at a time, with old roots retained as one-way
forwarders until measured retirement conditions pass.

## What Changes

- Record a package/import/native ADR that keeps distribution name `trade-py`,
  preserves `./trade` and the existing `trade-py` console command, adds the
  installed import namespace `trade`, and reserves `_trade_native` for the
  optional C++ extension.
- Require source-tree, editable-install and clean-wheel proof for dual package
  discovery before any source move. The installed wheel, not repository
  `sys.path`, is the authority for package correctness.
- Introduce `src/trade` first as an additive package-authority foundation.
  A production module enters it only through a separately strict-approved,
  digest-bound implementation child whose manifest names exact files,
  consumers, owner prerequisite SHAs, selectors and rollback commands. A
  legacy `trade_py` module may become a thin one-way forwarding module only
  after old/new identity and import behavior are tested. The target package
  never imports a legacy implementation as an architectural dependency.
- Move the FastAPI backend only after its Context query/use-case and Bootstrap
  owners exist. Preserve `trade_web:create_app`, route registry, OpenAPI/error/
  SSE goldens and reload child importability through a compatibility module.
- Move `trade_web/frontend` to `web/` as an independent Vite-root slice.
  Preserve URLs, API proxies, build output semantics, manifest, asset serving,
  explicit `--web-dist`, capability gates and frontend tests.
- Rename the optional native extension to `_trade_native` before any target
  Context adapter consumes it. Domain/use-case code may use it only through an
  owner Port and native adapter; no direct native import is added.
- Replace notebook repository discovery and `sys.path` mutation with an
  installed SDK after that SDK exists. Classify each root script as a public
  CLI adapter, owner migration, deployment tool or retireable historical
  utility before movement.
- Gradually classify tests as unit, integration, contract, architecture,
  golden or e2e without changing collection semantics in the same slice as a
  production module move.
- Treat `_bmad-output` as historical input only. Extract still-valid decisions
  into governed docs/OpenSpec, then retire individual files only after link,
  provenance and retention checks.
- Add package-authority, forbidden reverse-forwarding, wheel-membership,
  console parity, ASGI/reload, route/OpenAPI/SSE, Web asset, SDK/notebook,
  native-isolation and test-collection guards.
- Define a deployment-owned layout control store for real authority changes.
  It uses a per-scope monotonic revision/fencing token, linearizable
  compare-and-set, idempotent operation records, immutable evidence and
  crash reconciliation. The initial package foundation may add schemas,
  validators and read-only status, but it does not activate a generation;
  the mutable controller is delivered by its own strict-approved child.
- Establish measured startup/import, source-inventory, Web-build, telemetry
  cardinality and validation-resource budgets so compatibility cannot hide
  unbounded operational cost.

## Non-Goals

- No big-bang rename of `trade_py`, `trade_web` or all tests.
- No business-logic rewrite, behavior change, route redesign, command rename,
  database migration, artifact migration, provider access or real-data read.
- No claim that a directory move establishes a Context, table or transaction
  owner.
- No new global `common`, `shared`, `utils`, `helpers`, `services` or package
  facade that re-exports the whole system.
- No removal of legacy imports, root scripts, notebooks, generated planning
  evidence or Web paths merely because a target directory exists.
- No expansion or algorithm rewrite of the C++ engine.
- No duplication of Bootstrap/runtime ownership. The existing shutdown
  safeguards and `WebResourceContainer` remain behaviorally unchanged until
  the Platform/Bootstrap owner child explicitly migrates them.
- No implementation before this child has six-role review and current strict
  approval.
- No package/module, native, ASGI/Bootstrap, frontend-default or test-topology
  authority transfer under this umbrella digest. Every concrete transfer has
  its own OpenSpec child, frozen manifest, six-role review and strict approval.

## Alternatives Considered

1. **Rename all roots and rewrite imports in one change.** This is mechanically
   direct but couples 1,531 import bindings, dynamic import strings, monkeypatch
   paths, ASGI reload, wheel contents, CMake output and Web assets. Rollback
   would require reverting unrelated owner migrations. Rejected.
2. **Keep the current layout permanently.** This minimizes immediate work but
   preserves mixed ownership, the native namespace collision and a backend
   package outside the selected target architecture. Rejected as the long-term
   architecture.
3. **Duplicate implementations under both package roots.** This makes imports
   appear compatible but permits two module objects, two registries and two
   runtime owners. Rejected.
4. **Selected: staged authority transfer with one-way compatibility and a
   fenced deployment selector.** Prove packaging first, move only owner-ready
   modules through digest-bound children, preserve old names as explicit
   forwarders, compare public contracts, and retire bridges by measured
   criteria. This adds review and control-store overhead but keeps every slice
   independently testable, crash-recoverable and reversible. Python modules
   and ASGI intentionally share one immutable deployment selector; reversing
   an older logical slice after later accepted changes builds a new
   compensating generation instead of selecting a stale full environment.

## Capabilities

### New Capabilities

- `python-package-transition`: distribution, import namespace, module-authority,
  console and installed-artifact transition rules.
- `web-layout-transition`: staged FastAPI and Vite-root movement with route,
  reload, asset and build compatibility.
- `native-module-boundary`: `_trade_native` naming, packaging and owner-adapter
  isolation.
- `layout-migration-governance`: path classification, compatibility windows,
  tests, observability, rollback and retirement evidence.

### Modified Capabilities

- None. Existing runtime interfaces remain authoritative until their owning
  migration slice explicitly delegates them.

## Affected Contracts

- **Distribution and imports:** distribution remains `trade-py`; existing
  `trade_py` imports continue to work. New owner-ready modules are available
  from installed `trade` paths. Exactly one implementation module is
  authoritative for each migrated symbol.
- **CLI:** `./trade`, `trade-py`, all canonical and hidden compatibility
  commands, arguments, help, output and exit behavior remain compatible.
- **HTTP/Web:** `trade_web:create_app`, existing URL/method/query/path/body,
  status/error/SSE/capability behavior, frontend routes and static assets remain
  compatible during the bridge window.
- **SDK/notebook:** notebook access moves to the installed public SDK only after
  contract parity exists; no repository scanning, direct parquet/repository
  import or `sys.path` mutation is accepted in the target state.
- **Native:** the optional extension becomes `_trade_native`; target domain and
  use-case modules never import it directly.
- **Tools/tests:** developer commands and test collection remain stable while
  files are classified and moved in separate slices.

## Compatibility, Rollout and Rollback

The implementation is a sequence of independently reviewable changes. This
parent may implement only the additive package-discovery proof, authority and
read-only evidence vocabulary, source guards, deterministic inventory index and
read-only layout diagnostics. It does not implement selector mutation,
service-manager recovery or slice activation policy. Every authority-changing
unit below is a mandatory child OpenSpec change and separate reviewable PR:

1. package-authority foundation without activation;
2. deployment selector/control-plane implementation;
3. `_trade_native` isolation;
4. each owner-ready Python module slice plus one-way legacy forwarders;
5. installed SDK/notebook compatibility;
6. FastAPI compatibility bridge and target interface/bootstrap modules;
7. Vite workspace movement and later default activation;
8. each tools/examples/test-layout classification slice;
9. optional plugin/MCP/remote-worker boundary before those dependencies exist;
10. measured legacy retirement in `tests-and-legacy-cleanup`.

Every slice preserves the old entrypoint or root and has an explicit selector
or compensation path. A failed Python/ASGI logical slice produces a new
immutable generation from the current accepted composition with only that
slice reversed; Web and a reviewed typed native capability can select their
prior reference independently. Earlier semantic Context migrations remain
intact. No immutable artifact or runtime data is deleted on rollback.

## Design Quality Governance

This is a Non-trivial architecture, public-contract and durable-control-state
change. The `public_contract`, `persistent_write` and `runtime_concurrency`
profiles apply because package names, entrypoints, ASGI reload/process imports
and runtime ownership must remain stable during dual-root operation, while
real deployment activation requires a durable revision-fenced selector,
operation journal and immutable evidence store. Schema-migration,
point-in-time, predictive-model and external-event-data profiles do not apply:
the new store has no predecessor schema or business payload, no business data
is moved, and tests use temporary installation/control roots.

Implementation starts only after:

1. `./trade dev design-check python-package-and-web-layout` passes;
2. all six required judges review a frozen artifact generation and every P0 is
   resolved;
3. `./trade dev design-check python-package-and-web-layout --strict` passes on
   the implementation start date.
