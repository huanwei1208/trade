## ADDED Requirements

### Requirement: The legacy ASGI import SHALL remain a thin compatibility contract

`trade_web:create_app` and the reviewed `trade_web.backend` imports SHALL
remain usable during the compatibility window, including Uvicorn factory,
reload and runtime child-process modes. After target HTTP/Bootstrap owners
exist, the legacy ASGI module SHALL delegate to exactly one target factory and
SHALL NOT construct a second resource container, register a second handler set
or own shutdown.

The transition SHALL preserve the complete frozen route registry, parameter
metadata, OpenAPI success or known failure state, status codes, headers,
payload/error shapes, SSE framing and capability-off/enabled/error behavior.

#### Scenario: Uvicorn reload starts a worker
- **WHEN** `trade web --reload` imports the application in a newly spawned worker
- **THEN** `trade_web:create_app` resolves without checkout-only path mutation and delegates to the same authoritative Bootstrap generation

#### Scenario: A compatibility factory constructs resources
- **WHEN** review or a runtime test detects `TradeDB`, EventBus, executor, Process Manager or resource-container construction in both the legacy and target factory
- **THEN** ASGI cutover is rejected as duplicate runtime ownership

#### Scenario: OpenAPI currently has a known generation failure
- **WHEN** the frozen baseline records a real OpenAPI generation failure
- **THEN** the layout transition preserves that evidence or consumes an independently approved fix and SHALL NOT replace it with a reduced route inventory

### Requirement: Runtime module strings and lifecycle SHALL remain process-safe

Every runtime module string SHALL remain importable in subprocess and reload execution.
Each child module, application factory and console module used by subprocess or
reload behavior SHALL remain importable from source, editable
and clean-wheel installations until its caller and target are migrated in the
same slice.

Package movement SHALL NOT change startup/shutdown order, command admission,
EventBus admission, process-group supervision, DB close ordering, shared
deadlines, force-exit diagnostics or residual-worker behavior. Runtime
lifecycle changes require their own strictly approved owner change.
Process acceptance SHALL exercise real OS descendants, not importability alone:
parent death before and after child spawn, a grandchild that ignores SIGTERM,
bounded process-group KILL escalation, reload-supervisor teardown, cleanup
failure classification and zero residual PIDs. The rollout evidence SHALL
record the bounded shutdown stage, escalation signal, residual process/thread
counts and forced-exit receipt without arguments, stacks or user payloads.
The ASGI child SHALL freeze supervisor, worker and command-child parentage,
process-group or cgroup ownership, selector-fence propagation, signal routing
and PID enumeration. A durable start intent SHALL bind one stable deployment
unit and invocation token before spawn so a lost response can adopt the
matching live process or tear it down before retry/rollback.

#### Scenario: A workflow child is spawned after backend movement
- **WHEN** the runtime command runner starts its supervised child module
- **THEN** the child imports from the installed package, retains parent/process-group supervision and reports the same audited command outcome

#### Scenario: Web shutdown leaves residual work
- **WHEN** the moved application is stopped with a blocked command, handler or cleanup stage
- **THEN** existing bounded shutdown and forced-exit fixtures retain their approved outcome and the compatibility layer does not mask or duplicate the residual owner

#### Scenario: A descendant ignores graceful termination
- **WHEN** a supervised child or grandchild remains alive after the TERM deadline during shutdown, reload teardown or validation timeout
- **THEN** the owned process group receives bounded KILL escalation, zero residual PIDs are verified and any cleanup failure remains distinct from the original command outcome

#### Scenario: Startup automation fails after core resources start
- **WHEN** the frozen current runtime would log and continue after automation startup failure
- **THEN** the layout transition preserves an explicit `started_degraded` compatibility state and does not silently convert it to fully healthy or fatal startup; changing that policy belongs to the Bootstrap owner child

#### Scenario: Reload supervisor exits around worker spawn
- **WHEN** the supervisor dies immediately before or after worker spawn, including a TERM-ignoring grandchild
- **THEN** fence-bound process enumeration adopts or terminates the exact owned tree, bounded TERM-to-KILL cleanup reaches zero residual PIDs and no second worker generation starts from a missing receipt

### Requirement: Frontend workspace movement SHALL preserve build and served assets

`trade_web/frontend` SHALL move to `web/` as an independent slice after an
immutable old/new build comparison. The target workspace SHALL preserve
package lock semantics, TypeScript references, lint/format/typecheck/unit/e2e
commands, Vite manifest generation, Observatory bundle check, `/api` and
`/predict` development proxies. Output asset semantics SHALL also remain
unchanged.

`--web-dist` and `TRADE_WEB_DIST` SHALL remain explicit highest-precedence
overrides. During the compatibility window the default root selector SHALL be
reversible between the old and target build. Static hosting SHALL preserve
`/assets`, optional legacy `/static`, root response and non-API SPA deep-link
fallback.

Immutable `WebBuildRef` selection SHALL govern deployment cutover. Current
local-development `trade web --build` and source-newer auto-build behavior
SHALL remain compatible in this child and SHALL NOT be treated as deployment
activation evidence.

Root precedence SHALL select exactly one frontend source root before any
recursive stat or build. Build caching SHALL bind selected-root identity,
lockfile, Node/package-manager/Vite versions and sorted source digest, retain
only reviewed unreferenced generations within its size bound and never combine
legacy and target trees. No-change startup, cold build and incremental build
SHALL satisfy the reviewed absolute/relative budgets or fail without changing
the selected deployment build.

#### Scenario: Target Web build succeeds but assets are incomplete
- **WHEN** `web/` emits `index.html` but a manifest-referenced asset is missing or its digest differs from the recorded build
- **THEN** target-default activation fails and the prior Web build remains selected

#### Scenario: An operator supplies an explicit distribution path
- **WHEN** `--web-dist` or `TRADE_WEB_DIST` points to a valid build
- **THEN** that build is served regardless of whether the repository frontend is under the legacy or target root

#### Scenario: A client opens an existing deep link
- **WHEN** a non-API application path is requested from the target build
- **THEN** FastAPI serves the reviewed SPA index behavior without intercepting `/api`, `/docs` or `/openapi.json`

#### Scenario: A file changes under the unselected frontend root
- **WHEN** the legacy and target roots both exist but precedence selects only one root
- **THEN** source-newer detection and cache invalidation inspect only the selected root, and the unselected change neither triggers a build nor contaminates its cache key

### Requirement: Web product and BFF contracts SHALL not change through layout movement

Web product and BFF contracts SHALL remain unchanged by physical layout movement.
Today, Observatory, Assurance/Data Quality, Research, Symbol Workspace,
Signals/Candidates, Actions, Trust, Data Ops, Operations and Settings SHALL
retain client routes, API/SSE URLs, capability gates, DTO mapping and explicit
loading, empty, partial, stale, unavailable and error states.

The Web BFF SHALL continue to compose owner queries only. Moving source SHALL
NOT authorize direct business-table access, provider calls, data repair,
Dataset publication, Study execution or lifecycle-pointer movement.

#### Scenario: A BTC workspace route is built from the target root
- **WHEN** the target frontend and HTTP compatibility layer serve an existing BTC observation or analysis view
- **THEN** route/deep-link, capability, payload and evidence identity goldens match the approved UI/interface baseline

#### Scenario: A moved BFF handler reaches an owner table directly
- **WHEN** the architecture or DB-owner guard detects direct SQL/repository access introduced by a layout move
- **THEN** the move is rejected even if its response payload matches

### Requirement: Backend and frontend cutovers SHALL be independently reversible

ASGI/backend authority and Vite workspace/default-build authority SHALL use
separate generation records and rollback selectors. A frontend failure SHALL
not require changing the backend factory; an ASGI failure SHALL not require
rebuilding frontend assets.

#### Scenario: The new frontend fails after backend compatibility passes
- **WHEN** target asset or browser smoke fails
- **THEN** the default Web build returns to the legacy root while the approved ASGI generation remains unchanged

#### Scenario: The target ASGI factory fails
- **WHEN** route, reload, child-process or lifecycle parity fails
- **THEN** the shared Python deployment executes its reviewed forward-revision rollback: it selects the exact predecessor only when no later accepted slice exists, otherwise it selects a verified compensating successor from the current composition that preserves every later slice; `trade_web:create_app` remains the compatibility factory and either valid Web build remains independently selectable
