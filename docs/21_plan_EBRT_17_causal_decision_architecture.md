# EBRT_17 — Causal Decision Architecture（Phase 1）

## Goal

在不破坏现有 `WorldState -> Decision -> Explanation` 链路的前提下，补上第一版可观测、可审计、可验证的因果决策结构：

```
ObservedFacts
  -> InferredState
  -> CausalFactors
  -> ConvictionVector
  -> HorizonExpectations
  -> ActionDecision
  -> ValidationOutcome
  -> RewardPunishmentRecord
```

## Scope（本轮）

- 新增显式 domain objects：
  - `ObservedFact`
  - `CausalFactor`
  - `ConvictionVector`
  - `HorizonExpectation`
  - `CausalLink`
  - `ValidationOutcome`
  - `RewardPunishmentRecord`
  - `CausalDecisionChain`
- 新增 `CausalService`
  - 从现有 `WorldState / ScenarioSummary / ActionDecision / TrustBreakdown` 构建机器可读因果链
  - 支持落库快照、ex-post 验证、reward/punishment 脚手架
- 新增 API：
  - `GET /api/causal/{symbol}`
  - `GET /api/causal/{symbol}/validation`
- `DecisionExplanation` 补充 `causal_chain`
- `TradeDB` 新增因果快照/验证/奖惩表

## Progress（2026-03-22）

### 已完成

- [x] `trade_py/decision/causal.py`：显式因果对象
- [x] `trade_py/services/causal_service.py`：因果链构建 + 验证 + reward/punishment scaffold
- [x] `trade_py/services/explanation_service.py`：在不破坏旧 explain contract 的情况下接入 `causal_chain`
- [x] `trade_web/backend/app.py`：新增 `/api/causal/{symbol}`、`/api/causal/{symbol}/validation`
- [x] `trade_py/db/trade_db.py`：新增
  - `causal_decision_snapshots`
  - `causal_validation_outcomes`
  - `causal_reward_punishment`
- [x] `tests/test_causal_service.py`：覆盖
  - 因果链构建
  - 快照落库
  - 验证结果
  - reward/punishment 输出
- [x] 兼容性验证：
  - `tests/test_explanation_service.py`
  - `tests/test_state_service.py`

### 当前语义边界

- 当前 `CausalLink / HorizonExpectation / RewardPunishmentRecord` 仍是 **heuristic causal scaffold**，不是已校准因果模型。
- `sector_conviction` 目前显式返回 `None`，并附带 note，原因是系统还没有正式 sector causal layer。
- 未来收益预期 (`expected_return`) 是基于现有 `score / scenario / uncertainty` 的保守启发式推断，并明确打上 `calibrated=false`。

### 本轮已验证

- `python -m compileall ...` 通过
- `uv run pytest tests/test_causal_service.py tests/test_explanation_service.py tests/test_state_service.py -q` 通过
- 本地服务实测通过：
  - `GET /api/causal/603083.SH`
  - `GET /api/explain/603083.SH`
  - `GET /api/causal/603083.SH/validation?horizons=1,5,20`
  - 历史样本：`GET /api/causal/603083.SH?date=2026-03-10&persist=true`
  - 历史验证：`GET /api/causal/603083.SH/validation?date=2026-03-10&horizons=1,5,20`
- 期间修复了一处真实接口问题：
  - validation 中单日波动率可能是 `NaN`，FastAPI 无法 JSON 序列化
  - 已统一在 causal object serializer 中转成 `null`

## Next

- 用真实本地服务验证 `/api/causal/*` 返回结构
- 如有必要，再补一个更细的 validation contract test
