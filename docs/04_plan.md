# TradeDB 最小运行手册

这个版本以当前统一入口为准，目标是尽快把系统跑起来。

---

## 1. 最小前置

### Python 依赖

```bash
uv sync
```

### 前端构建

```bash
npm --prefix trade_web/frontend install
npm --prefix trade_web/frontend run build
```

### Tushare token

推荐三种方式，优先级从高到低：

1. DB
2. 环境变量
3. `config/trade.yaml`

#### 方式 A：写入 DB

```bash
./trade account setting-set tushare_token YOUR_TOKEN
```

#### 方式 B：环境变量

```bash
export TUSHARE_TOKEN=YOUR_TOKEN
```

#### 方式 C：`config/trade.yaml`

```yaml
tushare_token: YOUR_TOKEN
```

> `config/trade.yaml` 可以不存在；存在时只做 override。

---

## 2. 先看状态

```bash
./trade status
```

重点看：

- `Tushare token: 已配置 / 未配置`
- `质量门禁`
- `未来 7 天 planned events`
- `最近 jobs`

---

## 3. 最小启动路径

### 先跑一次同步链

```bash
./trade run sync
```

这个 workflow 当前会依次跑：

- `calendar_sync`
- `planned_event_sync`
- `agenda`
- `evaluate_daily`

如果 `Tushare` 没配好，`calendar_sync / planned_event_sync` 现在会尽量走缓存/fallback，不会在构造阶段直接炸掉整条链。

### 再跑一次晚间链

```bash
./trade run close
```

这个 workflow 当前会依次跑：

- `evening`
- `event-extract`
- `evaluate_daily`
- `market-close`

这条链更接近“把事件和评估跑起来”的主路径。

---

## 4. 启动 Web

```bash
./trade web --port 8080
```

然后打开：

`http://127.0.0.1:8080`

主页面只有三个：

- `报表`
- `事件`
- `KG`

---

## 5. 现在 Web 上应该看什么

### 报表

看：

- 今日结论
- workflow 进度
- root causes
- top signals
- 今日/未来事件

### 事件

看：

- DAG 图
- 失败节点
- 节点详情
- 节点重跑
- 每日事件流

### KG

看：

- active snapshot
- active relations
- candidates
- propagation summary

---

## 6. 常用命令

### 正式入口

```bash
./trade run <target>
./trade status
./trade inspect <thing>
./trade web
./trade backup
```

### 常用 workflow

```bash
./trade sync
./trade open
./trade close
./trade morning
./trade intraday
./trade evening
./trade agenda --limit 10
```

### 查看

```bash
./trade inspect dag
./trade inspect calendar --date 2026-03-17 --days 7
./trade inspect agenda --limit 20
./trade inspect events
./trade inspect kg
./trade inspect factors
./trade inspect models
```

---

## 7. 出问题先看哪里

### `run sync` 报 Tushare token not found

先执行：

```bash
./trade account setting-set tushare_token YOUR_TOKEN
./trade status
```

确认 `Tushare token: 已配置` 后再重跑。

### Web 事件页 SSE 报错或页面卡住

先重启 Web：

```bash
./trade web --port 8080
```

再浏览器强刷。

### 看 DAG / 失败节点

优先去 Web 事件页。

如果还要 CLI：

```bash
./trade inspect dag
./trade event runs --limit 20
./trade event list --limit 20
```

---

## 8. 当前建议的日常操作顺序

```bash
./trade status
./trade run sync
./trade run close
./trade web --port 8080
```

然后主要在 Web 里看：

- 报表
- 事件 DAG
- KG 运行态

---

## 9. 后续演进方向

当前最重要的不是继续堆命令，而是：

1. 让 `run / status / inspect / web / backup` 成为唯一日常入口
2. 让 Web 覆盖全部常用操作
3. 让配置彻底 `DB-first`
4. 让 `engine/tradedb` 继续承接 runtime 能力
