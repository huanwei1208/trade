"""Decision report generator for the event propagation model.

Combines model predictions, SHAP explanations, and actor profiling
into a human-readable investment decision report.

The report structure follows plan Section 4.3D:
  - Return prediction with confidence interval
  - Risk rating and source decomposition
  - Key risk scenarios
  - Industry character labels
  - Position sizing suggestion

Usage:
    gen = ReportGenerator(model)
    report = gen.generate(event, symbol, features)
    print(gen.format_markdown(report))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


# ── Actor profiles ─────────────────────────────────────────────────────────────

ACTOR_PROFILES = {
    "trump_style": {
        "label":   "特朗普型（高波动/零和博弈/意外冲击）",
        "warning": "政策可能随时反复，建议单票仓位 <5%，设置隔夜止损。",
        "risk_multiplier": 1.4,
    },
    "dovish_central": {
        "label":   "鸽派央行型（数据驱动/渐进/提前引导）",
        "warning": "政策变化已提前预期，市场冲击相对温和，关注措辞变化。",
        "risk_multiplier": 0.8,
    },
    "hawkish_central": {
        "label":   "鹰派央行型（通胀优先/可能超预期加息）",
        "warning": "高估值成长股风险较大，关注货币政策转向信号。",
        "risk_multiplier": 1.1,
    },
    "china_policy": {
        "label":   "中国政策型（长期战略/可能突然纠偏）",
        "warning": "板块持仓需分散，不宜过度集中监管敏感领域。",
        "risk_multiplier": 1.0,
    },
    "elon_style": {
        "label":   "马斯克型（社媒驱动/信念投资/高波动）",
        "warning": "适合短期事件交易，不宜做长期基本面配置。",
        "risk_multiplier": 1.3,
    },
    "corporate_mgmt": {
        "label":   "普通企业管理层",
        "warning": "按正常基本面分析评估。",
        "risk_multiplier": 1.0,
    },
    "regulator": {
        "label":   "监管机构",
        "warning": "政策方向明确后再配置，不确定期回避集中持仓。",
        "risk_multiplier": 1.1,
    },
    "unknown": {
        "label":   "未知行为者",
        "warning": "信息不完整，采用保守仓位。",
        "risk_multiplier": 1.1,
    },
}


# ── Sector profiles ────────────────────────────────────────────────────────────

SECTOR_PROFILES = {
    # SW sector name → (character, suggestion)
    "SW_FoodBeverage":     ("防御型",       "熊市保值、高确定性低弹性，底仓配置"),
    "SW_Medicine":         ("防御型",       "熊市保值，关注集采政策风险"),
    "SW_Utilities":        ("防御型",       "高股息价值股，利率敏感"),
    "SW_Banking":          ("防御+顺周期",  "关注信用周期，降息环境受益"),
    "SW_NonFerrousMetal":  ("顺周期型",     "经济上行放大收益，周期底部布局"),
    "SW_Steel":            ("顺周期型",     "地产/基建联动，PPI周期"),
    "SW_Coal":             ("顺周期+红利",  "高股息，能源安全政策受益"),
    "SW_Petroleum":        ("顺周期+红利",  "油价联动，注意新能源替代长期压力"),
    "SW_Computer":         ("主题型",       "政策催化驱动，快进快出"),
    "SW_Electronics":      ("主题型",       "半导体周期+政策，弹性大"),
    "SW_ElectricalEquipment": ("主题型",    "新能源赛道，政策敏感"),
    "SW_Defense":          ("主题型",       "军工订单周期，适合事件驱动"),
    "SW_Auto":             ("顺周期+主题",  "新能源车景气，供应链联动"),
    "SW_RealEstate":       ("政策敏感型",   "政策松紧决定命运，不确定期回避"),
    "SW_Construction":     ("政策敏感型",   "基建/地产双驱动，政策窗口把握"),
    "SW_Media":            ("政策敏感型",   "内容监管风险，谨慎集中持仓"),
}

_DEFAULT_SECTOR_PROFILE = ("市场型",        "按正常量化因子评估")


# ── Report dataclass ────────────────────────────────────────────────────────────

@dataclass
class RiskScenario:
    probability: float     # estimated probability [0,1]
    trigger:     str       # trigger condition description
    impact:      str       # expected price impact description
    signal:      str       # early warning signal to monitor
    action:      str       # recommended action


@dataclass
class DecisionReport:
    """Full decision report for one (event, symbol) pair."""
    # Identity
    event_id:      str
    event_type:    str
    symbol:        str
    sector:        str
    report_date:   str

    # Return forecasts
    return_5d:     Optional[float] = None   # excess return estimate
    return_20d:    Optional[float] = None
    return_60d:    Optional[float] = None

    # Risk metrics
    prob_loss_5pct:    Optional[float] = None   # P(drawdown > 5% in 20d)
    prob_drawdown_20:  Optional[float] = None   # P(drawdown > 20% in 60d)
    risk_score:        float = 5.0              # 1-10 scale
    risk_rating:       str = "中等风险"

    # Explanation (SHAP)
    shap_top_positive: list[tuple[str, float]] = field(default_factory=list)
    shap_top_negative: list[tuple[str, float]] = field(default_factory=list)

    # Scenarios
    scenarios: list[RiskScenario] = field(default_factory=list)

    # Labels
    actor_label:  str = ""
    actor_warning: str = ""
    sector_character: str = ""
    sector_suggestion: str = ""

    # Position suggestion
    max_position_pct: float = 5.0   # suggested max position as % of portfolio
    holding_days:     int = 20


def _risk_rating(score: float) -> str:
    if score <= 3:   return "低风险"
    if score <= 5:   return "中等风险"
    if score <= 7:   return "中高风险"
    return "高风险"


def _risk_score(pred: dict[str, float], actor_risk: float) -> float:
    """Compute composite risk score [1,10] from predictions and actor profile."""
    base = 5.0
    # Volatility contributes (if feature was passed through)
    p_loss = pred.get("loss_5pct_20d", 0.25)
    p_dd   = pred.get("drawdown_20pct", 0.10)
    risk_from_model = p_loss * 3.0 + p_dd * 4.0  # 0–7 scale
    # Actor adjustment
    score = base + (risk_from_model - 3.5) + (actor_risk - 0.5) * 2.0
    return float(max(1.0, min(10.0, score)))


# ── ReportGenerator ────────────────────────────────────────────────────────────

class ReportGenerator:
    """Generates decision reports from model predictions.

    Args:
        model: Trained PropagationModel instance.
    """

    def __init__(self, model) -> None:
        self._model = model

    def generate(self,
                 event,
                 symbol: str,
                 features: dict[str, float],
                 sector: str = "",
                 explain_target: str = "return_20d") -> DecisionReport:
        """Generate a full decision report.

        Args:
            event: HistoricalEvent
            symbol: Stock code
            features: Feature dict (from FeatureBuilder)
            sector: SW sector string e.g. "SW_Electronics"
            explain_target: Which model to use for SHAP explanations

        Returns:
            DecisionReport dataclass
        """
        # Run predictions
        try:
            preds = self._model.predict(features)
        except Exception as exc:
            logger.error("Prediction failed: %s", exc)
            preds = {}

        # SHAP explanation
        shap_contribs: dict[str, float] = {}
        if explain_target in preds:
            try:
                shap_contribs = self._model.explain(features, explain_target)
            except Exception as exc:
                logger.warning("SHAP explanation failed: %s", exc)

        # Sort SHAP contributions
        if shap_contribs:
            sorted_sh = sorted(shap_contribs.items(), key=lambda x: x[1], reverse=True)
            top_pos = [(k, round(v, 4)) for k, v in sorted_sh if v > 0][:5]
            top_neg = [(k, round(v, 4)) for k, v in sorted_sh if v < 0][:5]
        else:
            top_pos = top_neg = []

        # Actor profile
        actor_key = getattr(event, "actor_type", None)
        try:
            actor_key_str = str(actor_key.value)  # type: ignore[union-attr]
        except AttributeError:
            actor_key_str = str(actor_key) if actor_key is not None else "unknown"
        actor_prof = ACTOR_PROFILES.get(actor_key_str, ACTOR_PROFILES["unknown"])
        actor_risk = float(getattr(event, "actor_risk_score", 0.4))

        # Risk score
        rscore = _risk_score(preds, actor_risk)
        rscore *= actor_prof["risk_multiplier"]
        rscore = max(1.0, min(10.0, rscore))

        # Sector profile
        sec_char, sec_sug = SECTOR_PROFILES.get(sector, _DEFAULT_SECTOR_PROFILE)

        # Position suggestion based on risk
        pos_pct = max(1.0, 8.0 - rscore)

        # Generate scenarios (rule-based)
        scenarios = self._build_scenarios(event, preds, sector)

        return DecisionReport(
            event_id=event.event_id,
            event_type=getattr(event.event_type, "value", str(event.event_type)),
            symbol=symbol,
            sector=sector,
            report_date=event.event_date.isoformat(),
            return_5d=preds.get("return_5d"),
            return_20d=preds.get("return_20d"),
            return_60d=preds.get("return_60d"),
            prob_loss_5pct=preds.get("loss_5pct_20d"),
            prob_drawdown_20=preds.get("drawdown_20pct"),
            risk_score=round(rscore, 1),
            risk_rating=_risk_rating(rscore),
            shap_top_positive=top_pos,
            shap_top_negative=top_neg,
            scenarios=scenarios,
            actor_label=actor_prof["label"],
            actor_warning=actor_prof["warning"],
            sector_character=sec_char,
            sector_suggestion=sec_sug,
            max_position_pct=round(pos_pct, 1),
            holding_days=20 if rscore <= 5 else 10,
        )

    @staticmethod
    def _build_scenarios(event, preds: dict, sector: str = "") -> list[RiskScenario]:  # noqa: ARG004
        """Build 2-3 risk scenarios based on event type and predictions."""
        scenarios = []
        event_type = getattr(event.event_type, "value", str(event.event_type))

        # Scenario templates by event type
        templates = {
            "semiconductor_policy": [
                RiskScenario(
                    probability=0.25,
                    trigger="中美外交缓和，相关限制措施减轻",
                    impact="相关板块快速回调 -15%~-25%",
                    signal="外交部措辞软化；双边贸易谈判传闻",
                    action="出现信号则减仓 50%",
                ),
                RiskScenario(
                    probability=0.10,
                    trigger="国内经济超预期放缓，需求端下行",
                    impact="半导体周期下行，板块 -20%~-35%",
                    signal="PMI 连续 2 月 <49；消费电子出货量骤降",
                    action="触发止损，持仓期缩至 1-2 周",
                ),
            ],
            "new_energy_policy": [
                RiskScenario(
                    probability=0.20,
                    trigger="补贴政策退坡快于预期",
                    impact="新能源产业链估值收缩 -15%~-20%",
                    signal="政策文件发布；龙头企业降价信号",
                    action="逢反弹减仓，不追高",
                ),
            ],
            "geopolitical_risk": [
                RiskScenario(
                    probability=0.30,
                    trigger="地缘冲突意外缓和（谈判达成）",
                    impact="国防/稀土等概念股快速回调",
                    signal="外交部署声明；停火协议",
                    action="事件驱动仓位快进快出",
                ),
            ],
            "rate_cut": [
                RiskScenario(
                    probability=0.15,
                    trigger="通胀超预期反弹，降息空间收窄",
                    impact="市场短期调整 -5%~-10%",
                    signal="CPI 连续超预期；央行措辞收紧",
                    action="降低杠杆，回调时再加仓",
                ),
            ],
        }

        # Get event-specific scenarios, fallback to generic
        event_scenarios = templates.get(event_type, [])

        # Generic scenario always included
        loss_prob = preds.get("loss_5pct_20d", 0.2)
        generic = RiskScenario(
            probability=round(loss_prob, 2),
            trigger="宏观环境超预期恶化",
            impact="系统性风险导致个股 -10%~-15%",
            signal="大盘指数连续 3 日下跌 >2%；成交量萎缩",
            action="触发则止损退出，等待市场企稳",
        )

        scenarios = event_scenarios[:2] + [generic]
        return scenarios[:3]

    def format_markdown(self, report: DecisionReport) -> str:
        """Format a DecisionReport as Markdown text."""
        r = report

        def pct(v: Optional[float], decimals: int = 1) -> str:
            if v is None:
                return "N/A"
            return f"{v * 100:+.{decimals}f}%"

        def prob(v: Optional[float]) -> str:
            if v is None:
                return "N/A"
            return f"{v * 100:.0f}%"

        lines = [
            f"## 投资决策报告：{r.symbol}  ({r.sector})",
            f"**事件类型**：{r.event_type}    **日期**：{r.report_date}",
            "",
            "### 收益预测",
            f"| 时间窗口 | 超额收益预测 |",
            f"|---------|------------|",
            f"| 5  日   | {pct(r.return_5d)}  |",
            f"| 20 日   | {pct(r.return_20d)} |",
            f"| 60 日   | {pct(r.return_60d)} |",
            "",
            f"### 风险评级：{r.risk_rating}（{r.risk_score}/10）",
            "",
        ]

        # Probability stats
        lines += [
            "**风险概率**",
            f"- 20日内下跌 >5% 的概率：{prob(r.prob_loss_5pct)}",
            f"- 60日内出现 20% 回撤的概率：{prob(r.prob_drawdown_20)}",
            "",
        ]

        # SHAP explanation
        if r.shap_top_positive or r.shap_top_negative:
            lines.append("### 预测主要驱动因素（SHAP）")
            for name, val in r.shap_top_positive:
                lines.append(f"  ✅ `{name}`  {val:+.4f}")
            for name, val in r.shap_top_negative:
                lines.append(f"  ⚠️ `{name}`  {val:+.4f}")
            lines.append("")

        # Scenarios
        if r.scenarios:
            lines.append("### 主要风险场景")
            for i, sc in enumerate(r.scenarios, 1):
                lines += [
                    f"**场景 {i}（概率 {sc.probability*100:.0f}%）**",
                    f"- 触发条件：{sc.trigger}",
                    f"- 预期影响：{sc.impact}",
                    f"- 预警信号：{sc.signal}",
                    f"- 建议操作：{sc.action}",
                    "",
                ]

        # Actor & sector profile
        lines += [
            "### 行为者与板块画像",
            f"**行为者类型**：{r.actor_label}",
            f"> {r.actor_warning}",
            "",
            f"**板块特征**：{r.sector_character}",
            f"> {r.sector_suggestion}",
            "",
        ]

        # Position suggestion
        lines += [
            "### 仓位建议",
            f"- 建议最大单票仓位：**{r.max_position_pct}%**",
            f"- 建议持仓时间：约 **{r.holding_days}** 个交易日",
            "",
            "---",
            f"*报告生成于 {date.today().isoformat()}*",
        ]

        return "\n".join(lines)
