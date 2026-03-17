# TradeDB 架构与目录收敛计划

## 目标

把当前仓库收敛成一个单机、事件驱动、Web-first 的交易智能系统：

- `engine/`：高性能运行时内核与存储边界
- `trade_py/`：采集、编排、工作流、管理平面
- `trade_web/`：唯一 Web 产品面
- `data/`：运行数据
- `config/trade.yaml`：唯一外部 override 文件，可不存在

核心原则：

1. `DB-first`
2. `Web-first`
3. `少命令`
4. `少配置文件`
5. `旧链路直接删除，不长期兼容`

---

## 当前正式入口

正式保留：

- `./trade run`
- `./trade status`
- `./trade inspect`
- `./trade web`
- `./trade backup`

管理员/细分入口暂时保留，但不再作为主用户入口：

- `./trade data`
- `./trade model`
- `./trade factor`
- `./trade event`
- `./trade evaluate`
- `./trade kg`

---

## 目标目录结构

```text
engine/
  tradedb/
    core/                 # SQLite/schema/query/store facade
    calendar/             # trading_calendar + session runtime
    agenda/               # agenda claim/lease/ack
    graph/                # KG snapshot / propagation runtime
    cache/                # runtime signature + snapshot metadata
    factors/              # 高频聚合 / runtime factor helpers
    bindings/python/      # Python bindings

trade_py/
  app/
    workflows/            # sync / close / open / intraday / evening
    services/             # status / overview / trigger / admin
    pipelines/            # ingest / materialize / evaluate / backfill
    runtime/              # scheduler / agenda orchestration
  domain/
    market/
    events/
    kg/
    factors/
    models/
    account/
  infra/
    db/
    providers/
    settings/
    bus/
    backup/
    storage/
    notify.py
  cli/                    # 薄壳
  compat/                 # 短期兼容层
  migrations/

trade_web/
  backend/
    app.py                # FastAPI app factory
    inference.py          # Web-facing inference runtime
    api/
    services/
    dto/
    sse/
  frontend/
    src/
      pages/
        report/
        events/
        kg/
      components/

config/
  trade.yaml.example
  README.md

deployment/
  docker/
  systemd/
  examples/
```

---

## 模块职责边界

### `engine/`

负责：

- `trading_calendar` 查询与 session 判断
- `agenda_queue` claim/ack/lease
- `kg_relations` 与 snapshot 运行时加载
- 高频聚合 / runtime signature

不负责：

- provider 采集
- Web/API
- 训练编排

### `trade_py.app`

统一编排层。CLI、Web、scheduler 都只调这层。

### `trade_py.domain`

业务语义层。后续逐步把现在散落在：

- `analysis/`
- `signals/`
- `intelligence/`
- `event/`

的业务能力往这里收。

### `trade_py.infra`

外部依赖与持久化：

- DB repo
- Tushare / AKShare / RSS / GDELT / GDrive adapters
- settings / backup / bus

### `trade_web`

唯一产品面：

- `报表`
- `事件`
- `KG`

Web 不直接拼业务逻辑，只调用 `trade_py.app.services`。

---

## 配置策略

优先级固定：

`CLI args > ENV > config/trade.yaml > DB settings > built-in defaults`

### 运行时真源

- `settings` 表
- catalog / module / runtime 参数全部入 DB

### 文件只保留

- `config/trade.yaml.example`
- `config/trade.yaml`（可不存在）
- 少量历史基线文件，仅用于首次导入/恢复

### 明确退场

- `config/modules/*.yaml` 继续退场
- `config/feeds/*.json` 不应再被运行态直接依赖
- 页面级 JSON / Markdown 报表缓存不再新增

---

## Web 产品面

### 报表页

只展示 DB-backed summary：

- 今日结论
- operational / research 状态
- workflow 进度
- root causes
- top signals
- 今日事件 / 未来事件
- 数据健康摘要

### 事件页

核心是“Airflow 风格的运行态 + 每日事件流”：

- DAG 图
- 节点状态
- 失败节点与根因
- 从节点重跑并续跑下游
- 今日事件流
- agenda / planned events

### KG 页

第一版只做运行态与结果：

- active snapshot
- active relations
- candidate edges
- propagation summary
- relation type summary

先不做重型交互式图编辑器。

---

## 缓存体系

统一三层：

### 1. DB Snapshot Cache

例如：

- `ui_snapshots`
- 后续可扩 `overview_snapshots`
- `workflow_runtime_snapshots`
- `kg_runtime_snapshots`

### 2. In-process Hot Cache

仅给 Web/API 用：

- report：5-10s
- events：2-5s
- kg：15-30s
- data health：15-30s

### 3. Materialized Runtime Tables

这些本身就是业务结果，不再另建重复缓存：

- `signals`
- `factors`
- `market_events`
- `event_propagations`
- `planned_events`
- `agenda_queue`
- `kg_relations`

---

## 迁移优先级

### Phase 1

- Web / CLI 收口
- 旧报表 / 旧 UI 删除
- `trade_web` 固化为唯一 Web 项目

### Phase 2

- 配置完全 DB-first
- `config/feeds` / `config/modules` 退为迁移基线
- `trade.yaml` 只做 override

### Phase 3

- `analysis / signals / intelligence / meta` 继续往 `domain / infra / app` 收
- 减少跨目录直接 import

### Phase 4

- `engine/tradedb` 前移：
  - session runtime
  - agenda runtime
  - KG runtime
  - snapshot signature

---

## 当前已完成的关键收敛

- 旧 `report/ui` 主链已删除
- Web 主导航已收成 `报表 / 事件 / KG`
- 事件页已支持 DAG、失败节点、节点重跑
- `trade_web/backend` 已成为实际 Web 后端
- 配置已开始 `DB-first`
- `domain` facade 已开始承接调用方 import

---

## 下一步改造重点

1. 切断 `config/feeds`、`config/modules` 的运行时直接读取
2. 继续把 `analysis / signals / intelligence / meta` 往新边界迁移
3. 把 `engine/tradedb` 的 session / agenda / KG runtime 前移
4. 继续压缩旧 CLI 入口，只让日常落在 `run / status / inspect / web / backup`
