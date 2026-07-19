# 26 Plan - BTC Observatory and Research Lab V1

日期：2026-07-19

状态：产品与架构方向已对齐，待 OpenSpec、共识评审和实施

建议 OpenSpec change：btc-observatory-research-lab-v1

## 1. 结论先行

本计划不再把目标定义为“给 BTC parquet 加一张 K 线图”，而是建设一个证据优先的
BTC Observatory and Research Lab，使用户可以持续回答：

1. 市场发生了什么；
2. 系统最新采集到了什么；
3. 最新观测、质量评估候选和正式研究基线之间有什么差异；
4. 某个异常来自市场本身、数据源差异、修订还是发布流程；
5. 当前数据适合人工观察、探索研究还是正式验证；
6. 任意历史时点的指标和研究结论能否按当时信息完整复现。

目标产品不是纯展示大屏，也不是交易终端。它是一个能解释自身可信边界、支持
逐日观察、证据钻取、point-in-time 研究和可复现实验的本地研究工作台。

最终产品主线：

    Observe -> Investigate -> Research
       |            |             |
       +------ Data Trust --------+
                    |
               Runs / Lineage

Web 是长期、稳定、只读的正式观测入口；Jupyter 是开放研究与方法开发入口；两者
必须消费同一套快照解析和研究内核，不能各自直接拼接 parquet 路径。

## 2. 文档关系与范围边界

本计划的上游与相邻计划：

- docs/22_plan_analysis_first_research_system.md
  定义项目从 recommendation-first 转向 analysis-first。
- docs/23_plan_crypto_research_data_quality_and_signal_validation.md
  定义原始 BTC provider 方案、不可变 run、D0-D5、H1 和研究验证合同；provider/path
  已有后续覆盖，以下文 supersession 表为准。
- docs/24_plan_data_operations_workflow.md
  定义通用数据运维和观测入口。
- docs/25_plan_forecast_research_v1.md
  位于非阻塞并行分支 wt/forecast-research-plan-20260717 的 b15625b，聚焦 A 股
  point-in-time 预测研究；BTC 保持独立研究线。本计划不依赖该分支合入。

本计划负责：

- BTC 的正式产品信息架构；
- 最新观测、候选、正式基线和历史已知视图；
- Web 观测、日期证据钻取、质量解释、run diff 和研究结果浏览；
- Web/Jupyter 共用的 snapshot resolver 与 research kernel 边界；
- 对应 API、状态、不变量、测试、迁移和验收。

本计划不重新发明 provider 抓取、D0-D5 算法或 H1 统计方法。现有 assurance 能力
是基础，但其“单一 current 代表所有真相”的读侧模型需要重构。

docs/23 中的 C6 “read-only Web drill-down”由本计划替代并细化。docs/23 与其 active
OpenSpec 的部分 provider/path 叙述已经被后续实现覆盖，不能整体视为现行事实。

### 2.1 事实优先级与已失效条款

M0 必须把旧规范冲突写入新 OpenSpec 的 supersession 记录，不能让两套 provider
合同同时保持 active。当前基线如下：

| 主题 | V1 现行事实 | docs/23 处理方式 |
| --- | --- | --- |
| 资产身份 | asset_id=crypto.BTC，display_symbol=BTC | 保留 BTC 研究范围 |
| Primary | OKX，instrument=BTC-USDT，quote=USDT，interval=1Dutc | 保留 primary 不可被 shadow fallback 的原则 |
| Shadow | Binance，instrument=BTCUSDT，quote=USDT，interval=1d | CoinGecko/BTC-USD 叙述明确废止 |
| owner path | trade_py/data/market/crypto | market/cross_asset 仅兼容 shim，不是新实现 owner |
| 凭证/接口 | 以当前 provider contract version 和 manifest 为准 | CoinGecko credential/tier 要求不再作为 V1 blocker |
| 安全合同 | D0-D5、不可变 run、hash、锁、CAS、原子发布/回滚 | 继续有效，除非独立 OpenSpec 显式修改 |
| H1 | 非方向性 RV20 -> future RV7，沿用现有 identity 与结果读取 | 方法、门禁和生命周期继续有效 |

事实判定顺序为：不可变 run manifest/receipt 中记录的 contract version 与 artifact
hash，高于当前可执行 provider registry；当前实现及已合入的后续 OpenSpec，高于旧
计划中的 provider 名称和目录示例。Catalog 不得根据类名、deprecated alias、文件名
大小写或旧 provider label 猜测合同。历史 CoinGecko schema 如真实存在，只能通过
显式 versioned read adapter 读取，不能改写成 Binance 证据。

### 2.2 旧计划未完成项如何影响本计划

- 旧 CoinGecko live-pilot/credential 检查按原文已失效，M0 负责关闭或改写为 Binance
  等价合同；它不阻塞 M1-M4 的只读观测实现。
- 当前 provider contract 下的 D1 acquisition stability 仍可阻塞新的自动 Formal
  发布，但不阻塞 Latest Observed、Candidate、Trust 和历史 Formal 展示。
- D5/H1 的样本、成熟度和统计门禁只阻塞 strict research 或对应研究状态，不阻塞
  市场观测。
- pointer/hash/manifest/lock 完整性是 M1 及以后所有读侧的 blocker；不能以 UI 警告
  代替 fail closed。

## 3. 当前基线与真实问题

以下是 2026-07-19 的本地只读观察快照，会随运行变化，不得硬编码到产品逻辑：

| 项目 | 正式 Current | 最新 Evaluated Candidate |
| --- | --- | --- |
| run id | f2fd765097dcf21f16074fb3 | cdbbb5c608ba22b1c4aa06b0 |
| watermark | 2026-07-11 | 2026-07-18 |
| canonical rows | 730 | 725 |
| 发布状态 | Published | Unpublished |
| D0 / D2 / D3 / D4 | 历史发布证据存在 | pass / pass / pass / pass |
| D1 | 当前重评不足 | 3 / 29 个真实成功采集日 |
| 候选最终历史覆盖 | - | 99.315%，含 5 个隔离日期 |

这个状态暴露了现有模型的关键缺陷：

1. 正式数据与最新观测相差七个完整 UTC 日，但普通读侧只能看到旧 current。
2. Candidate 是生命周期位置，不等于质量差；Current 是发布位置，不等于仍新鲜。
3. 单一 data_readiness 无法同时表达采集、单次质量、发布和研究资格。
4. 当前 Web 根据 registry 中的 BTC 拼接大写 BTC.parquet，而实际 canonical 文件
   为小写 btc.parquet；在 Linux 上会表现为 missing 或空图。
5. Web 直接读 flat parquet，绕过 current pointer、artifact hash 和共享锁。
6. Data 页只有 sparkline 和表格，无法解释 source basis、quarantine、revision、
   candidate diff 和发布阻塞。
7. Research 页只是通用 ADS 表浏览器，不能说明研究假设、样本成熟度、walk-forward
   fold、效应区间和 point-in-time 证据。
8. 旧 run 在发布时通过与它是否兼容当前代码/策略是两个问题，不能事后压成一个
   invalid 状态。

## 4. 产品目标与非目标

### 4.1 产品目标

V1 必须让用户完成五个任务。

#### J1 - 每日 30 秒巡检

用户打开页面后，能立即知道：

- 最新完整 UTC 日；
- 最新观测水位；
- 正式研究基线水位；
- 二者相差多少日期、行和修订；
- 当前最重要的质量问题；
- 数据分别适合哪些用途。

#### J2 - 调查一个异常日期

从任意价格、收益、波动或质量异常，能够钻取到：

- primary 与 shadow 的原始/规范化证据；
- available_at 与 fetched_at；
- basis、revision、quarantine 和 gate finding；
- 包含该日期的 run 和 artifact hash；
- 该问题影响哪些用途和研究结果。

#### J3 - 解释为什么未发布

用户无需阅读 manifest JSON，即可沿着：

    Current/Candidate 差距
      -> 未发布主因
      -> 质量或 acquisition 日历
      -> provider attempt
      -> 原始证据

完成判断。

#### J4 - 复现历史视图

给定 knowledge time T，系统能够恢复：

- 当时系统真正捕获的数据版本；
- 当时可计算的特征；
- 当时已成熟或仍 pending 的 outcome；
- 当时可见的研究状态；
- 对应 run、hash、代码和配置版本。

#### J5 - 浏览和复现实验

用户可以查看一个预注册研究假设的样本、fold、效应、置信区间、placebo、
多重检验和生命周期，并能在 Jupyter 中固定相同 snapshot 重跑。

### 4.2 非目标

V1 明确不做：

- 自动交易、下单、仓位调整或强制买卖建议；
- 分钟级、逐笔或盘口实时监控；
- 从日线成交量推断可成交深度、滑点或交易所整体流动性；
- RSI/MACD/KDJ 指标墙；
- 新闻情绪总分或无证据的因果叙事；
- 用一个 trust score 掩盖阻断项；
- 在浏览器中临时计算正式研究指标；
- 直接把 Notebook 结论提升为正式产品结论；
- 在 BTC 语义尚未稳定前建设空洞的全资产通用平台；
- 第一轮删除 Today、Candidates、旧 Data、旧 Research 或 Ops。

## 5. 核心术语与状态合同

### 5.1 Current 与 Candidate

Current 和 Candidate 是生命周期位置，不是质量等级：

- Published Current：当前正式消费的不可变 release。
- Latest Staged：最新完成 staging 的 run，无论 assurance 是否完成或通过。
- Evaluated Candidate：最新完成 assurance 且 evaluation receipt 身份可验证的 staged run；
  它可以是 ready、degraded、insufficient_data 或 invalid。
- Candidate 可以质量良好但因长期证据不足而未发布。
- Current 可以保持正式身份但已经 stale，或者与当前代码合同不兼容。

产品文案默认使用“Candidate”指 Evaluated Candidate；任何需要 Latest Staged 或
“最近一次 ready candidate”的视图必须写全名，禁止都叫 latest candidate。

### 5.2 读侧正交状态轴

禁止再把所有状态压成一个 readiness。

| 状态轴 | owner 与建议状态 | 回答的问题 |
| --- | --- | --- |
| acquisition_state | CaptureAttempt/ObservationRun：not_attempted / running / succeeded / partial / empty / failed / abandoned / unknown | 数据源本次是否成功，是否零行或中断 |
| quality_state | ObservationRun：not_evaluated / assured / degraded / insufficient / invalid / unknown | 单次数据内容是否可解释地使用 |
| lifecycle_state | ObservationRun/Release：staged / published / superseded / rolled_back / unknown | run 处于什么发布位置 |
| research_state | Hypothesis/CryptoResearchRun：exploratory / eligible / candidate / monitoring / validated / rejected / blocked / unknown | 能支持哪一级研究结论 |

另有两个独立维度：

- freshness_state：fresh / stale / unknown；
- compatibility_state：compatible / contract_stale / replay_mismatch / unknown。

发布时认证状态是历史事实，不得被当前代码重评覆盖。当前重评结果作为
compatibility_state 单独展示。

这些轴、freshness、compatibility 和 purpose fitness 只是版本化读侧投影，不能替代
现行发布门禁、反向修改历史 manifest，或成为第二个写侧状态机。直到独立 OpenSpec
改变发布协议前，manifest 的 data_readiness=ready、D0-D4 与现行 publish/CAS 检查
仍是唯一 publish authority；Observatory 没有放宽发布条件的权限。

现有状态映射必须保留原值和 mapping_policy_version：

| manifest/研究事实 | 读侧投影 | 限制 |
| --- | --- | --- |
| assurance 尚未运行 | quality_state=not_evaluated | 不得推断 ready |
| data_readiness=ready | quality_state=assured | 仍需 release receipt 才是 Formal |
| data_readiness=degraded | quality_state=degraded | 可观察，不自动可发布 |
| data_readiness=insufficient_data | quality_state=insufficient | 不等于失败或零样本 |
| data_readiness=invalid | quality_state=invalid | 保留证据，默认不可作为 canonical layer |
| manifest 缺失/版本未知 | quality_state=unknown | fail closed，不按今天规则补写历史 |
| H1 现有 candidate/monitoring/validated/rejected | 同名 research_state | 通过 adapter 保留原 identity |

quarantined 是 per-date/per-finding 事实，不是一个互斥的 run quality_state。一个
degraded run 可以同时包含 assured、quarantined、missing 等不同日期。

### 5.3 用途适配

后端根据明确策略生成用途适配，不由前端猜测。

| 用途 | 初始要求 |
| --- | --- |
| manual_observation | 至少有规范化 final bar，所有警告持续可见 |
| exploratory_research | 固定不可变 run，明确 quarantine 和 provisional 状态 |
| formal_system_consumption | 仅正式 Published Current / Formal Baseline |
| strict_research | 固定 formal snapshot 且满足 point-in-time、样本与研究门禁 |
| automated_decision | 独立授权；不因数据存在或研究 validated 自动开启 |

响应必须包含 allowed、status、reason_codes 和 evidence_refs，不能只返回布尔值。
purpose fitness 从上述事实单向派生；它不能写回 data_readiness、release 或
research lifecycle。

## 6. 四时钟与 Point-in-Time 合同

每一条可研究事实至少区分：

1. event_time / bar_open_at / bar_close_at：
   行情本身发生和完成的时间；
2. available_at：
   理论上市场参与者最早可以知道的时间；
3. first_seen_at / fetched_at：
   本系统实际首次捕获它的时间；
4. certified_at / published_at：
   该数据被评估或正式采用的时间。

修订另需：

- revision_recorded_at；
- valid_from_run；
- valid_to_run 或 superseded_by。

历史回填数据可以用于带 available_at 合同的市场研究，但如果本系统在历史时点并未
真实捕获，必须标为 backfilled / PIT-unproven，不能声称重建了“当时系统所知”。

knowledge_mode 必须显式区分：

- market_available：按 available_at 判断市场理论上何时可知；允许通过审计合格的
  历史回填参与对应研究，但必须显示 backfilled provenance；
- installation_observed：按 first_seen_at/fetched_at 判断本机当时真正捕获了什么；
  用于事故复盘、系统行为回放和严格的“当时本机所知”叙述。

两种模式不得互相冒充。调用方不传时，Observe 最新视图默认
installation_observed/latest；历史系统复盘默认 installation_observed；研究必须在
hypothesis contract 中固定一种模式，不能由 UI 临时切换后沿用旧结果。

M0 必须先生成 evidence coverage report，按 asset/provider/contract/data family 记录：

- earliest_proven_knowledge_time；
- proven / partial / unproven 时间区间；
- first_seen、publication ledger 和 revision ledger 的覆盖率；
- 缺口 reason_codes 与可支持的 knowledge_mode。

legacy 数据缺 first_seen_at、不可变 artifact 或 publication/revision 证据时，
installation_observed 查询返回 PIT_NOT_PROVEN；禁止使用文件 mtime、今天的 manifest
或推测时间补齐。显式 unavailable 是合格结果，不应伪造一条完整历史曲线。

As-of 选择器必须控制整个 Snapshot Context：

- 数据版本；
- 价格和成交量；
- 特征和阈值；
- 质量 finding；
- 事件与上下文；
- 研究结果及 outcome 成熟状态。

只裁剪图表右侧不是 point-in-time。

Snapshot 身份和参数优先级必须确定：

1. snapshot_id 固定全部身份参数；与 run/release/channel/knowledge 参数冲突时返回
   INVALID_SNAPSHOT_SELECTOR；
2. exact run_id 或 release_id 次之，仍受 knowledge_as_of 可见性校验；
3. channel + knowledge_as_of + knowledge_mode + revision_policy 用于语义解析；
4. latest 在请求开始时冻结为当前 Catalog generation 内 asset-scoped 的
   relevant_fact_sequence/effective_knowledge_cut 和具体 run/release ids，响应不得继续
   保留移动 alias。requested_at/rendered_at 只是观测元数据，不作为 knowledge cut。

snapshot_id 是以下内容规范化序列化后的 SHA-256：asset contract id/version、resolved
run/release ids、按稳定顺序排列的 artifact SHA-256、effective knowledge cut、
knowledge_mode、revision_policy、quarantine/inclusion policy 和 resolver policy version。
显式 T 原样进入 effective knowledge cut；latest 使用参与该 asset snapshot 的最新事实
时间/单调序号，不能使用请求时间。requested_at、rendered_at、页面范围、图表指标和
排序不进入 snapshot_id。view_fingerprint 另由 snapshot_id、参与该 view 的运维/质量
事实 fingerprint、date range、metric versions、lens、分页/排序和 serialization
version 生成。没有相关事实或查询参数变化时，重复 latest 请求必须得到相同
snapshot_id、view_fingerprint 和 ETag；其他资产的 Catalog 更新不得使 BTC cache 抖动。

## 7. 选择器、语义引用与比较投影

Known at T 不是 channel，Latest Restated 也不是 channel。解析合同由三个正交维度
组成：

    lifecycle channel: observed | evaluated_candidate | formal | exact run/release
    knowledge cut: latest | knowledge_as_of=T
    revision policy: as_known | latest_restated

Latest Attempt 和 Latest Staged 是运维引用；composite 是比较投影。它们都不是可供
研究绑定的数据 snapshot。

### 7.1 Latest Attempt 运维引用

最近一次 provider acquisition attempt，无论 running、成功、partial、empty、失败或
进程崩溃。排序为 requested_at、started_at、attempt_id 的确定性降序。

仅靠 run manifest 无法覆盖 stage 前失败和进程崩溃。因此 V1 若承诺 Latest Attempt，
采集写侧必须 additive 写入最小 attempt receipt：先原子记录 started，再原子结束为
succeeded/partial/failed/abandoned；超时的 running 由显式 Operations reconcile 标为
abandoned。receipt 只追加，不由 Web/GET/SDK 创建或修复。

Latest Attempt 用于错误、重试、延迟、空响应和 acquisition 日历，不得用于画
canonical 市场图。若 M0 不接受 attempt receipt 这一写侧扩展，V1 必须将产品文案降级
为 Latest Completed Staged Run，不得声称拥有完整 attempt history；stage 前
running/abandoned/empty 的日历格显示 unsupported/unknown，不从缺失 manifest 推断。
WP1 中 attempt crash/reconcile 测试和对应 UI/E2E 验收随该能力一起移出 V1，并在
OpenSpec 记录 deferred task，不能保留一个永远无法通过的无条件验收项。

### 7.2 Latest Staged 运维引用

最新成功写完 immutable manifest 的 ObservationRun，无论 assurance 是否运行或通过。
资格是 manifest 可解析、run identity 唯一、staging receipt 完整；artifact 失败也保留
为该引用的事实。排序为 staged_at、manifest created_at、run_id 降序。

Latest Staged 用于暴露最新故障，不能静默回退到较旧良好 run，也不能直接进入主图。

### 7.3 Latest Observed channel

Latest Observed 是在 knowledge cut 内市场 watermark 最靠后的可观察 run。资格必须
同时满足：

- primary canonical artifact 存在且 hash/schema/asset/quote/interval/timezone 可验证；
- 至少一根完成 finality 的 bar；
- 没有 D0 identity/integrity blocker；
- overall acquisition 可以是 succeeded 或 primary 成功、shadow 失败的 partial；
- D1-D4 warning、quarantine 或 data_readiness=degraded 不排除人工观察，但持续可见。

排序键固定为 canonical market_watermark、effective_as_of、capture completed_at、run_id
降序；不能只按 manifest created_at，否则旧 as-of 补跑会抢占最新市场观测。

若最新 attempt/staged run 失败、为空或不满足资格，Latest Observed 保持在上一条合格
观测，同时返回 observation_lag、latest_attempt_id、latest_staged_id 和明确 reason_codes；
这是一条显式、可解释的保持规则，不是静默 fallback。没有任何合格 run 时 channel
返回 CHANNEL_UNAVAILABLE。

### 7.4 Evaluated Candidate channel

Evaluated Candidate 是 assurance_completed_at 最新、evaluation receipt/manifest identity
可验证的 staged run；它可以是 ready、degraded、insufficient_data 或 invalid，artifact
integrity 也可以是评估出的 blocker，并保留全部 gate、
quarantine、revision 和 Formal diff。排序为 assurance_completed_at、staged_at、run_id
降序，不以 watermark 替代“最新一次评估”。

它不得因最新评估结果差而静默回退到较旧 ready run。任意
quality_state=invalid，或 finding/purpose fitness 明确 blocks manual_observation/rendering
时，context 仍返回该 Candidate 及错误证据，但 candidate series 不进入任何 composite
layer，并返回 QUALITY_BLOCKED/CHANNEL_UNAVAILABLE。只有专门的诊断原始证据视图可以
展示无效行，且不得称为 canonical series。degraded/insufficient 只有在
manual_observation 明确 allowed 且 D0/integrity/rendering 无 blocker 时才可带持续警告
进入 layer。若产品未来需要“最近一次 ready 的未发布 run”，必须增加名字明确的
latest_ready_candidate 引用，并同时显示其年龄；V1 不用它替代 Evaluated Candidate。

若 Catalog 已记录一个更新的 assurance completion event，但其 receipt/manifest 本身
损坏到无法建立 identity，Evaluated Candidate 返回 MANIFEST_INVALID/CHANNEL_UNAVAILABLE，
不越过该事件选择旧 run；Latest Staged 与事件证据仍在 context 中可见。

### 7.5 Formal Baseline channel

Formal Baseline 是在 knowledge cut 内由 publication/rollback ledger 解析出的 active
不可变 Release，而不是“最近一个 ready run”。latest 时现有 btc_current.json 只作为
加速 pointer，必须和 release receipt、manifest、artifact hash、CAS 结果一致。

Formal 用于正式系统消费、默认严格研究、研究 lineage、回滚和审计。当前代码重评为
stale/degraded/replay mismatch 只改变 freshness/compatibility，不抹掉其历史发布身份。

### 7.6 Knowledge cut 与 revision policy

knowledge_as_of 对 observed、evaluated_candidate、formal 和 exact run/release 都生效：

- as_known：只使用在 T 前满足选定 knowledge_mode 的版本、finding、release 和研究
  结果；历史查询默认此策略；
- latest_restated：用今天已知的最新修订重述选定市场区间，仅用于修订诊断和最新
  数据形态分析，页面持续显示 RESTATED_NOT_PIT；不得作为历史系统回放或正式
  walk-forward 输入。

### 7.7 Legacy timestamp adapter

现存 manifest 没有 staged_at、assurance_completed_at、capture_completed_at，只有
created_at、acquisition_evidence.as_of 和行级 fetched_at。M1 必须使用显式
schema-versioned adapter，不能假设新字段已经存在：

| 目标字段/排序字段 | 新 schema | legacy 映射 | 证据限制 |
| --- | --- | --- | --- |
| assurance_completed_at | evaluation receipt 精确时间 | manifest.created_at | 标记 legacy_created_at_proxy |
| effective_as_of | run receipt 精确时间 | acquisition_evidence.as_of | 保留原 timezone/precision |
| staged_at | staging receipt 精确时间 | null，排序时才 coalesce created_at | 不能声称是精确 stage time |
| capture_completed_at | attempt receipt 精确时间 | null，排序时才 coalesce created_at | 行级 fetched_at 不冒充 run completion |
| first_proven_present_at | immutable receipt 时间 | manifest.created_at | 只证明不晚于该时间已登记，不证明更早可见 |

Legacy selector 的 null ordering 固定为：先使用各自业务主键；缺少精确 tie-break time 时
使用 manifest.created_at，再用 run_id。响应持续返回 time_provenance、time_precision 和
LEGACY_TIME_UNPROVEN；禁止读取 filesystem mtime。该 adapter 可保证 latest 页面排序
确定，但不能自动把精确 installation_observed PIT 变成 proven：T 早于
first_proven_present_at 或落在不确定区间时，按 evidence coverage 返回 partial 或
PIT_NOT_PROVEN。只有新 receipts 才记录精确阶段时间。

### 7.8 Composite 比较投影

Composite 不是 Snapshot，也不能成为 ResearchRun 输入。API 必须分别返回 resolved
formal、evaluated_candidate 和 latest_observed layers，每层保留自己的 snapshot_id、
OHLCV、contract 和 hash；重叠日期不得按优先级覆盖、平均或合并成一条“真值”。

默认视觉语义：

- Formal 为实线基线；
- Candidate 重叠部分显示 revision/delta 标记，Candidate-only tail 使用纹理；
- Observed 与 Candidate 不同的重叠部分显示独立轮廓，Observed-only tail 使用另一种
  纹理；
- 某层不可绘制时仍显示该层 context/error，不用其他层冒充。

每行将 membership、availability、quality 和 revision 正交表达：

- membership：formal / evaluated_candidate / latest_observed 的布尔集合；
- availability_state：present / missing / unobserved / unknown；
- quality_flags：quarantined / non_final / identity_blocked 等可多选事实；
- revision_state：unchanged / added / removed / changed / unknown；
- render_role：formal_baseline / candidate_overlap / candidate_only /
  observed_overlap / observed_only。

任何要求从 composite 导出单一 dataframe 的研究调用返回 COMPOSITE_NOT_DATASET；用户
必须显式选择一个 immutable snapshot。

## 8. 目标架构

    OKX / Binance / future providers
                  |
                  v
       provider-native raw captures
                  |
                  v
         immutable ObservationRun
         + normalized artifacts
         + canonical candidate
         + reconciliation
         + revisions
         + quality findings
         + manifest / hashes
                  |
                  v
       rebuildable Snapshot Catalog
         + attempts
         + runs
         + artifacts
         + findings
         + publication events
         + research runs
                  |
                  v
           Snapshot Resolver
         + latest_observed
         + evaluated_candidate
         + formal_baseline
         + exact run/release
         + knowledge/revision cut
                  |
          +-------+--------+
          |                |
          v                v
     FastAPI Web       Python SDK
     Observatory       Jupyter Lab
          |                |
          +-------+--------+
                  |
                  v
        versioned Research Kernel

### 8.1 事实源与投影

- 不可变 raw/artifacts/manifests/audits 是事实源。
- Snapshot Catalog 是可重建投影，不是第二事实源。
- Catalog 丢失后必须能从 manifests、audits 和 artifact hashes 重建。
- attempt history 还需要 additive attempt receipts；Catalog 不能从缺失事实推造崩溃前
  的 attempt。
- flat btc.parquet 降级为兼容性物化缓存。
- 浏览器和 Notebook 不得直接解析 current pointer 或拼文件路径。
- 只有 Snapshot Resolver 可以把语义通道解析为不可变 run。
- Catalog 只能由显式 Operations/CLI update、rebuild 或采集写侧事件更新；GET/SDK 只
  校验 catalog source fingerprint/watermark。Catalog 过期返回 CATALOG_STALE，不在
  浏览请求中自动建库、迁移或写 projection。

### 8.2 建议领域对象

#### CaptureAttempt

- attempt_id；
- asset_id=crypto.BTC、provider contract version、instrument、quote、interval、timezone；
- requested_at、started_at、completed_at；
- status、rows、latency、retry_count；
- raw_payload_hashes；
- error_kind、reason_code；
- attempt receipt schema version。

#### ObservationRun

- run_id；
- asset contract；
- effective_as_of 与 created_at；
- input/output watermarks；
- code/config/schema version；
- artifact refs 与 hashes；
- quality_state；
- lifecycle_state。

#### QualityFinding

- finding_id；
- run_id、gate、severity、reason_code；
- affected dates/range；
- metrics；
- evidence refs；
- blocks purposes。

#### Release

- release_id；
- channel；
- run_id；
- previous release；
- published_at；
- policy version；
- authorization/audit evidence；
- rollback eligibility。

Current 必须指向不可变 Release，而不是一个可变 parquet 文件。

#### ResearchRun

- research_run_id；
- hypothesis/version；
- dataset snapshot id；
- knowledge_as_of；
- feature/label versions；
- folds、purge、embargo、random seed；
- code/config/environment hashes；
- metrics、status 和 immutable outputs。

V1 使用领域限定名 BtcMarketSnapshot 与 CryptoResearchRun，不创建全局 Snapshot 或
ResearchState 基类/表；A 股 ForecastSnapshot 保持独立，等两条线稳定后再评估共享
抽象。

对现有 H1，CryptoResearchRun 是现行 deterministic validation_run_id、ADS
generation_id、_crypto_validation_current.json 和 pointer-aware
read_crypto_validation_outputs() 的 versioned receipt/adapter，不建立第三个 current
research pointer，也不复制一份互不映射的结果。未来实验可以使用同一 receipt envelope，
但必须声明其原生 identity 与 current-selection authority。

### 8.3 Content-addressed storage

V1 可以继续使用现有 run 目录，但目标设计应允许：

- raw payload 按 SHA-256 去重；
- run manifest 引用不可变 blob；
- manifests 和 publication/research receipts 长期保留；
- 多资产扩展后采用 hot/cold retention；
- 删除缓存不影响 lineage 重建。

第一轮不要求立即迁移全部存量 artifacts 到 CAS；任何迁移必须 additive、可回滚。

## 9. 关键不变量

实现不得破坏以下不变量：

1. 每个绘制的数据点都能追到 asset、instrument、provider、run 和 artifact hash。
2. Primary 与 shadow 不静默混合、不平均、不互相 fallback。
3. unknown、未采集、成功零值、缺失、隔离和无共同窗口必须保持不同语义。
4. Latest Observed 不得冒充 Formal Baseline。
5. ResearchRun 必须绑定不可变 snapshot，不能绑定会移动的 current alias。
6. 切换 snapshot 后，依赖旧 snapshot 的研究结果不得继续显示为当前结果。
7. 浏览请求不能触发 provider 网络、同步、发布、回滚或 DB migration。
8. pointer、manifest、artifact hash 不一致时 fail closed，不回退到另一文件继续画图。
9. Candidate 发布失败不能改变 Formal Baseline。
10. 历史 certification 与当前 compatibility 必须分别保存。
11. 研究特征只能读取 anchor 时刻以前可用的数据。
12. Observe/Investigate 不显示未来 outcome。
13. 图表缺口不得 forward-fill 或插值。
14. 所有阈值、分位数和异常基线必须注明窗口与版本。
15. Snapshot Catalog 可从不可变事实完整重建并核对。
16. 四轴/purpose fitness 不能写回或放宽 data_readiness 与发布门禁。
17. Composite 不得作为单一数据集或研究 snapshot。
18. latest alias 在一次响应开始时必须冻结，跨层读取共享同一 catalog fingerprint。
19. Web/GET/SDK 不得写 Catalog、attempt receipt 或 ResearchRun。
20. H1 只能有一个可审计 current-selection authority；adapter 不得生成竞争 pointer。

## 10. 产品信息架构

长期建议把应用一级导航调整为：

    Today
    Observatory
    Lab
    Decisions
    Operations

V1 不要求立即删除旧导航。可以先新增 Observatory，再逐步把现有 Data 页面降级为
资产库存与低层运维入口，把现有 Research 表格浏览器降级为审计工具。

BTC Observatory 包含：

1. Overview / Now；
2. Market；
3. Trust；
4. Runs and Lineage；
5. Research。

Snapshot Context Bar 在所有 Lens 顶部持续存在。

## 11. Overview 设计

### 11.1 页面草图

    + BTC-USDT / Daily UTC / Knowledge: Latest ---------------------------+
    | Observed 07-18 | Eval Candidate 07-18 | Formal 07-11 | Freshness/SLA |
    | Manual observe WARN | Formal consume CURRENT | Strict research BLOCK |
    +--------------------------------------------------------------------+
    | Price / Return / RV20 / Volume                                     |
    | [formal solid] | [candidate-only hatch] | [observed-only outline]    |
    |                       ^ formal watermark                            |
    | o quarantine   <> revision   ! quality event                        |
    +--------------------------------+-----------------------------------+
    | Market state                   | Why not formal                    |
    | 1d / 7d / 30d return           | acquisition stability 3 / 29     |
    | drawdown / RV percentile       | coverage / quarantine findings   |
    +--------------------------------+-----------------------------------+
    | Unified timeline: capture -> assurance -> publish -> research      |
    +--------------------------------------------------------------------+

### 11.2 顶部 Truth Bar

必须同时显示：

- asset_id、display symbol、provider contracts、instrument、quote、interval、timezone；
- expected latest completed bar；
- Latest Observed watermark；
- Latest Staged 与 Evaluated Candidate watermark；
- Formal Baseline watermark；
- knowledge_as_of 和 rendered_at；
- current release、candidate run、latest staged/attempt refs；
- freshness、compatibility 和 integrity；
- 用途适配。

不得只显示“更新时间”。

### 11.3 市场摘要

P0 指标：

- 最新 close；
- 1D / 7D / 30D 简单收益；
- 当前数据窗口内的 peak drawdown；
- RV20 年化波动率及过去窗口分位；
- 当日 true range 及滚动分位；
- OKX 同源成交量 90 日分位和 robust z-score。

所有摘要必须包含：

- value 与 unit；
- window；
- sample count；
- metric contract version；
- snapshot id；
- status/reason code。

“数据窗口内峰值”不得展示为 BTC 历史 ATH。

### 11.4 What Changed

生成确定性的、证据链接明确的变更摘要：

- 新增了哪些完整日期；
- 哪些历史日期被删除、隔离或修订；
- source basis 是否跨阈值；
- gate 或用途适配是否变化；
- Formal Baseline 是否移动；
- 研究状态是否被 suppression 或 revalidation。

第一版使用规则和结构化模板，不依赖 LLM。

## 12. Market 与 Investigate 设计

### 12.1 联动主图

共享时间轴的 small multiples：

1. Price：
   30D/90D 用日 K，可切换 log close；1Y/All 默认 log close；
2. Return：
   日简单收益柱，零线明确；
3. Risk：
   RV7 / RV20 / RV60，显示计算窗口和历史分位；
4. Volume：
   primary venue 原始 volume、滚动中位数倍数和 90 日分位。

约束：

- 不使用双 Y 轴制造相关性；
- 缺失日期断线；
- candidate-only 使用纹理和文字，不只依赖颜色；
- observed-only 使用与 candidate 不同的轮廓/纹理；
- formal/candidate/observed 重叠时保持独立 layer，revision 用 delta/marker 表达，
  不用某层 OHLCV 静默覆盖另一层；
- quarantine、revision、unobserved 使用不同形状；
- 长周期明确显示 log/linear scale；
- 十字光标锁定所有面板同一日期；
- 浏览器只负责表现，不重新定义正式指标。

### 12.2 Date Evidence Lens

点击日期后展示：

- 当前视图使用的 OHLCV；
- primary/shadow instrument、quote 和 close；
- basis bps 与阈值；
- bar_close_at、available_at、fetched_at；
- finality、payload hashes；
- 该日期在 selected run 中的 finding；
- revision history；
- quarantine 原因；
- 包含该日期的 run；
- 当时可计算的 feature；
- research outcome 状态：not_visible / pending / matured。

普通 Observe/Investigate 中 outcome 固定为不展示。只有进入 Research Lens 后，
明确分离 feature 区和 future outcome 区。

### 12.3 市场状态

第一版只提供描述性状态：

- low/high volatility；
- trend/range；
- drawdown regime；
- relative volume regime。

不得包装为方向性买卖信号。

## 13. Trust 设计

### 13.1 Coverage Calendar

每个行情日区分：

- complete；
- missing；
- quarantined；
- non_final；
- primary_only；
- shadow_only；
- unknown。

### 13.2 Acquisition Calendar

按真实采集日期聚合：

- dual-source success；
- primary-only；
- shadow-only；
- failed；
- empty observed；
- not observed。

一天多次重跑只计一个 qualified acquisition day，但 run 明细仍可钻取。
若 V1 不落 attempt receipt，Calendar 只展示现有 immutable manifest/audit 能证明的
completed facts；stage 前状态显示 unsupported/unknown，不把“没有记录”画成 failed。

### 13.3 Cross-source Basis

- 默认单位 bps；
- 绘制 warn/block 阈值带；
- 显示 aligned rows、warn rows、block rows；
- primary/shadow 原始 close 如需比较，使用并排 small multiples，不使用双轴；
- 不直接比较两个交易所的绝对成交量。

### 13.4 Revision Surface

目标图：

- 横轴：market/bar date；
- 纵轴：capture/run time；
- 颜色或纹理：revision magnitude；
- 点击单元格查看 old/new value、basis、run、payload hash。

若第一版实现二维 surface 成本过高，可以先提供 revision timeline + diff table，
但数据合同必须支持未来 surface。

### 13.5 Run Diff

任意两个 run 比较：

- added dates；
- removed dates；
- changed OHLCV；
- quarantine changes；
- provider/schema/config/code changes；
- watermarks、row count 和 coverage；
- artifact hashes；
- gate/finding changes；
- research impact。

不能只比较 watermark。

### 13.6 Gate 呈现

技术层继续使用 D0-D5；用户层显示：

- 合约与来源；
- 采集稳定性；
- 结构与覆盖；
- 跨源一致性；
- 修订稳定性；
- 发布与回滚。

每个问题必须说明：

- 发生了什么；
- 影响哪些日期；
- 阻塞哪些用途；
- 需要什么证据恢复；
- evidence refs。

## 14. Runs and Lineage 设计

### 14.1 统一时间线

时间线事件：

- acquisition started/succeeded/failed；
- run staged；
- assurance passed/degraded/invalid；
- candidate selected；
- release published；
- release superseded；
- rollback；
- schema/config/code policy changed；
- research run created/suppressed/revalidated。

### 14.2 固定 URL

页面 URL 至少能固定：

- asset；
- lens；
- run or release；
- selected date；
- knowledge_as_of；
- range；
- metric set。

刷新或分享后必须恢复同一证据上下文。

### 14.3 历史认证与当前兼容

每个已发布 release 同时显示：

- certified_at_publish；
- publish policy/version；
- artifact integrity；
- current compatibility；
- current freshness。

代码更新导致 replay mismatch 不得抹掉“当时通过并发布”的历史事实。

## 15. Research 设计

### 15.1 V1 假设

沿用 docs/23 的 H1：

> 当 BTC 20 日实现波动进入高波动状态后，未来七个完整 UTC 日的实现波动是否
> 显著且稳定地高于正常观察日？

H1 非方向性，不输出买卖建议。

### 15.2 研究页面

必须展示：

- hypothesis id/version 和预注册定义；
- dataset snapshot id 与 knowledge_as_of；
- feature、threshold、label contract；
- eligible events、normal comparators、pending labels；
- folds、purge、embargo；
- primary effect ratio；
- bootstrap CI；
- BH q value；
- fold stability；
- placebo；
- candidate/monitoring/validated/rejected/blocked；
- reason codes 和 evidence refs。

推荐图：

- past-only RV20 regime timeline；
- future RV7 分布或 ECDF；
- fold effect forest plot；
- bootstrap interval；
- sample maturity；
- event path，future outcome 区必须独立底色。

禁止只展示一个显著性数字或全样本均值。

### 15.3 不可变实验 manifest

每个正式实验记录：

- hypothesis_id/version；
- dataset_snapshot_id；
- knowledge_as_of；
- source run ids/hashes；
- feature/label definitions；
- folds、purge、embargo；
- random seed；
- code/config/environment hashes；
- metrics；
- artifact hashes；
- created_at。

输出至少包括：

- per-fold samples/results；
- matured/pending outcomes；
- metrics JSON；
- chart data；
- frozen HTML report；
- reproducible command。

## 16. Web、Jupyter 与共享研究内核

### 16.1 Web

负责：

- 日常正式观测；
- Current/Candidate/assurance 边界；
- 数据质量和异常调查；
- run/release/research 结果浏览；
- 状态变化和证据钻取。

不负责：

- 任意调参后自动生成正式结论；
- UI 内重写正式指标；
- 直接文件访问；
- 同步、发布或回滚。

### 16.2 Jupyter

负责：

- EDA；
- 新指标和图形原型；
- 方法开发；
- 固定 snapshot 的实验复现；
- 研究叙事。

Notebook 必须是 thin notebook：

- 研究参数和叙事可以留在 notebook；
- 读取、特征、标签、validation 逻辑进入版本化 Python package；
- 从干净 kernel 可重跑；
- 默认清除体积大的 cell outputs 后提交；
- 正式结果通过 ResearchRun 和 manifest 固化。

### 16.3 Open in Lab

Web 不向 notebook 传 filesystem path，而是冻结：

- asset；
- snapshot id；
- knowledge_as_of；
- instrument/quote/interval/timezone；
- excluded/quarantined dates；
- metric contract version；
- hypothesis version。

Notebook 结果默认是 exploratory，不能自动改变 Web formal state。

Web 的 Open in Lab 只返回或展示 deep link、参数文件内容或可复制命令；它不启动本地
进程、不创建 notebook、不写临时文件，也不注册 ResearchRun。deep link 必须固定
snapshot_id，不能只传 latest/current alias。

### 16.4 ResearchRun 写入、导入与晋级

正式 ResearchRun 只能由显式 CLI/Operations workflow 创建，建议合同为：

    trade research btc run --hypothesis H1 --snapshot-id SNAPSHOT_ID --dry-run

非 dry-run 的原子流程：

1. 解析并重新验证 snapshot identity、artifact hashes、PIT/eligibility 和 hypothesis
   version；
2. 在隔离临时目录用版本化 kernel 执行，失败时不注册半成品；
3. 原子写 immutable outputs、manifest 和 receipt；
4. 对 H1 映射现有 validation_run_id/generation_id/current pointer，不创建竞争 current；
5. 显式更新可重建 Catalog projection，并返回 research_run_id 和 reproducible command。

现有 H1 current 转换合同固定如下；唯一 current-selection authority 是现有 lifecycle
计算出的 activate_run 与 persist_crypto_validation_outputs() 的原子 transaction：

| workflow | 可写 immutable receipt/artifacts | 可移动 _crypto_validation_current.json |
| --- | --- | --- |
| run --dry-run | 否 | 否 |
| run | 是；记录 validation_run_id/generation_id | 仅当现有 lifecycle 产出 activate_run=true，由现有 atomic writer 移动；命令本身不另写 pointer |
| import notebook bundle | 仅 exploratory namespace | 永不 |
| promote imported run | 不直接改旧 run；在干净环境触发一次正式 rerun | 仍只由 rerun 后现有 lifecycle + atomic writer 决定，不允许命令强设 true |
| suppress/revalidate | 追加现有 lifecycle receipt | 仅走同一 atomic writer/rollback contract |

因此 run 和 promote 不是两个 current authority；Catalog 的 research projection 只镜像
receipt/pointer，不参与选择 active H1。

Notebook 普通执行只产生未注册 exploratory 输出。若需要保留，显式 import workflow
校验 snapshot、kernel/code/environment hashes 和完整 manifest 后，只能创建
exploratory CryptoResearchRun。晋级必须是另一个显式 promote workflow：从干净环境按
预注册合同重跑，检查样本、fold、CI、placebo、多重检验和人工/策略授权，追加 promotion
receipt；不得就地修改原 run，也不得因 notebook 中的图看起来合理而提升状态。

Web 只读这些 receipts/artifacts。运行、import、promote、suppress/revalidate 都属于
CLI/Operations 写侧，并要求 dry-run、审计、原子写和回滚/撤销语义。

### 16.5 Streamlit

允许用作短期交互原型，但：

- 不成为事实源；
- 不复制 snapshot/quality/research 语义；
- 不作为长期监控唯一入口；
- 原型验证完后收敛到正式 Web。

## 17. Snapshot Resolver 与 Python SDK

### 17.1 Resolver 输入

- asset_id，V1 固定 crypto.BTC；display symbol 不能代替 identity；
- channel：observed / evaluated_candidate / formal，或 exact run/release；
- snapshot_id，或 run_id/release_id，或 channel，按第 6 节优先级互斥解析；
- knowledge_as_of 与 knowledge_mode；
- revision_policy：as_known / latest_restated；
- market date range；
- metric contract version；
- include quarantined，默认 false。

include_quarantined=false 表示隔离行不进入 OHLCV/指标计算，不表示从响应和图上消失。
SnapshotContext/Layer 必须另带 excluded_dates：date、exclusion_reason、quality_flags、
evidence_refs 和 marker position，Overview 仍绘制无数值的 quarantine marker/缺口。
include_quarantined=true 只用于明确的诊断视图，行持续带 quarantine 标记，不能因此
提升 purpose fitness 或成为默认研究输入；该 inclusion policy 进入 snapshot_id。

### 17.2 Resolver 输出

SnapshotContext：

- snapshot_id；
- resolved channel；
- run/release；
- contract；
- market/input/output watermarks；
- requested knowledge_as_of、effective_knowledge_cut、relevant_fact_sequence、
  knowledge_mode、revision_policy、PIT coverage status；
- created/certified/published/rendered times；
- lifecycle/quality/freshness/compatibility；
- purpose fitness；
- artifact refs/hashes；
- findings summary；
- excluded_dates/evidence markers；
- reason codes。

Series rows：

- date、OHLCV；
- provider/instrument/quote；
- available_at/fetched_at；
- source_run_id；
- membership；
- availability_state；
- quality_flags；
- revision_state；
- render_role，仅比较投影需要；
- metric values 与版本。

### 17.3 Python SDK 目标形态

API 名称不是强制，但应支持类似语义：

    context = observe.asset("crypto.BTC").snapshot(
        channel="formal",
        knowledge_as_of="2026-07-19T00:00:00Z",
        knowledge_mode="installation_observed",
        revision_policy="as_known",
    )

    bars = context.bars()
    findings = context.findings()
    reconciliation = context.reconciliation()
    revisions = context.revisions()

SDK 只读调用不能隐式触发同步或 migration。

Composite SDK 返回 LayeredComparison，不返回可被 bars()/research 接受的 SnapshotContext。
调用方必须选择 context.formal、context.evaluated_candidate 或 context.observed 中的一个
immutable snapshot。

## 18. Web API 合同

建议使用面向语义的版本化路由。具体文件拆分可由实现者调整，但契约不得退化为
暴露服务器文件路径。

### 18.1 Context

    GET /api/v1/observatory/assets/crypto.BTC/context

返回：

- semantic channels 与 latest attempt/staged refs；
- Snapshot Context；
- purpose fitness；
- primary blockers；
- what changed；
- active alerts；
- supported lenses/ranges。

### 18.2 Series

    GET /api/v1/observatory/assets/crypto.BTC/series
        ?view=composite
        &from=2026-01-01
        &to=2026-07-18
        &knowledge_as_of=latest
        &knowledge_mode=installation_observed
        &revision_policy=as_known

view=composite 返回 LayeredComparison；单 snapshot 查询使用 channel 参数。支持：

- composite；
- observed；
- evaluated_candidate；
- formal；

known-at 和 restatement 分别由 knowledge_as_of/knowledge_mode 与 revision_policy 表达，
不得再伪装为 channel。view=composite 与 exact snapshot/run/release identity 的非法组合
返回 INVALID_SNAPSHOT_SELECTOR。

响应必须带 ETag、snapshot/view fingerprint。Composite 返回独立 layers，单 snapshot
返回 rows；二者都使用 membership、availability_state、quality_flags、revision_state，
不再返回混合语义 row_state。

### 18.3 Date evidence

    GET /api/v1/observatory/assets/crypto.BTC/dates/2026-07-18
        ?snapshot_id=...

返回 primary/shadow、basis、times、findings、revision、run lineage 和 research
visibility。

### 18.4 Trust

    GET /api/v1/observatory/assets/crypto.BTC/trust
        ?snapshot_id=...

返回 coverage、acquisition、basis、revision 和 gate findings；大明细分页或按日期范围
查询。

### 18.5 Runs and diff

    GET /api/v1/observatory/assets/crypto.BTC/runs
    GET /api/v1/observatory/runs/{run_id}
    GET /api/v1/observatory/runs/diff?base=...&compare=...

run id 必须做严格格式和根目录边界验证，禁止 path traversal。

### 18.6 Research

    GET /api/v1/observatory/assets/crypto.BTC/hypotheses
    GET /api/v1/observatory/research-runs/{research_run_id}

研究图数据由后端正式 research artifacts 提供，不由前端根据价格临时计算。

### 18.7 错误语义

至少包含：

- SNAPSHOT_NOT_FOUND；
- CURRENT_POINTER_INVALID；
- ARTIFACT_HASH_MISMATCH；
- MANIFEST_INVALID；
- CHANNEL_UNAVAILABLE；
- PIT_NOT_PROVEN；
- DATASET_STALE；
- QUALITY_BLOCKED；
- RESEARCH_NOT_ELIGIBLE；
- INVALID_SNAPSHOT_SELECTOR；
- COMPOSITE_NOT_DATASET；
- CATALOG_STALE；
- RESTATED_NOT_PIT；
- LEGACY_TIME_UNPROVEN。

错误返回 reason_codes、evidence refs 和 retryability，不使用空数组伪装成功。

### 18.8 HTTP、序列化与分页合同

M0 冻结 OpenAPI golden fixtures，前后端从同一 schema 验证：

| 情况 | HTTP | 合同 |
| --- | --- | --- |
| 参数/identity 非法 | 400 | 稳定 reason_code，不泄漏本地路径 |
| snapshot/run/release 不存在 | 404 | SNAPSHOT_NOT_FOUND |
| PIT 证据不支持 | 422 | PIT_NOT_PROVEN + coverage interval |
| quality/research policy 阻塞 | 422 | blocker 与 evidence，可重试性明确 |
| pointer/hash/manifest integrity 错误 | 409 | fail closed，不返回旧缓存伪成功 |
| catalog stale/rebuild 中 | 503 | CATALOG_STALE + retry_after |
| 未变化 | 304 | ETag 与 view fingerprint 一致 |

- 时间统一为带 Z 的 UTC RFC 3339；market date 单独为 YYYY-MM-DD。
- 金额/价格/比例的 JSON 精度与 decimal/string policy 在 schema 固定，禁止前后端各自
  round 后参与 hash。
- unknown 使用显式 status/reason；可空字段为 null，不能用 0、空串或空数组替代。
- runs/findings/research 列表固定 sort key + id tie-break，使用 cursor pagination；同一
  snapshot/catalog fingerprint 下翻页不得重复或漏行。
- API golden contract 覆盖 success/degraded/error、layered composite 和 exact snapshot。

## 19. 视觉真实性与可访问性规则

所有实现必须遵守：

1. 图表标题显示 asset、instrument、quote、interval、timezone、snapshot、as-of、
   sample count。
2. 长周期价格默认 log scale，并持续显示 scale。
3. 收益、basis、异常指标有明确零基线。
4. 不用双 Y 轴制造相关性。
5. Candidate/degraded 使用持续纹理或水印，不能只放一个小 badge。
6. 状态同时使用文字、图标、纹理和颜色。
7. 缺失、unknown 和 quarantined 不插值。
8. 阈值只由 anchor 之前的数据计算。
9. 事件标注只能表达时间邻近，不自动表达因果。
10. Observe 不展示未来 label。
11. Research 同时展示 effect、interval、sample、fold stability 和 multiple testing。
12. 不把平滑线、AI 摘要或技术指标当成证据。
13. 所有 tooltip 可以回到 Date Evidence Lens。
14. 用户选择自定义范围时，范围进入 URL/view context。

## 20. 性能与可维护性

### 20.1 初始规模

BTC V1 约 730 根日线，单次交互计算量小。优化重点不是分布式扩展，而是：

- 避免每次请求扫描所有历史 run；
- 避免重复读取完整 parquet；
- 保证语义一致性；
- 支持未来多资产增长。

### 20.2 Catalog

- run 目录变化时增量更新 projection；
- status/context 查询读取 catalog 和 manifest 摘要；
- catalog 与 artifacts 定期 checksum reconcile；
- catalog 可全量 rebuild；
- 不把 mtime 当业务时间；
- 各 selector 严格使用第 7 节的业务排序键和 run_id tie-break。

### 20.3 API

- series 默认 90D，设硬上限；
- 大型 run 列表和 findings 分页；
- ETag 基于 snapshot/run/hash/params；
- 指标在后端版本化并缓存；
- 浏览器不重复拉取未变化 artifact；
- SSE 或现有事件流只负责通知 refresh，不传大 payload。

### 20.4 可测性能预算

在 M0 记录 CPU、内存、磁盘、Python/Node 版本作为 benchmark envelope。V1 frozen
benchmark 至少包含 10,000 个 manifests/receipts、730 日三层 series、1,000 条 findings
和两份 730 行 run diff。单进程本地 reference 环境目标：

| 操作 | 冷态预算 | 热态 p95 | 额外约束 |
| --- | --- | --- | --- |
| context/status | <=500 ms | <=100 ms | 0 次 parquet open，仅读 catalog/manifest summary |
| 730 日 composite API | <=1.5 s | <=300 ms | 三层分开，压缩响应 <=2 MiB |
| 730 行 run diff | <=1.0 s | <=300 ms | 不扫描无关 run |
| 10k manifest full rebuild | <=60 s | 不适用 | peak RSS <=512 MiB，结果 hash 确定 |
| Catalog incremental update 100 runs | <=2 s | <=500 ms | 原子 generation 切换 |
| 前端 730 点三层首屏 | <=2 s | interaction <=100 ms | 无 console error，缩放/tooltip 不掉语义 |

若 CI/reference host 明显不同，可在 OpenSpec 中调整绝对值，但必须保留数据规模、I/O
计数、结果正确性和相对回归阈值；不能把“数据量小”当成跳过 benchmark 的理由。

### 20.5 存储增长

- manifest、publication receipt、research receipt 长期保留；
- raw blobs 内容寻址去重；
- 多资产扩展前定义 hot/cold retention；
- 缓存和物化视图可删除重建；
- 任何 retention 不得破坏 lineage 和复现实验。

## 21. 故障模式与响应

| 故障 | 必须行为 |
| --- | --- |
| provider 全失败 | 记录 attempt，Latest Observed/Formal 不移动 |
| 仅 primary 成功 | 若 canonical 合同合格可成为带警告的 Observed；不得冒充 dual-source assured |
| pointer/manifest/hash 不一致 | fail closed，显示 integrity error |
| 最新 Evaluated Candidate 质量失败 | 保留并选中该证据，不回退旧 good candidate，不移动 Formal |
| Evaluated Candidate D0/integrity 失败 | context 可见，series 不可绘制，不用 Observed/Formal 代替 |
| Observed 比 Candidate 更新 | Composite 增加 observed-only layer，不合并 OHLCV |
| Catalog 损坏 | 从 manifests/audits rebuild，不修改 artifacts |
| Catalog stale/rebuild 中 | GET 返回 CATALOG_STALE，不在读请求中更新 projection |
| 当前代码 replay mismatch | 历史 certification 保留，compatibility 单独告警 |
| Formal stale | 页面继续显示正式身份，同时显著显示 freshness 和 observed gap |
| quarantine 增加 | 影响日期与 purpose fitness 可见，研究结果做 impact analysis |
| research snapshot 被 supersede | 原结果保留历史，不能显示为新 snapshot 当前结论 |
| Web API 不可验证 artifact | 返回明确错误，不 fallback 到 raw path |

## 22. 安全、写入与操作边界

Observatory 默认全部只读：

- 不同步；
- 不回填；
- 不发布；
- 不回滚；
- 不做 migration；
- 不训练；
- 不写 research outcome。

写操作继续留在 Operations/CLI，并遵守：

- 显式命令；
- dry-run；
- backup/snapshot；
- 小样本；
- hash/schema/row count 核验；
- 原子 pointer/release 切换；
- rollback receipt。

允许的新写侧只有显式批准的三类：采集过程追加 attempt receipt、Operations/CLI 原子
更新或 rebuild Catalog projection、Research CLI 原子注册/晋级 ResearchRun。三者都要
有独立 schema version、dry-run/临时目标、审计 receipt 和失败不留半状态的测试；不能
借“读时自动初始化”绕过该边界。

如果未来 Web 增加操作入口，必须进入独立 Operations workflow，二次确认并展示
mutation plan；不得在 Observatory 图表按钮中隐式执行。

## 23. 迁移与兼容策略

### 23.1 保留

- provider-native capture；
- immutable run；
- D0-D5；
- manifest/hash/reconciliation/revision；
- exclusive/shared lock；
- predecessor CAS；
- publish/rollback audit；
- FastAPI/React shell；
- 现有 H1 方法。

### 23.2 重构

- 单一 current 读模型；
- Web 拼接 flat parquet；
- 大写 BTC 路径问题；
- 通用 DataPage 的 BTC 展示；
- 通用 ADS 表格式 Research 页面；
- readiness 单状态的读侧表达；manifest data_readiness 与发布 authority 保留；
- 浏览器临时计算正式指标。

### 23.3 兼容期

- btc_current.json 映射到 Formal Baseline；
- btc.parquet 作为 Formal materialized compatibility view；
- 旧 /api/data/kline/crypto.BTC 可通过新 resolver 适配，标记 deprecated；
- 旧 Data inventory/Gaps/Coverage 页面 additive 保留，只在 BTC 行和详情增加
  Observatory deep link；不整页重定向；
- 旧 Research 表格浏览保留审计用途；
- 新旧 API 并行一段时间，以 contract tests 验证结果。

Catalog 引入遵循 schema-versioned、additive、可回滚流程：

1. 先用 frozen fixtures 与真实数据只读样本生成 evidence coverage report；
2. rebuild --dry-run 写到独立临时 Catalog，输出 source fingerprint、row counts、
   unresolved facts 和 deterministic hash；
3. 新旧 resolver dual-read，对 Formal identity、Candidate、watermarks、hash、findings 和
   error semantics 做逐项对账；差异不能只比较行数；
4. 通过后以 generation pointer/CAS 原子切换 Catalog，保留上一 generation；
5. Web route/navigation 由 feature flag 单独开启，不能与 Catalog schema 切换绑成一次
   不可回滚动作；
6. publish/rollback 与 Catalog update/rebuild 并发时，reader 要么读完整旧 generation，
   要么读完整新 generation；禁止混合 pointer 与 artifacts。

### 23.4 回滚

新读侧 rollout 不修改 provider artifacts 和旧 current：

- 关闭新导航或 route；
- 恢复旧 Web API adapter；
- 切回上一 Catalog generation 并保留新 generation 供取证；确认不再需要后才可清理
  纯缓存，不删除事实 receipts；
- 保留所有新 manifests 和 receipts；
- Formal Baseline 不因 UI 回滚而变化。

任何需要改变正式发布语义的后续步骤，必须单独 OpenSpec 和数据安全计划。

## 24. 实施阶段

### M0 - OpenSpec 与共识评审

目标：冻结语义后再写代码。

任务：

- 创建 btc-observatory-research-lab-v1 OpenSpec；
- 至少包含 snapshot-semantics、observatory-workspace、
  point-in-time-research-lab 三个 capability；
- 明确本计划与 crypto-data-assurance-and-validation-v1 的边界；
- 在 supersession 记录中废止 CoinGecko/cross_asset provider/path 条款，保留 D0-D5、H1
  与发布安全不变量；关闭或重写冲突的 active OpenSpec tasks；
- 固定 crypto.BTC/OKX BTC-USDT/Binance BTCUSDT identity map；
- 产出 PIT evidence coverage report；
- 决定接受 attempt receipt 写侧扩展，或把 Latest Attempt 降级为 Latest Completed
  Staged Run；
- 运行 review-this 六角色共识评审；
- 解决全部 P0；
- 冻结 selector predicates/order、knowledge mode、revision policy、snapshot identity、
  用途适配、API reason code、H1 identity adapter 和 frontend test runner/scripts。

退出条件：

- OpenSpec strict validation 通过；
- 没有未决的 Current/Candidate/PIT 语义；
- 任务全部绑定测试或明确 no-test reason。

### M1 - Snapshot Catalog 与 Resolver

目标：建立唯一读语义，不依赖 Web。

任务：

- 定义领域模型；
- 从现有 manifests/current/audits 构建可重建 catalog；
- 如 M0 批准，接入 additive attempt receipts；
- 实现 channel resolution；
- 实现 artifact/hash/shared-lock 验证；
- 实现 Current/Candidate/run diff；
- 提供 Python SDK；
- 提供 legacy adapter；
- 提供 Catalog dry-run rebuild、incremental update、generation CAS 和 stale 检测 CLI；
- 修复 BTC 大小写路径，但新逻辑不得继续依赖大小写猜测。

退出条件：

- 可解析当前真实 Formal、Evaluated Candidate、Latest Observed 与 Latest Staged；
- catalog rebuild 结果确定；
- pointer/hash 不一致 fail closed；
- 所有只读调用无网络、无 DB schema mutation、无数据写入；
- focused UT 全部使用 tmp_path/frozen fixtures。

### M2 - Observatory Overview 纵向切片

目标：30 秒看懂真实状态。

任务：

- context/series API；
- Snapshot Context Bar；
- composite 主图；
- formal/candidate/observed 独立分层与分界；
- market summary；
- purpose fitness；
- why-not-formal；
- deterministic what-changed；
- 固定 URL。

退出条件：

- frozen fixture 能证明 observed_watermark > formal_watermark，并同时展示 Candidate 与
  observed-only layer；真实数据 smoke 只记录运行时实际水位，不把 2026-07-18/07-11
  硬编码为测试预期；
- Candidate 不可能被误标为 Published；
- 缺失/quarantine/revision 有非颜色语义；
- frontend build/typecheck 与 API contract tests 通过。

### M3 - Trust、Date Evidence 与 Run Diff

目标：从异常追到证据。

任务：

- Date Evidence API/Lens；
- Coverage Calendar；
- Acquisition Calendar；
- Basis 图；
- Revision timeline/surface；
- run list/detail/diff；
- historical certification 与 current compatibility；
- quality issue 的用途影响。

退出条件：

- 任意异常日期可以追到 provider/run/hash；
- 能解释 candidate 未发布的首要原因；
- unknown/failed/empty/unobserved 不混淆；
- diff 包含新增、删除、修改与 contract 变化。

### M4 - Point-in-Time

目标：恢复当时系统真正知道的视图。

任务：

- 两种 knowledge_mode 的 as-of resolution；
- revision validity；
- backfilled/PIT-unproven；
- As-of 控制所有 Lens；
- PIT URL 和 snapshot fingerprint；
- evidence coverage 与 PIT_NOT_PROVEN；
- 历史回放与 determinism tests。

退出条件：

- 冻结 fixture 下，同一 knowledge time 重放 hash 完全一致；
- 后续修订不会渗入旧 as-known 视图；
- unavailable 证据显式返回，不用今天数据替代。

### M5 - Research Lab

目标：建立 H1 的正式证据页和可复现 Notebook。

任务：

- research run registry；
- 现有 H1 identity/current pointer adapter；
- 显式 run/import/promote CLI 与原子 receipts；
- H1 hypothesis UI；
- sample/fold/effect/CI/placebo/multiple-testing 图；
- Open in Lab；
- thin notebook template；
- frozen report 与 reproducible command；
- snapshot supersede impact。

退出条件：

- Web 和 Notebook 使用同一 snapshot/metric contract；
- Observe 不显示 future outcome；
- 同一 research manifest 重放一致；
- 数据不够时诚实显示 insufficient/blocked。

### M6 - 产品收敛与扩展

目标：语义稳定后再扩大范围。

任务：

- 根据实际使用决定旧 Data/Research 页面去留；
- 增加状态变化告警和 incident timeline；
- 保存 investigation context 与人工注释；
- 评估 ETH/Gold 接入；
- 多资产前完成 storage retention 与性能复核。

退出条件：

- BTC 工作流稳定；
- 新资产复用语义而非复制页面；
- 没有通过泛化掩盖 BTC 未解决的问题。

## 25. 推荐代码所有权

具体目录可以在 OpenSpec 设计评审中调整，但责任边界必须保持。

| 责任 | 推荐 owner |
| --- | --- |
| Snapshot domain、channel、四时钟、purpose fitness | trade_py/observatory/domain/ |
| Catalog projection/rebuild/reconcile | trade_py/observatory/catalog/ |
| Artifact verification 和 snapshot resolution | trade_py/observatory/service/ |
| Run/date/trust/research query facade | trade_py/observatory/query/ |
| 版本化指标和研究内核 | trade_py/research/crypto/ 或现有 crypto validation 模块的清晰拆分 |
| FastAPI routes/schemas | trade_web/backend/observatory/ |
| React workspace | trade_web/frontend/src/pages/observatory/ |
| Shared chart/evidence components | trade_web/frontend/src/components/observatory/ |
| Thin notebook/template | notebooks/ 或 research/notebooks/，由 OpenSpec 决定 |
| DB/cursor/repository | 现有 DB owner 模块下 additive repository，不在 service 写 SQL |
| Contract/fixture tests | tests/observatory/ 或现有 tests/ 下按模块分组 |

避免：

- 继续扩张 trade_web/backend/app.py；
- 把所有前端逻辑塞进 DataPage.tsx；
- service 直接写 SQL；
- notebook 复制正式特征逻辑；
- 新建另一个隐含事实源。

## 26. 测试矩阵

### 26.1 Snapshot 与 Catalog

- manifests/audits 重建 catalog 确定性；
- latest attempt/staged/observed/evaluated_candidate/formal 的资格、业务排序和 tie-break；
- legacy timestamp adapter、null ordering、provenance reason 与禁止 mtime；
- 最新失败 Candidate 不回退、失败 attempt 不移动 Observed；
- invalid/D2-D4 rendering blocker 只返回 evidence，不进入 composite；
- 若 M0 批准 attempt receipt：crash/abandoned reconciliation；否则测试
  unsupported/unknown 降级合同；
- Catalog stale、dry-run、generation CAS 与增量/全量一致；
- pointer/manifest/path/hash tampering；
- current certification vs current compatibility；
- catalog 损坏/缺失恢复；
- legacy btc_current/btc.parquet adapter；
- 大小写 symbol 路径回归；
- path traversal 拒绝。

### 26.2 只读安全

- GET/SDK read 不调用 provider；
- 不创建数据文件；
- 不执行 migration；
- 不修改 DB；
- 不切换 pointer；
- 不产生 research outcome；
- shared lock 一致快照；
- publish 并发窗口 fail closed。
- publish/rollback 与 Catalog rebuild/update 并发 generation 一致性。

### 26.3 Series 与视觉语义

- formal/candidate/observed composite 独立 layers；
- candidate-only/observed-only tail；
- 重叠 OHLCV revision 不覆盖、不平均；
- missing 不插值；
- include_quarantined=false 排除数值但保留 excluded_dates/evidence marker；
- membership/availability/quality/revision 正交字段；
- source/quote/interval 不混合；
- metric window/version；
- timezone/available/fetched 序列化；
- 30D/90D/1Y/All 边界。

### 26.4 Trust

- acquisition 按不同日期计数，同日多 run 不重复；
- failed/empty/unobserved 区分；
- basis pass/warn/block；
- revision diff；
- added/removed/changed rows；
- purpose fitness blocker propagation。

### 26.5 Point-in-Time

- future row 不可见；
- later revision 不污染旧 as-of；
- backfill 标为 PIT-unproven；
- market_available 与 installation_observed 不混用；
- legacy evidence coverage 与最早可证时间；
- selector 冲突、identity hash 与 view fingerprint；
- latest 重复请求稳定 ID/ETag；BTC 相关事实变化才失效，其他资产更新不使其抖动；
- pending outcome 不变成 0；
- threshold 只读过去；
- known-at replay hash 确定。

### 26.6 Research

- snapshot 必须不可变；
- experiment manifest 完整；
- fold/purge/embargo；
- effect/CI/sample/fold stability；
- observe 不泄漏 future labels；
- superseded snapshot 不继续显示为当前研究；
- Notebook 从干净环境可重跑。
- H1 validation_run_id/generation_id/current pointer 一一映射；
- run/import/promote 原子性、失败无半成品、promotion receipt 不改写旧 run；
- Web/Open in Lab 不启动进程、不创建文件、不注册 run。

### 26.7 Web

- API schemas；
- OpenAPI golden success/degraded/error fixtures；
- HTTP status/reason code mapping；
- UTC、decimal、null 和 stable cursor pagination；
- loading/empty/error/degraded states；
- Candidate 水印/纹理；
- Observed-only layer 与三层 legend；
- 非颜色可访问性；
- 固定 URL 恢复；
- API stale cache/ETag；
- 浏览器 E2E：Overview -> Date Evidence -> Run Diff -> Research -> URL restore；
- Observe/Investigate DOM/API 均无 future-label leakage；
- frontend typecheck/build。

## 27. 验证命令

实现者应先落下以下 focused test owners；如模块拆分导致改名，OpenSpec tasks 必须
记录等价映射，不能用一个笼统测试文件替代各层合同：

    uv run pytest \
      tests/test_btc_observatory_catalog.py \
      tests/test_btc_observatory_snapshot_resolver.py \
      tests/test_btc_observatory_api.py \
      tests/test_btc_observatory_research.py -q
    uv run pytest tests/test_crypto_data_cli.py \
      tests/test_cross_asset_data_assurance.py \
      tests/test_data_gateway_cross_asset_read.py -q
    python -m compileall trade_py trade_web tests
    npm --prefix trade_web/frontend run build
    npm --prefix trade_web/frontend run test:unit
    npm --prefix trade_web/frontend run test:e2e
    npm --prefix trade_web/frontend run test:a11y
    openspec validate btc-observatory-research-lab-v1 --strict

当前 frontend 尚无上述 test scripts；WP0 必须冻结 runner（建议 Vitest + Playwright，
a11y 可由 axe 驱动），WP4 在 package.json 落下这三个稳定入口，CI 和本地使用同一命令。
若 a11y 合并进 E2E，test:a11y 仍作为可独立执行的目标保留。

共享模块变化后运行完整 Python suite。所有测试使用 tmp_path 或 frozen fixtures，
不得访问真实 provider 或修改真实 data/。

性能 smoke 必须使用第 20.4 节 frozen benchmark envelope，记录耗时分布、I/O 次数、
peak RSS、response bytes、浏览器 interaction latency 和测试机信息；至少覆盖 10k
Catalog rebuild、730 日三层 composite、run diff、重复请求 ETag/304 和前端交互。只写
“页面能打开”或“不扫描全部 parquet”不算完成证据。

## 28. 交付与 Git 约束

执行 agent 必须遵守仓库 AGENTS.md：

1. 开始前检查 git status -sb。
2. 每个实现 run 创建独立 worktree 与新分支：

       wt/btc-observatory-wp2-20260719

   实际名称替换 WP 编号与日期，不复用其他 agent 的 worktree。

3. 中大型实现先执行 review-this 六角色共识评审。
4. P0 未解决前不进入实现。
5. 每个行为变化增加或更新 UT。
6. 每个逻辑完整单元验证后立即 commit。
7. 每 3-5 个 commit push。
8. 真实 data 默认只读；测试只用 tmp_path。
9. 不提交 parquet、DB、cache、raw capture、Notebook 大输出。
10. 只 stage 有意文件。
11. 合回 master 使用 rebase 后 squash merge。
12. 最终报告包含范围、验证、兼容/数据风险、性能 smoke 和剩余项。

不同 agent 可以并行处理互不重叠的 slice，但：

- Snapshot semantics 与 API schema 必须由一个 owner 统一；
- frontend 不可在 backend contract 未冻结时自行发明状态；
- Notebook 不可复制未落地的研究逻辑；
- 多 agent 不得共享同一可写 worktree；
- 每个 slice 合并前先 rebase 最新集成分支并跑契约测试。

## 29. Agent 实施顺序与依赖

每个 WP 由一个 owner agent 在独立 worktree 负责；owner 对输出合同、focused tests、
commit 和完成证据负责。后续 WP 不得通过复制代码绕过未完成依赖。

| WP | 单一 owner 范围 | 输入 | 必须输出 | 依赖 |
| --- | --- | --- | --- | --- |
| WP0 | OpenSpec 与语义冻结 | 本计划、当前代码/manifests、旧 OpenSpec | supersession、identity map、selector/API schema、fixtures、PIT coverage report | 无 |
| WP1 | Attempt/Catalog 投影 | WP0 schemas、manifests/audits/receipts | optional attempt receipt、versioned Catalog、rebuild/update/CAS CLI | WP0 |
| WP2 | Resolver + Python SDK | WP0 contracts、WP1 Catalog | BtcMarketSnapshot、selectors、purpose fitness、layered comparison | WP1 |
| WP3 | FastAPI query facade | WP2 SDK、OpenAPI golden | context/series/date/trust/runs/research GET APIs | WP2 |
| WP4 | Overview/Market Web | WP3 API/schema | Truth Bar、三层 composite、summary、URL restore | WP3 |
| WP5 | Trust/Lineage Web | WP1/WP3 | calendars、Date Evidence、basis/revision、run diff | WP3，可与 WP4 并行 |
| WP6 | PIT resolver | WP0 coverage、WP2 identity | 双 knowledge mode、revision policy、fingerprints、PIT errors | WP2 |
| WP7 | Crypto research workflow | WP6、现有 H1 validation identities | versioned kernel adapter、run/import/promote CLI、immutable receipts | WP6 |
| WP8 | Research UI + thin notebook | WP3/WP7 artifacts | H1 evidence UI、Open in Lab deep link、repro notebook | WP7 |
| WP9 | 兼容、性能与 rollout | WP1-WP8 | dual-read report、feature flag、E2E/benchmark、rollback drill | WP4/WP5/WP8 |

### 29.1 每个 WP 的合同与完成证据

#### WP0 - OpenSpec 与语义冻结

- 不改业务运行代码。
- 输出严格校验通过的 change，解决 provider/OpenSpec 冲突；冻结 reason codes、HTTP
  golden schema、frozen fixture relations 和 agent 文件 ownership map。
- 完成证据：OpenSpec validate 输出、六角色 review-this 共识、P0 closure 表、fixture
  inventory 与 evidence coverage report。

#### WP1 - Attempt 与 Catalog

- 只能读取现有真实 data；所有写测试进入 tmp_path。
- 输出 catalog_schema_version、source/generation fingerprint、dry-run/full/incremental
  命令和原子 generation 切换。若实现 attempt receipt，采集改动和 crash 测试属于此 WP。
- 完成证据：10k manifest benchmark、全量/增量结果 hash 一致、损坏恢复、并发 publish
  不出现 mixed generation。

#### WP2 - Resolver 与 SDK

- 是 selector、状态映射、snapshot identity 和 composite layer 的唯一代码 owner。
- 输出只读 facade；不得把 Web DTO 或 Notebook helper 放入 domain。
- 完成证据：selector truth table 全覆盖、移动 alias 冻结、invalid Candidate 不回退、
  composite 拒绝研究、零 provider/零写入测试。

#### WP3 - API

- 只调用 WP2 query facade，不拼路径、不重算业务指标、不在 GET 更新 Catalog。
- 输出 OpenAPI golden、稳定分页/序列化、ETag/error mapping；app.py 只做最小注册。
- 完成证据：schema diff、API contract tests、path traversal、Catalog stale、并发窗口和
  304 测试。

#### WP4/WP5 - Web surfaces

- WP4 owner 负责全局 Snapshot Context 与三层视觉语义；WP5 owner 复用它，不新建状态
  定义。两者只通过冻结 API 并行。
- 完成证据：frontend build、浏览器 E2E、非颜色可访问性、固定 URL 恢复、730 点交互
  benchmark 和截图/录屏证据；截图不能代替自动化断言。

#### WP6 - Point-in-Time

- 输出 market_available 与 installation_observed 两条 truth table、coverage interval、
  revision validity 和 deterministic snapshot/view fingerprint。
- 完成证据：later revision 隔离、legacy PIT_NOT_PROVEN、future fact 不可见、同输入
  hash 相同。

#### WP7/WP8 - Research

- WP7 复用现有 H1 identity/current selection，是唯一 ResearchRun 写侧 owner；WP8 只读
  artifacts，并生成 deep link/命令。
- 完成证据：H1 identity 一一映射、clean-environment replay、failed run 无半成品、
  promote 追加 receipt、Observe future-label leakage 为零、Web/Notebook 结果一致。

#### WP9 - Rollout

- 不新增产品语义，只做兼容对账、feature flag、performance/error budgets 和回滚演练。
- 完成证据：真实数据只读 dual-read 报告、旧 Data inventory/Gaps/Coverage 仍可用、
  generation/route 分别回滚、无 facts 被删除、全套验证通过。

### 29.2 并行与集成边界

- WP0 合入后才允许 WP1 开始；WP1 合入后 WP2 开始。
- WP3 与 WP6 可在 WP2 contract 冻结后并行，但只能一个 owner 修改 domain/schema。
- WP4/WP5 可在 WP3 schema 冻结后并行，不能修改 backend schema 来迁就页面局部实现。
- WP7 必须建立在 WP6 和现有 crypto validation contract 上；WP8 不得先造假的
  ResearchRun JSON。
- Notebook prototype 可以提前验证图形，但不进入 WP 完成证据、不成为正式计算源。
- 每个 WP 开始前记录 base commit；合入前 rebase 集成分支并跑自身 focused tests、上游
  contract tests 和受影响的 compatibility suite。

## 30. V1 退出标准

V1 完成不是“页面上线”，而是以下合同全部成立。

### 30.1 每日观测

- 30 秒内能判断最新观测、正式基线、差距和用途；
- 当 observed_watermark > formal_watermark 时能看到 observed-only 尾部，同时不会误认
  其已发布；
- Formal stale 与 Candidate warning 同时可见。

### 30.2 证据追溯

- 任意已绘制 bar 可追到 provider/run/hash；
- 任意 quarantine/revision 可追到 reason 和证据；
- Candidate 未发布原因可以完整解释。

### 30.3 Point-in-Time

- 任意受支持 knowledge time 可按选定 knowledge_mode 确定重放；
- 后续修订不污染历史视图；
- PIT-unproven 明确可见。

### 30.4 研究

- H1 绑定不可变 snapshot；
- effect、CI、sample、fold 和 status 同时可见；
- Web 与 Notebook 复现一致；
- insufficient/rejected 是可接受结果。

### 30.5 安全与可靠性

- 所有浏览路径只读；
- integrity mismatch fail closed；
- Formal 发布/回滚合同不被 UI 破坏；
- Catalog 可重建；
- 完整 focused/contract/build/OpenSpec validation 通过。

最终验收问题：

> 给定任意一个受支持的历史时点，用户能否看到当时系统真正知道的数据、数据的
> 可信边界、当时可计算的指标和研究结论，并用相同快照、代码和配置完整复现？

如果答案不是明确的“可以”，本计划尚未完成。

## 31. 实施前最后检查

本计划已经确定产品和语义方向。实现者在 M0 只需冻结以下实现选择，不得重新打开
核心目标：

1. Snapshot Catalog 使用现有 trade DB 的 additive tables，还是独立可重建 SQLite；
2. React 主图继续扩展现有 SVG，还是引入新的图表实现；
3. Notebook 目录和 JupyterLab 的 dev dependency 归属；
4. content-addressed raw storage 在 V1 实施还是仅预留；
5. 旧 Data/Research 页面在兼容期的 deep link 和最终弃用时间；V1 不整页重定向；
6. 接受 additive attempt receipt，还是在 V1 降级 Latest Attempt 产品承诺。

这些选择可以根据维护成本调整，但不得改变：

- 正交 selector、knowledge/revision cut 与 layered comparison；
- 四时钟；
- Current/Candidate 与质量状态分离；
- purpose fitness；
- per-date evidence；
- immutable research snapshot；
- read-only/fail-closed；
- point-in-time 和可复现验收。
