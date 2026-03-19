# ARCH_REFACTOR_01 / EBRT_03：架构重构计划与进度跟踪

> 版本：v1.1 | 日期：2026-03-19 | 作者：principal architect
>
> ⚠️ **注意**：架构评估中部分行数来自 Explore agent，经实际核查后已修正：
> - `evaluation/service.py`: 实际 **1,668 行**（非 70,982 行）
> - `analysis/feature_builder.py`: 实际 **909 行**（非 40,021 行）
> - `analysis/knowledge_graph.py`: 实际 **758 行**（非 34,724 行）
> - `analysis/propagation_training.py`: 实际 **791 行**（非 29,693 行）
>
> ---
>
> ## 重构执行进度（2026-03-19）
>
> | 步骤 | 描述 | 提交 | 状态 |
> |------|------|------|------|
> | **Hotfix** | `propagation_runtime.py:511` 破损 import（`domain.models` → `trade_web.backend.inference`） | `84cde6f` | ✅ 完成 |
> | **Phase 1** | `evaluation/service.py`（1,668 行）→ 7 个专责文件（utils/sources/events/models/gate/trust/service） | `84cde6f` | ✅ 完成 |
> | **Phase 2** | `factors/` 包：从 `propagation_runtime.py` 拆出 6 职责 → 5 文件（definitions/technical/encoder/materializer/inference_bridge） + shim | `84cde6f` | ✅ 完成 |
> | **Phase 3** | `trust/` 包 + `BeliefEngine.gain_eta` 动态化（读取 `trust_scalar` 替代二值 operational_status） | `1637a0a` | ✅ 完成 |
> | **Phase 4** | DB 层按职责拆分（`trade_db.py` 4,192→2,422 行 + 3 mixin：ebrt_crud/signal_crud/kg_crud + `_utils.py`） | - | ✅ 完成 |
> | **Phase 5** | 因子信任元数据（FactorMeta + composite_trust 反馈训练权重） | - | ⬜ 待开始 |
> | **Phase 6** | C++ pybind11 binding（FeatureEngine + RiskMonitor） | - | ⬜ 低优先级 |
>
> ### Phase 1 详情：evaluation/ 拆分结果
>
> | 新文件 | 行数 | 职责 |
> |--------|------|------|
> | `evaluation/utils.py` | ~300 | 常量、EvalOutcome、cache helpers、日期工具、统计函数 |
> | `evaluation/sources.py` | ~200 | `evaluate_sources()` + `_source_health_rows()` |
> | `evaluation/events.py` | ~115 | `evaluate_events()` |
> | `evaluation/models.py` | ~255 | `evaluate_models()` + dataset helpers |
> | `evaluation/gate.py` | ~195 | `evaluate_gate()` |
> | `evaluation/trust.py` | ~280 | `compute_trust_vector()`, `scalar_trust()`, `write_quality_report()` |
> | `evaluation/service.py` | ~145 | `evaluate_daily()` + 全量 backward-compat re-exports |
>
> ### Phase 2 详情：factors/ 包结构
>
> | 新文件 | 行数 | 职责 |
> |--------|------|------|
> | `factors/definitions.py` | ~70 | FEATURE_COLS, FACTOR_DEFINITIONS, TECHNICAL_DEFAULTS |
> | `factors/technical.py` | ~115 | RSI/MACD/KDJ/MA 计算 |
> | `factors/encoder.py` | ~60 | 分类编码 + feature_maps 持久化 |
> | `factors/materializer.py` | ~195 | 特征物化 + DB 写入 |
> | `factors/inference_bridge.py` | ~40 | InferenceService 预测同步 |
> | `analysis/propagation_runtime.py` | ~35 | 兼容 shim（全量 re-export） |
>
> ### Phase 3 详情：trust/ + Feedback 回路
>
> - `trust/__init__.py`：re-export `compute_trust_vector`, `scalar_trust`, `to_gain_eta`
> - `trust/gate.py`：`to_gain_eta(trust_scalar=0.5, base_eta=0.15)` → `0.149`
> - `belief/__init__.py`：读取 `QualityReport.metrics_json["trust_scalar"]` 动态设置 `trust_gate`
>   - trust=1.0 → gain_eta=0.249；trust=0.5 → 0.149；trust=0.0 → 0.050
>
> ### Phase 4 详情：DB 层 Mixin 拆分结果
>
> | 新文件 | 行数 | 职责 |
> |--------|------|------|
> | `db/_utils.py` | 19 | `_json_loads_safe` 共享 helper |
> | `db/ebrt_crud.py` | 412 | ArticleEvent/Evidence/BeliefState/AttentionScore/BeliefTransition/Recommendation/QualityReport/FreshnessStatus/InfluenceSignal |
> | `db/signal_crud.py` | 838 | signals/factors/factor_registry/model_registry + 评估表（source_health/event_eval/model_eval/dataset_snapshots/quality_gate） |
> | `db/kg_crud.py` | 584 | market_events/event_propagations + kg_nodes/kg_relations/kg_edge_candidates |
> | `db/trade_db.py` | 2,422 | 连接管理 + schema/migrations + 核心基础表（settings/instruments/job_runs/event_log/pipeline_dag/trading_calendar/agenda/backup/sync_state） |
>
> - `TradeDB` 改为 `class TradeDB(EBRTCRUDMixin, SignalCRUDMixin, KGCRUDMixin)`
> - 向后完全兼容（调用方代码零修改）：所有方法仍通过 `db.method_name()` 调用
> - 24 个关键方法通过 smoke test 验证；33 个现有测试通过（4 个预存在失败无变化）
>
> ---

---

## 目录

1. [当前架构评估](#1-当前架构评估)
2. [与目标架构的主要偏差](#2-与目标架构的主要偏差)
3. [应保留的部分](#3-应保留的部分)
4. [立即重构的部分](#4-立即重构的部分)
5. [目标模块架构](#5-目标模块架构)
6. [C++/Python 边界设计](#6-cpython-边界设计)
7. [数据层重设计](#7-数据层重设计)
8. [因子层重设计](#8-因子层重设计)
9. [Trust 层重设计](#9-trust-层重设计)
10. [分阶段迁移计划](#10-分阶段迁移计划)
11. [Top-10 重构优先级清单](#11-top-10-重构优先级清单)
12. [不重构的最大风险](#12-不重构的最大风险)

---

## 1. 当前架构评估

### 目标架构（参考）

```
Evidence → Factors → Belief → Recommendation → Trust → Feedback
```

### 各层对齐评估

| 层 | 状态 | 说明 |
|----|------|------|
| **Evidence 层** | ✅ 对齐 | `evidence/` 包已完整实现 Bronze/Silver/Gold 三级管道，接口清晰（`run_ingest / run_enrich / run_aggregate`），EMA 平滑已就位 |
| **Factors 层** | ⚠️ 部分对齐 | `signals/window_scorer.py`（5 分量，100 分制）+ `analysis/propagation_runtime.py`（47 维 FEATURE_COLS）已实现，但因子信任/来源追踪完全缺失；`propagation_runtime.py` 混合 6 个职责 |
| **Belief 层** | ✅ 对齐 | `belief/` 包完整（`BeliefEngine`、`AttentionScorer`、`ConflictDetector`、残差更新）；公式正确（decay + gain_eta × Σ w_i·Δ_i）；BeliefState 写入 SQLite |
| **Recommendation 层** | ✅ 对齐 | `decision/` 包完整（`produce_recommendations`、`rank_symbols`、`DecisionExplainer`）；三因子评分（belief 40% + window 30% + event_kg 30%）已实现 |
| **Trust 层** | ❌ 不对齐 | `QualityReport.metrics_json` 中 `trust_scalar=0.7501` 但 `trust_components={}` 未分解；7 分量向量定义于 `RecommendationTrace.trust_json` 但未持续写入；无独立 Trust 服务 |
| **Feedback 层** | ⚠️ 部分对齐 | `reliability_update` 通过 Brier loss 更新 `InfluenceSignal.reputation_score`；但反馈回路未形成闭环（BeliefEngine 的 `gain_eta` 未受 trust_gate 动态调节） |
| **数据层** | ⚠️ 部分对齐 | Bronze/Silver/Gold Parquet 路径已标准化；但 `trade_py/data/` 中 kline/service.py 混合拉取+持久化+业务逻辑 |
| **C++/Python 边界** | ❌ 不对齐 | C++ engine 有完整 FeatureEngine/BacktestEngine/RiskMonitor/LgbmModel，但**零 Python binding**；所有计算仍在 Python 层进行 |

### 特别警示：超大文件

| 文件 | 行数 | 问题 |
|------|------|------|
| `trade_py/analysis/knowledge_graph.py` | **34,724 行** | 单文件 KG 实现，无法测试、无法分层 |
| `trade_py/analysis/feature_builder.py` | **40,021 行** | 特征工程全部堆在一个文件 |
| `trade_py/analysis/propagation_training.py` | **29,693 行** | 训练逻辑、数据加载、评估全混合 |
| `trade_py/evaluation/service.py` | **~70,982 行** | 评估服务极度膨胀，无法维护 |
| `trade_py/db/trade_db.py` | **4,192 行** | schema + CRUD + migration 全混合 |

---

## 2. 与目标架构的主要偏差

### 偏差 1：Trust 层未实现为独立层

**现状**：`trust_scalar` 存在于 `QualityReport`，但 `trust_components={}` 为空；7 分量 Trust 向量（fresh/evidence/model/calib/drift/ops/explain）仅定义于 `RecommendationTrace.trust_json` schema，未实际计算并写入。Trust 没有独立服务，没有时序历史，不可查询。

**目标**：Trust 应是独立层，每天运行后可查询各分量；`gain_eta` 应由 trust_gate 动态调整（当前硬编码）。

### 偏差 2：因子层无信任/来源

**现状**：`propagation_runtime.py` 的 47 个 FEATURE_COLS 均以相同权重输入模型，无 Measurement Trust（测量可信度）、无 Utility Trust（历史 IC）、无数据新鲜度降权。

**目标**：每个因子应携带 `(value, measurement_trust, utility_trust, staleness_days)`；特征矩阵应按因子信任加权。

### 偏差 3：C++ 引擎未接入

**现状**：`engine/` 目录下有完整的 FeatureEngine（向量化特征计算）、BacktestEngine（离散事件回测）、RiskMonitor（VaR + 集中度 + drift）、LgbmModel（LightGBM 封装）——但无任何 Python binding（pybind11/ctypes/cffi 均未使用）。所有计算仍在 Python 层完成。

**目标**：FeatureEngine 应取代 `propagation_runtime.py` 的技术指标计算；BacktestEngine 应取代 Python 回测逻辑；RiskMonitor 应为 Trust 层提供 VaR 输入。

### 偏差 4：Feedback 回路未闭合

**现状**：`reliability_update` 计算 Brier loss 并更新 `InfluenceSignal.reputation_score`，但 BeliefEngine 的 `gain_eta` 是固定常数，未读取 trust_gate 输出。

**目标**：`gain_eta` = `base_eta × trust_gate_factor(T-1)`，使信念增益随模型可靠性动态调整。

### 偏差 5：超大文件破坏可测试性

`knowledge_graph.py`（34,724 行）、`feature_builder.py`（40,021 行）、`evaluation/service.py`（~70,982 行）无法进行单元测试，任何修改都有高风险。这是最严重的结构性问题。

### 偏差 6：`propagation_runtime.py` 混合 6 个职责

单文件同时负责：技术指标计算、分类编码、因子注册管理、特征物化、持久化写入、推断集成。违反单一职责原则。

---

## 3. 应保留的部分

| 模块 | 保留理由 |
|------|---------|
| `evidence/` 包 | 接口清晰、三层分离、EMA 已就位；与目标架构完全对齐 |
| `belief/` 包 | 公式正确、组件化好（attention/conflict/update 分离）；信念层核心 |
| `decision/` 包 | 三因子评分逻辑正确；叙事生成（DecisionExplainer）有价值 |
| `bus/` + `jobs/` DAG 系统 | bootstrap_from_dag 机制成熟；17 个 job 注册规范；scheduler gate 11 个时间触发点完整 |
| SQLite v14 schema | 10 个 EBRT 表设计合理；Evidence/BeliefState/Recommendation/QualityReport 结构良好 |
| `signals/window_scorer.py` | 5 分量窗口评分实现完整；数据降级（fund_flow miss）处理到位 |
| `intelligence/` 包（迁移后） | meta_store/feed_scorer/raw_record 已整合到位 |
| `infra/` 包 | settings + config 分离合理 |
| C++ engine 的 **设计** | BacktestEngine/RiskMonitor/FeatureEngine 的接口设计本身是好的——问题是未暴露给 Python |

---

## 4. 立即重构的部分

按优先级排序（详见第 10 节分阶段计划）：

### P0：立即（安全紧急）

1. **拆分 `evaluation/service.py`（~70,982 行）** — 这个文件大到任何 git diff 都无法审阅，任何 bug 都无法定位。必须先拆。
2. **拆分 `analysis/feature_builder.py`（40,021 行）** — 每次特征修改都触及整个文件。
3. **拆分 `analysis/knowledge_graph.py`（34,724 行）** — KG 读/写/验证/传播全混合。

### P1：短期（阻碍迭代）

4. **分解 `propagation_runtime.py`**（527 行，6 职责 → 4 类）
5. **实现 Trust 7 分量写入**（当前 trust_components={} 为空）
6. **因子信任元数据**（Measurement Trust + Utility Trust）

### P2：中期（技术债）

7. **C++ FeatureEngine Python binding**（pybind11）
8. **Feedback 回路闭合**（`gain_eta` 动态化）
9. **`trade_py/data/market/kline/service.py` 拆分**（fetch/persist/business 混合）
10. **`trade_py/db/trade_db.py`（4,192 行）按职责分文件**

---

## 5. 目标模块架构

```
trade_py/
├── evidence/                    # 层 1：证据摄入（保留，现已对齐）
│   ├── ingest.py                # Bronze: RSS/GDELT 原始文章
│   ├── enrich.py                # Silver: 情绪打分、实体提取
│   ├── aggregate.py             # Gold: 聚合 + EMA 平滑
│   └── quality.py               # 质量检测 + 新鲜度校验
│
├── factors/                     # 层 2：因子层（重构）
│   ├── registry.py              # 因子注册 + 元数据 (type, trust, ic_history)
│   ├── technical.py             # 技术因子 (RSI/MACD/KDJ/MA) → 委托 C++ FeatureEngine
│   ├── sentiment.py             # 情绪因子 (来自 Gold)
│   ├── event.py                 # 事件 KG 因子 (来自 event_propagations)
│   ├── fundamental.py           # 基本面因子
│   ├── trust.py                 # 因子信任模型 (MeasurementTrust + UtilityTrust)
│   └── materializer.py          # 特征矩阵构建 (原 propagation_runtime 的物化职责)
│
├── belief/                      # 层 3：信念层（保留，小幅增强）
│   ├── __init__.py              # BeliefEngine（入口）
│   ├── attention.py             # AttentionScorer：8 分量 logit + softmax
│   ├── conflict.py              # ConflictDetector
│   ├── update.py                # 残差更新：b_new = (1-λ)b + η×Σ(w_i·Δ_i)
│   └── cold_start.py            # 冷启动信念初始化
│
├── decision/                    # 层 4：推荐层（保留，小幅增强）
│   ├── __init__.py              # produce_recommendations()
│   ├── rank.py                  # rank_symbols()：三因子评分
│   ├── explain.py               # DecisionExplainer：中文叙事
│   └── portfolio.py             # 仓位权重计算（新）
│
├── trust/                       # 层 5：Trust 层（新建，从 evaluation/ 分离）
│   ├── __init__.py              # TrustService：计算 + 写入 7 分量向量
│   ├── components/
│   │   ├── freshness.py         # T_fresh：数据新鲜度
│   │   ├── evidence.py          # T_evidence：证据覆盖
│   │   ├── model.py             # T_model：模型信心
│   │   ├── calibration.py       # T_calib：Brier score 校准
│   │   ├── drift.py             # T_drift：MMD 分布漂移
│   │   ├── ops.py               # T_ops：系统运行状态
│   │   └── explainability.py    # T_explain：叙事完整性
│   └── gate.py                  # TrustGate：trust_scalar → gain_eta 调节
│
├── feedback/                    # 层 6：反馈层（新建，从 reliability_update 分离）
│   ├── __init__.py              # FeedbackService：Brier loss 反馈
│   ├── brier.py                 # BrierScorer：预测校准评估
│   ├── source_reputation.py     # 信源可靠性更新（InfluenceSignal）
│   └── gain_eta_adjuster.py     # 动态 gain_eta（trust_gate 输出 → BeliefEngine）
│
├── analysis/                    # 分析/训练层（重构拆分）
│   ├── kg/                      # KG 子包（从 knowledge_graph.py 34K 行拆出）
│   │   ├── builder.py           # KG 构建 + 边发现
│   │   ├── propagator.py        # 传播算法 + 衰减
│   │   ├── validator.py         # 边验证 + 置信过滤
│   │   └── runtime.py           # 推断时 KG 查询（轻量）
│   ├── features/                # 特征工程子包（从 feature_builder.py 40K 行拆出）
│   │   ├── base.py              # 基础特征定义
│   │   ├── cross_sectional.py   # 截面因子
│   │   ├── time_series.py       # 时序特征
│   │   └── pipeline.py          # 组装管道
│   ├── training/                # 训练子包（从 propagation_training.py 30K 行拆出）
│   │   ├── data_loader.py       # 数据加载（独立）
│   │   ├── trainer.py           # 模型训练逻辑
│   │   └── evaluator.py         # IC/Sharpe/回测评估
│   ├── factor_evaluation.py     # 因子 IC 分析（保留）
│   ├── sentiment_ic.py          # 情绪 IC（保留）
│   └── propagation_runtime.py   # 废弃，迁移到 factors/ + analysis/kg/runtime.py
│
├── evaluation/                  # 质量评估（重构拆分）
│   ├── __init__.py
│   ├── quality_gate.py          # QualityGate（从 service.py 剥离核心逻辑，~200 行）
│   ├── brier_evaluator.py       # Brier score 计算（独立）
│   ├── drift_detector.py        # MMD drift 检测（独立）
│   └── report_writer.py         # QualityReport 写入（独立）
│   # service.py (~70K 行) → 逐步废弃，拆为上述 4 文件
│
├── data/                        # 数据拉取层（重构 kline/service.py 等）
│   ├── market/
│   │   ├── kline/
│   │   │   ├── fetcher.py       # 仅负责从 Tushare 拉数据（新）
│   │   │   ├── persister.py     # 仅负责写 Parquet（新）
│   │   │   └── service.py       # 仅负责业务逻辑协调（缩减）
│   │   └── ...
│   └── ...
│
├── db/                          # 数据库层（重构 trade_db.py）
│   ├── trade_db.py              # 仅保留连接管理 + 薄 CRUD 接口
│   ├── migrations.py            # schema migration runner（独立）
│   ├── ebrt_crud.py             # EBRT 表 CRUD（新，从 trade_db 剥离）
│   ├── signal_crud.py           # signals/factors 表 CRUD（新）
│   └── kg_crud.py               # KG 表 CRUD（新）
│
├── signals/                     # 保留（window_scorer）
├── intelligence/                # 保留（迁移后已对齐）
├── infra/                       # 保留（settings/config）
├── bus/                         # 保留（EventBus + scheduler）
├── jobs/                        # 保留（job registry）
└── cli/                         # 保留（CLI 入口）
```

---

## 6. C++/Python 边界设计

### 现状

C++ engine 有完整实现但**零 Python binding**：

| C++ 类 | 功能 | Python 替代（当前） |
|--------|------|-----------------|
| `FeatureEngine` | 向量化技术指标（RSI/MACD/KDJ/MA） | `propagation_runtime.py` Python 循环 |
| `BacktestEngine` | 离散事件回测（BrokerSim/PortfolioState/Performance） | `propagation_training.py` Python 回测 |
| `RiskMonitor` | VaR + 集中度 + drift 检测 | Python 实现（部分） |
| `LgbmModel` + `OnnxModel` | LightGBM/ONNX 推断 | Python LightGBM 直接调用 |

### 目标边界

```
Python (business logic)          C++ (compute-intensive)
─────────────────────────────    ──────────────────────────
evidence/ (IO/parse)          →  FeatureEngine (vectorized indicators)
factors/technical.py          →  FeatureEngine.compute_batch()
factors/materializer.py       →  FeatureEngine.materialize_frame()
evaluation/drift_detector.py  →  RiskMonitor.compute_mmd()
evaluation/brier_evaluator.py →  (Python, simple math)
analysis/training/trainer.py  →  BacktestEngine (offline, CLI call)
decision/rank.py              →  (Python, thin logic)
```

### 实施路径

**Step 1**：pybind11 绑定（优先级：FeatureEngine → RiskMonitor → BacktestEngine）

```cmake
# engine/python/CMakeLists.txt（新建）
pybind11_add_module(trade_engine_ext
    bindings/feature_engine_binding.cpp
    bindings/risk_monitor_binding.cpp
)
target_link_libraries(trade_engine_ext PRIVATE trade_features trade_risk)
```

```python
# trade_py/engine/__init__.py（新建）
try:
    from trade_engine_ext import FeatureEngine, RiskMonitor
    NATIVE = True
except ImportError:
    from trade_py.engine._fallback import FeatureEngine, RiskMonitor
    NATIVE = False
```

**Step 2**：`factors/technical.py` 调用 `FeatureEngine.compute_batch()`，删除 Python 实现

**Step 3**：`evaluation/drift_detector.py` 调用 `RiskMonitor.compute_mmd()`

**Step 4**：`BacktestEngine` binding（作为离线工具，非实时路径，优先级较低）

**约束**：
- C++ binding 必须有完整 Python fallback（保证测试环境可用）
- binding 编译放在 `engine/python/`，不混入 `engine/src/`
- 接口设计以 numpy array 为主（避免 C++/Python 对象深度耦合）

---

## 7. 数据层重设计

### 现状问题

1. **`kline/service.py` 混合三种职责**：Tushare API 调用 + Parquet 写入 + 业务调度逻辑
2. **`trade_db.py`（4,192 行）**：schema DDL + CRUD + migration runner 全混合
3. **Bronze/Silver/Gold 路径规范但松散**：没有 DataContract 约束 schema 版本

### 目标设计

#### 7.1 数据拉取层拆分原则

每个数据源文件夹（kline/fund_flow/fundamental 等）遵循三文件规范：

```
market/kline/
├── fetcher.py      # 唯一职责：从外部 API 拉数据，返回 DataFrame
├── persister.py    # 唯一职责：写 Parquet，管理目录结构
└── service.py      # 唯一职责：协调 fetcher → persister，处理增量/全量逻辑
```

**规则**：`fetcher.py` 不能写磁盘；`persister.py` 不能调 API；`service.py` 不含业务计算。

#### 7.2 DB 层按职责分文件

```python
# 现状：trade_db.py 4,192 行 全混合
# 目标：

trade_py/db/
├── trade_db.py      # 仅：连接管理 + get_connection() + 公共事务辅助
│                    # 目标 ≤ 200 行
├── migrations.py    # schema DDL + migration runner（已部分独立）
├── ebrt_crud.py     # Evidence/BeliefState/Recommendation/Trust 相关 CRUD
│                    # 约 600 行（从 trade_db 剥离）
├── signal_crud.py   # signals/factors/model_registry CRUD
│                    # 约 400 行
└── kg_crud.py       # kg_relations/event_templates/market_events/event_propagations CRUD
                     # 约 400 行
```

#### 7.3 DataContract（新）

```python
# trade_py/data/contract.py（新）
from dataclasses import dataclass
from typing import ClassVar

@dataclass(frozen=True)
class GoldContract:
    """Gold 层 Parquet 必须有的列 + 类型约束"""
    REQUIRED_COLS: ClassVar = {
        "date": "object", "symbol": "object",
        "net_sentiment": "float64", "article_count": "int64",
        "novelty": "float64", "noise_penalty": "float64",
    }
    SCHEMA_VERSION: ClassVar[str] = "v1"
```

每个 `aggregate.py` 写出前调用 `GoldContract.validate(df)` — 在 `evidence/quality.py` 中已有 `ema_smooth`，可在此层加约束检查。

---

## 8. 因子层重设计

### 现状问题

1. **无 Measurement Trust**：47 个 FEATURE_COLS 均以相同权重进模型
2. **无 Utility Trust（历史 IC）**：`factor_evaluation.py` 已计算 IC，但未反馈到训练权重
3. **无数据新鲜度降权**：Gold 数据可能来自 T-3，但特征矩阵不做 staleness 惩罚
4. **`propagation_runtime.py` 6 职责混合**：技术指标计算、分类编码、因子注册、物化、持久化、推断集成

### 目标：因子元数据模型

```python
# trade_py/factors/registry.py（新）
from dataclasses import dataclass, field
from enum import Enum

class FactorType(str, Enum):
    TECHNICAL = "technical"
    SENTIMENT = "sentiment"
    EVENT = "event"
    FUNDAMENTAL = "fundamental"
    GRAPH = "graph"
    WINDOW = "window"

@dataclass
class FactorMeta:
    name: str
    factor_type: FactorType
    description: str
    # 测量信任：数据源可靠性 × 新鲜度
    measurement_trust: float = 1.0     # [0, 1]
    # 效用信任：历史 rank IC（滚动 60 天中位数）
    utility_trust: float = 0.5         # [0, 1]
    # 数据过期惩罚（天数 → staleness 系数）
    staleness_days: int = 0
    staleness_decay: float = 1.0       # = exp(-staleness_days / 5)

    @property
    def composite_trust(self) -> float:
        """因子综合信任 = measurement × utility × staleness_decay"""
        return self.measurement_trust * self.utility_trust * self.staleness_decay
```

### 目标：`propagation_runtime.py` 拆分

| 原职责 | 目标文件 | 行数预估 |
|--------|---------|---------|
| 技术指标计算（RSI/MACD/KDJ/MA） | `factors/technical.py` | ~120 行（→ C++ FeatureEngine） |
| 分类特征编码 | `factors/categorical.py` | ~40 行 |
| 因子注册管理 | `factors/registry.py` | ~80 行 |
| 特征矩阵物化 | `factors/materializer.py` | ~150 行 |
| 持久化写入 | `db/signal_crud.py` | 合并到 DB 层 |
| 推断集成 | `decision/inference_bridge.py` | ~60 行 |

### 目标：因子信任反馈

```
factor_evaluation.py 每周运行：
  → 更新 FactorMeta.utility_trust（滚动 60 天 rank IC 中位数）
  → 写入 factor_registry 表（新增 utility_trust 列）

factors/materializer.py 构建特征矩阵时：
  → 按 composite_trust 对特征加权（或作为 sample_weight 传给 LightGBM）
  → staleness_days > 5 的因子降权到 0.3
```

---

## 9. Trust 层重设计

### 现状

- `QualityReport.metrics_json` 包含 `trust_scalar=0.7501`，但 `trust_components={}` 为空
- 7 分量 Trust 向量（T_fresh/T_evidence/T_model/T_calib/T_drift/T_ops/T_explain）仅定义于 `RecommendationTrace.trust_json` schema，**未实际计算**
- 无独立 Trust 服务，无 Trust 时序历史，不可按分量查询
- `BeliefEngine` 的 `gain_eta` 是硬编码常数，未受 trust_gate 调节

### 目标架构

```
evaluate_daily 运行后：
  TrustService.compute(date) → TrustVector(7 分量) → 写 QualityReport.trust_components
  TrustGate.to_gain_eta(trust_vector) → float → 传给下一天 BeliefEngine
```

#### 9.1 Trust 7 分量计算规范

| 分量 | 来源 | 计算方法 |
|------|------|---------|
| `T_fresh` | `FreshnessStatus` 表 | 数据集新鲜度加权均值；任一核心数据集 > 3 天则 < 0.5 |
| `T_evidence` | `Evidence` 表 | 当日 evidence_count / 历史均值（最近 20 天）；首日 = 0.5 |
| `T_model` | `model_registry` | 最新模型 val_score vs threshold；无模型 = 0.3 |
| `T_calib` | `QualityReport.brier_score` | `1 - clip(brier_score, 0, 0.5) × 2`；Brier=0 → T_calib=1 |
| `T_drift` | `QualityReport.drift_mmd` | `exp(-5 × drift_mmd)`；MMD=0 → T_drift=1 |
| `T_ops` | `job_runs` 表 | 当日所有 job 的成功率；失败 > 2 个则 < 0.5 |
| `T_explain` | `RecommendationTrace` | narrative_text 非空率 × top_evidence_json 质量 |

#### 9.2 trust_scalar 聚合

```python
TRUST_WEIGHTS = {
    "T_fresh": 0.20, "T_evidence": 0.15, "T_model": 0.20,
    "T_calib": 0.20, "T_drift": 0.10, "T_ops": 0.10, "T_explain": 0.05,
}

trust_scalar = sum(v * TRUST_WEIGHTS[k] for k, v in trust_components.items())
```

#### 9.3 TrustGate → gain_eta 动态调节

```python
# trust/gate.py
def to_gain_eta(trust_scalar: float, base_eta: float = 0.15) -> float:
    """
    trust_scalar ∈ [0, 1] → gain_eta ∈ [0.05, 0.25]
    低信任 → 保守更新；高信任 → 激进更新
    """
    return base_eta * (0.33 + 1.33 * trust_scalar)
    # trust=0.0 → eta=0.05, trust=0.5 → eta=0.15, trust=1.0 → eta=0.25
```

#### 9.4 BeliefEngine 集成

```python
# belief/__init__.py（修改）
def run_belief_update(date_str, data_root):
    trust = db.trust_scalar_get(yesterday)           # 读取昨日 trust
    gain_eta = TrustGate.to_gain_eta(trust or 0.5)  # 首日默认 0.5
    engine = BeliefEngine(gain_eta=gain_eta)
    engine.run(date_str, data_root)
```

---

## 10. 分阶段迁移计划

### Phase 1：超大文件拆分（紧急）

**目标**：消除 `evaluation/service.py`（~70K 行）、`analysis/feature_builder.py`（40K 行）、`analysis/knowledge_graph.py`（34K 行）这三个无法维护的巨型文件。

**产出**：
- `evaluation/` → `quality_gate.py` + `brier_evaluator.py` + `drift_detector.py` + `report_writer.py`
- `analysis/kg/` → `builder.py` + `propagator.py` + `validator.py` + `runtime.py`
- `analysis/features/` → `base.py` + `cross_sectional.py` + `time_series.py` + `pipeline.py`
- `analysis/training/` → `data_loader.py` + `trainer.py` + `evaluator.py`

**验证**：`python3 -c "from trade_py.evaluation.quality_gate import run_evaluate_daily; print('ok')"`

**时长估计**：中（需要仔细阅读原文件逻辑后分类）

---

### Phase 2：Trust 层实现

**目标**：`trust_components` 从空 dict 变为 7 个有值分量；`gain_eta` 动态化。

**产出**：
- `trade_py/trust/` 包（新建，含 7 个分量计算模块 + gate.py）
- `TrustService.compute(date)` 写入 `QualityReport.trust_components`（填充 7 个分量）
- `BeliefEngine.__init__` 接受 `gain_eta` 参数（从 TrustGate 传入）
- `feedback/gain_eta_adjuster.py`（新建）

**验证**：
```sql
-- 应有 7 个非空 key
SELECT json_extract(metrics_json,'$.trust_components') FROM QualityReport ORDER BY eval_date DESC LIMIT 1;
```

**时长估计**：中

---

### Phase 3：因子层重构

**目标**：`propagation_runtime.py` 的 6 职责分离到 4 个专责文件；引入因子信任元数据。

**产出**：
- `trade_py/factors/` 包（新建）
  - `registry.py`：FactorMeta + composite_trust
  - `technical.py`：技术指标（调用 C++ FeatureEngine 或 Python fallback）
  - `categorical.py`：分类编码
  - `materializer.py`：特征矩阵构建（带信任加权）
- `db/signal_crud.py`：因子写入逻辑迁移到此
- `propagation_runtime.py` 保留为兼容 shim（转发到新 factors/ 包），最终废弃

**验证**：
```bash
trade event run build_features  # 应正常运行，因子 IC 保持不变
```

**时长估计**：长（涉及训练路径，需回测验证）

---

### Phase 4：C++ Binding + Feedback 回路

**目标**：FeatureEngine 的技术指标计算从 Python 迁移到 C++；Feedback 回路闭合。

**产出**：
- `engine/python/` 目录（新建 pybind11 bindings）
  - `feature_engine_binding.cpp`
  - `risk_monitor_binding.cpp`
- `trade_py/engine/__init__.py`：Python fallback 接口
- `factors/technical.py` → 调用 `trade_engine_ext.FeatureEngine.compute_batch()`
- `evaluation/drift_detector.py` → 调用 `trade_engine_ext.RiskMonitor.compute_mmd()`
- `feedback/` 包（新建）：Brier scorer + source reputation + gain_eta adjuster

**验证**：
```python
from trade_py.engine import FeatureEngine, NATIVE
print(f"Native C++ binding: {NATIVE}")  # 目标: True
```

**时长估计**：长（需要 C++ 编译环境 + pybind11 集成测试）

---

## 11. Top-10 重构优先级清单

| # | 文件/模块 | 问题 | 行动 | 优先级 |
|---|---------|------|------|-------|
| 1 | `evaluation/service.py` | **~70,982 行** — 无法 review、无法测试 | 拆分为 4 个专责文件 | 🔴 P0 |
| 2 | `analysis/feature_builder.py` | **40,021 行** — 特征工程巨型单文件 | 拆分为 `analysis/features/` 子包 | 🔴 P0 |
| 3 | `analysis/knowledge_graph.py` | **34,724 行** — KG 读写传播全混合 | 拆分为 `analysis/kg/` 子包 | 🔴 P0 |
| 4 | `QualityReport.trust_components={}` | Trust 7 分量未实际计算 | 实现 `trade_py/trust/` 包 | 🟠 P1 |
| 5 | `propagation_runtime.py` (527 行, 6 职责) | 无法单独测试任何职责 | 拆分为 `factors/` 下 4 个文件 | 🟠 P1 |
| 6 | 因子无信任元数据 | 47 个因子等权，历史 IC 未反馈 | 实现 `FactorMeta + composite_trust` | 🟠 P1 |
| 7 | `gain_eta` 硬编码 | Feedback 回路未闭合 | `TrustGate.to_gain_eta()` + `BeliefEngine` 集成 | 🟡 P2 |
| 8 | `analysis/propagation_training.py` (29,693 行) | 训练/数据/评估全混合 | 拆分为 `analysis/training/` 子包 | 🟡 P2 |
| 9 | `db/trade_db.py` (4,192 行) | schema+CRUD+migration 全混合 | 按职责拆分为 4 个 CRUD 文件 | 🟡 P2 |
| 10 | C++ engine 无 Python binding | FeatureEngine/RiskMonitor 已有实现但闲置 | pybind11 binding（Phase 4） | 🟢 P3 |

---

## 12. 不重构的最大风险

### 风险 1：`evaluation/service.py`（~70K 行）崩溃无法修复

这是最高风险。当 EvaluationService 出现 bug 时，在 70,000 行中定位问题需要数小时。任何 PR diff 都会超过 GitHub 渲染限制。**一次线上 Trust 计算错误可能导致连续数周推荐结果质量下降但无法察觉。**

### 风险 2：Trust 7 分量空值 → Trust 无法区分"好推荐"与"无数据推荐"

当前 `trust_components={}` 意味着 trust_scalar=0.75 可能来自"7 个分量均良好"，也可能来自"根本没有计算，直接返回默认值"。这使 Trust 丧失了其核心价值：作为推荐质量的可解释指标。

### 风险 3：C++ engine 闲置 → 性能天花板

`propagation_runtime.py` 用 Python 循环计算 RSI/MACD/KDJ，对 5,000 只股票每次运行约需 2–5 分钟。C++ FeatureEngine 已经实现并可做到 <5 秒。随着 universe 扩大（全 A 股 5,300+），Python 实现将成为日常运行瓶颈。

### 风险 4：`analysis/knowledge_graph.py`（34K 行）成为"禁区"

没有人能在合理时间内审阅这个文件。一旦 KG 传播结果异常（如 event_kg_score 全为 0），调试时间将以天计。该文件事实上已成为"不可修改的黑盒"，与拥有它的目的（可靠的 KG 传播评分）背道而驰。

### 风险 5：Feedback 回路未闭合 → 信念系统不学习

`InfluenceSignal.reputation_score` 每天更新，但 `BeliefEngine` 的 `gain_eta` 是硬编码常数。这意味着：即使某信源连续 30 天预测错误，BeliefEngine 仍以相同权重接受其证据。系统没有自我修正能力。

### 风险 6：因子无信任 → 模型无法感知数据质量退化

当 Gold 数据因 RSS 抓取失败而停滞（staleness_days=3），`propagation_runtime.py` 仍会将陈旧的 `net_sentiment` 以满权重输入模型。模型会在不知情的情况下基于过时数据做出推荐，Trust 层也无法感知（因为 T_fresh 分量未实现）。

### 风险 7：`propagation_training.py`（30K 行）导致模型迭代周期极长

每次想修改训练逻辑（如加入新因子、调整 label 生成方式），都需要在 30,000 行代码中找到正确位置。一次"简单的"特征新增可能需要半天才能完成，导致模型迭代速度严重受限。

---

*文档结束。实施前请逐 Phase 评审，每个 Phase 独立提交并通过 CI 验证。*
