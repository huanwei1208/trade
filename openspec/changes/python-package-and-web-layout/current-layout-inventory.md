# Current Layout Inventory

Audit date: 2026-07-27  
Scope: Git-tracked source/config/test paths only  
Data access: none

## Inventory Method

The audit used `git ls-files`, `git grep`, `rg`, line-numbered source reads and
the parent architecture ownership map. Counts exclude untracked cache, local
data, build products and `node_modules`. A source reference count is a migration
signal, not proof that every match is a public contract.

## Tracked Root Inventory

| Root | Tracked paths | Python files | Current role | Target disposition |
|---|---:|---:|---|---|
| `trade_py/` | 334 | 318 | mixed domain/data/DB/runtime/CLI/devtools package | owner-by-owner into `src/trade`; retained compatibility root |
| `trade_web/backend/` | 18 | 18 | ASGI, BFF, capability, runtime/process ownership | split into Interfaces/Bootstrap/owner adapters after prerequisites |
| `trade_web/frontend/` | 129 | n/a | React/Vite product workspace | `web/` in an independent slice |
| `tests/` | 94 | 91 | mixed pytest suites and Observatory sub-suite | gradual category/component classification |
| `scripts/` | 4 | 3 | package marker, backup, two migrations | individual tool/owner/historical classification |
| `research/` | 2 | 1 plus paired notebook | BTC Observatory notebook | `examples/notebooks` after installed SDK |
| `_bmad-output/` | 6 | 0 | historical planning | extract valid governed facts, then individual retirement |
| `engine/` | 185 | 0 | C++ engine, CMake and tests | remain root; consume as Context adapters |

## Python Consumer Signals

| Signal | Current result | Consequence |
|---|---:|---|
| Python files with `trade_py` import/attribute match | 347 | no global rename |
| matching `trade_py` import/attribute lines | 1,531 | deterministic per-owner inventory required |
| files with `sys.path` match | 17 | classify direct execution, notebook, test and debug use |
| non-document files with Web root/path dependency | 17 | ASGI/Vite roots need explicit bridge |

Known `sys.path` consumers include:

- `trade_py/cli/main.py`;
- `trade_py/cli/_sentiment.py`;
- `trade_py/signals/window_scorer.py`;
- `research/notebooks/btc_h1_observatory.py`;
- `debug/eval_baseline/evaluate_factors.py`;
- architecture-guard tests.

The target state forbids notebook/example repository discovery. Direct
execution compatibility in CLI/debug paths requires an explicit per-path
decision rather than a blanket ban or rewrite.

## Package and Entrypoint Inventory

| Contract | Current owner/path | Current fact | Target/bridge |
|---|---|---|---|
| distribution | `pyproject.toml` | `trade-py` | retain during window |
| console | `pyproject.toml` | `trade-py = trade_py.cli.main:main` | retain, later delegate after parity |
| package discovery | setuptools find | `trade_py*`, `scripts*` | dual root with explicit allowlist |
| root command | `trade` | invokes `trade_py.cli.main` | stable facade |
| CLI domain loading | `trade_py/cli/main.py` | string import `trade_py.cli.<name>` | explicit compatibility dispatch |
| Python target | absent | no `src/trade` package in this worktree | add only through approved package proof |
| native probe | `trade_py/__init__.py` | self-import collision | explicit `_trade_native` capability |
| native CMake target | `engine/cmake/python_bindings.cmake` | `trade_py` | `_trade_native`, blocked on source reconciliation |

## Web and Process Import Inventory

| Contract | Current path/string | Compatibility requirement |
|---|---|---|
| ASGI factory | `trade_web:create_app` | keep importable for Uvicorn factory/reload |
| backend re-export | `trade_web.backend` | keep reviewed imports during window |
| runtime child | `trade_web.backend.runtime.command_child` | keep process import and supervision |
| frontend source root | `trade_web/frontend` | independent Vite move |
| default build output | `trade_web/frontend/dist` | old/new selector plus explicit override |
| explicit build override | `--web-dist`, `TRADE_WEB_DIST` | preserve highest precedence |
| static assets | `/assets`, optional `/static` | preserve mount semantics |
| SPA index | `/` and non-API deep links | preserve fallback; never intercept API/docs |
| dev proxy | `/api`, `/predict` to `127.0.0.1:8080` | preserve |
| lifecycle | FastAPI lifespan plus `WebResourceContainer` | one Bootstrap owner |
| force-exit safeguard | `trade_py.cli.web` | preserve until owner migration |

## Test-Bound Import Inventory

Representative hidden consumers:

- `tests/test_cli_lazy_loading.py` asserts loaded module names;
- `tests/test_engine.py`, `tests/test_jobs.py` and `tests/test_news_job.py`
  inject legacy paths into `sys.modules`;
- many tests patch string paths such as `trade_py.jobs.run_job`;
- `tests/test_runtime_commands.py` imports the current Web child module;
- route/Observatory tests import `trade_web` and `trade_web.backend.*`;
- architecture baseline and guard fixtures contain legacy source literals.

These are migration contracts or validation fixtures. They cannot be bulk
rewritten independently of the module-authority slice they protect.

## Root Script Disposition

| Path | Observed behavior | Disposition | Blocker |
|---|---|---|---|
| `scripts/__init__.py` | makes root scripts installable | compatibility/packaging audit | decide which scripts are installed commands |
| `scripts/backup.py` | Google Drive transport, archive, DB metadata/CLI behavior | split-required: Platform backup plus owner repositories/CLI | backup boundary and contract |
| `scripts/migrate_kline_consolidate.py` | reads/writes parquet, manifest, DB symbol inventory, archives directories | owner migration/historical | Datasets migration reconciliation, dry-run/backup/rollback |
| `scripts/migrate_paths.sh` | moves data roots, copies DBs, instructs destructive deletion | historical/blocked | usage, provenance, retention and data-safety review |

No script is executed, moved or deleted by the design phase.

## Notebook Disposition

The paired BTC notebook currently:

- searches parents for a `trade_py` directory;
- inserts the repository into `sys.path`;
- imports `trade_py.observatory.query.sdk`;
- uses a repository/default relative data root.

It is a candidate for `examples/notebooks` only after the installed public SDK
exists and clean-environment parity proves immutable snapshot behavior.

## Historical Material

Tracked `_bmad-output` contains:

- one brainstorming file;
- four planning artifacts;
- one project context file.

These files may contain valid historical rationale but do not override actual
code or governed OpenSpec. Cleanup requires a link/provenance ledger and
extraction of any still-valid decision before deletion.

## Immediate Implementation Eligibility

| Slice | Eligibility at audit time | Reason |
|---|---|---|
| package discovery proof | conditionally eligible after this strict gate and kernel package-proof reconciliation | additive, no business move |
| module authority guard/manifest | conditionally eligible after strict gate | source/build governance only |
| `_trade_native` rename | blocked | referenced binding sources are not tracked in this worktree |
| business module movement | blocked per module | owner child must be implemented |
| CLI authority switch | blocked | interface child/baseline delegation required |
| ASGI/backend authority switch | blocked | Bootstrap/interface owners required |
| SDK/notebook move | blocked | installed SDK required |
| Vite source move | design-ready but activation gated | needs independent Web build/asset compatibility implementation |
| script retirement | blocked | individual owner and retention evidence |
| `_bmad-output` deletion | blocked | provenance/link/retention evidence |
| broad test reorganization | blocked | must follow production slices |

## Audit Limitations

- The count is a point-in-time tracked-source snapshot and must be refreshed
  immediately before each implementation slice.
- The CMake file references binding sources absent from the tracked inventory;
  native implementation cannot be inferred from build metadata alone.
- Historical OpenAPI inventory includes a known generation defect. Layout
  validation must preserve the failure evidence or consume an independently
  approved fix; it must not claim a reduced schema as parity.
- No installed wheel was built during this design audit. That proof is an
  implementation task and a hard gate before target authority.
