# Forecast Research V1：从“数据可用”到“可验证预判”

日期：2026-07-17

状态：计划已落地，待实施评审

OpenSpec：`openspec/changes/build-forecast-research-v1/`

## 1. 结论先行

当前项目的数据采集和存储主链路已经能运行，但“能运行”不等于“可以拿来预测”。
现阶段还不能可信地回答未来 1/5/20 个交易日的涨跌、局部高低区间和风险，主要
阻塞在历史深度、时点一致性、复权/单位异常、验证样本量和预测留痕上。

V1 不直接做一个新的“买/卖”推荐器，而是先建立一条可审计的研究闭环：

```text
时点一致数据 -> 数据质量门禁 -> 基线模型 -> 防泄漏验证
     -> 多周期概率预测 -> 局部区间/风险 -> 预测快照 -> 实际结果 -> 持续校准
```

第一阶段聚焦 A 股日频，范围为“历史时点的沪深 300 成分 + 有生效日期的本地
关注列表”。BTC 继续作为独立研究线，后续可作为市场状态或风险证据接入，不与
本阶段的数据可用性和模型可信度混为一谈。

## 2. 当前基线与阻塞证据

以下是 2026-07-17 对本地数据和代码的只读检查快照，不代表以后自动保持有效：

| 项目 | 当前证据 | 判定 |
| --- | --- | --- |
| 数据主链路 | core data check 可通过，crypto 有单独 warning | 运维可用，研究状态需另判 |
| 常规因子 | 39 个因子，约 299.8 万行，但最大日期为 2026-03-23 | 已过期 |
| 事件特征 | 816,901 行、4,944 个 symbol，但只有 53 个日期，最大日期 2026-03-12 | 时间深度不足 |
| 事件标签 | 5d/20d 存在绝对值大于 100 的结果 | 复权、分母或单位待查 |
| 传播结果 | `actual_return_5d` 有大量极端值，最大值超过 100 万 | P0 数据缺陷 |
| 风险单位 | 训练使用 `-0.05`，一个评估路径使用 `-5.0` | P0 单位不一致 |
| 现有模型评估 | 评估日到 2026-03-23，只有 5 个 valid days | 不足以证明稳定性 |
| 推荐输出 | 最近快照 5,310 条中几乎全部为 `watch` | 不是可校准概率预测 |

因此数据状态分成两层：

- `operational_ready`：采集、落盘、查询链路是否能工作；
- `research_ready`：是否满足时点、单位、复权、历史深度、标签成熟和质量门禁。

只有第二层通过，模型才能训练；只有离线和线上观察均通过，预测才可以标记为
`validated`。

## 3. 用户最终能看到什么

每个标的分别给出 1d、5d、20d，而不是压成一个模糊结论：

| 输出 | 含义 |
| --- | --- |
| `p_up` | 上涨概率及校准状态 |
| `expected_excess_return` | 相对基准/行业的预期收益，内部统一小数单位 |
| `q10/q50/q90` | 收益区间，不用一个点估计伪装确定性 |
| `p_local_low_zone` | 未来窗口出现局部低位区间的概率 |
| `p_local_high_zone` | 未来窗口出现局部高位区间的概率 |
| `p_loss_5pct` | 跌幅超过 5% 的概率，阈值统一为 `-0.05` |
| `expected_mae` | 预期最大不利波动 |
| `volatility_regime` | 当前波动状态及是否超出训练分布 |
| `state/reason` | candidate/monitoring/validated/blocked 及具体原因 |

“局部最优”明确建模为未来窗口内的高/低区间概率，不承诺精确的顶、底日期和
价格。系统必须同时展示数据版本、模型版本、证据时点、置信/校准状态和未知状态。

## 4. 命令重新设计

日常只保留一层命令：

```bash
./trade research status
./trade research forecast 000001.SZ
./trade research rank --horizon 5d
./trade research risk 000001.SZ
./trade research outcomes --days 20
```

维护操作也保持短路径，但必须显式触发：

```bash
./trade research status --detail
./trade research build --dry-run
./trade research validate --dry-run
```

约束：

- `status/forecast/rank/risk/outcomes` 全部只读；
- 只读命令不隐式同步数据、建表、训练、切换模型或写 outcome；
- `build/validate` 先支持 `--dry-run`，打印范围、版本、检查项和写入计划；
- 保留原有 `./trade data ...` 和其他 CLI 行为，不做破坏性改名。

## 5. 设计边界

### 5.1 数据合同

- 内部收益率统一为小数：`0.05 == 5%`；展示层可以转百分比。
- 特征在时点 `t` 只能使用 `t` 当时已知的数据。
- 未来收益和局部区间标签单独存放，完整窗口成熟后才能进入训练/评估。
- 沪深 300 和关注列表都必须有历史生效日期，不能把今天的列表投射到过去。
- 数据集版本不可变，记录 as-of、来源、复权、单位、代码版本、行数和 hash。
- 异常值保留原始证据并隔离；未解释前不裁剪、不填充、不训练。

### 5.2 模型合同

- 先做历史比例、行业比例、动量、线性/逻辑回归等透明基线。
- 复杂模型必须用完全相同的数据、切分、成本和指标击败最佳基线。
- 采用 expanding walk-forward，并 purge 重叠标签、embargo 相邻样本。
- 预处理只在各训练折拟合，不允许用全量数据提前归一化或选特征。
- 事件、KG、belief、causal 和 recommendation 仅作为可选证据；未校准状态必须保留。

### 5.3 留痕合同

- `ForecastSnapshot` 保存预测当时看到的一切，之后不覆盖。
- `ForecastOutcome` 在标签成熟后追加，并关联确切快照和标签版本。
- 每次验证保存数据、模型、切分、成本、市场状态、代码和指标版本。
- 无法预测时返回明确的 `stale_data`、`unit_violation`、
  `insufficient_history` 等原因，不能用 0、0.5 或 `watch` 掩盖。

## 6. 分阶段执行计划

### M0：数据语义止血（2-3 个工作日）

目标：先证明现有收益率究竟哪里错，不带病训练。

- 复现并追踪事件标签、传播结果的极端值；
- 对齐 `-0.05` 和 `-5.0` 风险阈值；
- 建立 decimal-return 类型合同和 exact-once 转换；
- 建立异常隔离报告和 fixture UT。

退出条件：所有进入新研究链路的收益率都有明确单位；极端值有原始价格、复权、
分母和来源证据；未知原因数据全部被门禁阻断。

### M1：时点一致的数据集（3-5 个工作日）

目标：产出可重放的沪深 300 + watchlist 研究数据集。

- 接入历史成分、关注列表、交易日历和复权策略；
- 分离 point-in-time 特征和 matured labels；
- 建立版本 manifest、hash、质量报告和 active pointer；
- 先做小样本 dry-run、重放和 hash 对比，再扩到完整范围。

退出条件：至少 500 个交易日；时点泄漏、重复关键键、单位错误、未知历史成分均
为 0；状态命令无需扫描全量 parquet。

### M2：基线与验证框架（3-5 个工作日）

目标：先回答“是否比最简单的方法更好”。

- 建立历史/行业概率、动量、线性和逻辑回归基线；
- 完成 purged expanding walk-forward；
- 统一排名、方向、校准、区间、成本后收益、回撤和分层指标；
- 固化 candidate/monitoring/validated/rejected/blocked 状态机。

退出条件：至少 6 折、120 个不同样本外交易日；验证可重放；离线结果最多进入
`monitoring`，不能直接标为 `validated`。

### M3：涨跌与收益区间（4-5 个工作日）

目标：提供第一版可检查的 1d/5d/20d 概率预测。

- 输出 `p_up`、预期超额收益和 q10/q50/q90；
- 完成概率校准和基线对照；
- 实现 `status/forecast/rank`；
- 缺失、过期、未校准时 fail closed。

退出条件：所有 horizon 独立展示版本和状态；复杂候选必须在预注册指标上超过
最佳基线，否则保留 candidate/rejected。

### M4：局部区间与风险（3-5 个工作日）

目标：补齐局部高低区间、尾部风险和波动状态。

- 冻结局部区间标签的窗口、容差、反弹/反转阈值；
- 输出高/低区间概率、`p_loss_5pct`、MAE 和波动 regime；
- 使用 PR-AUC、Brier、校准、固定告警预算下 precision/recall、lead/lag；
- 实现 `risk` 和罕见事件的 unavailable 状态。

退出条件：不再用总体 accuracy 掩盖罕见事件失败；不提供“精确抄底/逃顶”语义。

### M5：影子运行与连续验证（至少 60 个交易日）

目标：让预测与实际结果闭环，建立可信度而不是只看回测。

- 每日写不可变快照，标签成熟后追加 outcome；
- 观测数据新鲜度、失败率、延迟、漂移、校准和成本后表现；
- 经过至少 60 个成熟交易日，人工审查后才允许 `validated`；
- 任何异常可回退 active dataset/model 指针，历史快照不删除。

第一版“可查看 candidate 预测”预计在 M0-M3 后获得，目标为 3-4 周；可信状态需要
完整的线上影子观察窗口，不能用加班压缩市场时间。

## 7. 初始质量门禁

门禁在看候选结果前版本化，后续调整必须新建 policy 版本并说明原因。

| 层次 | 初始门禁 |
| --- | --- |
| 数据 | >=500 个交易日；关键键重复=0；point-in-time 违规=0；单位违规=0；eligible 范围未知历史成分=0 |
| 切分 | >=6 folds；>=120 个不同 OOS 交易日；重叠标签已 purge；预处理 fold-local |
| 方向 | ROC-AUC、Brier/log loss 和校准相对最佳概率基线有改进，且多数折稳定 |
| 排名 | Rank IC 和成本后 top-decile 超额收益为正，并报告置信区间、行业和 regime 切片 |
| 区间 | q10/q50/q90 顺序合法，实际覆盖率在预注册容差内 |
| 局部/尾部 | PR-AUC、Brier、precision/recall@alert-budget 优于事件基准率；事件数不足则 unavailable |
| 推广 | 离线仅可到 monitoring；validated 需要 >=60 个成熟 live days、稳定校准和人工批准 |

不设置一个“神奇准确率”决定成败。任何模型都必须同时通过基线增益、校准、成本、
跨行业/市场状态稳定性和样本量门禁。

## 8. 验证与数据安全

- 所有 UT 使用临时目录、临时 DB 和小型 fixture；不修改真实 `data/`。
- 真实构建顺序固定为：backup/snapshot -> dry-run -> 小样本 -> hash/行数/schema
  核验 -> 全量版本 -> 显式激活。
- Python 变更运行聚焦 pytest 及
  `python -m compileall trade_py trade_web tests`。
- CLI 需要契约测试，证明只读命令没有隐藏写入。
- 性能 smoke 至少覆盖 manifest 状态查询、增量分区构建和沪深 300 批量预测。
- 严格执行 `openspec validate build-forecast-research-v1 --strict`。
- 不提交本地 parquet、模型文件、DB、cache 或真实研究数据。

## 9. 代码落点

| 责任 | 建议落点 |
| --- | --- |
| 数据集 manifest、时点装配、标签成熟、质量门禁 | `trade_py/research/dataset/` |
| target、baseline、walk-forward、校准、局部区间和风险 | `trade_py/research/forecast/` |
| 元数据与快照/outcome 持久化 | 现有 DB owner module 下的 additive models/repositories |
| 简洁命令 facade | `trade_py/cli/research.py` + `./trade` 路由 |
| 行为契约与 fixture | `tests/` 对应 research/dataset/forecast/cli 路径 |

不在 service 中直接写 SQL，不把所有逻辑继续堆进现有大文件，不在第一阶段改 Web
和 C++ engine。

## 10. 开始实施前的决定

实施第一轮前必须确认或以 fail-closed 方式解决以下四项：

1. 历史沪深 300 成分权威来源；
2. watchlist 的稳定 owner 和生效日期；
3. 基准、行业分类和交易成本版本；
4. 局部高低区间的初始窗口、容差、反弹/反转阈值。

随后按仓库规则创建新的实现 worktree，执行六角色 `review-this`，先解决 P0，再从
M0 开始逐个验证、提交；每 3-5 个提交 push，最终只以 squash commit 合回 master。
