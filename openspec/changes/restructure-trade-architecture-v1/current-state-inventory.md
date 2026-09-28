# Current-State Inventory

## Audit Identity and Safety

| Field | Audited value |
|---|---|
| Repository | `huanwei1208/trade` local worktree |
| Source baseline | `cb6cb248f07594734ae7ff72e2aa44d719c54d87` |
| Source commit | `docs(openspec): record kernel design gate` |
| Audit branch | `wt/restructure-trade-architecture-v1-v2-20260726` |
| Audit date | 2026-07-26, Asia/Shanghai |
| Change tier | Non-trivial architecture change |
| Data access | source/configuration reads only; no real SQLite, parquet, provider or production-data access |
| Runtime probes | route metadata only; FastAPI lifespan was not entered; unused `/tmp/trade-route-audit-*` roots remained absent |
| Production code changes | none |

`AGENTS.md`, `README.md`, `pyproject.toml`, the root `trade` facade,
OpenSpec governance/active changes, current architecture plans and actual code
were reviewed. Historical documents supplied vocabulary but did not override
source facts.

## Repository and Technology Shape

| Area | Current fact | Target consequence |
|---|---|---|
| Python | 335 tracked `.py` files; package/distribution is `trade-py`, import root is `trade_py`; Python >=3.10; setuptools/uv | staged transition to `src/trade`; keep `trade_py` forwarding and package discovery until compatibility exit |
| Python tests | pytest 8 declared; `tests/` has 94 tracked files; ruff and basedpyright are configured | retain focused Python ownership; add unit/integration/contract/architecture/golden/e2e partitions incrementally |
| HTTP backend | FastAPI factory in `trade_web/backend/app.py`; no declared response models on current business routes | registry plus payload/error goldens are mandatory before extraction; OpenAPI alone is insufficient |
| Frontend | React 19, TypeScript 5.8, Vite 7, Vitest, Playwright, axe; 107 tracked TS/TSX files | move workspace to `web/` only after API, build, route, asset and screenshot parity |
| C++ | 155 tracked C/C++ headers/sources under `engine/`; CMake presets, Ninja/CTest path and nanobind plan | keep `engine/` independent; expose Context-specific adapters through ports and reserve `_trade_native` |
| CLI/build | Bash `trade` facade dispatches Python, CMake, CTest and developer gates | keep root facade and command/exit behavior stable |
| CI | no tracked `.github/` directory was present at the audited commit | CI/platform selection is a child infrastructure decision; this parent does not invent a provider |
| Local/generated | `data/`, `.venv/`, build output, frontend `node_modules`, caches and local config are excluded or runtime-owned | never use them as migration input without explicit fixture/rehearsal approval |
| Third party | `engine/vendor` and frontend dependencies are external/build inputs | never move them into business Contexts or include them in owner migration |

Tracked top-level source concentrates 334 files under `trade_py`, 149 under
`trade_web`, 185 under `engine`, 130 under `openspec` and 94 under `tests`.
These counts describe the audited commit, not a permanent capacity target.

## Stable Entry Points

### CLI

The root Bash script delegates Python domains through
`trade_py.cli.main:main`, and also owns setup/configure/build/test/C++ CLI
commands. The code comment and help text say "10 domains", but the actual
canonical registration contains 13:

```text
run status data show research kg observatory config event backup start web dev
```

Eight hidden compatibility domains are dispatchable:

```text
doctor inspect daily ops account model factor evaluate
```

This discrepancy is a documentation/compatibility baseline fact. A migration
must snapshot the actual registry and aliases, not rely on the numeric comment.

### HTTP

Read-only route registration introspection against the audited code produced:

| Mode | `app.routes` | Business `APIRoute` | Observatory behavior |
|---|---:|---:|---|
| default-off | 72 | 68 | capability probe only |
| enabled | 81 | 77 | capability probe plus nine BTC data routes |
| enabled registration error | 72 | 68 | capability probe reports `state=error`; data routes absent |

The four non-`APIRoute` entries are FastAPI documentation/schema routes.
Application construction alone did not start Web resources or access a data
root.

`app.openapi()` fails under FastAPI 0.135.1/Pydantic 2.12.5 because the
function-local `PredictRequest` remains an unresolved forward reference.
`POST /predict` is nevertheless a registered public route and cannot be
dropped. All inspected business routes have `response_model=None`, so current
payload/error behavior must be frozen from code and golden tests before
delegation.

Two SSE contracts are present:

- `GET /api/events/stream(after_id=0, limit=50, poll_seconds=2.0)`, with
  `after_id >= 0`, `1 <= limit <= 500`, and `0.25 <= poll_seconds <= 60`.
- `GET /api/runtime/stream(scope="report", poll_seconds=2.0)`, with the same
  polling interval bounds.

Both return `text/event-stream` with `Cache-Control: no-cache`,
`Connection: keep-alive` and `X-Accel-Buffering: no`.

### Web Pages and Product Surfaces

Tracked page entry points are:

```text
TodayPage
CandidatesPage
SymbolPage
ResearchPage
DataPage
OpsPage
observatory/ObservatoryPage
observatory/MarketWorkspace
```

Actions, Trust, Assurance/Data Quality, Operations and Settings are also
visible product surfaces or page regions through API widgets/navigation even
when they are not separate tracked page files. They require explicit BFF
ownership and cannot be inferred from filenames.

The current Observatory page uses four lenses (`overview`, `trust`, `runs`,
`research`), URL/local-storage restoration, capability fail-closed behavior,
snapshot identity validation, decimal-string price values and granular routes.
It is a product surface, not a business Context.

### SDK and Notebook

`trade_py.observatory.query.sdk` is a current read-only, BTC-focused internal
SDK seed. `research/notebooks/btc_h1_observatory.py` mutates `sys.path`, and the
notebook can reach internal repository modules. These are compatibility facts,
not the desired formal SDK boundary.

### Scheduler and Events

`trade_py.bus` contains event models, admission, scheduler and handler
mechanics. `trade_py.jobs.__init__` is a broad registry that imports and invokes
business work. CLI and Web routes can publish or directly run work. The target
must preserve event IDs/topics while separating generic Platform mechanics
from Context use cases and Process Managers.

## Persistent State and Artifacts

The code-derived `architecture-baseline.toml` is valid TOML and records:

| Inventory | Count | Classification |
|---|---:|---|
| logical tables | 56 | 31 candidate, 25 deferred |
| artifact families | 8 | 6 candidate, 2 deferred |
| public-interface seeds | 8 | CLI, HTTP, OpenAPI, Observatory and SSE |
| source facts | 3 | global DB, central migrations and pipeline DB |
| warehouse producers | 19 | 17 materializer calls and 2 CLI fetch writers |
| capture temporal/rights risks | 13 | collapsed/substituted clocks, mutable source config, replay and quarantine mixing |
| dynamic SQL limitations | 3 | recommendation, recommendation trace and factor registry DDL |

The detailed target ownership and migration block are in
`table-and-artifact-ownership.md`. The baseline's
`process-manager-and-platform-boundary` name predates the selected split into
Platform foundation and Process Manager children.

### Current Data Boundaries

- `trade_py/db/trade_db.py` is a global SQLite facade and schema owner across
  settings, events, jobs, source metadata, quality, research, causal/decision
  and graph facts.
- `trade_py/db/migrations.py` alters unrelated domains from one migration
  module, including dynamic DDL.
- `trade_py/db/pipeline_db.py` owns ingest, coverage and enrichment state.
- `trade_py/intelligence/meta_store.py` owns a separate SQLite store while its
  compatibility class still says DuckDB and performs implicit legacy import.
- warehouse and market paths contain mutable pointers, parquet products,
  validation receipts and raw/canonical artifacts with uneven identity rules.
- Observatory catalog SQLite is declared rebuildable, but readiness currently
  inspects live files and performs SQLite integrity/table scans.
- `DataGateway` and some GET routes can repair, persist or mark state, so the
  current read/write boundary is not reliable.

No target Context is allowed to inherit the global `TradeDB` API or expose
`db._conn`.

## Mixed Ownership Evidence

The following directories are not owners:

```text
trade_py/analysis
trade_py/evaluation
trade_py/evidence
trade_py/factors
trade_py/intelligence
trade_py/observatory
```

Actual files mix provider interaction, SQL/parquet reads, canonicalization,
features, validation, model fitting, decision state, projection and response
shaping. Examples include:

- `analysis/intraday_runtime.py`: provider access, decision/watchlist reads,
  factor calculation and parquet/DB persistence;
- `evaluation/trust.py`: Dataset quality, Study/model validation,
  Decision/Recommendation and Platform job facts;
- `intelligence/meta_store.py`: source configuration and scoring tables plus
  migration behavior;
- `observatory/domain/models.py`: Dataset, Study and presentation DTOs;
- `observatory/research/workflow.py`: import, Study run/promotion and direct
  file receipts; and
- `factors/materializer.py`: direct global DB access and cross-owner features.

The complete per-file classification is in `file-ownership-map.md`.

## Runtime Shutdown Audit

### Current Ownership

| Layer | Current behavior |
|---|---|
| FastAPI lifespan | starts `WebResourceContainer`; on exit sets an async event then calls `resources.stop(wait=True)` |
| Web resource owner | one 10-second monotonic deadline for commands, bus and DB; promotes `wait=False` to draining; uses helper daemon threads for bounded calls |
| command executor | admission/shutdown/drain logic owned below the Web container |
| EventBus | bounded executor/admission and its own shutdown semantics |
| Uvicorn CLI | three-second graceful timeout |
| SIGINT watchdog | five-second forced-exit guard |
| post-return fallback | two-second forced exit after Uvicorn returns |

### Why Closing Can Appear Hung

There is no single lifecycle owner across Uvicorn, Web resources, command
children, EventBus, schedulers and process groups. Each layer has a local
timeout, but a lower-level `wait=True`, non-cooperative thread/child, DB user or
executor can continue after an upper layer's budget. The timeouts are nested
rather than one propagated deadline, and helper daemon threads cannot safely
kill arbitrary work they do not own. The result is either an apparently stuck
shutdown or an abrupt forced exit with incomplete component evidence.

This is a reliability root cause, not a reason to shorten all constants. The
selected design gives Bootstrap one admission fence, monotonic deadline,
ordered resource graph, owned process-group TERM/KILL escalation, component
receipts and retryable `stopping` state.

## Build, Test and Governance

| Component | Current mechanism |
|---|---|
| Python | uv/setuptools; pytest, ruff, basedpyright |
| Frontend | npm; ESLint, Prettier, TypeScript, Vitest, Playwright and axe |
| C++ | CMake presets, Ninja and CTest |
| Quality gate | `./trade dev check --show-plan`, `./trade dev check` |
| Design gate | `./trade dev design-check <change>` and `--strict` |
| OpenSpec | repository-local schemas under `openspec/`; active changes use `.openspec.yaml`, specs, tasks and digest-bound review evidence |
| Multi-role review | six roles from `.agents/skills/review-this/SKILL.md` in an isolated review worktree |

Relevant existing governed/active changes include
`architecture-guardrails-and-baselines`, `kernel-and-public-contracts`,
`converge-runtime-boundaries`, BTC research/workspace changes and this parent
architecture change. They are prerequisites or compatibility seeds only where
the child DAG explicitly names them; their historical documents do not prove
current production behavior.

## Directory Disposition Baseline

| Current path | Target direction | Parent authorization |
|---|---|---|
| `trade_py/` | staged `src/trade/` package | design only; no move until package/layout child |
| `trade_web/backend/` | `src/trade/interfaces/http/` plus Bootstrap/owner adapters after classification | design only; route-by-route extraction |
| `trade_web/frontend/` | `web/` | design only; build/route/asset/UI parity required |
| `engine/` | remains `engine/` | Context adapter boundary only |
| root `research/` | `examples/notebooks/` or deletion after SDK/import proof | no move/delete in parent |
| root `scripts/` | formal CLI, Context adapter, migration, tools or deployment by behavior | file-by-file only |
| `_bmad-output/` | extract still-valid evidence then remove | no deletion without inventory/retention proof |
| `tests/` | unit/integration/contract/architecture/golden/e2e/fixtures over time | test ownership remains language/component appropriate |

## Known Baseline Limitations

1. OpenAPI is currently unavailable because of the local `PredictRequest`
   forward reference; route registration and goldens are authoritative until
   repaired.
2. HTTP business routes do not declare response models, so generated schema
   cannot prove payload compatibility even after the blocker is fixed.
3. CLI help numeric text says 10 while 13 canonical domains are registered.
4. No tracked GitHub Actions workflow exists; this design does not assume a
   hosting CI provider.
5. Twenty-five tables and two artifacts remain deliberately deferred.
6. Current PIT selection admits missing selected clocks and does not implement
   true latest-restated transformation.
7. Current source manifests do not consistently bind rights, clock precision,
   revision/finality and processor provenance.
8. Runtime shutdown improvements are Web-local and do not prove whole-process
   containment.

Every limitation is a blocker or explicit compatibility debt for its named
child. None is silently accepted as target behavior.
