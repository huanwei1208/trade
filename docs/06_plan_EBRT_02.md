# EBRT_02 系统深化计划

## 背景

EBRT_01 已实现（Phase 1-6 完成）：
- Engine API (run_node/run_daily/update_belief/produce_picks/evaluate_daily)
- 10张 EBRT 表（v13 migration）：ArticleEvent/InfluenceSignal/Evidence/BeliefState/AttentionScore/BeliefTransition/Recommendation/QualityReport/FreshnessStatus/RecommendationTrace
- BeliefEngine：attention logit + residual update + conflict detection
- Decision 层：三因子排序（belief_mu + window_score + event_kg_score）
- Trust Gate：Brier + MMD drift + 运营/研究状态
- UI：Today Trust Gate 条 + EBRT picks 展示 + belief delta 显示

**EBRT_02.pdf 的新要求（delta）：**

| 差距 | EBRT_02 规范 | 当前状态 |
|------|-------------|----------|
| 多时间跨度信念 | BeliefState (symbol, as_of_date, **horizon**) PK；μ_1d/5d/20d | 只有单一 mu/sigma |
| 7维 Trust 向量 | T_fresh/evidence/model/calib/drift/ops/explain → T*=σ(w^T·φ) | 只有 op/research 两态 |
| 奖惩反馈循环 | per-source 可靠性权重用 Brier loss 指数更新 | InfluenceSignal 写了但无更新 |
| Evidence 正式包 | trade_py/evidence/ (ingest/enrich/aggregate) formal API | 仍调 data/pipeline/*.py |
| NodeRegistry | 节点 = 纯函数（显式 inputs→outputs） | jobs/__init__.py 仍有 CLI 耦合 |
| Recommendation 扩展 | expected_return_5d, risk_5pct, position_weight, horizon_set_json | 缺这些字段 |
| RecommendationTrace | trust_json（7分量）+ narrative_text | 只有 top_evidence + fingerprint |
| Gold 层去噪 | EMA/Kalman 平滑日级情绪聚合 | 无平滑 |

---

## 优先级决策

按**影响大小 × 可行性**排序，分4个 Phase：

---

## Phase A：多时间跨度 BeliefState + 扩展字段（v14 migration）✅

**目标**：让信念系统支持 1d/5d/20d 三个时间跨度，让 Recommendation 和 Trace 有完整字段。

### A1. DB Schema 变更（migration v14）

```sql
-- BeliefState 新增 horizon 列（不改 PK，用 belief_vec_json 内字段区分）
-- 策略：belief_vec_json 扩展为 {"mu_1d":..., "mu_5d":..., "mu_20d":...,
--                               "sigma_1d":..., "sigma_5d":..., "sigma_20d":...,
--                               "p_up_5d":..., "p_down_5d":...}
-- PK 保持 (as_of_date, symbol) 不变，避免大量数据迁移
-- 旧的 "mu"/"sigma" 字段作为 mu_5d/sigma_5d 向后兼容

-- Recommendation 新增列
ALTER TABLE Recommendation ADD COLUMN expected_return_5d REAL;
ALTER TABLE Recommendation ADD COLUMN risk_5pct REAL;
ALTER TABLE Recommendation ADD COLUMN position_weight REAL;
ALTER TABLE Recommendation ADD COLUMN horizon_set_json TEXT;

-- RecommendationTrace 新增列
ALTER TABLE RecommendationTrace ADD COLUMN trust_json TEXT;
ALTER TABLE RecommendationTrace ADD COLUMN narrative_text TEXT;
```

### A2. 修改文件

| 文件 | 变更 |
|------|------|
| `trade_py/db/migrations.py` | `_migrate_v14()`: ALTER TABLE 4 条 + 更新 schema_migrations |
| `trade_py/db/trade_db.py` | `belief_state_upsert` 接受扩展 belief_vec；`recommendation_upsert` 增加 expected_return_5d/risk_5pct/position_weight；`recommendation_trace_upsert` 增加 trust_json/narrative_text |
| `trade_py/belief/update.py` | `residual_update` 输出 mu_1d/5d/20d/sigma_1d/5d/20d（1d=0.3×mu，5d=mu，20d=0.7×mu 线性近似，Phase B 再用真实 KG 数据） |
| `trade_py/decision/rank.py` | `rank_symbols` 利用 mu_5d（默认）做排序；输出 expected_return_5d = mu_5d；horizon_set_json = {"1d": mu_1d, "5d": mu_5d, "20d": mu_20d} |
| `trade_py/decision/explain.py` | `build_reasons` 写 narrative_text（中文段落） |

### A3. 验证

```bash
python3 -c "import sqlite3,conn=sqlite3.connect('data/.db/trade.db'); print(conn.execute('SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1').fetchone())"
# → 14
```

**提交**：`feat(ebrt): Phase A — multi-horizon belief fields + extended Recommendation/Trace schema (v14)` ✅ `40885d8`

---

## Phase B：7维 Trust 向量 ✅

**目标**：把当前"运营/研究"两态改为 EBRT_02 定义的 7 分量 Trust 向量，collapsed 为标量 T*。

### Trust 向量定义

```
Trust = (T_fresh, T_evidence, T_model, T_calib, T_drift, T_ops, T_explain)

T_fresh    = 1 - max(lag_days) / 7           # FreshnessStatus.lag_days
T_evidence = mean(reliability) from Evidence  # 当日 Evidence.reliability 均值
T_model    = clip(rank_ic_5d / 0.05, 0, 1)   # 来自 evaluation
T_calib    = 1 - brier_score                  # QualityReport.brier_score
T_drift    = 1 - clip(drift_mmd / 0.2, 0, 1) # QualityReport.drift_mmd
T_ops      = 1 - pipeline_error_rate          # job_runs 中 error/total
T_explain  = trace_completeness               # 有 RecommendationTrace 的比例

T* = sigmoid(w^T · φ(Trust))  # 初期 w=[1,0.8,1,1,0.8,0.6,0.4] 等权，φ=identity
```

### 修改文件

| 文件 | 变更 |
|------|------|
| `trade_py/evaluation/service.py` | `_compute_trust_vector(db, eval_date) → dict` 返回 7 分量；`_scalar_trust(vec) → float` sigmoid 加权；`_write_quality_report` 把 trust_json 写入 QualityReport.metrics_json |
| `trade_py/decision/explain.py` | `build_trace_trust_json(db, rec_id, asof)` 从 7 分量生成 per-rec trust_json 写到 RecommendationTrace |
| `trade_web/backend/app.py` | `/api/today-page` trust_gate 新增 `trust_scalar: float` + `trust_components: dict` |
| `trade_web/frontend/src/App.tsx` | Today Trust Gate 条显示 T*=0.xx 标量 + 7 分量进度条 |
| `trade_web/frontend/src/styles.css` | `.trust-scalar-badge` + `.trust-components-row` + `.trust-component-item` 样式 |

**提交**：`feat(ebrt): Phase B — 7-component Trust vector T*(fresh/evidence/model/calib/drift/ops/explain)` ✅ `f3f865a`

---

## Phase C：奖惩反馈循环（Source 可靠性在线学习）✅

**目标**：根据 Recommendation 结果 vs 实际收益，用 Brier loss 指数更新 per-source 可靠性权重，闭合反馈环。

### 算法（来自 EBRT_02.pdf §Reward/penalty）

```python
# 每日 outcome 到达后（T+5 天收益已知）：
for source_id in active_sources:
    recs_T5 = db.recommendation_list(date_T5)  # 5天前的推荐
    actual = fetch_actual_return_5d(symbol)     # 从 event_propagations
    brier = (rec.score - int(actual > 0)) ** 2
    # 指数权重更新：w_new = w_old * exp(-lr * brier)
    # 归一化保持 Σw = 1
    feed_scorer.update_source_reliability(source_id, brier, lr=0.1)
```

### 修改文件

| 文件 | 变更 |
|------|------|
| `trade_py/db/trade_db.py` | `source_reliability_upsert(source_id, reliability, eval_date)` + `source_reliability_get(source_id)` — 写/读 InfluenceSignal 的 reputation_score |
| `trade_py/intelligence/feed_scorer.py` | `update_source_reliability(source_id, brier_loss, lr)` — 指数权重更新；`get_source_reliability(source_id) → float` |
| `trade_py/evaluation/service.py` | `_update_source_reliabilities(db, eval_date)` — 遍历 T-5 推荐，查 actual_return_5d，调 feed_scorer.update |
| `trade_py/jobs/__init__.py` | `_job_reliability_update()` — 每日 COMPUTE 阶段；注册 `reliability_update` job |
| `trade_py/belief/attention.py` | `compute_logits` 读取 per-source 更新后的 reliability；`influence_boost` 改为动态读 source_reliability |

**提交**：`feat(ebrt): Phase B — 7-component Trust vector T*(...)` ✅ `f3f865a`（与 Phase B 合并提交）

---

## Phase D：trade_py/evidence/ 正式包 ✅

**目标**：为 Bronze→Silver→Gold 建立正式的 Evidence API，把 data/pipeline/*.py 包装进来，让 engine.py 用 evidence.* 而非直接调 CLI。

### 新建文件

```
trade_py/evidence/
├── __init__.py     ← EvidenceAPI: run_ingest(), run_enrich(), run_aggregate()
├── ingest.py       ← wrap engine.ingest_articles → run_ingest(date_from, date_to, ...) → dict
├── enrich.py       ← wrap engine.build_silver → run_enrich(asof_date, ...) → dict
├── aggregate.py    ← wrap engine.build_gold + EMA smoothing → run_aggregate(asof_date, ...) → dict
└── quality.py      ← EMA/Kalman 平滑情绪聚合（Gold 级去噪）
```

### evidence/quality.py — Gold 层 EMA 去噪

```python
# Kalman-style EMA 平滑（一阶）
def ema_smooth(series: list[float], alpha: float = 0.3) -> list[float]:
    """Apply EMA smoothing to sentiment/evidence time series."""
    ...

def smooth_gold_sentiment(asof_date: str, data_root: str) -> dict:
    """Read Gold parquet for date window, apply EMA to net_sentiment, write back."""
    ...
```

**提交**：`feat(ebrt): Phase D — trade_py/evidence/ formal package wrapping Bronze/Silver/Gold with EMA smoothing` ✅ `d7a391d`

---

## 实施顺序（已完成）

```
Phase A（v14 schema）→ Phase B（Trust vector）→ Phase C（反馈循环）→ Phase D（evidence 包）
```

所有 Phase 独立提交，按序实施。

---

## 不做的事（范围外）

- C++ 加速（engine/vendor/re2 已有，但 belief state_store/attention 不做）
- NodeRegistry 完整替换（jobs 已足够，保持现有结构）
- A/B 影子模式（优先级低，等 Phase C 稳定后再考虑）
- trade_py/ops/ 包迁移（不值得重构，ops 命令已有）
- Transformer embedding（不引入 NN，保持符号式）

---

## 关键文件

| 文件 | Phase |
|------|-------|
| `trade_py/db/migrations.py` | A |
| `trade_py/db/trade_db.py` | A, B, C |
| `trade_py/belief/update.py` | A |
| `trade_py/decision/rank.py` | A |
| `trade_py/decision/explain.py` | A, B |
| `trade_py/evaluation/service.py` | B, C |
| `trade_py/intelligence/feed_scorer.py` | C |
| `trade_py/jobs/__init__.py` | C |
| `trade_py/belief/attention.py` | C |
| `trade_py/evidence/__init__.py` | D |
| `trade_py/evidence/ingest.py` | D |
| `trade_py/evidence/enrich.py` | D |
| `trade_py/evidence/aggregate.py` | D |
| `trade_py/evidence/quality.py` | D |
| `trade_web/backend/app.py` | B |
| `trade_web/frontend/src/App.tsx` | B |
| `trade_web/frontend/src/styles.css` | B |

---

## 验证 checklist

Phase A:
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('data/.db/trade.db')
print(conn.execute('SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1').fetchone())
cols = [r[1] for r in conn.execute('PRAGMA table_info(Recommendation)').fetchall()]
print('expected_return_5d:', 'expected_return_5d' in cols)
"
# version: 14, expected_return_5d: True
```

Phase B:
```bash
python3 -c "
from trade_py.evaluation.service import _compute_trust_vector, _scalar_trust
print('trust vector functions: ok')
"
# trade ops status  →  trust_scalar=0.xx
# curl http://localhost:8080/api/today-page | python3 -m json.tool | grep trust_scalar
```

Phase C:
```bash
python3 -c "from trade_py.jobs import JOB_REGISTRY; print('reliability_update' in JOB_REGISTRY)"
# trade event run reliability_update
```

Phase D:
```bash
python3 -c "from trade_py.evidence import run_ingest; print('ok')"
python3 -c "from trade_py.evidence.quality import smooth_gold_sentiment; print('ok')"
```
