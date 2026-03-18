# Trade Web UI 重构计划（v3）

## Context

系统本质是**每日决策辅助**：原始数据 → 计算信号 → 告诉你做什么。
当前 UI 按"数据管道"组织（Report/Events/KG），与用户决策流不匹配。

核心重构方向：
1. **Tab 重组**：3 个以决策为中心的 tab
2. **推荐系统**：信号 → 有解释的推荐（含 delta：新出现/持续/转弱）
3. **Job 配置化**：粒度可拆分、参数可从 UI 配置
4. **时域感知**：DAG 节点同时展示"执行时间"和"数据时间"，支持回补

---

## 一、Tab 结构（3 个）

| Tab | 回答的问题 |
|-----|----------|
| **今日** | 今天需要知道什么？市场 + pipeline + 今日推荐 |
| **选股** | 具体看哪只？推荐理由 + K线 + 预测 |
| **流水线** | 哪个节点在跑/失败/数据缺失？ |

---

## 二、推荐系统设计（召回 → 粗排 → 精排 → 解释）

### 当前问题
`signal_suggest()` 是单阶段按 score 排名，没有：
- 多源召回（事件驱动的股票 vs 纯技术面的股票混在一起）
- 今天"新出现"还是"持续"在列的 delta
- 为什么推荐的具体证据和历史支撑

### 三阶段推荐流水线

```
召回 (Recall) ~500支
  ├── 模型召回：model_score > 0.5 → top 200
  ├── 事件召回：event_affected=1 AND kg_score > 0.6 → 全部
  ├── 技术召回：window_score > 70 → top 200
  └── 关注列表：watchlist 全量（不过滤）

粗排 (Coarse Rank) ~50支
  加权：0.4×model + 0.3×window + 0.3×kg
  过滤：排除 net_sentiment < -0.5（强负情绪）
  去重：union，按粗排分降序取 top 50

精排 (Fine Rank) ~10-20支
  risk 惩罚：score × (1 - model_risk × 0.5)
  板块多样性：sector_limit=3（现有逻辑复用）
  delta bonus：新出现的股票 +5分

解释生成 (Explain)
  对精排每支股票生成 3 层理由
```

### 新增方法：signal_recommend()

```python
# trade_py/db/trade_db.py
def signal_recommend(self, limit: int = 20) -> dict:
    """三阶段推荐 + delta + 理由骨架"""
    # 召回
    model_pool = self._signal_recall("model_score", 200, threshold=0.5)
    event_pool = self._signal_recall_event(kg_threshold=0.6)
    tech_pool  = self._signal_recall("window_score", 200, threshold=70)
    watch_pool = [r["symbol"] for r in self._conn.execute(
        "SELECT symbol FROM watchlist WHERE active=1"
    ).fetchall()]

    # 合并去重，粗排
    all_syms = {r["symbol"]: r for pool in [model_pool, event_pool, tech_pool]
                for r in pool}
    for sym in watch_pool:
        all_syms.setdefault(sym, self._signal_get_latest(sym))

    coarse = sorted(all_syms.values(),
        key=lambda r: 0.4*(r.get("model_score") or 0)
                    + 0.3*(r.get("window_score") or 0)/100
                    + 0.3*(r.get("event_kg_score") or 0)/100,
        reverse=True
    )
    coarse = [r for r in coarse if (r.get("net_sentiment") or 0) >= -0.5][:50]

    # Delta：与昨日 top-N 比较
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    yest_syms = {row["symbol"] for row in self._conn.execute(
        "SELECT symbol FROM signals WHERE date=? ORDER BY model_score DESC LIMIT 50",
        (yesterday,)
    ).fetchall()}

    # 精排
    fine = []
    sector_count: dict[int, int] = {}
    for r in coarse:
        sector = r.get("industry", 255)
        if sector_count.get(sector, 0) >= 3:
            continue
        risk = r.get("model_risk") or 0.1
        adj_score = (0.4*(r.get("model_score") or 0)
                   + 0.3*(r.get("window_score") or 0)/100
                   + 0.3*(r.get("event_kg_score") or 0)/100) * (1 - risk * 0.5)
        status = "new" if r["symbol"] not in yest_syms else "continued"
        if status == "new":
            adj_score += 0.05
        fine.append({**r, "adj_score": adj_score, "status": status})
        sector_count[sector] = sector_count.get(sector, 0) + 1
        if len(fine) >= limit:
            break

    fine.sort(key=lambda x: x["adj_score"], reverse=True)

    # 今日跌出的（供参考）
    fine_syms = {r["symbol"] for r in fine}
    dropped = [{"symbol": s} for s in yest_syms if s not in fine_syms][:5]

    return {"picks": fine, "dropped": dropped}
```

### 详细推荐理由（build_recommendation_context）

每只推荐股票生成 3 层解释：

**1. 事件层**（event_propagations JOIN market_events）
```sql
SELECT AVG(ep.actual_return_5d) AS hist_ret_5d,
       COUNT(*) AS hist_count, ep.rel_path, ep.kg_score
FROM event_propagations ep
JOIN market_events me ON ep.event_id = me.event_id
WHERE ep.symbol = :symbol
  AND me.event_type = :event_type
  AND ep.actual_return_5d IS NOT NULL
```
→ "policy 事件，历史12次均5日超额 +2.8%，传导路径: 政策→银行"

**2. 技术层**（kline parquet）
- RSI-14：从 tail 30 OHLCV 内联计算
- 量比：vol_today / vol_20d_avg
- 距52周低点：(close - low_52w) / (high_52w - low_52w)

**3. 资金情绪层**（signals 表）
- large_order_net_ratio 近3日均值（从 fund_flow parquet）
- net_sentiment 方向变化（昨日 vs 今日）

**生成文案（规则模板，非 AI）**：
```python
if hist_count > 3 and hist_ret_5d > 1.5:
    reasons.append(f"{event_type} 事件，历史{hist_count}次均5日收益 +{hist_ret_5d:.1f}%")
if rsi < 45:
    reasons.append(f"RSI {rsi:.0f}，接近超卖，低位机会")
if vol_ratio < 0.8:
    reasons.append(f"近期缩量（量比 {vol_ratio:.2f}），低位蓄势")
if net_sent_delta > 0.2:
    reasons.append(f"情绪由负转正（{sent_prev:.2f}→{sent_curr:.2f}）")
```

---

## 三、实时数据架构（流式 + 增量）

### 核心分层策略

| 层 | 更新频率 | 触发方式 | 模型影响 |
|----|---------|---------|---------|
| K线（日K） | 盘后一次 | gate.market_close | 全量重算 window_score |
| K线（10分钟K） | 09:30-15:00 每10分钟 | gate.intraday（降频） | 更新技术分量 C/D |
| 文章/情绪 | 有新文章即触发 | 轮询 + 去重 | 更新情绪分量 E |
| 模型 | 每周日 | gate.model_weekly | 不变，保持周级重训 |

**模型实时训练的结论**：LightGBM 不支持 online learning。实际策略：
- **模型层**（LightGBM）：保持周级全量重训，不改
- **信号层**：特征实时更新 → 用已训练模型做推理 → 信号自动更新
- **情绪层**：文章到达 → 立刻评分 → 更新 E 分量 → 影响 window_score

### K线：10分钟降采样

当前 `realtime_quote_sync` 每分钟运行，改为可配置窗口：

```python
# pipeline_dag: realtime_quote_sync 的 config_json 示例
{
  "interval_minutes": 10,   # 降采样间隔（可在 UI 配置）
  "symbols_limit": 50,      # 关注列表上限
  "trading_hours": ["09:30", "15:00"],  # A股
  "region": "CN"
}
```

DAG 中，`gate.intraday` 通过 `interval_minutes` 判断是否触发，而不是每分钟都运行所有 job。

### 文章：事件驱动拉取

新增 `sentiment_fetch` 作为独立 streaming 节点（从 sentiment_pipeline 拆出后）：

```python
# 工作模式：
# - batch 模式（现有）：gate.evening 22:00 触发，全量处理当日文章
# - streaming 模式（新增）：polling loop，每 N 分钟拉取增量文章

def _job_sentiment_fetch(data_root: str, config: dict = {},
                         date_from=None, date_to=None) -> str:
    mode = config.get("fetch_mode", "incremental")   # incremental | streaming
    interval = config.get("poll_interval_min", 15)   # streaming 轮询间隔

    if mode == "streaming":
        # 拉取自上次拉取后新增的文章（通过 sync_state 记录 cursor）
        cursor = db.sync_state_get("sentiment", "bronze", "").cursor  # 上次 offset
        new_articles = rss_fetch_since(cursor, data_root)
        if new_articles:
            db.sync_state_set("sentiment", "bronze", "", cursor=new_cursor)
            return f"streaming: 新增 {len(new_articles)} 篇"
        return "streaming: 无新文章"
    else:
        # 现有 incremental 逻辑
        ...
```

**文章到达后的级联触发**：
```
sentiment_fetch (streaming) 发现新文章
    → emit: sentiment.new_articles
    → sentiment_silver 订阅 → 立刻评分
    → emit: sentiment.silver_updated
    → sentiment_gold 订阅 → 滚动聚合更新
    → emit: sentiment.gold_updated
    → window_score (E分量更新) 订阅 → 只重算情绪分量
```

### pipeline_dag 增加 mode 列

```sql
ALTER TABLE pipeline_dag ADD COLUMN mode TEXT DEFAULT 'batch';
-- 取值: 'batch' | 'streaming' | 'both'
```

| 节点 | mode |
|------|------|
| kline_update | batch |
| realtime_quote_sync | streaming |
| sentiment_fetch | both |（支持两种模式，config 切换）
| sentiment_silver | both |
| window_score | both |（batch=全量，streaming=增量E分量）
| model_train | batch |

### 流水线 tab 的 streaming 展示

在流水线 tab 中，新增"实时流"区域，与批处理 DAG 并排：

```
BATCH PIPELINE              STREAMING (盘中)
gate.morning ✓              realtime_quote_sync
  └─ kline_update ✓           ◉ 09:45 运行中 | 10min窗口
  └─ window_score ✓           最新: 09:40 | 50 symbols
                            sentiment_fetch
gate.evening (22:00)          ◉ 每15min轮询 | 今日28篇新文章
  └─ sentiment_fetch (batch)  最新: 09:52 | 上次新增: 3篇
  └─ ...
```

### 本期范围说明

- **本次实现**：mode 列 + config_json 的 poll_interval/trading_hours；streaming sentinel fetch 逻辑骨架
- **暂不实现**：真正的 push 推送（webhook），需要 RSS 源支持；毫秒级 tick 数据

---

## 四、Job 粒度拆分 + 配置化

### pipeline_dag 表扩展

新增 2 列（migration v6）：
```sql
ALTER TABLE pipeline_dag ADD COLUMN config_json TEXT DEFAULT '{}';
ALTER TABLE pipeline_dag ADD COLUMN sync_source TEXT;   -- 对应 sync_state.source
ALTER TABLE pipeline_dag ADD COLUMN sync_dataset TEXT;  -- 对应 sync_state.dataset
ALTER TABLE pipeline_dag ADD COLUMN mode TEXT DEFAULT 'batch';
```

`config_json` 存储可配置参数（UI 可编辑）：
```json
{
  "lookback_days": 30,
  "semantic_mode": "base",
  "magnitude_threshold": 0.4,
  "sector_limit": 3
}
```

### Job 拆分：sentiment_pipeline → 3 节点

当前：`sentiment_pipeline`（一个黑盒，内部3步）

拆分后：
```
sentiment_fetch  → emits: sentiment.fetched
sentiment_silver → source: sentiment.fetched, emits: sentiment.silver_done
sentiment_gold   → source: sentiment.silver_done, emits: sentiment.gold_done
```

对应 jobs/__init__.py 拆分：
```python
def _job_sentiment_fetch(data_root: str, config: dict = {}) -> str:
    """抓取原始新闻到 Bronze 层"""
    ...

def _job_sentiment_silver(data_root: str, config: dict = {}) -> str:
    """Bronze → Silver：逐文章情绪评分"""
    ...

def _job_sentiment_gold(data_root: str, config: dict = {}) -> str:
    """Silver → Gold：按 symbol/date 聚合"""
    ...
```

### Job 拆分：event_pipeline → 2 节点

```
event_extract  → source: sentiment.gold_done, emits: events.extracted
kg_propagate   → source: events.extracted, emits: signals.events_updated
```

### 所有 Job 支持 config_json

job 运行时从 pipeline_dag 读取 config_json 并传入：
```python
def run_job(name: str, data_root: str) -> str:
    meta = db.pipeline_dag_get_by_job(name)
    config = json.loads(meta.get("config_json") or "{}")
    return JOB_REGISTRY[name]["fn"](data_root, config=config)
```

### UI 节点配置面板

流水线 tab 中，每个节点新增"配置"按钮：
```
┌─────────────────────────────────────┐
│ ⚙ sentiment_fetch         [▶] [⚙]  │
│ ✓ 完成  3m12s  1240篇文章            │
│ 数据覆盖: 2026-03-17 (0d 延迟)       │
└─────────────────────────────────────┘
         ↓ 点击 ⚙ 后展开
┌─────────────────────────────────────┐
│ 配置  sentiment_fetch               │
│ fetch_mode:   [incremental ▼]       │
│ lookback_days: [30        ]         │
│ semantic_mode: [base ▼]             │
│ [保存配置]  [取消]                   │
└─────────────────────────────────────┘
```

新增后端接口：
- `GET /api/dag/{id}` — 返回节点详情（含 config_json）
- `PATCH /api/dag/{id}/config` — 更新 config_json

---

## 五、时域感知 + 回补

### 核心概念区分

| 概念 | 含义 | 来源 |
|------|------|------|
| **执行时间** | job 什么时候运行的 | job_runs.started_at |
| **数据时间** | 产出的数据覆盖到哪个日期 | sync_state.last_date |

这两个截然不同！比如 kline_update 今天07:05运行，但数据是昨天收盘的（数据时间=昨日）。

### DAG 节点时域展示

每个节点在数据层面显示（通过 sync_source + sync_dataset 关联 sync_state）：

```
kline_update
✓ 完成 | 执行: 07:05 耗时42s
数据: 2026-03-17 (0d延迟) | 4821/5000 symbols (96.4%)
[▶ 重跑] [📅 回补]
```

pipeline_dag 中每行的 sync_source/sync_dataset 映射：
```python
_DAG_SYNC_MAP = {
    "kline_update":     ("tushare_kline", "daily"),
    "fund_flow_update": ("tushare_fundflow", "daily"),
    "sentiment_fetch":  ("sentiment", "bronze"),
    "sentiment_silver": ("sentiment", "silver"),
    "sentiment_gold":   ("sentiment", "gold"),
    "event_extract":    ("events", "market_events"),
    "fundamental":      ("tushare_fina", "indicator"),
    "macro":            ("tushare_macro", "shibor"),
}
```

### 回补（Backfill）UI

每个支持回补的节点显示"📅 回补"按钮，点击后：
```
回补 kline_update
开始日期: [2026-03-10]
结束日期: [2026-03-15]
[确认回补]
```

调用：`POST /api/dag/{id}/run { mode: "backfill", date_from: "...", date_to: "..." }`

后端扩展：
```python
# app.py: run endpoint 增加 date_from/date_to 参数
@app.post("/api/dag/{dag_id}/run")
async def run_dag_node(dag_id: int, body: RunBody):
    # body: {mode, date_from?, date_to?}
    meta = db.pipeline_dag_get(dag_id)
    job_name = meta["job_name"]

    kwargs = {}
    if body.date_from and body.date_to:
        kwargs["date_from"] = body.date_from
        kwargs["date_to"] = body.date_to

    asyncio.get_event_loop().run_in_executor(
        None, lambda: run_job(job_name, DATA_ROOT, **kwargs)
    )
```

Jobs 支持回补的函数签名扩展：
```python
def _job_kline(data_root: str, config: dict = {},
               date_from: str | None = None, date_to: str | None = None) -> str:
    ...

def _job_sentiment_fetch(data_root: str, config: dict = {},
                         date_from: str | None = None, date_to: str | None = None) -> str:
    ...
```

---

## 六、K线端点 + 预测叠加

### `GET /api/kline/{symbol}?days=60`

```python
# Response
{
  "symbol": "000001.SZ",
  "name": "平安银行",
  "ohlcv": [  # tail 60 日 K，从 data/market/kline/ parquet 读取
    {"date": "2026-01-15", "open": 11.2, "high": 11.5, "low": 11.0, "close": 11.3, "volume": 1234567}
  ],
  "event_markers": [  # 该 symbol 历史事件标记
    {"date": "2026-02-10", "event_type": "policy", "magnitude": 0.72, "kg_score": 0.91}
  ],
  "indicators": {
    "rsi_14": 38.2,        # 从 ohlcv 计算，内联
    "vol_ratio": 0.62,     # today_vol / ma20_vol
    "dist_52w_low": 0.18   # (close - low52w) / (high52w - low52w)
  },
  "prediction": {
    "predicted_return_5d": 0.032,   # from model_registry inference
    "predicted_return_20d": 0.068,
    "model_risk": 0.12,
    "confidence": "high"
  },
  "recommendation": {
    "conviction": "高",
    "bullish_dims": 3,
    "rr_ratio": 1.5,
    "reasons": [
      "policy 事件历史12次均5日收益 +2.8%",
      "RSI 38，接近超卖低位",
      "情绪由负转正 (+0.42)"
    ],
    "hist_event_stats": {
      "event_type": "policy",
      "hist_count": 12,
      "hist_ret_5d_avg": 2.8,
      "hist_ret_20d_avg": 5.1
    }
  }
}
```

K线图：lightweight-charts（TradingView，~40KB）
预测展示：最后一根K线后加阴影区 + 方向箭头

---

## 七、完整变更清单

### 后端文件

| 文件 | 变更 |
|------|------|
| `trade_py/db/trade_db.py` | 新增 signal_recommend()（3阶段）, signal_suggest_delta()；pipeline_dag +4列 |
| `trade_py/db/migrations.py` | migration v6：pipeline_dag 加 config_json + sync_source + sync_dataset + mode |
| `trade_py/jobs/__init__.py` | 拆分 sentiment_pipeline→3, event_pipeline→2；所有 job 接收 config + date_from/to；streaming 模式 |
| `trade_py/bus/__init__.py` | 更新 topic 路由（新增 sentiment.new_articles / silver_updated / gold_updated） |
| `trade_web/backend/app.py` | 新增 /api/today-page, /api/signals-page, /api/kline/{sym}；PATCH /api/dag/{id}/config；扩展 run 接收 date_from/to |

### 前端文件

| 文件 | 变更 |
|------|------|
| `trade_web/frontend/src/App.tsx` | 3 tab 重构；renderToday/renderPicks/renderPipeline；K线侧板；节点配置面板；streaming 区域 |
| `trade_web/frontend/src/styles.css` | 节点卡片；侧板；K线容器；配置面板；streaming 状态条 |
| `trade_web/frontend/package.json` | 新增 lightweight-charts |

### 不动的部分
- 现有 21 个后端端点全部保留（向后兼容）
- signals/DB schema 核心不变
- sync_state schema 不变（pipeline_dag 新增 sync_source/dataset 作为 hint）
- ELK.js 保留（节点布局继续用）

---

## 八、实施顺序

**Phase 1 — DB + Job 架构（纯后端，无 UI）**
1. migrations.py 新增 v6：pipeline_dag 加 config_json + sync_source + sync_dataset + mode
2. jobs/__init__.py：拆分 sentiment_pipeline → 3 函数，event_pipeline → 2 函数
3. 所有 job 函数接收 config dict + 可选 date_from/date_to 参数
4. sentiment_fetch 增加 streaming 模式（polling + cursor 去重）
5. bus/__init__.py：更新 topic 路由，新增 streaming 级联订阅
6. trade_db.py：新增 signal_recommend()（3阶段）+ signal_suggest_delta()
7. 验证：`trade event dag` CLI 显示 22 个节点；streaming 节点可用

**Phase 2 — 后端新端点**
8. `/api/today-page`（市场快照 + pipeline health + top5 推荐含 delta）
9. `/api/signals-page`（top50 + delta status + 推荐理由）
10. `/api/kline/{symbol}`（OHLCV + RSI + 事件标记 + 推荐上下文）
11. `PATCH /api/dag/{id}/config`（更新 config_json）
12. 扩展 `POST /api/dag/{id}/run` 接受 date_from/date_to
13. 验证：curl 新端点，数据结构正确

**Phase 3 — 前端今日 + 选股 tab**
14. App.tsx 切换到 3 tab 结构（今日/选股/流水线）
15. renderToday()：市场卡片 + pipeline 状态 + top5（含 new/continued 标签）
16. renderPicks()：50行信号表（含 delta badge）+ 侧板框架
17. 安装 lightweight-charts，实现 K线组件（含预测区域 + 事件标记点）
18. 推荐理由区块（conviction + R/R + reasons 列表）

**Phase 4 — 流水线 tab 改造**
19. 改造 DAG 节点卡片：加执行时间 + 数据覆盖时间 + 数据量
20. 节点配置面板（⚙ 按钮 → 展开 config_json 编辑表单）
21. 回补按钮（📅 → 日期范围选择 → POST /api/dag/{id}/run）
22. 状态动画（running 时旋转指示器）

**Phase 5 — 清理**
23. 删除旧 renderReport/renderKG/renderEvents 函数
24. 删除旧 eventsPage/kgPage state 变量
25. CSS 清理

---

## 九、验证方式

1. `trade event dag` → 显示22个节点，情绪链路: sentiment_fetch→sentiment_silver→sentiment_gold→event_extract→kg_propagate
2. 今日 tab：market cards + pipeline 3灯 + top5 picks 含 [新] [持续] 标签
3. 点击股票 → 侧板 K线图 60 日 + 预测阴影 + 事件标记点
4. 流水线节点：显示"执行: 07:05 / 数据: 2026-03-17"
5. 点击 📅 回补 → 输入日期范围 → 触发 job → 节点变 running 状态
6. 点击 ⚙ 配置 → 修改 semantic_mode → 保存 → 下次运行生效
