"""Multi-persona analyst debate system.

Orchestrates Bull / Bear / Neutral personas to challenge a trading idea from
three independent viewpoints.  Each persona uses Claude Haiku (with API key)
or falls back to rule-based templates.

Usage:
    from trade_py.analysis.multi_persona import MultiPersonaDebate
    debate = MultiPersonaDebate(api_key="sk-...")
    result = debate.run("600036.SH", context="技术突破，量价配合，板块轮动")
    for r in result.rounds:
        print(f"[{r.persona}] {r.argument}")
    print("裁判:", result.arbiter_summary)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Templates ──────────────────────────────────────────────────────────────────

_BULL_TEMPLATES = [
    "量能放大配合价格突破，说明主力资金积极参与，上涨动能充足。",
    "基本面改善叠加估值合理，长期配置价值显现，机构增持迹象明显。",
    "板块政策支持，行业景气度持续提升，公司在细分领域具备领先优势。",
    "技术面看多头排列，均线系统扭转向上，回调即为买入良机。",
    "北向资金连续净买入，外资对A股配置持续增加，流动性环境偏宽松。",
]

_BEAR_TEMPLATES = [
    "估值已处于历史高位分位，安全边际不足，任何利空都可能触发大幅回调。",
    "成交量虽放大但主要来自散户跟风，机构实际减仓迹象不可忽视。",
    "宏观层面流动性边际收紧，高Beta股将承受更大回撤风险。",
    "竞争加剧压缩行业利润空间，盈利预测存在大幅下调风险。",
    "技术面上方历史套牢盘密集，短期突破可持续性存疑。",
]

_NEUTRAL_TEMPLATES = [
    "多空双方论据均有道理，当前最佳策略是分批建仓，严格设置止损。",
    "基本面改善方向明确，但短期催化剂尚不充分，等待确认信号更稳妥。",
    "行业景气向上但个股分化加剧，精选个股比追涨更重要。",
    "关注量能是否能持续放大，以及大盘环境是否配合，再决定仓位。",
    "建议以小仓位试多，用实际走势验证判断，而非全仓押注。",
]

_ARBITER_TEMPLATES = [
    "综合多空分析，当前风险收益比尚可但不算突出，轻仓参与、严控风险为宜。",
    "多方动量与空方估值压力并存，建议等待更清晰的价量确认后再加仓。",
    "三方观点分歧较大，显示该标的不确定性较高，谨慎为上。",
    "多方基本面逻辑占优，空方提示的风险属于小概率但高影响事件，建议持股但保留止损位。",
]

_PERSONA_PROMPTS = {
    "Bull": (
        "你是一位乐观的多头分析师，擅长从正面挖掘投资机会。"
        "针对 {symbol} 的分析背景：\n{context}\n"
        "给出 2 条支持做多的有力论点（每条 1-2 句，以'- '开头）。"
    ),
    "Bear": (
        "你是一位谨慎的空头分析师，擅长识别下行风险。"
        "针对 {symbol} 的分析背景：\n{context}\n"
        "给出 2 条反对做多的风险提示（每条 1-2 句，以'- '开头）。"
    ),
    "Neutral": (
        "你是一位客观中立的量化研究员，擅长平衡多空观点给出操作建议。"
        "针对 {symbol}，多头认为{context}；结合潜在风险，"
        "给出 2 条中立的操作建议（每条 1-2 句，以'- '开头）。"
    ),
    "Arbiter": (
        "你是首席投资官，综合了多头、空头和中性三方意见后给出最终裁决。"
        "关于 {symbol}，三方观点如下：\n{debate_so_far}\n"
        "用 2-3 句话给出综合判断和操作建议。"
    ),
}


@dataclass
class PersonaRound:
    persona: str    # "Bull" | "Bear" | "Neutral"
    argument: str
    method: str     # "llm" | "rule_based"


@dataclass
class DebateResult:
    symbol: str
    context: str
    rounds: list[PersonaRound] = field(default_factory=list)
    arbiter_summary: str = ""


class MultiPersonaDebate:
    """Run a structured three-persona debate about a stock.

    Personas:
        Bull    — presents supporting arguments
        Bear    — presents opposing risks
        Neutral — offers balanced operational advice
        Arbiter — synthesises the debate into a final recommendation
    """

    def __init__(self,
                 api_key: Optional[str] = None,
                 model: str = "claude-haiku-4-5-20251001") -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model

    # ── LLM helper ────────────────────────────────────────────────────────────

    def _llm_respond(self, prompt: str) -> Optional[str]:
        if not self._api_key:
            return None
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)
            msg = client.messages.create(
                model=self._model,
                max_tokens=250,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text.strip()
        except Exception as exc:
            logger.debug("MultiPersona LLM failed: %s", exc)
            return None

    @staticmethod
    def _parse_bullets(text: str) -> list[str]:
        return [line.lstrip("- ").strip()
                for line in text.splitlines()
                if line.strip().startswith("-")]

    # ── Rule-based responses ──────────────────────────────────────────────────

    @staticmethod
    def _rule_response(persona: str) -> str:
        import random
        if persona == "Bull":
            pts = random.sample(_BULL_TEMPLATES, min(2, len(_BULL_TEMPLATES)))
        elif persona == "Bear":
            pts = random.sample(_BEAR_TEMPLATES, min(2, len(_BEAR_TEMPLATES)))
        elif persona == "Neutral":
            pts = random.sample(_NEUTRAL_TEMPLATES, min(2, len(_NEUTRAL_TEMPLATES)))
        else:
            pts = [random.choice(_ARBITER_TEMPLATES)]
        return "\n".join(f"- {p}" for p in pts)

    # ── Persona runner ────────────────────────────────────────────────────────

    def _run_persona(self, persona: str, symbol: str,
                     context: str, debate_so_far: str = "") -> PersonaRound:
        prompt_tpl = _PERSONA_PROMPTS[persona]
        prompt = prompt_tpl.format(symbol=symbol, context=context,
                                   debate_so_far=debate_so_far)
        response = self._llm_respond(prompt)
        method = "llm"
        if not response:
            response = self._rule_response(persona)
            method = "rule_based"

        # Clean up bullet formatting
        bullets = self._parse_bullets(response)
        if not bullets:
            bullets = [response]
        argument = "\n".join(f"- {b}" for b in bullets)

        return PersonaRound(persona=persona, argument=argument, method=method)

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, symbol: str, context: str) -> DebateResult:
        """Run the full multi-persona debate.

        Args:
            symbol:  Stock code e.g. "600036.SH"
            context: Analysis context / thesis to debate

        Returns:
            DebateResult with three persona rounds and an arbiter summary
        """
        result = DebateResult(symbol=symbol, context=context)

        for persona in ("Bull", "Bear", "Neutral"):
            round_ = self._run_persona(persona, symbol, context)
            result.rounds.append(round_)

        # Arbiter synthesises all three
        debate_text = "\n\n".join(
            f"[{r.persona}]\n{r.argument}" for r in result.rounds
        )
        arbiter = self._run_persona("Arbiter", symbol, context,
                                    debate_so_far=debate_text)
        result.arbiter_summary = arbiter.argument.lstrip("- ")

        return result

    def to_markdown(self, result: DebateResult) -> str:
        """Render a DebateResult as a Markdown string."""
        lines = [f"## {result.symbol} — 多角色辩论\n",
                 f"**背景：** {result.context}\n"]
        icons = {"Bull": "🐂 多头", "Bear": "🐻 空头", "Neutral": "⚖️ 中性"}
        for r in result.rounds:
            label = icons.get(r.persona, r.persona)
            lines.append(f"### {label}\n{r.argument}\n")
        lines.append(f"### 🎯 裁判综合\n{result.arbiter_summary}\n")
        return "\n".join(lines)
