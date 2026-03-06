# Trade 2.0 重构执行计划（Authoritative）

## 目标

1. `engine` 仅保留高性能计算与存储内核。
2. 数据抓取、回补、账户元数据管理统一迁到 Python 侧。
3. `trade_py` 提供统一 CLI 入口，默认不要求显式传 `data-root`。
4. 清理 C++ 情绪数据入口与相关接口，避免双栈职责重叠。

## 核心决策（已锁定）

1. `engine` 与 Python 一并重构。
2. `sentiment` 完全移出 `engine`（不保留 C++ 兼容层）。
3. 采用一步到位迁移策略（结构与职责同步收敛）。
4. C++ `data` 命令全部迁到 Python。
5. `account` 命令迁到 Python。

## 目录蓝图（无省略号）

```text
trade/
├── engine/
│   ├── CMakeLists.txt
│   ├── cmake/
│   │   ├── deps.cmake
│   │   ├── submodule_check.cmake
│   │   ├── trade_core_sources.cmake
│   │   ├── trade_cli_sources.cmake
│   │   └── tests.cmake
│   ├── include/trade/
│   │   ├── app/pipelines/train_pipeline.h
│   │   ├── backtest/{backtest_engine,broker_sim,performance,portfolio_state,reporting,slippage,strategy,validation}.h
│   │   ├── cli/{args,commands,shared}.h
│   │   ├── common/{config,time_utils,types}.h
│   │   ├── decision/{decision_report,order_manager,portfolio_opt,pre_trade_check,signal,signal_combiner,universe_filter,verdict}.h
│   │   ├── features/{calendar,feature_engine,feature_monitor,fund_flow,fundamental,fundamental_features,industry,interaction,liquidity,momentum,preprocessor,price_limit,smart_money_signal,technical_signals,volatility}.h
│   │   ├── ml/{lgbm_model,model_evaluator,model_trainer,xgb_model}.h
│   │   ├── model/{account,bar,financial_report,instrument,market,timeframe}.h
│   │   ├── normalizer/bar_normalizer.h
│   │   ├── regime/regime_detector.h
│   │   ├── risk/{covariance,drawdown,kelly,position_sizer,risk_attribution,risk_monitor,stress_test,var}.h
│   │   ├── signal/propagation.h
│   │   ├── stats/{attribution,correlation,descriptive}.h
│   │   ├── storage/{cloud_sync,duck_store,google_drive_sync,metadata_store,parquet_reader,parquet_writer,storage_path}.h
│   │   └── validator/data_validator.h
│   ├── src/
│   │   ├── app/pipelines/train_pipeline.cpp
│   │   ├── backtest/{backtest_engine,broker_sim,performance,portfolio_state,reporting,slippage,strategy,validation}.cpp
│   │   ├── cli/{args,commands_analysis,commands_report,main,shared}.cpp
│   │   ├── common/{config,time_utils}.cpp
│   │   ├── decision/{decision_report,order_manager,portfolio_opt,pre_trade_check,signal_combiner,universe_filter}.cpp
│   │   ├── features/{calendar,feature_engine,feature_monitor,fund_flow,fundamental,fundamental_features,industry,interaction,liquidity,momentum,preprocessor,price_limit,smart_money_signal,technical_signals,volatility}.cpp
│   │   ├── ml/{lgbm_model,model_evaluator,model_trainer}.cpp
│   │   ├── model/{bar,instrument}.cpp
│   │   ├── normalizer/bar_normalizer.cpp
│   │   ├── regime/regime_detector.cpp
│   │   ├── risk/{covariance,drawdown,kelly,position_sizer,risk_attribution,risk_monitor,stress_test,var}.cpp
│   │   ├── signal/propagation.cpp
│   │   ├── stats/{attribution,correlation,descriptive}.cpp
│   │   ├── storage/{cloud_sync,duck_store,google_drive_sync,metadata_store,parquet_reader,parquet_writer,storage_path}.cpp
│   │   └── validator/data_validator.cpp
│   └── tests/
│       ├── integration/test_pipeline.cpp
│       └── unit/{test_backtest,test_bar,test_decision,test_duck_store,test_features,test_fundamental_features,test_google_drive_sync,test_metadata,test_ml,test_normalizer,test_parquet,test_propagation,test_regime,test_risk,test_smart_money,test_stats,test_technical_signals,test_types,test_validator}.cpp
├── trade_py/
│   ├── __init__.py
│   ├── config/{__init__,context,defaults}.py
│   ├── meta/
│   │   ├── __init__.py
│   │   ├── records/{__init__,raw,silver,gold}.py
│   │   ├── market/{__init__,kline,fund_flow,signal}.py
│   │   ├── feed/{__init__,config,score}.py
│   │   ├── schema/{__init__,pipeline,bronze,meta_store}.py
│   │   └── store/{__init__,base,duckdb_store,memory_store}.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── registry.py
│   │   ├── news/
│   │   │   ├── __init__.py
│   │   │   ├── rss/{__init__,base,sina,wsj_cn,gelonghui,eastmoney,cls}.py
│   │   │   └── gdelt/{__init__,source,channels}.py
│   │   ├── market/
│   │   │   ├── __init__.py
│   │   │   ├── kline/{__init__,akshare,baostock}.py
│   │   │   ├── fund_flow/{__init__,akshare}.py
│   │   │   └── cross_asset/{__init__,gold,fx,btc}.py
│   │   ├── pipeline/{__init__,pipeline_db,ingest,enrich,aggregate}.py
│   │   └── account/{__init__,repository,service}.py
│   ├── intelligence/
│   │   ├── __init__.py
│   │   ├── clients/{__init__,base,anthropic,ollama}.py
│   │   ├── enricher.py
│   │   ├── feed_scorer.py
│   │   ├── nlp_train.py
│   │   └── graph/{__init__,builder,query}.py
│   ├── signals/{__init__,window_scorer,cross_asset,regulatory_tone_monitor}.py
│   ├── report/{__init__,morning_brief,scheduler,decision_journal,report_generator}.py
│   ├── cli/{__init__,main,data,model,report,account}.py
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── services/{__init__,cpp_bridge}.py
│   │   └── tabs/{__init__,tab_analysis,tab_brief,tab_journal,tab_settings,tab_signals}.py
│   └── utils/{__init__,log,time,retry,html,progress,scoring}.py
├── config/
│   ├── README.md
│   ├── config.yaml
│   ├── defaults.json
│   ├── sentiment_dict.txt
│   ├── feeds/{rss,gdelt,backfill_priority}.json
│   └── modules/{security,storage,engine}.yaml
├── notebooks/{01_market_overview,02_sentiment,03_knowledge_graph,04_model_training}.ipynb
├── deployment/rsshub/{.env.example,README.md,docker-compose.yml}
└── docs/{architecture-2.0,claude-latest-plan,engine-refactor-migration,existing-documentation-inventory,project-parts,project-scan-report,project-structure,user-provided-context}.md
```

## 实施顺序

1. 统一日志与配置上下文（`trade_py/utils`、`trade_py/config/context.py`）。
2. Meta 层定型（`trade_py/meta/*`）。
3. Python 数据层重组（`trade_py/data/*`），并将历史回补渠道配置化。
4. Python CLI 统一入口（`trade_py/cli/*`），替代 `python/scripts/run_*.py`。
5. C++ `sentiment` 全量移除（头文件、实现、CMake、测试、命令参数）。
6. C++ `data/account` 命令下线，保留计算相关命令。
7. `engine` 目录与构建入口收敛，根目录只做聚合。
8. 文档与验收脚本更新，完成端到端自检。

## 验收标准

1. `uv run python -m trade_py.cli.main --help` 正常。
2. 不传路径时默认使用仓库 `data/`，配置加载幂等。
3. 历史模式请求日志不再显示 `incremental`。
4. C++ 不再编译/链接 `sentiment` 相关源文件。
5. C++ CLI 不再暴露 `collect/silver/sql/verify/info/account` 数据入口命令。
6. `cmake --build` 与 `uv run pytest` 均通过。

## 进度跟踪（2026-03-06）

- [x] 计划文档落盘并设为唯一追踪文档（`docs/claude-latest-plan.md`）。
- [x] C++ 构建面收敛：`cmake` 不再编译 sentiment 模块与 data/account CLI 源文件。
- [x] C++ 命令注册收敛：移除 data/account 相关命令注册与帮助文案入口。
- [x] Python 统一 CLI 初版：新增 `trade_py/cli/{main,data,model,report,account}.py`。
- [x] Config Context 幂等化：新增 `trade_py/config/context.py`，旧 `python/scripts/config_context.py` 改为桥接。
- [x] 默认配置统一：新增 `config/defaults.json`，`run_sentiment.py` 默认读取该文件。
- [x] feed 配置重构：新增 `config/feeds/{rss,gdelt,backfill_priority}.json`。
- [x] 新配置路径收敛：RSS/GDELT loader 仅使用 `config/feeds/*`（旧路径已移除）。
- [x] `vendor/` 物理迁移到 `engine/vendor/`，并更新 `.gitmodules` 与 submodule 路径。
- [x] C++ sentiment 头文件与 API 彻底物理删除（`engine/include/trade/sentiment`、`engine/src/sentiment` 已删除，`parquet_writer` sentiment API 已移除）。
- [x] `src/include/tests/cmake` 已物理迁移到 `engine/`。
- [x] CMake 端到端验证（clang 线）：`cmake --preset linux-clang && cmake --build --preset linux-clang --target trade_cli`。
- [x] CMake Preset 收敛：移除 `linux`（gcc）系 preset，仅保留 `linux-clang` 系。
- [x] Arrow 构建路径修复：固定 Arrow binary dir 到 `${CMAKE_BINARY_DIR}/vendor/arrow/cpp`，消除 `rapidjson_ep` 路径漂移。
- [x] 配置清理：移除 `config/rss_feed_index.json`、`config/sentiment_backfill_channels.json`、`config/sentiment_cli_defaults.json`（只保留 `config/feeds/*` 与 `config/defaults.json`）。
- [x] CLI 收敛（首批）：`trade_py.cli.data` 直接接管 `collector/cross-asset`，`trade_py.cli.model` 直接接管 `score`，`trade_py.cli.report` 直接接管 `brief`。
- [x] 旧脚本首批 shim：`run_collector.py`、`run_cross_asset.py`、`run_window_score.py`、`morning_brief.py` 改为转发到 `trade_py.cli.main`。
- [x] UI 命令提示切换到新入口（signals/brief tab）。
- [x] `report schedule/graph` 迁出 `_legacy`：新增 `trade_py/report/scheduler.py` 与 `trade_py/intelligence/graph/builder.py`。
- [x] `data sentiment` 迁出 `_legacy`：改为 `trade_py.cli.data` 定向调用 `scripts.run_sentiment`。
- [x] 旧脚本继续 shim 化：`scheduler.py`、`build_graph.py` 改为转发到 `trade_py.cli.main`。
- [x] Meta 契约补齐：新增 `trade_py/meta/market/{kline,fund_flow,signal}.py` 与 `trade_py/meta/schema/bronze.py`。
- [x] News 目录拆分（结构层）：新增 `trade_py/data/news/rss/*` 与 `trade_py/data/news/gdelt/*`，保留 `rss_source.py` / `gdelt_source.py` 兼容导入层。
- [x] Account 目录落地：新增 `trade_py/data/account/{repository,service}.py`，`trade_py/cli/account.py` 改为调用 service。

## TODO 任务清单（蓝图推进）

- [x] CLI 新入口可用：`trade_py/cli/{main,data,model,report,account}.py`。
- [x] `data collector` 与 `data cross-asset` 已由 `trade_py.cli.data` 直接接管（不再经 legacy）。
- [x] `model score` 与 `report brief` 已由 `trade_py.cli` 直接接管（不再经 legacy）。
- [x] 旧脚本 shim 化（首批）：`run_collector.py`、`run_cross_asset.py`、`run_window_score.py`、`morning_brief.py`。
- [x] `data sentiment` 从 `_legacy` 迁出（当前为 CLI 定向调用 `scripts.run_sentiment`）。
- [x] `report schedule/graph` 从 `_legacy` 迁出到 `trade_py.cli.report` 原生实现。
- [x] `data sentiment` 进一步原生化：新增 `trade_py/cli/_sentiment.py` 完整原生实现，`python/scripts/run_sentiment.py` 已删除。
- [x] `model run` 迁出 `_legacy`：`cli/model.py` 已原生实现 build-features/build-labels/train/predict/report，`scripts/run_model.py` 已删除。
- [x] 补齐 `trade_py/meta/market/{kline,fund_flow,signal}.py`。
- [x] 补齐 `trade_py/meta/schema/bronze.py`。
- [x] 落地 `trade_py/data/account/{repository,service}.py`，CLI 只保留参数解析。
- [x] `python/trade_py` 物理迁移到仓库根 `trade_py/`，`config/context.py` parents 层级修正，`pyproject.toml` 加入 `[project.scripts]` 入口。
- [x] 全量删除 `python/` 目录（scripts + trade_py + app），`python/app/` 迁移到 `trade_py/ui/`，更新所有 `app.*` 导入为 `trade_py.ui.*`。
- [x] 删除 `trade_py/cli/_legacy.py`（所有命令已原生化，无残留调用）。

### 配置层清理
- [x] `config/context.py` 移除 `_PYTHON_ROOT` / `python_root` 字段（python/ 目录已删除）。
- [x] 删除三个兼容导入 shim：`data/news/rss_source.py`、`data/news/gdelt_source.py`、`intelligence/_utils.py`。

### 目录结构收敛
- [x] `journal/` 目录并入 `report/`：`morning_brief.py`、`decision_journal.py`、`report_generator.py` 移入 `report/`，`journal/` 已删除，全部导入已更新。
- [x] `data/market/` 落地：四个 fetcher 移入 `data/market/{kline,fund_flow,cross_asset}/` 及 `data/market/fundamental.py`，旧文件已删除，相关导入已更新。
- [x] `intelligence/clients/` 落地：`claude_client.py` 拆分为 `clients/{base,anthropic,ollama}.py`，旧文件已删除，`_sentiment.py` 改用 `create_client()` 工厂。
- [x] `data/news/rss/` 深度拆分：catalog 辅助函数提取到 `rss/catalog.py`，`base.py` 只保留 `RssSource` + `_fetch_feed`。
- [x] `data/registry.py`：实现数据源注册表，`register/get/list_sources`，默认注册 rss/gdelt。

### 文档与工具
- [x] README.md 修正：`python/app/ui.py` → `trade_py/ui/ui.py`；`scripts.run_sentiment` → `trade_py.cli.main data sentiment`。
- [x] `./trade` shell 脚本：`ui` 子命令的 streamlit 入口改为 `trade_py/ui/ui.py`，移除过时 PYTHONPATH。
- [x] notebooks/04_model_training.ipynb：所有导入路径已更新为新目录结构。
- [x] notebooks/02_sentiment.ipynb：移除过时的 `python/` sys.path 操作。

### 验证 & 测试
- [x] `build/linux/` 已在 `.gitignore` 中，不需要额外清理。
- [x] `pyproject.toml` 补充 `[tool.setuptools.packages.find]`（只打包 trade_py）与 `[tool.pytest.ini_options]`（testpaths=tests）。
- [x] `uv run pytest` 全量验证通过：12/12 smoke tests（imports、config、utils、meta、data/market、news、intelligence/clients、report、signals、CLI）。
- [x] `uv run python -m trade_py.cli.main --help` 所有子命令冒烟测试通过。
