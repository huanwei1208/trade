# EBRT 系统改造计划（最终版）

> 基于 EBRT.pdf — Evidence → Belief → Recommendation → Trust

## 核心主题

将 trade 系统从"命令蔓延的 DAG"升级为 EBRT 架构。

| 痛点 | 改造 |
|------|------|
| 命令太多（CLI imports 10+ domains） | Engine API 作为唯一入口，CLI 变薄壳 |
| DAG nodes 调用 CLI 命令（如 `_sentiment.main`） | Jobs 直接调用 `engine.*` 函数 |
| 表太多、逻辑散落 | 引入 EBRT 规范表，折叠运维表到 `ops_*` 命名空间 |

---

## 进度

### Phase 1 — Engine API skeleton
- [x] docs/05_plan_EBRT_01.md 创建（本文件）
- [x] trade_py/engine/__init__.py 新建（8 个函数签名 + thin wrappers）
- [x] 验证：engine.run_node() 可调用
- [x] 提交: feat(ebrt): Phase 1

### Phase 2 — Jobs 去 CLI 化
- [x] _job_sentiment_fetch 调 engine.ingest_articles（去除 cli._sentiment.main）
- [x] _job_sentiment_pipeline 同步修复
- [x] 验证：trade event run sentiment_fetch 正常
- [x] 提交: feat(ebrt): Phase 2

### Phase 3 — BeliefState 表 + BeliefEngine
- [x] migration v13 DDL（10 张表）
- [x] trade_db.py CRUD（article_event/evidence/belief_state/attention/transition）
- [x] trade_py/belief/ 包（4 文件）
- [x] belief_update job 注册 + BELIEF_UPDATED topic
- [ ] 验证：BeliefState >100 行；AttentionScore 有记录
- [x] 提交: feat(ebrt): Phase 3

### Phase 4 — Recommendation + Trace
- [x] trade_db.py CRUD（recommendation/trace/quality_report/freshness）
- [x] trade_py/decision/ 包（3 文件）
- [x] recommend job 注册（消费 BeliefState）
- [x] FreshnessStatus 每日写入
- [ ] 验证：Recommendation >0 行；RecommendationTrace >0 行
- [x] 提交: feat(ebrt): Phase 4

### Phase 5 — UI 展示
- [x] /api/today-page 带 trust_gate
- [x] GET /api/belief/{symbol} 新端点
- [x] /api/kline 附加 belief_overlay + ebrt_recommendation
- [x] Today Trust Gate 状态栏
- [x] Picks 展开 belief delta + top evidence（EBRT source 分支表头 + 展开行）
- [x] styles.css Trust badge + delta 可视化
- [x] KlineData 类型扩展 belief_overlay / ebrt_recommendation
- [ ] 验证：serve 后浏览器可见 Trust Gate + belief delta
- [x] 提交: feat(ebrt): Phase 5

### Phase 6 — Trust 加固 + 清理
- [x] QualityReport Brier + MMD 写入（evaluate_daily）
- [x] InfluenceSignal 写入（feed_scorer）
- [x] influence_score job（周级）
- [x] trade daily / trade ops / trade dev 命令族
- [ ] 验证：QualityReport brier_score 字段存在
- [x] 提交: feat(ebrt): Phase 6

---

## 目标架构：新增 5 个包

```
trade_py/
├── evidence/          ← Bronze→Silver→Gold 整合
├── belief/            ← BeliefState 更新引擎（全新）
│   ├── __init__.py    ← BeliefEngine.run(asof_date, data_root, db)
│   ├── attention.py   ← 符号 attention logit 计算
│   ├── update.py      ← 残差更新（decay + gain + conflict）
│   └── conflict.py    ← 冲突检测 + AGM 保守主义
├── decision/          ← 推荐决策层
│   ├── __init__.py    ← produce_recommendations()
│   ├── rank.py        ← coarse→fine 排序
│   └── explain.py     ← reasons_json 生成
├── ops/               ← 运维基础设施（整合）
└── engine/            ← 唯一可执行 API（全新，薄层）
    └── __init__.py    ← run_node(), run_daily(), update_belief(), produce_picks()
```

---

## EBRT DB 表（migration v13，10 张）

1. `ArticleEvent` — Silver 行规范化
2. `InfluenceSignal` — 信源影响力
3. `Evidence` — 规范化证据单元（symbol/day 粒度）
4. `BeliefState` — 每日每 symbol 的信念快照
5. `AttentionScore` — 注意力权重（可解释审计）
6. `BeliefTransition` — 残差更新记录
7. `Recommendation` — 每日决策输出
8. `QualityReport` — Trust 合同
9. `FreshnessStatus` — 每数据集新鲜度
10. `RecommendationTrace` — 端到端溯源

---

## Attention Logit 公式

```
ℓ_{t,s,i} = α·σ_i            # 兼容分（方向相似度）
           + β·log(1 + m_i)   # 幅度
           + γ·log(ε + r_i)   # 可靠性
           + δ·log(ε + n_i)   # 新颖度
           − κ·log(ε + ν_i)   # 噪声惩罚
           + ξ·log(ε + u_i)   # 影响力加成
           − ρ·conflict(i, b) # 与当前信念冲突惩罚

w_{t,s,i} = softmax(ℓ / τ)
b_{t+1,s} = (1−λ)·b_{t,s} + η_{t,s}·Σ w_{t,s,i}·Δ(e_{t,s,i})
```

---

## 实施 Gantt

```
Mar 18-19  基准冻结（tag current + golden tests）
Mar 19-22  Phase 1: Engine API skeleton          ✓
Mar 22-26  Phase 2: Jobs 调 engine（去除 CLI 调用）✓
Mar 26-30  Phase 3: BeliefState 表 + attention    ✓
Mar 30-Apr 3  Phase 4: Recommendation + Trace     ✓
Apr 3-10   Phase 5: UI Today/Picks/Pipeline 展示 trace
Apr 7-14   Phase 6: Trust 加固 + schema 清理
```
