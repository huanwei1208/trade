# 28 Plan - 可演进、可插拔、高性能的交易研究与决策系统

> 状态：架构总规划，仅用于后续分阶段实施；本轮不实现任何生产代码
>
> 规划日期：2026-07-22
>
> 审计基线：master @ d288660
>
> 适用范围：trade、trade_py、trade_web、engine、tests、data 合同与运行治理
>
> 决策优先级：本文件定义长期方向；具体行为仍以已批准的 OpenSpec、
> 冻结合同和较新的专项计划为准

## 0. 结论先行

本项目不适合做一次“大重写”，也不适合现在就拆微服务或整体改成
C++/Rust。推荐的长期架构是：

> 领域模块化单体 + Ports/Adapters + 类型化插件 SPI + 不可变证据/PIT
> 内核 + 有界、可恢复的事件运行时 + 按实测热点下沉的原生计算内核。

核心决策如下：

1. Python 继续承担控制面、应用编排、研究、数据治理、Web/API 和插件宿主。
2. SQLite 继续承担单机控制元数据，Parquet/Arrow 继续承担批量事实数据，
   DuckDB 继续承担分析；先拆代码所有权，不先拆物理数据库。
3. C++ 不再被口号式地称为“全部计算的主引擎”。它应收敛为纯计算、
   确定性、粗粒度的原生 kernel，并通过真实绑定或 Arrow IPC 接入。
4. Rust 不是重写目标；它是未来逐笔/L2 接入、订单簿重建、长连接和执行
   边缘的候选语言，是否采用由容量、隔离和维护风险决定。
5. 当前系统继续以“研究 + 辅助决策”为默认模式。完整交易能力按
   research → advisory → paper → shadow → live 分层建设，live 必须是独立
   安全项目，不能由某个策略插件直接开启。
6. 插件化不是任意动态加载代码。V1 使用显式 allowlist、版本化合同、
   权限边界、conformance suite 和可观测生命周期。
7. 订单流、供应商资金流、OHLCV 代理指标和 SMC 是不同概念。当前
   smart_money_flow 实际是 Chaikin Money Flow；未来必须保留 proxy 标签，
   不能把它宣传为真实订单流或机构行为。
8. 迁移采用绞杀者模式：新增边界、兼容委托、双跑比对、调用遥测、逐步
   下线。禁止一次搬完目录、一次换完存储、一次切完语言。
9. 第一优先级不是增加功能，而是清理 correctness P0、冻结术语、建立
   依赖护栏、拆分读写语义和资源所有权。
10. 每个后续非平凡阶段都必须独立 worktree、OpenSpec、Design Quality
    Brief、六角色评审、严格 design-check、单元测试、性能 sanity 和可回滚
    提交；本文件本身不代替这些门禁。

## 1. 规划目标、成功标准与非目标

### 1.1 目标

项目最终应同时满足以下目标：

- 可读：从目录和类型就能看出业务边界、数据方向、副作用和 owner。
- 简洁：入口薄、领域内聚、共享内核小，不再依靠巨型 facade 维持功能。
- 易扩展：新增 provider、特征、研究假设、策略、风控或执行适配器时，
  不需要修改多个全局字典和 catch-all 文件。
- 可验证：每份数据、特征、研究、决策和执行结果都能追溯到输入、
  时点、版本、代码、配置、质量状态和证据。
- 可替换：Python/C++/Rust 或存储实现可以在稳定 port 后替换，业务语义
  不跟随语言或框架漂移。
- 高性能：通过容量模型、基准和 profile 优化真实热点，不以重写语言
  代替测量。
- 高可靠：任务有唯一 owner、有界容量、幂等、重放、隔离、恢复和明确
  unknown 状态。
- 交易安全：研究信号不能越过决策、风险、订单意图、执行计划和 broker
  适配边界；任何不确定状态默认禁止新单。
- 好打理：文档、代码、测试、运行状态和迁移记录都有唯一真相源。

### 1.2 可验收的长期成功标准

| 维度 | 长期退出标准 |
| --- | --- |
| 依赖 | 领域模块之间无循环依赖；domain 不 import CLI、FastAPI、SQLite、provider |
| 文件职责 | 新代码不再增长 catch-all；超过 800 行的新文件必须有设计说明和拆分理由 |
| 数据访问 | 所有 query 明确只读；网络、修复、迁移和写入只能经显式 command/use case |
| DB 所有权 | CLI、Web 和 domain 对 TradeDB._conn 的直接访问为 0 |
| 运行时 | Web 裸 daemon workflow thread 为 0；长任务全部由统一 runtime owner 管理 |
| 插件 | 每个插件都有 manifest、版本、权限、输入输出合同、健康状态和 conformance receipt |
| 研究 | 正式研究输出可追到 immutable snapshot、schema、config、code 和 plugin hash |
| PIT | strict as-known 查询不会看到 knowledge cut 之后或时间未知的事实 |
| 回测一致性 | Python/native、backtest/paper 对同一 golden input 满足声明的差分容差 |
| 执行安全 | risk veto 不可绕过；order ledger、幂等、对账、kill switch 和审计闭环完备 |
| 可观测性 | degraded 不报告 ok；关键路径都有 p50/p95/p99、容量、错误和恢复指标 |
| 迁移 | 每阶段可独立回滚；旧 facade 只在调用量归零且兼容测试通过后下线 |

### 1.3 非目标

- 不在本轮实现代码、移动目录、修改 schema 或接入 provider。
- 不做 big-bang rewrite。
- 不把微服务、Kafka、Kubernetes、GPU、SIMD 或新语言当作里程碑本身。
- 不承诺 HFT；未来实时订单流的压测包络只服务于选型。
- 不把启发式 scaffolding 重新包装成经过验证的模型。
- 不允许第三方插件在主进程任意热加载。
- 不在 paper、reconciliation、risk 和 kill switch 完成前连接真实资金。
- 不为架构美观重复建设 Observatory 已有的 PIT、catalog、hash 和发布能力。

## 2. 审计方法与事实基线

本规划由三个并行审计组覆盖六个视角：

- 架构 + 可运维性；
- 数据质量 + 新闻/未来能力；
- 性能 + 可靠性。

主审计同时检查了实际目录、主要入口、依赖关系、巨型文件、C++ 构建、
当前 OpenSpec、BTC 数据保障和 Observatory 合同。结论来自当前 checkout，
不是通用交易系统模板。

### 2.1 当前已有的好地基

应保留并推广，而不是重写：

- trade Bash 统一门面和 Python CLI 的 lazy dispatch。
- WebResourceContainer、FastAPI lifespan 和 runtime router。
- RuntimeCommandRunner 的持久 run、data-root owner lock、进程组监管、
  reconcile 与有界 shutdown。
- EventBus 的 durable event/handler 状态、pending replay、五类有界通道和
  capacity snapshot。
- data operations 的 typed result 和真正只读 SQLite 访问。
- BTC provider contract、raw capture、hash、run identity、D0-D4、candidate、
  current、publish receipt 和 rollback。
- Observatory 的 immutable domain、snapshot selector、PIT resolver、
  read-only query facade、catalog、golden tests 和性能测试框架。
- FactorGroupResult 的 coverage、missing、defaults 和 source range。
- C++ FeatureCalculator、IStrategy、IClock、IMarketDataFeed、
  IExecutionVenue、风险和回测抽象。
- ODS/DIM/DWD/DWS/ADS 与 evidence/reason/validation_status 输出合同。
- OpenSpec、design-quality、code-quality 和多角色 review 门禁。

### 2.2 当前结构性问题

| 问题 | 当前证据 | 影响 |
| --- | --- | --- |
| 巨型 DB facade | trade_py/db/trade_db.py 约 4690 行；构造时开库、建表、迁移、seed | 读写、副作用、事务和 schema owner 不清晰 |
| 巨型 Web composition | trade_web/backend/app.py 约 3781 行，create_app 后仍有大量内联路由 | HTTP、业务编排、DB、Parquet 和后台任务耦合 |
| 巨型 CLI/data | trade_py/cli/data.py 约 2725 行 | 公共命令和内部 workflow 混在一起 |
| 巨型运行时文件 | bus/__init__.py 约 1752 行；jobs/__init__.py 约 1409 行 | topic、admission、replay、job 定义和执行难以独立演进 |
| 私有 DB 穿透 | readiness.py、factor materializer 等直接使用 db._conn | 绕过 repository 语义、锁和测试替身 |
| 读路径会写 | DataGateway.get_kline/get_fund_flow 可联网、补数、写 Parquet 和 DB | GET、研究和回放不再确定、难以审计 |
| 入口反向依赖 | engine facade 和 data gateway 会调用 CLI main | 领域/应用依赖 presentation，生命周期失控 |
| 注册表碎片化 | data、crypto ingest、factor、jobs、C++ feature/strategy 各有一套 | 无统一版本、schema、权限、PIT、资源和健康合同 |
| 前端 catch-all | api.ts、i18n.tsx、pages.css 等持续膨胀 | feature 边界、类型和发布影响面不清晰 |
| 文档真相冲突 | 旧文档称 C++ 主引擎，真实 Python 控制面很重且 binding 不存在 | 后续 agent 容易按失效假设继续设计 |

### 2.3 依赖密度快照

Python 包体量较大的区域为 data、cli、db、devtools、analysis；高频双向耦合
集中在 cli/data、data/utils、data/jobs、db/utils。该事实说明不能只把长文件
拆成小文件，必须同时固定依赖方向和所有权。

2026-07-22 的只读本地数据规模快照：

| 项目 | 当前规模 |
| --- | --- |
| data/ 总量 | 约 2.6 GiB |
| 主 SQLite | 约 1.1 GiB，49 张表 |
| WAL | 约 137 MiB |
| factors | 2,997,792 行 |
| signals | 386,702 行 |
| Parquet 文件 | 17,377 个 |
| Kline Parquet | 5,702 个 |

观测对象为当前 data/；使用 du、find 和 sqlite3 -readonly 获取。该表只冻结
容量事实，不代表性能结论；实施时在 benchmark receipt 中补主机、命令、
冷热缓存和采样窗口。

这说明 SQLite 仍可作为当前单机控制面，但必须立刻监控 transaction、WAL 和
checkpoint；当前按证券整文件的 Kline 也仍可用，但不能直接承载未来分钟、
逐笔或 L2 规模。

### 2.4 C++ 的真实状态

- engine/CMakeLists.txt 已把 storage、feature、stats、ML、risk、backtest、
  decision 等源文件分组，但最终聚合为一个 trade_core。
- BUILD_PYTHON_BINDINGS 默认关闭。
- engine/cmake/python_bindings.cmake 引用的 engine/python/bindings 当前不存在。
- 绑定目标也叫 trade_py，与 Python 包重名。
- trade_py/engine 实际是 Python jobs/services facade，不是 C++ binding。
- trade_py/__init__.py 自导入 trade_py 作为 _cpp，使 HAS_CPP 语义失真。

因此第一步不是扩大 C++，而是修正能力声明、建立稳定 schema、选择一个
真实热点，做可回退、可差分验证的接入。

仓库还包含 engine/tradedb-driver Java/JDBC 适配器。当前审计只发现其自身
README、测试和质量门禁，未发现生产 consumer。Phase 0 必须登记实际 owner
和 consumer：若确有外部 Java 使用者，则将它作为只读基础设施 adapter 并
纳入 DB contract tests；若没有，则另起兼容性清理任务弃用，不能默认为
核心计算语言，也不能在架构迁移中顺手删除。

### 2.5 订单流与 SMC 的真实状态

- engine 的 Bar 是日级 OHLCV/成交额/换手和部分资金流字段。
- SmartMoneyCalculator 明确使用 Chaikin Money Flow，只依赖 OHLCV。
- Tushare 的大单/超大单是供应商日级聚合，不是逐笔 order flow。
- AkShare 的部分成交额和 distribution zone 是估算/启发式。
- auction_vol_ratio 仍是等待 L2/竞价数据的占位值。
- 当前没有逐笔成交、L2 snapshot/delta、exchange sequence、gap/reset、
  deterministic book reconstruction 或微观结构 replay。

长期计划必须把以下四类标签永久分开：

1. OHLCV 派生代理；
2. provider 聚合资金流；
3. 真实逐笔/盘口微观结构；
4. 可证伪的 SMC 研究定义。

## 3. 先处理的正确性与可靠性阻塞项

这些是本轮只读审计发现的“待 regression test 复现”的候选 P0。任何大规模
架构迁移、实时数据或执行工作开始前，应逐项独立 OpenSpec/修复或纳入已有
remediation：

| ID | 候选问题 | 处理原则 |
| --- | --- | --- |
| C1 | PIT resolver 在时间字段为 None 时仍让行可见 | strict PIT 必须 fail closed |
| C2 | latest_restated 目前只打标，不重建实际修订版本 | 不得宣称真正 restated |
| C3 | RSS/GDELT 缺失或错误发布时间时写入当前时间 | 保留 unknown，不伪造事件时间 |
| C4 | event_features 查询 event_propagations 中不存在的 event_date 并吞异常 | 让 schema/查询一致，禁止静默空因子 |
| C5 | fear/greed z-score 先看全历史再按时间过滤 | 改为 expanding/rolling PIT 统计 |
| C6 | 历史训练连接当前 instruments/sector 属性 | 建立 bitemporal instrument master |
| C7 | 某些 unknown freshness/calibration 被当作成功或中性值 | unknown 必须正交传播并阻断正式晋级 |
| C8 | 模型可直接替换 active，缺 immutable promotion receipt | candidate 与 active 原子晋级、可回滚 |
| C9 | Web readiness/ops 仍启动旁路 daemon thread | 全部进入统一 CommandExecutor |
| C10 | ingest 成功事件可能早于 canonical artifact 最终提交 | artifact commit → outbox → event |
| C11 | Kline 损坏文件可能被忽略后覆盖，manifest 无跨进程提交锁 | fail closed、隔离原件、原子 receipt |
| C12 | SQLite check_same_thread=False 但锁/事务策略不完整 | repository transaction owner 统一 |
| C13 | scheduler 缺单 owner lease、durable catch-up 和完整信号退出 | 稳定 fire key、drain、missed-fire 恢复 |
| C14 | 当前 C++/Python capability 声明与真实接线不一致 | 先纠正文档和检测，再优化 |
| C15 | Java tradedb-driver 的真实 consumer/owner 不明确 | Phase 0 盘点，保留 adapter 或独立弃用 |

这些问题不能夹带在目录重构中修复。每项先添加失败测试，再用最小行为修改
修复，以免结构变化掩盖语义变化。

## 4. 设计原则与不可破坏的不变量

### 4.1 单向依赖

~~~text
interfaces (CLI / HTTP / scheduler)
              |
              v
application (commands / queries / workflows)
              |
              v
domain + contracts  <----- ports
              ^                ^
              |                |
adapters / infrastructure -----+

runtime 只组合 application public API
domain 不知道 FastAPI、CLI、SQLite、Parquet 路径、provider 或 broker SDK
~~~

### 4.2 读写分离

- Query 名称和类型保证无 provider acquisition、无业务状态写入、无 migration、
  无 repair、无 pointer switch；允许访问显式只读 datastore，并记录日志/指标。
- Command 明确声明写入、网络、重试、幂等、权限和资源类别。
- 缺数据的 query 返回 typed unavailable/partial/unknown，不自行补数。
- repair、backfill、publish、promote、rollback 都是显式 use case。
- 需要缓存或聚合的读模型由 ProjectionMaterializer/ReadModelStore 在写侧或
  后台 command 中预物化；GET 只读已提交 projection，cache miss 不在请求内写。

### 4.3 证据优先

任何正式输出必须能追溯：

~~~text
输入 artifact/hash
 -> canonical snapshot + knowledge cut
 -> feature manifest + implementation version
 -> hypothesis/model/policy version
 -> validation/calibration receipt
 -> decision/risk receipt
 -> optional execution/order ledger
~~~

### 4.4 Unknown 不是 0

present、empty、partial、stale、invalid、unavailable、rate_limited 和 unknown
是不同状态。禁止用 0、neutral、0.5、1.0 或前向填充把 unknown 伪装成业务值。

### 4.5 语义与实现解耦

- 合同先于语言。
- schema 先于 FFI/RPC。
- strategy/risk 语义在 backtest、paper 和 live 共用。
- provider/broker SDK 对象不能越过 adapter。
- 物理路径不成为业务身份；业务只持 logical ID 和 SnapshotRef。

### 4.6 默认安全

- research/advisory 为默认模式。
- live adapter 默认不存在或 disabled。
- data degraded、model unknown、broker uncertain、audit 不可写时 no-trade。
- risk veto 不可绕过。
- 真实执行凭证与 paper 凭证物理隔离。

## 5. 架构方案比较与决策

| 方案 | 可读/扩展 | 迁移风险 | 性能潜力 | 运维复杂度 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 继续横向分层，只拆大文件 | 中 | 低 | 中 | 低 | 仅作为过渡，领域仍横跨多层 |
| 领域模块化单体 + Ports/Adapters | 高 | 中低 | 高 | 低中 | 选择 |
| 立即微服务 + 外部消息总线 | 中 | 高 | 高 | 很高 | 当前拒绝 |
| 整体 C++/Rust 重写 | 表面高 | 极高 | 未知 | 高 | 明确拒绝 |
| 插件优先大框架后迁业务 | 未知 | 高 | 未知 | 中高 | 拒绝；先做 vertical slice |

选择模块化单体的原因：

- 当前主要使用场景仍是本地研究、辅助决策和 Web 控制面。
- 已有 SQLite durable bus、RuntimeCommandRunner 和生命周期治理可复用。
- 最大痛点是边界、所有权和数据语义，而不是部署单元数量。
- 模块化单体仍允许 C++/Rust worker 或未来服务通过稳定 port 替换。
- 每个 vertical slice 都能保持可运行、可回滚。

### 5.1 未来拆服务的硬触发条件

一个模块只有同时具备稳定合同，并满足至少一项运行触发条件，才可独立
进程或服务化：

- 需要独立扩缩容或独立故障域；
- 原生崩溃会拖垮控制面；
- 有跨主机/多语言消费者；
- 组件在批准观测窗口内持续占用单机 CPU/RSS 25% 以上、影响其他 workload，
  且有独立 owner/SLO；
- 需要安全域隔离，例如真实 broker 凭证；
- 发布节奏、owner 和 SLO 确实独立；
- RPC 计算量至少是传输/序列化开销的 10 倍。

拆分前必须已有版本化 schema、幂等、replay、timeout、owner、SLO、runbook
以及进程前后 golden parity。

## 6. 目标系统全景

~~~text
External Providers / Exchanges / Brokers
          |
          v
Market & Event Ingestion
  raw capture -> normalize -> assure -> immutable publish
          |
          v
Evidence / Catalog / PIT Kernel
  snapshot -> lineage -> quality -> selector -> replay
          |
          +-----------------------------+
          |                             |
          v                             v
Features & Microstructure         Research & Experiment
technical/fundamental/news        hypothesis/backtest/validation
order-flow/SMC detectors          calibration/promotion
          |                             |
          +-------------+---------------+
                        v
Strategy & Decision Support
signal proposal -> opposing evidence -> decision record
                        |
                        v
Portfolio & Risk
allocation -> constraints -> pre-trade veto -> risk receipt
                        |
             gated by operating mode
                        v
Execution
order intent -> execution plan -> broker command
 -> execution report -> reconciliation -> ledger

Cross-cutting:
Runtime / Plugin Host / Config / Audit / Observability / Security

Interfaces:
./trade CLI / FastAPI / React / Notebook SDK
~~~

### 6.1 四个逻辑平面

| 平面 | Owner | 内容 |
| --- | --- | --- |
| 控制面 | Python | 配置、命令、workflow、plugin lifecycle、API、治理 |
| 数据面 | Parquet/Arrow + catalog | raw/canonical/feature/research artifact 和 immutable snapshot |
| 计算面 | Python + C++/Rust kernel | 纯计算、订单簿 replay、特征、回测、优化 |
| 执行面 | 独立安全域 | 风控、订单状态机、broker、对账、ledger |

控制面和执行面不能共享隐式全局状态；计算面不拥有 DB、网络或 broker。

## 7. 推荐目标目录与所有权

下面是最终逻辑树，不是一次性搬迁清单。每次只迁一个 vertical slice。

~~~text
contracts/
  schemas/                 # 语言中立的数据/事件/计算合同
  events/
  compute/

trade_py/
  platform/
    identity/              # typed IDs
    time/                  # clock、PIT、calendar、session
    errors/
    config/
    audit/

  instruments/
    domain/
    application/
    ports/
    adapters/

  market_data/
    domain/                # Bar/Trade/Quote/Book/Auction
    application/           # acquire/normalize/assure/publish/repair
    ports/
    providers/
    quality/

  evidence/
    catalog/
    snapshot/
    lineage/
    publication/
    pit/

  microstructure/
    book/
    order_flow/
    smc/

  features/
    contracts/
    registry/
    technical/
    fundamental/
    flow/
    event/
    microstructure/

  research/
    hypothesis/
    dataset/
    experiment/
    validation/
    backtest/
    observatory/

  strategy/
    contracts/
    registry/
    assessment/

  decision_support/
    belief/
    causal/
    explanation/
    trust/

  portfolio/
    accounting/
    allocation/
    constraints/

  risk/
    pretrade/
    limits/
    stress/
    monitoring/

  execution/
    orders/
    algos/
    paper/
    reconciliation/
    brokers/               # 后期，默认 disabled

  runtime/
    events/
    jobs/
    scheduler/
    commands/
    plugins/
    lifecycle/

  observability/
    context/
    logging/
    metrics/
    health/

  interfaces/
    cli/
    api/

  infrastructure/
    sqlite/
    parquet/
    duckdb/
    native/
    ipc/

trade_web/
  backend/
    app.py                 # 仅 composition、middleware、router registration
    dependencies.py
    routers/<domain>.py
    dto/<domain>.py
  frontend/src/
    app/
    features/
      operations/
      observatory/
      research/
      symbol/
      portfolio/
      execution/           # 后期
    shared/

engine/
  include/trade/
    market/
    microstructure/
    features/
    strategy/
    portfolio/
    risk/
    backtest/
    compute/
  src/
  bindings/                # 真实存在的 _trade_core bindings
  tests/

tests/
  unit/
  contract/
  integration/
  replay/
  differential/
  fault/
  perf/
  e2e/
~~~

### 7.1 防止“新目录形式主义”

- 只有一个简单纯函数时，不机械创建 domain/application/ports/adapters 四层。
- 出现外部 IO、多个 use case、独立生命周期或替换需求时才建立 port。
- shared/platform 只能放稳定、无业务偏好的小内核，不能成为新 utils。
- 每个 bounded context 必须有 owner、public API、依赖清单和禁止依赖。
- TradeDB、旧 CLI、旧 import 路径先保留兼容 facade，但只委托，不再新增业务。

## 8. 核心领域对象与端到端合同

### 8.1 标准流水线

~~~text
RawEnvelope
 -> CanonicalEvent / CanonicalDataset
 -> DatasetSnapshot
 -> FeatureSnapshot
 -> EvidenceBundle
 -> HypothesisResult / SignalProposal
 -> StrategyAssessment
 -> DecisionRecord
 -> PortfolioProposal / PortfolioIntent
 -> RiskDecision
 -> ApprovedOrderIntent
 -> ExecutionPlan
 -> BrokerCommand
 -> ExecutionReport
 -> Position/Cash LedgerEntry
~~~

### 8.2 每层唯一职责

| 对象 | 能做什么 | 不能做什么 |
| --- | --- | --- |
| RawEnvelope | 保留来源原文、时钟、hash、许可 | 不做业务真相 |
| CanonicalEvent | 统一单位、标识、时区和 schema | 不隐藏来源或修订 |
| DatasetSnapshot | 固定一组可重放输入 | 不自动成为 current |
| FeatureSnapshot | 记录依赖、warm-up、missing 和实现版本 | 不发出订单 |
| HypothesisResult | 表达可证伪命题和证据 | 不宣称已验证 |
| SignalProposal | 给出方向/强度/周期/不确定性 | 不绕过策略与风险 |
| StrategyAssessment | 汇总支持与反对证据 | 不触达 broker |
| DecisionRecord | 形成辅助决策或 no-action | 不等于 OrderIntent |
| RiskDecision | 引用账户/组合/行情/限额并 allow/reject/resize | 不允许被插件跳过 |
| ApprovedOrderIntent | 引用 decision 与 risk receipt 的批准交易意图 | 不包含 broker SDK 对象 |
| ExecutionReport | 保存 ack/fill/reject/cancel/unknown | 不猜测未确认状态 |
| LedgerEntry | 形成持仓、现金和费用真相 | 不从临时内存反推 |

### 8.3 DecisionRecord 最低字段

- decision_id、decision_time、knowledge_cut；
- asset/universe、horizon、operating_mode；
- action：observe、avoid、watch、consider_entry、consider_exit、no_action；
- score/probability、calibration_state、confidence_state；
- supporting_evidence、opposing_evidence、unknowns、blockers；
- dataset_snapshot_id、feature_set_id、model/policy id；
- config/schema/code/plugin hashes；
- decision_risk_assessment_ref（可选、仅表示策略侧风险信息）；
- reason_codes、expiry。

DecisionRecord 不包含执行风控回执。强制 RiskDecision 发生在组合/账户上下文
确定之后，它引用 decision_id、position/cash/market snapshot 和 limits version；
只有通过该风控的 ApprovedOrderIntent 才引用 risk_receipt。

当前固定阈值/固定权重推荐必须标注 legacy heuristic，不能直接晋升为正式
决策内核。

## 9. 公共 Evidence、PIT 与发布内核

### 9.1 统一时钟

公共合同至少支持：

- event_time：事实发生时间；
- published_at：来源公开时间；
- source_seen_at：来源首次可观察时间；
- received_at：本系统接收时间；
- available_at：允许决策使用的时间；
- materialized_at：衍生结果生成时间；
- revised_at：修订进入系统时间；
- decision_time/knowledge_cut：决策所知截止时间。

不是所有来源都能提供所有时钟；缺失时必须标 unknown。strict as-known 模式
下缺少所需时钟的事实不可见，不能用文件 mtime 或当前时间补造。

### 9.2 统一身份与状态

每条事实或 artifact 至少包含：

- provider/source、external id、asset/instrument/venue/session；
- schema version、payload/content hash、ingest run；
- revision、supersedes、finality；
- availability、quality flags、provenance refs、license policy；
- logical dataset id、physical artifact refs。

正交状态轴必须分开：

| 轴 | 示例 |
| --- | --- |
| Channel | observed / evaluated_candidate / formal / exact |
| Acquisition | not_attempted / running / succeeded / partial / empty / failed / abandoned / unknown |
| Quality | not_evaluated / assured / degraded / insufficient / invalid / unknown |
| Lifecycle | staged / published / superseded / rolled_back / unknown |
| Research | exploratory / eligible / candidate / monitoring / validated / rejected / blocked / unknown |
| Freshness | fresh / stale / unknown |
| Compatibility | compatible / contract_stale / replay_mismatch / unknown |
| Availability | present / missing / unobserved / unknown |
| 运行健康 | ready / degraded / saturated / stopping / failed |
| 执行模式 | research / advisory / paper / shadow / live |

这些名称优先沿用 Observatory 已冻结 vocabulary；公共内核不得把 Channel
重新解释为 Lifecycle。新增状态必须带 mapping policy version，禁止把这些
压成一个模糊的 trust score。

### 9.3 不可变 Snapshot

~~~text
snapshot_id = hash(
  logical dataset identity,
  input artifact hashes,
  schema versions,
  transformation/plugin versions,
  transformation implementation/code hash,
  config hash,
  knowledge cut,
  knowledge mode,
  revision policy,
  PIT/resolver policy version,
  universe/selector definition version,
  exchange calendar/session version
)
~~~

current/candidate 只是原子 pointer，不是数据本身。publish 必须有 receipt，记录
旧指针、新指针、gate、hash、actor、时间和 rollback target。

publication channel 按 artifact kind 独立，例如 dataset、feature、model 和
research result 各有自己的 candidate/current；禁止一个全局 current 混合覆盖。
所有 Quality Gate 使用统一 receipt：gate definition/version、purpose、
applicability、threshold/config hash、evidence refs、affected ranges、
evaluated_at、code hash 和 outcome。

### 9.4 存储层含义

- ODS：不可变原始证据；清洗失败不能阻塞原始留存。
- DIM：bitemporal 主数据、日历、分类和映射。
- DWD：规范化事实。
- DWS：派生特征、状态和聚合。
- ADS：研究、决策、产品投影。
- Catalog/manifest：所有层的逻辑身份、hash、lineage、quality、pointer。

不立即移动现有物理路径。先让 Catalog/Resolver 提供逻辑寻址和兼容 adapter。

## 10. 类型化插件体系

### 10.1 插件类型

- DataProvider
- Canonicalizer
- QualityRule
- FeatureCalculator
- OrderFlowFeature
- SMCDetector
- Hypothesis/SignalModel
- Strategy
- PortfolioAllocator
- RiskRule
- ExecutionAlgo
- BrokerAdapter
- Reporter/Projection

BrokerAdapter 只共享 manifest/contract vocabulary，不由通用研究 PluginHost
加载；live execution host 和 core Risk Authority 是独立安全域。

### 10.2 CapabilityDescriptor

~~~yaml
plugin_id: market.okx.trades
plugin_version: 1.2.0
api_version: plugin/v1
kind: data_provider
capabilities: [trade_print]
asset_classes: [crypto]
venues: [okx]
frequencies: [tick]
input_contracts: []
output_contracts: [TradeEvent/v1]
clock_semantics: exchange_and_received
correction_policy: append_revision
deterministic: false
statefulness: session
resource_class: io_worker
runtime: worker_process
permissions: [network:okx, write:raw_capture]
failure_modes: [rate_limited, gap, reconnect, invalid_schema]
degraded_behavior: unavailable
owner: market-data
research_state: candidate
~~~

正式 manifest 还必须包含 config schema、依赖、units、warm-up、PIT policy、
idempotency、timeout/cancellation、资源预算、许可/数据分类、test receipt 和
兼容范围。

### 10.3 生命周期

~~~text
discover
 -> validate manifest/config/schema
 -> resolve dependency graph
 -> compatibility negotiation
 -> start with scoped capabilities
 -> execute with RunContext
 -> emit result/evidence/metrics
 -> health/capacity
 -> drain/stop
 -> quarantine or retire
~~~

### 10.4 执行隔离

| 模式 | 适用 | 约束 |
| --- | --- | --- |
| trusted_inproc | 小型、纯 Python、无副作用计算 | allowlist、静态护栏、scoped API、协作式取消 |
| native_inproc | 稳定、粗粒度、已验证 C++ kernel | ABI、GIL、内存 owner、崩溃风险 |
| worker_process | provider、长任务、高内存、第三方、Rust 或强隔离 | 强制 deadline、资源/网络/文件隔离、IPC、可重启 |
| remote_service | 未来独立扩缩容/安全域 | 只有满足服务化触发门槛 |

V1 不支持运行时 pip install、任意 entry point 或不受信二进制。

in-process 权限只是对可信代码的架构约定和静态 fitness，不是安全沙箱；
线程内 timeout 也只能协作取消。需要强制终止、CPU/RSS/网络/文件权限隔离、
第三方代码或原生 crash isolation 时必须使用 worker process/container。

### 10.5 权限与安全边界

- 插件获得 capability-scoped port，不获得 TradeDB、data root 或 broker client。
- 数据插件只能产生数据和质量证据。
- 特征、新闻、SMC 和模型插件只能产生 evidence/signal。
- 策略/DecisionPolicy 只能产生 SignalProposal、StrategyAssessment 或
  PortfolioProposal，不能产生 OrderIntent。
- 可插拔 RiskRule 只能提供补充约束；不可关闭的核心 Risk Authority 拥有
  fail-closed veto，并由 application 层创建 ApprovedOrderIntent。
- BrokerAdapter 不与研究插件共用通用 PluginHost；它运行在独立执行安全域，
  只有 execution application 可调用。
- current pointer、model promotion 和 live enable 由独立 authority 管理。
- 插件失败返回 typed unavailable/degraded/invalid，不能悄悄填 0。

### 10.6 迁移策略

先为现有 data registry、FactorGroupResult、C++ FeatureCalculator 和 IStrategy
写 adapter，再迁一个低风险 vertical slice。首个建议切片：

1. 将现有 CMF 明确命名为 cmf_ohlcv_proxy；
2. 用 FeaturePlugin manifest 描述输入、单位、warm-up 和 missing；
3. Python/C++ 对同一 golden bars 做 differential test；
4. 保持原字段兼容映射和 deprecation telemetry；
5. 验证后再迁 fund-flow provider。

## 11. Order Flow、L2 与 SMC 专项设计

### 11.1 必须分开的概念

| 能力 | 输入 | 可以说明 | 不能说明 |
| --- | --- | --- | --- |
| CMF/OHLCV proxy | K 线 + volume | 日级量价累积/派发代理 | 真实委托、主动买卖或机构身份 |
| Provider fund flow | 供应商聚合字段 | 供应商口径下的大/中/小单净额 | 原始逐笔或独立交叉验证 |
| Order Flow | trades/quotes/book | 成交方向、深度、流动性、撤单和冲击 | 必然的未来方向 |
| SMC detector | bar 或 microstructure evidence | 某个版本化形态定义被触发 | “聪明钱真实意图”这一不可观察事实 |

### 11.2 Canonical 微观结构事件

首版合同至少包括：

- TradeEvent：price、quantity、trade id、aggressor side 或 inference method；
- QuoteEvent：best bid/ask、size、source sequence；
- BookSnapshot：多档 bid/ask、snapshot id、checksum；
- BookDelta：side、price、new quantity/action、sequence、prev sequence；
- AuctionEvent：indicative price、imbalance、matched/unmatched quantity；
- SessionEvent：open/close/halt/resume/reset；
- 公共字段：venue、instrument、stream/channel/partition id、source session id
  或 sequence epoch、exchange time/原始精度、received time、clock quality/
  offset bound、sequence、provider、schema、raw hash、run id；
- 价格和数量使用 integer ticks/lots 或声明 currency、multiplier 和
  fixed-decimal precision；
- aggressor/inference method 必须有 version 和 confidence。

available_at 是由版本化 eligibility policy 根据来源时钟、接收时钟、session
和质量状态派生的决策资格时间，不假设两个来源时钟天然严格可比。无法约束
clock error 的数据只能进入 exploratory。

### 11.3 L2 数据质量门禁

| Gate | 要求 |
| --- | --- |
| D0 Contract | venue/instrument、时区、tick/lot、价格精度、单位、provider identity |
| D1 Acquisition | 成功率、延迟、覆盖、quota、断路器、raw payload 留存 |
| D2 Structure | sequence 单调、重复、gap、snapshot/delta 衔接、reset、crossed book、负深度 |
| D3 Reconciliation | 优先独立来源；缺少第二来源时用 sequence/checksum、trade/top-of-book/session totals 等独立不变量验证 |
| D4 Revision/Replay | immutable input；增量和全量 replay hash 一致 |
| D5 PIT/Fitness | event_time <= available_at <= decision_time；未知时间 fail closed |
| D6 Operations | 吞吐、延迟、队列、丢包、DLQ、恢复、成本和许可 |

所有 gate 都必须声明 applicability。D3 无合法独立来源时允许
not_applicable，但必须有批准理由、single-source confidence 和替代不变量；
同源转售不能冒充独立来源。受许可限制无法永久保留原始字节时，至少保留
hash、签名/provider receipt 和受限审计元数据。未通过所有适用 D0-D5 的
数据最多用于探索性可视化，不能进入严格回测、正式推荐或 paper/live。

### 11.4 订单簿重建

目标流水线：

~~~text
raw snapshot/delta
 -> schema and sequence validation
 -> partitioned append-only capture
 -> deterministic book state machine
 -> checkpoint + replay hash
 -> objective microstructure features
 -> research hypothesis
~~~

状态机必须处理：

- reconnect 后的新 snapshot；
- duplicate、out-of-order、gap、reset；
- checksum mismatch；
- crossed/locked book；
- venue session 和 auction；
- 源时钟漂移与延迟；
- poison partition 隔离；
- 未知状态进入 GAP/REBUILDING，不用上一份 book 冒充当前。

### 11.5 第一批客观 Order Flow 特征

- signed volume / CVD；
- trade imbalance；
- top-N depth imbalance；
- spread、microprice、depth、resiliency；
- OFI；
- cancel/add intensity；
- sweep/large print；
- absorption/exhaustion 的可重复定义；
- auction imbalance；
- venue/session-normalized liquidity regime。

每个特征必须声明单位、方向、窗口、warm-up、缺失策略、输入 capability、
event-time/PIT 语义、计算版本和适用 venue。

### 11.6 SMC Research Lab

SMC 不是 core truth，也不是一个巨型策略插件。每种定义是独立、
可证伪的 detector：

- swing high/low；
- BOS / CHOCH；
- displacement；
- fair value gap；
- order block；
- liquidity pool / sweep；
- premium/discount range。

输出合同：

~~~text
pattern_id
definition_version
asset/venue/timeframe
anchor_time + confirmation_time
input_snapshot_id
parameter_set
evidence rows/ranges
confidence_state
invalidation condition
validation_status
~~~

研究门禁：

1. 与随机、buy-and-hold、简单动量、CMF 等基线比较；
2. purged walk-forward + embargo；
3. 样本外、跨年份、跨 regime、跨市场稳定性；
4. 交易成本、滑点、延迟和容量敏感性；
5. 参数敏感性、消融和 multiple-testing correction；
6. calibration 和失败切片；
7. 先 candidate，再 shadow；未通过不得进入正式决策。

## 12. 研究、策略、回测与模型治理

### 12.1 研究对象

每次 ExperimentRun 应冻结：

- hypothesis id/version 和预注册问题；
- DatasetSnapshot/knowledge cut/revision policy；
- universe 和 bitemporal instrument definition；
- labels、horizon、purge/embargo；
- feature manifest；
- code/config/environment hash；
- baseline 和 evaluation protocol；
- costs/slippage/capacity assumptions；
- seed 和 determinism；
- artifacts、metrics、slice results 和 failure notes。

### 12.2 统一 FeatureSpec

当前多套 Python/C++ feature schema 应逐步收敛为单一逻辑 authority。
FeatureSpec 至少包括：

- stable feature id、semantic version、owner；
- input contract 和 dependencies；
- units、scale、direction、valid range；
- event/available time policy；
- warm-up、lookback、label exclusion；
- missing/default policy；
- deterministic/approximate；
- implementation ref/hash；
- research_state 和 deprecation。

禁止为图方便继续给 signals 表加大量可空列。特征值属于版本化
FeatureSnapshot，索引/摘要才进入控制库。

### 12.3 Backtest、Paper 与 Live 同核

三种模式必须共享：

- market/session calendar；
- strategy interface；
- portfolio accounting；
- risk rules；
- order intent；
- fee/slippage model contract；
- execution report contract；
- clock injection。

允许不同的是 venue adapter 和 timing model。现有 t 收盘生成信号、t+1
开盘执行的不变量应保留为日频 golden case。

### 12.4 模型生命周期

模型不是一个混合所有含义的线性状态机，必须维护正交轴：

| 状态轴 | 示例 | Authority |
| --- | --- | --- |
| research_state | exploratory/candidate/validated/rejected | Research Promotion |
| publication_channel | none/candidate/current/retired | Artifact Publisher |
| deployment_state | not_deployed/shadow/active/disabled | Deployment Authority |
| health_state | ready/degraded/failed/unknown | Runtime Health |
| operating_mode | research/advisory/paper/shadow/live | Safety Authority |

每份 promotion receipt 只能修改自己拥有的轴。monitoring 是持续活动，
degraded 是 health，二者都不是 current 的后继枚举。promotion 必须原子、
有 receipt、可回滚，绑定 dataset、feature、code、config、evaluation、
calibration、approver 和旧版本。模型不可用时使用明确 deterministic
fallback 或 no-action，禁止静默切换。

### 12.5 防泄漏验证

- 未来行注入不改变过去结果；
- 当前行业/证券属性变化不改变历史样本；
- 缺失 available_at 的事实不可进入 strict dataset；
- label window 与 feature window 不重叠；
- rolling/expanding 统计只使用 knowledge cut 内数据；
- 新闻 revision、撤稿和 pseudo-label 可回放；
- train/inference 使用同一 FeatureSpec；
- restated 与 as-known 结果明确分开。

### 12.6 防选择偏差与试验治理

时间无泄漏不等于研究无过拟合。还必须建立：

- immutable experiment-family/trial registry，失败、放弃和负结果也登记；
- 运行前登记 hypothesis、primary metric、config hash 和 stopping rule；
- sealed final holdout，仅在 promotion 决策时按权限开启；
- multiple-testing budget/correction；
- 置信区间、经济显著性、成本/容量压力测试；
- corporate action、退市、历史成分股和 censored labels 的 PIT 门禁；
- 重复试验、参数搜索和人工挑选全部进入 audit。

## 13. Portfolio、Risk、OMS 与 Execution

### 13.1 能力分层

| 层 | 核心职责 |
| --- | --- |
| Portfolio | position/cash/lot accounting、allocation、exposure、constraints |
| Risk | pre-trade veto、limits、stress、drawdown、concentration、liquidity |
| OMS | durable order state machine、idempotency、cancel/replace、ledger link |
| EMS | execution algo、venue routing、throttle、market/session handling |
| Reconciliation | broker order/fill/position/cash 与本地 ledger 对账 |

### 13.2 Order 状态机

至少覆盖以下分支，不得解释为一个线性枚举：

| From | 允许的 To | 说明 |
| --- | --- | --- |
| DRAFT/PENDING_RISK | RISK_REJECTED / APPROVED | RISK_REJECTED 为终态 |
| APPROVED | SUBMITTING / EXPIRED / CANCELLED | 提交前仍可取消或过期 |
| SUBMITTING | ACKNOWLEDGED / BROKER_REJECTED / SUBMIT_UNKNOWN | 超时不能猜测是否已提交 |
| SUBMIT_UNKNOWN | RECONCILING | 冻结 scope，查询 broker |
| RECONCILING | ACKNOWLEDGED / BROKER_REJECTED / CANCELLED / MANUAL_REVIEW | 只能由 reconciliation receipt 推进 |
| ACKNOWLEDGED | PARTIALLY_FILLED / FILLED / CANCEL_PENDING / EXPIRED | 以 broker event 为证据 |
| PARTIALLY_FILLED | PARTIALLY_FILLED / FILLED / CANCEL_PENDING | 累计成交单调 |
| CANCEL_PENDING | CANCELLED / PARTIALLY_FILLED / FILLED / RECONCILING | cancel pending 后允许 late fill |

RISK_REJECTED、FILLED、CANCELLED、BROKER_REJECTED、EXPIRED 通常为终态；
若 venue 支持 trade correction/bust，只能通过显式 correction/adjustment
事件形成新账本投影，不能改写历史终态。
RISK_REJECTED 后若条件改变，必须创建新的 intent/version 和新的
RiskDecision receipt，不能复活原 intent。

每次状态迁移使用单调 transition_version/CAS，并记录 attempt、owner
lease epoch/fencing token、broker event sequence、client_order_id、
broker_order_id 和 event id。重启后从 durable ledger 与 broker execution log
恢复，禁止因本地状态不明而重新下单。

### 13.3 不可绕过的安全控制

- max order notional/quantity/rate；
- account/asset/sector/venue exposure；
- position、cash、borrow 和 settlement 检查；
- A 股 T+1、涨跌停、停牌、lot size；
- stale decision 和 stale market state 拒绝；
- daily loss/drawdown；
- price collar/fat-finger；
- global/account/strategy/asset kill switch；
- audit store 不可写时禁止新单；
- broker uncertain 时冻结相关 scope 并先对账；
- paper/live credentials、data root 和 endpoint 隔离；
- 双重 enable 和人工确认。

### 13.4 Broker 与本地账本的权威语义

- broker order/fill/position/cash 消息是不可变外部证据，不覆盖删除。
- 本地现金、持仓、成交采用 append-only、double-entry ledger projection。
- 本地与 broker 差异创建 ReconciliationCase，不直接改历史行。
- 未解决差异冻结受影响 account/asset/strategy 的新订单。
- 调账必须使用显式 AdjustmentEntry，记录 actor、reason、evidence 和审批。
- 每个 RiskDecision 绑定 account、position、cash、market snapshot、
  limits version、decision id 和 expiry。
- broker submit 超时属于 SUBMIT_UNKNOWN；只能通过稳定 client id、查询和
  reconciliation 收敛。

### 13.5 渐进路径

~~~text
research-only
 -> decision advisory
 -> deterministic simulator
 -> paper broker
 -> live-data shadow, no orders
 -> shadow orders, not submitted
 -> small-account canary
 -> bounded live
~~~

每次升级都需要独立 receipt 和 rollback。现有 C++ OrderManager/IExecutionVenue
只能作为 planning/simulation 的输入，不是现成实盘 OMS。

## 14. 多语言与高性能路线

### 14.1 语言职责

| 技术 | 推荐职责 | 不推荐职责 |
| --- | --- | --- |
| Python | 编排、研究、数据治理、插件宿主、Web/API、低频策略 | 极细粒度逐消息 Python object 热循环 |
| NumPy/Arrow/DuckDB/Polars | 批量列式计算、扫描、join、aggregation | 订单状态和业务事务真相 |
| C++ | 已有数值核、批量特征、回测撮合、风险矩阵、组合优化 | DB/network/lifecycle/plugin discovery |
| Rust | 新 L2 流、book replay、长连接、执行边缘候选 | 重写已有稳定 Python/C++ 业务 |
| TypeScript | 前端和 DTO | 正式研究、风险和执行真相 |
| Java | 已存在 JDBC compatibility adapter（如有真实 consumer） | 新计算内核或无 owner 的长期旁路 |
| Go | 未来独立高并发网络服务的备选 | 当前模块化单体重写 |

### 14.2 跨语言接口层级

1. 首选 Python/列式库：先消除逐行循环、整表复制和无界扫描。
2. native in-process：nanobind + Arrow C Data Interface，适合纯、稳定、
   粗粒度 kernel。
3. worker process：Protobuf/JSON 控制面 + Arrow IPC/Flight 数据面，适合
   crash isolation、Rust worker 或独立资源限制。
4. remote service：只在服务化门槛达到后采用。

原生扩展应命名为 _trade_core，不能再与 trade_py 包重名。

### 14.3 Native 下沉门槛

采用以下初始政策，基线评审后可在 OpenSpec 中调整：

- profiler 证明该纯计算路径占端到端时间至少 20%，或明确错过 SLO；
- NumPy/Arrow/DuckDB 向量化后仍不达标；
- kernel 本身至少 2 倍提升；
- 包含转换/复制后的端到端收益至少 20%；若要长期承担复杂维护，目标应
  接近 3 倍；
- 数据转换不超过 kernel 总耗时 20%；
- 峰值内存不高于基线 1.2 倍；
- golden/differential、null/NaN、时区、精度、错误和生命周期测试全部通过；
- 必须保留 Python reference 或可回退 adapter，直到稳定期结束。

Python fallback 只覆盖 feature flag、版本/兼容性错误、数值校验失败和调用前
路由。native in-process 的 segfault/abort 会终止宿主，不能在同进程捕获后
回退；其策略是 fail-fast/fail-closed，由外部 supervisor 重启。需要 crash 后
自动恢复的 kernel 必须使用 worker process。

### 14.4 Kernel 合同

每个 kernel 必须声明：

- schema/version；
- deterministic 和数值容差；
- null/NaN/infinity 规则；
- timezone、price/quantity precision；
- input ownership 和 output ownership；
- GIL、thread safety、cancellation；
- copy count、bytes、RSS、throughput、p50/p95/p99；
- Python reference 和 golden vectors；
- incompatible version 的 fail-fast 行为；
- compiler/stdlib ABI、wheel/platform/CPU ISA compatibility；
- reproducible build、SBOM、symbol visibility 和 binary rollback。

### 14.5 初始 workload 和容量基线

Phase 0 只建立当前已经存在的 workload：

- 当前约 5700 个证券、约 300 万 factor rows 的真实规模；
- 10x 合成批量规模；
- 10k/100k EventBus replay；
- API 轻查询/重查询/SSE 10、100 clients；
- Parquet append/merge/scan/compaction 和文件发现；
- 现有 Python/C++ 能力的基准和差分；
- 当前 runtime 的 24 小时阶段退出 soak。

SSE 1000 clients 属于专项/夜间容量实验，不进入每次 CI。Rust differential、
订单簿 1x/10x burst 和 L2 24h soak 分别在 Phase 8B/9 能力存在后建立。

### 14.6 性能预算

每个 benchmark receipt 必须冻结 hardware/CPU governor、软件版本、数据
规模/分布、payload bytes、并发、warm/cold cache、样本数、采样窗口和
置信区间。代表性 workload 的 p95 上升 5% 和 RSS 上升 10% 先作为 review
告警，不直接作为易抖动的硬失败；硬门禁由实测噪声、统计显著性和绝对 SLO
共同校准。如为正确性或可恢复性主动交换性能，必须在 Design Quality Brief
中记录理由、容量余量和后续优化任务。

建议的初始辅助决策 SLO，必须先实测再冻结：

| 路径 | 初始目标 |
| --- | --- |
| EventBus durable publish | p95 < 20 ms，p99 < 50 ms |
| admission decision | p99 < 5 ms |
| scheduler 到 durable event | p99 < 1 s |
| 轻量 API | p95 < 200 ms，p99 < 500 ms |
| 重查询 | p95 < 1 s；预计超 1 s 转异步 job |
| event-loop lag | p99 < 50 ms |
| 有界 shutdown | <= 10 s，残留 owner/lease/process 为 0 |
| 正常 backlog | oldest age < 1 min；恢复 < 5 min |
| 控制/研究面 RTO | <= 15 min |

未来 L2 选型压测包络，不是 HFT 产品承诺：

- 单节点持续 50k market messages/s，但测试必须同时声明平均 encoded
  bytes、symbols、book depth、压缩、durability 和 retention；
- 10 秒 burst 200k messages/s；
- receive → low-latency canonical visibility p99 < 20 ms；
- canonical → strategy visibility p99 < 50 ms；
- 对提供连续 sequence/checksum 的来源，gap 检测率 100%；
- durable raw capture 的 acknowledgement 单独定义，不与低延迟可见点混淆；
- execution runtime 恢复目标 < 30 s；broker session 和 reconciliation
  使用独立 RTO，恢复先冻结新单并对账。

50k/s 若平均 200 bytes/event，仅原始未压缩量就约 864 GB/day。Phase 9
必须先批准 retention/tiering、压缩、索引、副本、临时空间、磁盘/网络成本
和数据许可；否则该吞吐数字没有实施意义。

### 14.7 Durability 与 RPO/RTO 故障模型

所有耐久声明必须区分 acknowledgement boundary 和故障域：

| 指标 | 定义 |
| --- | --- |
| local durable commit | fsync/transaction commit 已完成，但未承诺主机/磁盘故障 |
| replicated commit | 独立故障域副本确认 |
| broker acknowledgement | 外部 broker 已确认，可通过其查询/日志恢复 |
| RPO_process | 仅进程崩溃 |
| RPO_host | 宿主机丢失 |
| RPO_disk/site | 磁盘或站点丢失 |
| RTO_runtime | 本地进程恢复 |
| RTO_broker_session | 连接、认证、session 恢复 |
| RTO_reconciliation | 不确定订单与账本收敛 |

当前单机 SQLite/Parquet 只能对已 fsync 的本地进程崩溃给出相应保证，不能
宣传主机/磁盘级 RPO 0。若 live 要求主机/磁盘级 RPO 0，必须使用同步复制
或等价 durability。live ledger 不默认复用当前 SQLite 控制库及其
synchronous=NORMAL 策略。已被 broker 接收的 order/fill 以 broker 查询/
execution log + 本地 reconciliation 恢复，不承诺外部系统所有故障下绝对零
信息丢失。

若实际目标继续是日线/分钟辅助决策，应降低这些预算，而不是因此提前引入
分布式流处理。

## 15. 存储架构与演进触发器

### 15.1 当前推荐

| 数据 | 当前 owner | 建议 |
| --- | --- | --- |
| 配置/任务/状态/catalog/audit 索引 | SQLite | 保留；按 repository 拆 owner 和 transaction |
| 日线/研究/特征大表 | Parquet + DuckDB | 保留；改 immutable partition + manifest |
| raw provider payload | immutable files/Parquet | content-addressed、保留许可和 hash |
| 高频逐笔/L2 | 新 append-only partitions | 从第一天避免整证券文件重写 |
| order/fill/ledger | 未来独立 durability domain | 先定义 port；live 前评估 PostgreSQL/复制 |

DuckDB 只作为 immutable/只读输入上的分析查询引擎，不承载运行时事务真相。
多进程写入必须有单一 owner，或只写彼此独立的 immutable partitions。

TradeDB 拆分时先保留一个物理 trade.db，避免跨库事务和迁移风险。拆的是：

- Connection/TransactionManager；
- SchemaMigrator；
- SettingsRepository；
- InstrumentRepository；
- Job/Event/RuntimeRepository；
- DataQuality/CatalogRepository；
- Research/ModelRepository；
- Decision/AuditRepository。

旧 TradeDB 作为 compatibility facade 委托这些 repository。

### 15.2 构造与配置

- 正常 reader 不触发 migration、seed 或目录创建。
- migration 是显式 setup/startup command。
- writer startup 在 data-root/schema owner lock 下执行 schema version gate；
  纯 reader 遇到缺失或过旧 schema 时 fail closed，并返回 typed
  schema_not_ready，不自行升级。
- fresh install、旧版本 DB、migration failure 和 rollback 都要有 CLI 流程、
  backup/receipt 和恢复测试。
- 配置加载生成 immutable typed SettingsSnapshot 和 config hash。
- DB 配置、YAML 和 env 的优先级保持兼容，但读取不应隐式打开可写 DB。
- secrets 只通过 env/keyring/secret adapter，不落普通 config 或日志。

### 15.3 PostgreSQL 触发条件

以下都是“启动迁移 ADR/容量评估”的触发器，不会自动授权迁库：

- 同一 DB 出现两个及以上长期并发 writer 进程/节点；
- SQLITE_BUSY/timeout 超过事务 0.1%；
- write transaction p99 连续 15 分钟超过 50 ms；
- checkpoint 超过 5 秒；
- WAL 长期超过 512 MiB 或主库 20% 且无法回收；
- 需要主备、远程访问、行级锁或订单账本 HA；
- 恢复演练无法满足 RPO/RTO。

文件大小本身不是迁库理由。先有 repository port、双写/影子读和恢复方案。
Phase 0 先盘点当前 Web、daemon、CLI subprocess 是否已经构成并发 writer。

### 15.4 Parquet 分区与 compaction 触发条件

以下条件触发分区/compaction ADR，而非看到一个比例就立即搬迁：

- 相对写放大超过 5 倍，并且绝对 bytes、CPU、延迟或成本也超过批准预算；
- foreground append p95 超过 2 秒；
- 单个代表查询需枚举超过 10000 文件，或 file discovery p95 超过 500 ms；
- small-file ratio 或 compaction debt 连续超过数据集预算；
- 查询扫描放大超过预算；
- 引入分钟、逐笔或 L2。

逻辑 partition 可以包含多个文件。128–256 MiB 可作为初始目标文件大小区间，
不是 partition 上限；实际值由压缩率、查询和 object/filesystem 决定。
每个 dataset 明确 partition key、target file size、foreground append、
background compaction、small-file ratio 和 compaction debt。immutable snapshot
不等于立即搬迁全部既有日线文件。

目标协议：

~~~text
same-filesystem temp write
 -> fsync temp + close
 -> schema/hash/row-count verification
 -> atomic rename/link
 -> fsync parent directory
 -> immutable manifest generation
 -> pointer CAS by the single publication authority
 -> pointer/outbox intent or durable receipt
 -> downstream visibility
 -> startup reconciliation for every intermediate state
~~~

temp 与目标必须位于同一 filesystem；immutable generation 不覆盖同名内容。
多 writer 不得对一个 manifest 做无锁全量 read-modify-write。文件与 SQLite
无法同事务时，明确每个 crash window 的 write-ahead intent、幂等 reconcile、
孤立 artifact 处理和 receipt-verified visibility，并为每个 crash point 写
fault test。

Publication 状态机固定为：

~~~text
PREPARED -> COMMITTED -> PROJECTED
~~~

- PREPARED：artifact/manifest 已验证，但不对正式 reader 可见；
- COMMITTED：authoritative publication receipt 已耐久提交；
- PROJECTED：pointer、catalog read model 和 outbox 投影已收敛。

authoritative receipt 是唯一发布真相；pointer 是可 CAS、可重建的读侧投影，
不能单独证明发布成功。pointer 与 outbox 之间崩溃时，startup reconciliation
按 receipt 幂等补投影。没有 receipt 的孤立 immutable artifact 可隔离并按
retention/GC policy 处理，不能被 reader 猜测为 current。

Catalog 还需按 manifest bytes/entries、加载 p95、更新率和 CAS conflict rate
设分片/索引评估阈值，不能让单个全量 manifest 成为新的 catch-all。

### 15.5 外部消息总线评估触发条件

- 多进程/多主机消费者；
- 合法稳态流量在足够样本下 saturation 连续 5 分钟超过 1%；
- durable publish p99 超过 50 ms；
- replay backlog 恢复超过 5 分钟；
- 需要 broker 复制、分区顺序或跨服务消费。

攻击、误请求或安全拒绝造成的 saturation 不作为迁移理由。达到条件只启动
ADR；仍需验证 owner、schema、成本、运维和回滚。

消息只携带小型控制信息和 artifact reference。超过 64 KiB 的数据应进入
artifact store。跨服务后再在 NATS JetStream、Redpanda/Kafka 中按语义选型。

## 16. Runtime、并发与可靠性语义

### 16.1 共享 Composition Factory 与明确 Runtime Owner

CLI、Web、scheduler、worker 和 tests 共享 composition factory 与合同，但
不是跨进程全局 singleton。每个 process/resource graph 有一个生命周期 owner；
每个 data-root 的写 authority、scheduler leader 和 publication authority 另由
lease/lock 明确。

| 角色 | 生命周期 owner | 可并存行为 | 独占要求 |
| --- | --- | --- | --- |
| Web process | FastAPI lifespan | 只读 query、提交 durable command | 不直接成为任意后台线程 owner |
| Daemon/scheduler | daemon main | event/job worker | 每 data-root 一个 scheduler leader |
| One-shot CLI | command scope | 只读可并存 | 写命令获取同一 scoped writer/publication lock |
| Worker process | parent supervisor | immutable input 计算 | 不拥有 current pointer 或 schema migration |
| Tests | fixture scope | 临时 data-root | 不共享生产 data-root |

composition factory 构造：

- SettingsSnapshot；
- repositories/unit of work；
- EventRuntime；
- CommandExecutor；
- Scheduler；
- PluginHost；
- observability context；
- optional native/worker adapters。

禁止 use case 自己创建 TradeDB、EventBus、线程、process 或 provider client。
CommandExecutor 是 application port；现有 RuntimeCommandRunner 是首个 adapter，
不能再造第二个并行命令 owner。

SQLite 初始连接模型：

- read-only/query 使用 query_only 的独立连接或有界 read pool；
- write use case 每个 UnitOfWork 独立连接，不跨线程共享连接；
- 写事务经 TransactionManager 串行/协调，默认显式 BEGIN IMMEDIATE；
- busy timeout + bounded retry，不无限等待；
- 每个 data-root 一个 checkpoint owner；
- shutdown 顺序为 stop admission → drain → commit/rollback → checkpoint
  （适用时）→ close connections → release lease。

若 Phase 2 benchmark 证明其他 BEGIN/连接策略更合适，必须在 OpenSpec 中记录
新合同和并发测试。

### 16.2 任务状态机

~~~text
QUEUED -> CLAIMED -> RUNNING -> SUCCEEDED
             |          |
             |          +-> RETRY_WAIT -> QUEUED (new attempt)
             |          +-> FAILED_TERMINAL
             |          +-> QUARANTINED
             |          +-> CANCELLED
             |          +-> UNKNOWN_RECONCILING
             +-> LEASE_EXPIRED/ABANDONED -> QUEUED (fenced new owner)
~~~

### 16.3 可靠性规则

- 传输按 at-least-once 设计；内部可控写操作以幂等状态转换实现可重复效果。
  外部 provider/broker/filesystem 副作用不假设 exactly-once，通过稳定 client
  id、查询、receipt 和 reconciliation 收敛。
- key 至少含 capability、schema、asset/partition、as_of 和 input hash。
- 每次执行记录 attempt、lease expiry、owner epoch/fencing token；stale owner
  不能提交新状态。
- DB 状态与事件使用 transaction outbox。
- 文件与 DB 无法同事务时，以 content hash/receipt + startup reconciliation 闭环。
- retry 使用 exponential backoff + jitter + 总预算。
- provider 有 timeout、circuit breaker 和 quota state。
- saturated 返回 typed saturated 与 Retry-After，不创建无限线程/队列。
- poison event 进入 quarantine/DLQ，不阻塞整个通道。
- heartbeat/lease renewal 使用共享调度器，不为每个 handler 创建线程。
- SIGTERM/SIGINT 先停止准入，再 drain、checkpoint、reconcile、释放 owner。
- scheduler 使用 owner lease、稳定 fire key、durable next-fire 和 missed-fire
  catch-up；允许的重放量必须能在批准 RTO 内由实测吞吐处理。

### 16.4 容量模型

- worker 利用率：rho = arrival_rate × service_time / workers，长期 < 0.7；
- burst capacity 覆盖允许的 burst duration，并同时计算最大消息内存；
- SQLite writer 利用率：write_rate × p95 transaction time < 0.5；
- SSE 查询放大：clients / poll_seconds，应通过共享 change feed 降低；
- Parquet write amplification 目标 < 3x；超过 5x 时结合绝对成本启动评估；
- FFI compute/convert ratio 目标 >= 10。

### 16.5 ResourceGovernor 与全局线程预算

局部 channel capacity 不足以防止嵌套并行过载。Runtime 还要统一治理：

- CPU/thread、RSS、DB writer、disk I/O、network/provider quota token；
- 每个 JobSpec/PluginSpec 的资源需求、最大并行度和 burst；
- OMP、BLAS、Arrow、DuckDB、LightGBM、C++/Rust worker 的线程额度；
- 默认禁止 nested parallelism，或由 governor 显式分配；
- 为 Web control、reconciliation、health 和 kill-switch 保留资源；
- admission 同时检查 channel capacity 与全局预算；
- fan-out、GIL、共享 DB 和长尾 workload 使用 soak/queue age 验证，而不是
  只看平均 rho。

## 17. CLI、API、Web 与 Notebook 边界

### 17.1 CLI

- ./trade 继续是唯一稳定用户门面。
- Bash 只保留环境、setup/build/test 和无业务知识的转发。
- Python CommandSpec 成为 help、dispatch、completion 和 docs 的真相源。
- 用户命令表达意图，不暴露内部 provider/job 表。
- 所有命令支持稳定 exit code、JSON 输出和 dry-run（适用时）。
- query 命令保证无副作用；sync/repair/publish/promote 名字明确写操作。
- legacy alias 有 deprecation telemetry、兼容测试和下线门禁。

### 17.2 FastAPI

- app.py 只做 composition、lifespan、middleware 和 router registration。
- router 只做 transport validation/DTO mapping。
- application service 承担 use case 和 transaction。
- blocking Parquet/DuckDB/SQLite 工作离开 event loop。
- 长任务返回 202 + durable run id，支持 status/cancel。
- route schema、错误码、分页、ETag、range 和 no-build read 有契约测试。
- 生成 OpenAPI client 类型只在 API 稳定后启用。

### 17.3 Frontend

- 按 feature slice 组织，而不是继续增长 api.ts/i18n.tsx/pages.css。
- 每个 feature 拥有 API client、types、state、components、tests。
- shared 只存设计 token、通用控件、HTTP base 和无业务工具。
- 页面通过 capability/readiness 决定可见性，不用 build-time 假设。
- formal/candidate/observed、data quality、research status、unknown 和 blocker
  在 UI 中视觉分离。
- execution 页面即使未来存在，也必须始终显示 mode、account、kill switch、
  reconciliation 和 audit durability。

### 17.4 Notebook/SDK

- Notebook 和 Web 使用同一个 query facade/SnapshotSelector。
- SDK 返回 logical refs 和 typed objects，不返回隐式可写 DB handle。
- notebook 写入实验必须通过 import/commit workflow，不能直接切 current。
- 相同 snapshot id 在 Web、SDK、CLI 和 Jupyter 得到一致结果。

## 18. 可观测性、运维与安全

### 18.1 统一 RunContext

所有入口和下游传播：

- request_id、correlation_id；
- run_id、event_id、parent_event_id、job_id；
- plugin_id/version；
- asset/dataset/snapshot/release；
- model/policy version；
- config/schema/code revision；
- operating mode 和 actor。

### 18.2 健康状态分轴

- liveness：进程是否活着；
- readiness：依赖是否可提供服务；
- capacity：队列、worker、process 和 saturation；
- data_quality：freshness、coverage、revision、sequence gap；
- research_quality：candidate、validated、rejected、monitoring；
- execution_safety：kill switch、limits、broker、reconciliation、audit。

顶层 status 必须由这些轴汇总，不能内部 degraded 而外部固定 ok。

### 18.3 最低指标集

| 域 | 指标 |
| --- | --- |
| API | latency/status/concurrency/payload/event-loop lag |
| Event/Job | admitted/active/saturated/retry/duration/outcome/replay lag |
| DB | busy/lock/transaction/checkpoint/WAL/schema version |
| Provider | attempt/latency/quota/http class/rows/watermark/revision |
| Data | freshness/coverage/missing/duplicate/gap/checksum |
| Plugin | load/start/execute/stop/schema mismatch/CPU/RSS/timeout |
| Research | feature coverage/default/drift/calibration/gate state |
| Execution | reject/fill/cancel/slippage/limit utilization/kill-switch |

本地无 OTel/Prometheus collector 时，结构化日志、audit 和本地 metrics endpoint
仍须工作；外部 collector 是 adapter，不是系统可用性的前提。

### 18.4 安全

- secrets 分类和最小权限；
- provider/broker scopes；
- artifact license/retention；
- audit append-only、hash 和访问控制；
- live command 强确认和双重 enable；
- 依赖/SBOM/漏洞扫描；
- plugin manifest 签名或 allowlist；
- 日志禁止凭证、个人数据和完整 broker payload；
- Web 写操作鉴权、CSRF/Origin、rate limit；
- backup/restore 和灾难演练：backup boundary、加密、保留周期、校验、
  restore time、抽样恢复和 RPO/RTO receipt；
- L2/raw 数据单独设 retention/tiering 和成本上限，不能默认永久全量保留。

## 19. 测试、质量门禁与完成定义

### 19.1 测试矩阵

| 层级 | 必测内容 |
| --- | --- |
| Unit | 纯领域规则、状态机、时钟、单位、错误和边界值 |
| Architecture | import direction、cycle、private DB、CLI reverse import、裸线程 |
| Contract | repository、provider、plugin、API、CLI、event、native schema |
| Data quality | schema、单位、时区、coverage、duplicate、revision、finality |
| PIT/leakage | 未来注入、缺失时钟、迟到、修订、撤稿、universe PIT |
| Replay | 相同 input/code/config 产生相同 snapshot/output hash |
| Publication | candidate 不自动 current、CAS 冲突、hash 篡改、rollback |
| Feature | golden、property/metamorphic、warm-up/missing、Python/native parity |
| Model | purged walk-forward、embargo、calibration、drift、slice、ablation |
| Research governance | trial registry、sealed holdout、multiple-testing、负结果留痕 |
| Backtest | t/t+1、calendar、停牌、涨跌停、费用、slippage、partial fill |
| L2 | duplicate、out-of-order、gap、reset、checksum、book conservation |
| Risk | veto、limits、stale/unknown fail closed、kill switch |
| OMS | idempotency、乱序回报、partial fill、cancel race、reconcile |
| Fault | SIGTERM、kill -9、disk full、read-only FS、DB busy、坏 Parquet |
| Publication crash | PREPARED/COMMITTED/PROJECTED 每个 crash window、orphan、reconcile |
| Resource | nested pools、global thread/RSS/I/O budget、reserved safety capacity |
| Performance | p50/p95/p99、throughput、RSS、copy bytes、write amplification |
| Soak | 24h thread/FD/RSS/WAL/queue oldest age 不持续增长 |
| E2E | CLI/API/Web/SDK 对同一 snapshot 和 workflow 一致 |

### 19.2 Architecture fitness tests

早期即加入自动护栏：

- domain 禁止 import trade_py.cli、trade_web、sqlite3、provider SDK；
- application 只能依赖 domain/contracts/ports；
- adapter 不被 domain 反向 import；
- 新代码禁止访问 TradeDB._conn/_conn_lock；
- 新 use case 禁止调用 CLI main；
- Web route 禁止直接 Thread(..., daemon=True)；
- read/query package 禁止 provider network 和 write API；
- plugin 禁止直接 import broker/DB/current pointer authority；
- bounded context import cycle 为 0。

初期可以 warning + allowlist 记录现存债务；每阶段减少 allowlist，禁止增加。

### 19.3 每个 implementation unit 的完成定义

1. 独立 worktree 和 feature branch。
2. 非平凡变更有 OpenSpec proposal/design/spec/tasks。
3. Design Quality Brief 十项完整，reliability、performance、architecture、
   data-quality、observability、news/future 六角色 review 无 P0。
4. ./trade dev design-check <change> --strict 通过。
5. 行为变化有近邻 UT；合同变化有 contract/golden。
6. focused tests、compile/build/typecheck 通过。
7. ./trade dev check --show-plan 和 ./trade dev check 通过。
8. git diff --check 通过。
9. performance smoke 分类为 added/updated/existing/not-needed，并给证据。
10. data safety、compatibility、rollout、rollback 已验证。
11. 只 stage intentional files，完成一个逻辑单元立即 commit。
12. 3–5 commits push；最终实施 diff 再做六角色 review。
13. merge 回 master 使用 rebase + squash，保留一条干净逻辑提交。

## 20. 渐进迁移总策略

### 20.1 Strangler 规则

每个迁移切片遵循：

~~~text
冻结旧行为 + golden
 -> 定义新 contract/port
 -> 新 adapter 委托旧实现
 -> 迁一个 use case
 -> shadow/differential
 -> 切默认读或写
 -> 观察调用和错误
 -> 下线旧实现
~~~

### 20.2 一个切片只改变一类风险

避免同一阶段同时做：

- 目录搬迁 + schema migration；
- 数据语义变化 + 原生优化；
- provider 切换 + 模型晋级；
- EventBus 重构 + 外部 broker；
- OMS 状态机 + live 接入；
- API contract + 全前端重写。

### 20.3 兼容政策

- CLI/API/DB/Parquet/native 都要记录 old/new contract。
- 兼容 facade 有 owner、telemetry、deadline 条件，而不是无期限保留。
- 下线条件以调用量归零、consumer migration 和兼容测试为准，不只看日期。
- 数据迁移先 snapshot/backup、dry-run、小样本、双读、hash/row count、rollback。
- current pointer 只在 gate 和 CAS receipt 成功后切换。

## 21. 分阶段实施路线

下面按依赖顺序排列。工期是假设一名熟悉仓库的工程师专注实施的粗略量级，
用于拆分，不是交付承诺：

- S：3–5 个工作日；
- M：1–2 周；
- L：3–6 周；
- XL：6–12 周或更长。

Phase 是路线 program，不等于一个 OpenSpec 或一个 PR。每个编号工作包仍要
按“一类风险、一个可回滚切片”拆成独立 change；不能用本总规划或 Phase
名称直接跳过 OpenSpec。

### Phase 0 - 事实冻结、correctness P0 与基线

优先级：P0；规模：XL program，由多个 M/L change 组成；依赖：无。

目标：

- 建立唯一架构事实和 capability inventory；
- 先分级，再复现并处理第 3 节候选 P0；
- 建立 correctness、performance、capacity 和 recovery 基线；
- 不进行大目录重构。

工作包：

1. P0-A 事实与基线 change：
   - capability matrix：implemented / partial / scaffold / absent；
   - 术语、authoritative docs、supersession ADR；
   - 当前真实规模、10x、EventBus、API/SSE、Parquet、现有 C++ 基准；
   - C++/Java capability/consumer 事实修正。
2. P0-B Runtime remediation changes：
   - Web 裸线程；
   - scheduler owner/catch-up/signal；
   - 每项按独立可回滚行为切片。
3. P0-C Storage/concurrency remediation changes：
   - ingest commit/outbox；
   - Kline 损坏/manifest；
   - SQLite transaction/connection；
   - 每项独立 fault model。
4. P0-D Data/research correctness changes：
   - PIT、news time、event feature；
   - leakage、unknown、model promotion；
   - 每项先有 regression reproducer。

候选问题先进入矩阵：

| 字段 | 含义 |
| --- | --- |
| finding | C1...Cn |
| confirmation | unverified / reproduced / disproved |
| severity | P0/P1/P2 |
| affected_mode | research/advisory/paper/live |
| reproducer | test/probe/fixture |
| owner | bounded context |
| blocks_phase | 被阻断阶段 |
| disposition | fix/isolate/defer + reason |

产物：

- docs/architecture/current-state.md；
- docs/architecture/capabilities.md；
- docs/architecture/adr-index.md；
- correctness regression suites；
- benchmark receipts 和 recovery drill 报告。

退出门：

- 所有候选项都有 confirmation/severity/owner/blocks_phase；
- 冻结 inventory 中 confirmed P0 全部 fix 或 fail-closed isolate；
- 不对 inventory 之外的“所有已知问题”做不可证明承诺；
- SIGTERM/kill -9/坏 Parquet/DB busy 基础演练有结果；
- 基线可重复，perf smoke 固化；
- 现有 active OpenSpec 状态被纳入依赖图。

回滚：

- correctness 修复逐项回滚；基线/文档纯 additive。

### Phase 1 - 平台合同与依赖护栏

优先级：P0；规模：M；依赖：Phase 0。

目标：

- 建立不含业务偏好的最小共享内核；
- 让错误依赖在 CI 失败，而不是靠人记忆。

工作包：

1. P1.1 typed IDs、Clock、RunContext、Availability、Finality、typed error。
2. P1.2 SettingsSnapshot 和 config hash。
3. P1.3 Command/Query、Result/Evidence、deadline/cancellation 合同。
4. P1.4 architecture fitness tests 和 debt allowlist。
5. P1.5 composition root/RuntimeResources 的通用接口。
6. P1.6 deprecation/compatibility ledger。

退出门：

- 新 domain 不依赖 presentation/infrastructure；
- 新 use case 不自行创建资源；
- allowlist 只减不增；
- 零行为改变或有完整兼容 golden。

回滚：

- additive contracts 可移除；旧路径仍为默认。

### Phase 2 - DB、配置与存储所有权拆分 Program

优先级：P0；规模：XL program；依赖：Phase 1。

目标：

- 拆 TradeDB 的职责，不先拆物理库；
- query 绝对只读，migration/seed 显式。

工作包：

1. P2.1 独立 change：Connection/TransactionManager 和显式 SchemaMigrator。
2. P2.2 独立 changes：Settings/Instrument repositories。
3. P2.3 独立 changes：Job/Event/Runtime repositories。
4. P2.4 独立 changes：DataQuality/Catalog、Research/Model、Decision/Audit；
   每次只迁一个 consumer vertical slice。
5. P2.5 TradeDB 逐步改为 compatibility facade。
6. P2.6 按 consumer 清零外部 _conn/_conn_lock 使用。
7. P2.7 独立 change：MarketDataReader 与 DataRepairService。
8. P2.8 inventory PipelineDb/EventDatabase，决定 authority 或 adapter。
9. P2.9 read-only 打开模式和 resource close/leak tests。

退出门：

- schema 不变，除非独立 migration OpenSpec；
- old facade/new repository 对 golden DB 双跑一致；
- query 不创建目录、不 migration、不 seed、不触发 provider acquisition；
  只允许合同中声明的 read-only datastore；
- transaction/concurrency/fault tests 通过；
- private connection 使用为 0。

回滚：

- facade 可切回旧 implementation；不做不可逆数据迁移。

### Phase 3 - Application boundary、CLI、Web、Jobs 与 Event Runtime Program

优先级：P0/P1；规模：XL program；依赖：Phase 2 的对应 repository slice。

目标：

- application use case 成为资源和事务 owner；
- 所有入口变薄，运行时只有一个 owner。

工作包：

1. P3-A Web changes：逐域 router/DTO/service；long task 接入现有
   RuntimeCommandRunner adapter。
2. P3-B Jobs changes：按一个业务域拆 jobs，并把 JobDef 升级为 JobSpec。
3. P3-C Event changes：contracts/store、admission/dispatcher、
   replay/lifecycle 分开切片。
4. P3-D Runtime follow-up：topic/channel、command capacity、degraded status。
5. P3-E Scheduler change：owner lease、fire key、catch-up、signal drain。
6. P3-F CLI change：CommandSpec 真相源、Bash 变薄。
7. 每个 change 都保持旧 public import/command adapter。

退出门：

- app.py 只保留 composition/middleware/router；
- Web 裸 workflow thread 为 0；
- JobSpec 显式 input/output/idempotency/PIT/resource/retry；
- replay/admission/shutdown/CLI/API snapshots 全绿；
- status 正确传播 degraded/saturated/stopping。

回滚：

- router/job/bus public re-export 指向旧实现；逐域切回。

### Phase 4 - 公共 Evidence、Catalog、PIT 与 Publication Kernel Program

优先级：P0；规模：XL；依赖：Phase 2；可与 Phase 3 后半并行。

目标：

- 将 BTC 的成熟语义泛化，但不破坏 BTC 现有路径；
- 为所有研究和决策提供一个不可变、可重放输入内核。

工作包（至少拆成四组独立 OpenSpec）：

1. P4-A Vocabulary/Clocks：
   RawEnvelope、typed refs、frozen state mapping、多时钟和 bitemporal master。
2. P4-B Identity/PIT：
   Snapshot identity、knowledge mode、resolver policy、strict PIT。
3. P4-C Artifact Publication：
   immutable artifact/manifest、PREPARED/COMMITTED/PROJECTED、receipt、
   pointer projection、CAS、outbox、rollback/reconcile。
4. P4-D Catalog/Adapters：
   logical path、legacy resolver、Observatory reference adapter，以及
   warehouse/news/factor/model 各自的单一 vertical slice。

退出门：

- 同一 snapshot id 在 CLI/API/Web/SDK/Jupyter 一致；
- missing time strict fail closed；
- current/candidate 正交，receipt authoritative，pointer CAS 可重建；
- GET/query 无 build、provider acquisition 或业务状态写入；
- hash 篡改、CAS 冲突、crash recovery、rollback 测试通过；
- BTC 现有合同保持或有明确版本迁移。

回滚：

- legacy resolver 仍可读；新 pointer 切回旧 generation；artifact 不删除。

### Phase 5 - Plugin SDK V1

优先级：P1；规模：L；依赖：Phase 1、4。

目标：

- 建立类型化、可治理的扩展机制；
- 不开放任意第三方热加载；
- V1 不加载 live BrokerAdapter，也不把 core Risk Authority 插件化。

工作包：

1. P5.1 CapabilityDescriptor、manifest schema、version negotiation。
2. P5.2 PluginHost lifecycle、dependency resolution、health、metrics。
3. P5.3 scoped ports/permissions 和 resource class。
4. P5.4 conformance kit、golden fixture，以及按执行隔离模式区分的
   cooperative cancellation、hard timeout、fault/quarantine。
5. P5.5 legacy data/factor/job/C++ adapters。
6. P5.6 迁移 CMF proxy vertical slice。
7. P5.7 迁移一个 fund-flow/data provider。
8. P5.8 capability/status CLI 和 Web projection。

退出门：

- 插件不能直接访问 DB/broker/current pointer；
- incompatible schema/version fail fast；
- failure 局部隔离并呈现 degraded/unavailable；
- old/new result differential 通过；
- plugin load/execute/stop 无资源泄漏。

回滚：

- registry adapter 切回旧 factory；新 manifest 不改变旧数据。

### Phase 6 - Feature、Dataset 与 Research Kernel

优先级：P1；规模：L；依赖：Phase 4、5。

目标：

- 统一 FeatureSpec、DatasetBuilder、ExperimentRun 和 promotion。

工作包：

1. P6.1 FeatureSpec authority 和 legacy schema mapping。
2. P6.2 DatasetBuilder 只接受 SnapshotSelector。
3. P6.3 warm-up/missing/units/PIT/dependency graph。
4. P6.4 train/inference/backtest 共享 feature manifest。
5. P6.5 purged walk-forward、embargo、calibration、slice、ablation。
6. P6.6 immutable experiment/model promotion receipt。
7. P6.7 完成或重映射 build-forecast-research-v1。
8. P6.8 候选/验证/监控状态在 Observatory/CLI/Web 展示。

退出门：

- future perturbation 和 universe PIT tests 通过；
- unknown 不再被默认值掩盖；
- dataset/model 可完整 replay；
- 旧 32/57/C++ feature schema 有明确 authority/adapter；
- 模型无法直接越过 gate 替换 active。

回滚：

- 旧 feature builder 只读兼容；current model pointer 可回滚。

### Phase 7 - 新闻、情绪、On-chain 与外部事件

优先级：P1；规模：L；依赖：Phase 4、5；可与 Phase 6 并行。

raw capture、revision 和 enrichment contract 可与 Phase 6 并行；任何新闻
FeatureSpec、DatasetBuilder 或模型集成必须同时依赖 Phase 6 与 Phase 7 完成。

目标：

- 把新闻从覆盖式 enrichment 变成可回放证据；
- 为未来 on-chain/监管/宏观事件复用同一合同。

工作包：

1. P7.1 append-only Bronze raw capture 和 received/available 时钟。
2. P7.2 article revision/tombstone/correction/dedup。
3. P7.3 enrichment model/prompt/parser/taxonomy/entity resolver 版本。
4. P7.4 source observation、semantic inference、market hypothesis 分层。
5. P7.5 LLM output 标为 pseudo-label，独立 truth/evaluation set。
6. P7.6 许可、retention、source quality 与 provider health。
7. P7.7 On-chain 仅作为新 ProviderPlugin，不创建特殊旁路。

退出门：

- 不再用当前时间伪造发布时间；
- as-known/revised/retracted 可回放；
- prompt/model 更新不会覆盖历史输出；
- source identity/许可/质量对正式研究可见。

回滚：

- legacy Silver/Gold 保留只读；新 snapshot pointer 可切回。

### Phase 8 - Deterministic Replay 与 Native Kernel Program

优先级：P1；规模：L/XL program；依赖：Phase 6。

目标：

- 先冻结确定性 replay/backtest reference contract；
- 再只接入 profiler 证明的 1–2 个原生热点；
- 不抢先创建生产级 Portfolio/Risk/Execution authority。

工作包：

1. P8-A Deterministic Replay（独立 OpenSpec）：
   - canonical market feed、clock、StrategyProposal 和 simulation fill contract；
   - 日频 t/t+1、calendar 和市场规则 golden；
   - 只定义 Phase 11/12 未来必须兼容的 reference semantics；
   - 在 Phase 11/12 完成前，不宣称 backtest/paper/live 已共享完整风险/执行语义。
2. P8-B Native Kernel（profiling 后的独立 OpenSpec）：
   - 修正 _trade_core target 和真实 bindings/Arrow adapter；
   - 选择 feature matrix、book replay 或 backtest matching 等实测热点；
   - Python reference、C++ differential、copy/RSS/ABI benchmark；
   - C++ target 按依赖拆小，保留 aggregate compatibility target；
   - in-process fail-fast，需 crash recovery 的 kernel 改 worker process。

退出门：

- 端到端收益满足下沉门槛；
- golden/parity、ASAN/UBSAN（适用时）、GIL/lifetime tests 通过；
- native 不拥有 DB/network/thread lifecycle；
- feature flag/调用前退回 Python 不改变业务合同；
- production Portfolio/Risk/Execution authority 仍只由 Phase 11/12 建立。

回滚：

- feature flag/adapter 切回 Python；原生产物不是数据 authority。

### Phase 9 - Order Flow/L2 数据与订单簿 Program

优先级：P1/P2；规模：XL program；依赖：Phase 4、5；优化部分依赖 Phase 8B。

目标：

- 一个 venue、一个 asset class、少量 symbols 建立可信端到端微观结构能力；
- 先做客观数据和特征，不做 SMC 营销结论。

工作包：

1. P9-A Contracts/Capture：
   - provider、许可、retention/tiering/成本；
   - Trade/Quote/Book/Auction contracts；
   - append-only raw partition、sequence/gap/reset/checksum/reconnect。
2. P9-B Book Reconstruction：
   - deterministic state machine、checkpoint、full/incremental replay；
   - network jitter、duplicate/out-of-order、crash recovery。
3. P9-C Features/Optimization：
   - CVD、imbalance、spread、microprice、OFI；
   - microstructure backtest feed/BrokerSim；
   - 先 profile；Python 不达 SLO 才做 C++/Rust worker；
   - 24h soak 和 1x/10x burst。

P9-A 不被 C++ binding 阻塞；P9-C 原生优化才依赖 Phase 8B 的质量边界。

退出门：

- D0-D6 gate 有证据；
- 对提供连续 sequence/checksum 的来源，gap 100% 检出并 fail closed；
- full/incremental replay hash 一致；
- 不可读 partition 隔离，不覆盖；
- 性能达到经批准的真实 workload SLO；
- 输出仍为 research/candidate。

回滚：

- 停 provider/worker；不切正式 decision；immutable raw 保留审计。

### Phase 10 - SMC Research Lab

优先级：P2；规模：L；依赖：Phase 6；使用 L2 的 detector 另依赖 Phase 9。

目标：

- 把 SMC 从主观术语变成版本化、可证伪的研究插件。

工作包：

1. P10.1 逐个定义 swing/BOS/CHOCH/FVG/order block/liquidity sweep。
2. P10.2 区分 bar-only 与 microstructure-backed capability。
3. P10.3 detector evidence 和 invalidation contract。
4. P10.4 baseline、walk-forward、cost、regime、ablation、multiple testing。
5. P10.5 Observatory 可视化证据和失败切片。
6. P10.6 candidate/shadow promotion，不接 broker。

退出门：

- 任何图形结论都能从固定 snapshot 重现；
- 参数、确认时点和 invalidation 无未来信息；
- 与简单基线的效果和失败边界完整披露；
- 未通过研究 gate 的 detector 显示 rejected/experimental。

回滚：

- disable plugin；不影响 canonical data 和其他策略。

### Phase 11 - Decision、Portfolio 与 Risk

优先级：P1/P2；规模：XL；依赖：Phase 6、8A；可不依赖 L2/SMC。

目标：

- 从 heuristic recommendation 升级为证据驱动、no-action-first 的决策链；
- 建立与 execution 解耦的组合和风控。

工作包：

1. P11.1 DecisionRecord、supporting/opposing/unknown/blocker。
2. P11.2 strategy assessment 和 model/policy governance。
3. P11.3 position/cash/lot accounting 的纯模型和输入 snapshot contract；
   此阶段不是执行账本 authority。
4. P11.4 allocation/constraints/exposure。
5. P11.5 pre-trade RiskDecision 和不可绕过 veto。
6. P11.6 limits/stress/drawdown/liquidity。
7. P11.7 research/advisory 模式 UI/CLI。
8. P11.8 legacy recommendation adapter 和 truth label。

退出门：

- unknown/stale/quality failure 默认 no-action；
- risk property/fault tests 通过；
- 每份决策可追完整 evidence；每个 ApprovedOrderIntent 可追 RiskDecision receipt；
- 不存在直接 broker 调用。

回滚：

- 决策 UI/CLI 切回 legacy advisory；不改变 position/order truth。

### Phase 12 - Paper OMS/EMS 与 Reconciliation

优先级：P2；规模：XL；依赖：Phase 3/4 的 runtime/publication、Phase 8A
reference semantics、Phase 11。

目标：

- 在无真实资金前完成 durable order lifecycle，并建立唯一 paper
  order/fill/position/cash ledger authority。

工作包：

1. P12.1 order/event/ledger append-only authority 和 double-entry projection。
2. P12.2 idempotent client order id 和状态机。
3. P12.3 simulator/paper broker。
4. P12.4 fee/slippage/partial fill/cancel race。
5. P12.5 reconciliation 和 UNKNOWN_RECONCILING。
6. P12.6 kill switch、limits、audit durability。
7. P12.7 paper credentials/data root 隔离。
8. P12.8 长时间 paper/shadow soak。

退出门：

- 对本地进程崩溃，已 local-durable-commit 的 paper ack/fill 可恢复；
- 主机/磁盘级目标按第 14.7 节单独声明，不使用无条件 RPO 0；
- duplicate/out-of-order/restart/reconcile tests 通过；
- audit 不可写、market stale、broker unknown 时禁止新单；
- 24h/多日 paper run 无资源和账本漂移。

回滚：

- paper adapter 停止；ledger 保留；无真实 broker 副作用。

### Phase 13 - Shadow 与可选 Live Execution

优先级：P3；规模：独立安全项目；依赖：Phase 12 长期稳定。

开始前硬条件：

- paper/replay parity 已证明；
- 独立 execution security review；
- 双重 enable、default deny、最小权限凭证；
- broker order/fill/position/cash reconciliation；
- kill switch、stale/unknown policy；
- backup/restore/incident runbook；
- 人工演练和审计；
- 小账户/低限额 canary 方案；
- 监管、许可和数据协议确认。

顺序：

1. live market data shadow，无订单；
2. 生成 shadow orders，不提交；
3. broker sandbox；
4. 小账户 canary；
5. 按 receipt 扩大；
6. 任何安全轴 degraded 自动降到 no-trade/reconcile。

回滚：

- kill switch + disable adapter + cancel eligible orders + reconcile；
- 不删除 ledger/audit；不自动恢复 live。

### Phase 14 - Frontend 产品化与运维工作台

优先级：P1/P2；规模：L program；基础 shell 依赖 Phase 3/4，各 feature
按其后端能力单独声明依赖，可沿后续阶段并行。

目标：

- 页面与 bounded context 对齐；
- 同时呈现市场、数据质量、研究和执行安全，而非混成一个分数。

工作包：

1. P14.1 feature folder、domain API clients、shared design tokens（Phase 3）。
2. P14.2 Observatory 作为 data/research truth 模板（Phase 4/remediation）。
3. P14.3 Research workspace（Phase 6）。
4. P14.4 Data operations（Phase 3/4）。
5. P14.5 Decision（Phase 11）。
6. P14.6 Paper execution（Phase 12）。
7. P14.7 accessibility、responsive、error/empty/loading/degraded states。
8. P14.8 generated OpenAPI types（合同稳定后）。

退出门：

- api.ts/i18n/styles 不再是 catch-all；
- capability 决定 nav/readiness；
- candidate/current、PIT 和 unknown 语义无歧义；
- real-stack E2E，不只 mock。

回滚：

- feature flag 回旧页面；API contract 保持。

### Phase 15 - 按证据扩容、迁库或拆服务

优先级：P3；规模：按需；依赖：实际指标触发。

候选边界：

- Market Data；
- Research/Feature；
- Decision/Risk；
- Execution/Reconciliation；
- Control Plane/Web。

可能动作：

- SQLite → PostgreSQL；
- local EventBus → NATS/Redpanda/Kafka；
- native in-process → isolated worker/RPC；
- L2 worker 独立部署；
- object storage/remote catalog；
- 读模型/cache。

每个动作必须先给触发指标、成本模型、schema、数据迁移、双跑、故障域、
RPO/RTO 和回滚。未触发就继续模块化单体。

## 22. 阶段依赖与并行车道

~~~text
Phase 0
   |
   v
Phase 1 -------> Phase 3 ---------> Phase 14
   |                |
   v                |
Phase 2 ------------+
   |
   v
Phase 4 -------> Phase 5
   |                |
   +----> Phase 6 --+----> Phase 8A ----> Phase 11 ----> Phase 12 ----> Phase 13
   |          |                |
   |          +----> Phase 7   +----> Phase 8B (profile-triggered)
   |                           |
   +----> Phase 9A -> 9B -> 9C +----> Phase 10
   |
   +----> Observatory/Forecast/Workspace 现有计划对齐

Phase 14 各 feature 分别挂到 3/4/6/11/12 的稳定 API
Phase 15 仅由任意阶段的实测容量/隔离门槛触发
~~~

可并行：

- Phase 3 的 Web/CLI 与 Phase 4 的 data contracts，可在共同 contract 冻结后并行。
- Phase 6 研究与 Phase 7 新闻可并行。
- Phase 14 前端按已稳定 API 逐 feature 并行。
- Phase 9A/B L2 与 Phase 11 日频决策可并行，因为决策内核不能依赖特定频率。

不可并行或不可倒置：

- Plugin SDK 不能早于公共 contract/PIT。
- SMC microstructure 不能早于可信 L2 replay。
- Native 下沉不能早于 profiler、schema 和 Python reference。
- Paper OMS 不能早于 Risk/Decision。
- Live 不能早于 durable OMS、reconciliation 和长期 shadow。

## 23. 与当前 OpenSpec/专项计划的衔接

截至 2026-07-22 的快照：

该表来自当前 checkout 的 openspec list --json；任务数会变化，实施前必须
刷新。数据规模和性能事实也必须由带命令、data root、hardware 和时间的
benchmark receipt 冻结。

| Change | 状态 | 本计划处理 |
| --- | --- | --- |
| converge-runtime-boundaries | 28/28 | 作为 Runtime seed；补其已知 capacity/status/topic/async follow-up |
| add-design-quality-gates | 23/23 | 全部后续非平凡阶段继续使用 |
| add-cross-language-quality-gates | 27/27 | Phase 8/9 的原生与 Rust 接入直接复用 |
| complete-cli-lazy-loading | 15/15 | 保留；Phase 3 只统一 CommandSpec |
| simplify-data-workflow | 21/21 | 保留短命令；不重新暴露内部 job/provider |
| crypto-data-assurance-and-validation-v1 | 22/26 | 先完成 live rollout/rollback 演练；作为公共 Evidence kernel seed |
| btc-observatory-research-lab-v1 | 46/56 | implemented seed，但尚非 trusted complete；先完成 correctness remediation，不复制其 authority |
| btc-research-workspace | 3/16 | 在 Phase 14 feature boundary 下完成，避免并行重写同一区域 |
| build-forecast-research-v1 | 0/58 | 在 Phase 6 Feature/Dataset/Experiment 合同下重映射后实施 |

协调原则：

1. 先完成或明确暂停 active change，再在同一文件区域做结构迁移。
2. 已批准语义不因目录规划自动失效。
3. 若本计划要求改变 frozen contract，必须回到对应 OpenSpec 重新评审。
4. Observatory 是公共内核的参考实现，不应在抽象时降级其 fail-closed、
   immutable、candidate/current 和 replay 语义。
5. Kline 路径刚完成规范化，不在早期再次物理搬家。

## 24. 优先级 Backlog

### P0 - 现在到第一个稳定里程碑

- correctness 候选 P0 复现与清零；
- authoritative architecture/capability/ADR；
- baseline/perf/recovery；
- typed contracts、RunContext、SettingsSnapshot；
- dependency fitness；
- DB repository seam 和 query/command 分离；
- Web 裸线程、scheduler owner、ingest commit/outbox；
- 公共 Evidence/PIT kernel 的设计与第一个 slice。

### P1 - 可扩展研究与决策平台

- Web/CLI/jobs/bus 拆分；
- Plugin SDK；
- Feature/Dataset/Experiment；
- 新闻/外部事件；
- native kernel V1；
- Decision/Portfolio/Risk；
- frontend feature slices。

### P2 - 微观结构与 Paper 交易

- L2/Order Flow；
- SMC Research Lab；
- Paper OMS/EMS/Reconciliation；
- 长期 shadow。

### P3 - 有证据才做

- live broker；
- PostgreSQL；
- external broker；
- Rust/Go 独立服务；
- 多主机 HA；
- 第三方插件市场或 WASM sandbox。

## 25. 风险登记表

| 风险 | 概率/影响 | 早期信号 | 缓解 | 回滚 |
| --- | --- | --- | --- | --- |
| 目录搬迁变成大爆炸 | 高/高 | 单 PR 跨多个 bounded context | vertical slice、compat facade | 切回旧 facade |
| 抽象过早 | 中/高 | SPI 没有第二个真实 consumer | 先两个迁移切片再泛化 | 删除 additive abstraction |
| 数据语义在重构中漂移 | 高/极高 | golden/hash/PIT 改变 | freeze contracts、differential | old resolver/pointer |
| Unknown 被默认值吞掉 | 高/高 | fillna(0)、neutral fallback | typed availability、fitness test | fail closed |
| C++/Rust 维护成本大于收益 | 中/高 | E2E 增益不足、copy 多 | adoption threshold、Python ref | feature flag 回 Python |
| 微服务提前引入 | 中/高 | 无独立 SLO/owner 仍拆服务 | hard trigger checklist | 合回本地 adapter |
| 插件越权 | 中/极高 | 直接 DB/broker import | scoped ports、allowlist、process | quarantine/disable |
| L2 数据质量不足 | 高/高 | gap/reset/许可不清 | D0-D6 gates、单 venue slice | research-only/停采 |
| SMC 过拟合或语义营销 | 高/高 | 定义模糊、无基线/样本外 | versioned detector、研究门禁 | rejected/disable |
| 实盘状态不确定 | 中/极高 | ack/fill 对不上 | ledger/reconcile/freeze/kill | cancel/reconcile/no-trade |
| SQLite 并发到瓶颈 | 中/中高 | busy/WAL/checkpoint 阈值 | repository、metrics、Postgres gate | 降 writer/恢复备份 |
| 当前 active work 冲突 | 高/中 | 同文件并行改动 | finish/pause map、worktree | rebase/分阶段 |
| 文档再次失效 | 中/中 | 新设计无 supersession | ADR index、owner、closeout | 标历史，不静默覆盖 |

## 26. 明确拒绝的反模式

- 继续向 TradeDB、app.py、data.py、jobs/__init__.py、bus/__init__.py 塞业务。
- 把 utils/shared/platform 变成新的杂物间。
- 让 GET/query 自动补数、迁移、创建目录或切 pointer。
- 在 domain/application 内调用 CLI main。
- 通过 check_same_thread=False 假设 SQLite 自动线程安全。
- 事件先发布、artifact 后提交。
- 捕获 integrity/schema 错误后返回空结果或 HTTP 200。
- 把 CMF、大单聚合、K 线形态叫真实 Order Flow/SMC。
- 把 latest restated 标志当成真实修订重建。
- 用当前分类、最新修订或全历史统计做历史训练。
- 用 fillna(0)、neutral、default trust 替代 unknown。
- 让插件直接写 DB、切 current 或调用 broker。
- Python/C++ 各自维护不同策略语义。
- 为“高性能”在无 profile 时做重写。
- 为“先进架构”在无独立 SLO 时上微服务/Kafka/Kubernetes。
- 在账本、risk、reconciliation 和 kill switch 前连接 live。

## 27. 每阶段 Design Quality Brief 模板

每个后续 OpenSpec 的 design.md 必须具体回答：

### Impact Applicability

- DB/schema、storage/data、trading semantics、CLI/API、runtime/concurrency、
  native/engine、external ingestion、execution safety 各自是 applicable 还是 N/A？
- 每个 N/A 给证据和理由，不能省略。

### Requirements and Acceptance

- 用户可观察行为是什么？
- 明确非目标是什么？
- 可执行 acceptance commands、数据集和阈值是什么？

### Ownership and Boundaries

- 哪个 bounded context 拥有状态和 contract？
- 谁创建/关闭 DB、thread、process、provider、broker？
- 禁止依赖是什么？

### Data and State Invariants

- identity、time、unit、revision、PIT、candidate/current 有何不变量？
- crash 前后如何恢复？
- unknown 如何传播？

### Contracts and Compatibility

- CLI/API/DB/Parquet/event/native/plugin 的 old/new contract？
- consumer 如何迁移？
- deprecation telemetry 和下线门禁？

### Failure and Recovery

- timeout、retry、backpressure、quarantine、reconcile？
- disk full、坏 artifact、DB busy、provider/broker uncertain？
- RPO/RTO？

### Performance and Capacity

- 当前基线、代表 workload、10x 情形？
- p50/p95/p99、RSS、copy、write amplification？
- 性能回归是否有明确批准？

### Observability and Operability

- logs/metrics/traces/audit/health/capacity？
- operator 如何诊断、停机、重放、回滚？

### Validation

- unit/contract/PIT/replay/differential/fault/perf/e2e？
- data safety 和真实数据只读 probe？

### Alternatives and Tradeoffs

- 至少两个可行方案；
- 为什么选择当前方案；
- 为什么现在不微服务/不换语言/不迁库？

### Rollout and Rollback

- shadow/dual-read/dual-write/canary/pointer CAS？
- 回滚是否需要反向数据迁移？
- stop conditions 和 acceptance owner？

## 28. 建议的首批独立 OpenSpec

用户后续开始实施时，不创建覆盖 Phase 0 或多个风险域的巨型 change。首个
change 只建立 inventory；后续按 confirmed blocker 分开评审，顺序由矩阵决定。

### 28.1 inventory-architecture-and-confirm-correctness-risks-v1

范围：

- 复现/分级第 3 节候选 P0；
- authoritative architecture/capability/ADR；
- workload/perf/recovery baseline；
- 输出 confirmed/severity/mode/owner/blocks-phase 矩阵。

不包含：

- 生产行为修复；
- 目录大搬迁；
- plugin framework；
- native 重写。

### 28.2 remediate-runtime-ownership-v1

范围：

- 已确认的 Web 裸任务、scheduler owner/lease/shutdown；
- 共享 composition factory 和每进程/data-root owner；
- 复用 RuntimeCommandRunner，不新增第二套 command owner。

不包含：

- PIT/news/model 修复；
- storage commit/schema 重构。

### 28.3 remediate-storage-commit-and-concurrency-v1

范围：

- 已确认的 artifact/manifest 提交顺序和 crash recovery；
- SQLite connection/transaction/checkpoint owner；
- Kline 损坏隔离和 writer fencing。

不包含：

- 全量 repository 抽取；
- PIT/news/model 修复。

### 28.4 remediate-temporal-data-correctness-v1

范围：

- 已确认的 PIT fail-open、新闻时间伪造、feature leakage、unknown 语义；
- 每项有独立 reproducer、影响模式和 rollback；
- 如果影响面仍跨多个 owner，继续拆成更小 changes。

### 28.5 establish-platform-contracts-and-dependency-fitness-v1

范围：

- typed IDs/Clock/RunContext/Errors/SettingsSnapshot；
- dependency fitness tests；
- resource ownership/composition contract；
- legacy debt allowlist。

上述 28.2–28.4 只在 inventory 确认对应 blocker 后创建。Repository program、
Evidence/PIT program 和 Plugin SDK 都在这些稳定后分别提案。

## 29. 总体退出标准

当本总规划的核心阶段完成时，应能回答并用系统证据证明：

1. 任意一个结果来自什么数据、什么时点、什么版本和什么代码？
2. 该结果是 observation、candidate、validated 还是 formal？
3. 缺失、陈旧、修订和 unknown 是否被正确呈现？
4. 新增一个 provider/feature/strategy/risk plugin 要改哪些稳定接口？
5. 插件失败、超时、饱和或版本不兼容时怎样隔离？
6. Python/C++/Rust 的边界由什么 benchmark 决定？
7. 同一策略在 backtest、paper 和未来 live 是否共享语义？
8. order/fill/position/cash 的权威账本在哪里？
9. broker 状态不确定时为什么不会继续下单？
10. 任意阶段如何回滚，是否保留审计和旧读路径？
11. degraded 为什么不会显示成 ok？
12. 当前架构、历史文档和 active OpenSpec 哪个是 authority？

如果这些问题仍依赖“熟悉代码的人脑补”，则架构迁移尚未完成。

## 30. 最后建议

最合理的执行顺序不是“先把目录整理漂亮”，而是：

1. 先冻结真实能力与语义，处置 inventory 中 confirmed correctness P0；
2. 再建立依赖护栏和资源所有权；
3. 再把 BTC 已验证的 evidence/PIT/publish 模式推广为公共内核；
4. 再用两个真实 vertical slice 证明插件体系；
5. 再统一研究、特征、决策和回测；
6. 有可靠数据后做 Order Flow，有可证伪定义后做 SMC；
7. 有 profile 后下沉 C++/Rust；
8. 有 durable risk/OMS/reconciliation 后做 paper；
9. 只有长期 shadow 和安全评审通过后，才单独讨论 live。

项目现在不是“能力太少”，而是“能力的边界、语义和晋级路径还不统一”。
把这些统一后，系统既能保持当前单机、本地、易打理的优点，也能在确有
需求时替换语言、迁移数据库、隔离进程或拆服务，而不必再次推倒重来。
