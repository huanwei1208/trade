"""Devil's advocate — adversarial counter-argument generator.

Generates counter-arguments to a bullish trading thesis using Claude Haiku
(when available) or falling back to a rule-based approach.

Usage:
    from trade_py.analysis.devil_advocate import DevilAdvocate
    da = DevilAdvocate(api_key="sk-...")  # or set ANTHROPIC_API_KEY
    result = da.challenge("600036.SH", thesis="招行技术形态突破，量价配合良好，看涨")
    print(result["devil_argument"])
    # "虽然技术形态向好，但需要关注以下风险：..."
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── Rule-based counter-arguments by theme ─────────────────────────────────────
_COUNTER_TEMPLATES = [
    "技术突破可能是机构诱多，散户跟进后主力出货。",
    "量价配合仅反映短期情绪，不代表基本面改善。",
    "当前板块整体高估，回调压力不可忽视。",
    "利率环境对估值形成压制，高PE标的面临重估。",
    "历史高点附近成交密集，套牢盘压力较大。",
    "融资余额高位，杠杆资金对下跌的放大效应需警惕。",
    "政策不确定性仍在，监管周期可能提前结束行情。",
    "外资持续流出信号可能预示更大级别的结构调整。",
    "竞争格局恶化或行业供给过剩可能侵蚀盈利空间。",
    "如果大盘指数走弱，个股α难以抵御系统性风险。",
]

_PROMPT_TEMPLATE = """你是一位经验丰富的空头分析师，擅长发现多头论据中的漏洞。

以下是关于 {symbol} 的看涨论据：
{thesis}

请以批判性视角，生成 3 条简洁有力的反驳论点（每条 1-2 句话），
重点关注技术面的虚假突破风险、基本面隐患、宏观压力或资金面风险。
不要重复看涨论据中已提及的内容。
每条以 "- " 开头，不要加编号。"""


@dataclass
class DevilResult:
    symbol: str
    thesis: str
    devil_argument: str    # formatted counter-arguments
    points: list[str]      # individual bullet points
    method: str            # "llm" or "rule_based"


class DevilAdvocate:
    """Generate adversarial counter-arguments for a trading thesis.

    Falls back to rule-based templates when the Anthropic API is unavailable.
    """

    def __init__(self,
                 api_key: Optional[str] = None,
                 model: str = "claude-haiku-4-5-20251001") -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model

    # ── LLM path ──────────────────────────────────────────────────────────────

    def _llm_challenge(self, symbol: str, thesis: str) -> Optional[list[str]]:
        """Try to generate counter-arguments via Claude Haiku.

        Returns list of bullet strings, or None on failure.
        """
        if not self._api_key:
            return None
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)
            prompt = _PROMPT_TEMPLATE.format(symbol=symbol, thesis=thesis)
            msg = client.messages.create(
                model=self._model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            points = [line.lstrip("- ").strip()
                      for line in text.splitlines()
                      if line.strip().startswith("-")]
            return points if points else [text]
        except Exception as exc:
            logger.debug("DevilAdvocate LLM failed: %s", exc)
            return None

    # ── Rule-based path ───────────────────────────────────────────────────────

    @staticmethod
    def _rule_based(n: int = 3) -> list[str]:
        """Return N random counter-argument templates."""
        import random
        population = list(_COUNTER_TEMPLATES)
        random.shuffle(population)
        return population[:min(n, len(population))]

    # ── Public API ────────────────────────────────────────────────────────────

    def challenge(self, symbol: str, thesis: str,
                  n_points: int = 3) -> DevilResult:
        """Generate adversarial counter-arguments for `thesis`.

        Args:
            symbol:   Stock code e.g. "600036.SH"
            thesis:   The bullish narrative to challenge
            n_points: Number of counter-argument bullets to produce

        Returns:
            DevilResult with formatted counter-arguments
        """
        points = self._llm_challenge(symbol, thesis)
        method = "llm"
        if not points:
            points = self._rule_based(n_points)
            method = "rule_based"

        # Trim to requested count
        points = points[:n_points]
        devil_arg = "\n".join(f"- {p}" for p in points)

        return DevilResult(
            symbol=symbol,
            thesis=thesis,
            devil_argument=devil_arg,
            points=points,
            method=method,
        )
