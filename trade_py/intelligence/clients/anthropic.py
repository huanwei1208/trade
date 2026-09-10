"""Anthropic Claude API client for news sentiment analysis."""

from __future__ import annotations

import logging
import os

from trade_py.intelligence.clients.base import BaseLLMClient

logger = logging.getLogger(__name__)


class AnthropicClient(BaseLLMClient):
    """Calls Claude via the Anthropic Messages API."""

    # MODEL = "claude-sonnet-5"
    MODEL = "claude-haiku-4-5"

    @classmethod
    def factory_fields(cls) -> set[str]:
        return {"api_key", "model", "market"}

    def __init__(self, api_key: str | None = None,
                 model: str | None = None,
                 market: str | None = None) -> None:
        super().__init__(market=market)
        self.model = model or self.MODEL
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key."
            )
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=key)
        except ImportError:
            raise ImportError("Install anthropic: pip install anthropic>=0.40.0")
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    def _call_llm(self, prompt: str) -> tuple[str, int, int]:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.MAX_TOKENS,
            # Sonnet 5 runs adaptive thinking when the field is omitted; this is a
            # fixed-schema extraction task, so disable it for cost and latency.
            thinking={"type": "disabled"},
            system=self.system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = next(
            (block.text for block in response.content if block.type == "text"), ""
        ).strip()
        in_tok = response.usage.input_tokens
        out_tok = response.usage.output_tokens
        self._total_input_tokens += in_tok
        self._total_output_tokens += out_tok
        return raw, in_tok, out_tok

    # USD per 1M tokens (input, output), matched by model-id prefix.
    _PRICING = {
        "claude-haiku": (1.00, 5.00),
        "claude-sonnet": (3.00, 15.00),
        "claude-opus": (5.00, 25.00),
    }

    @property
    def estimated_cost(self) -> float:
        in_price, out_price = next(
            (p for prefix, p in self._PRICING.items() if self.model.startswith(prefix)),
            (3.00, 15.00),  # default to Sonnet pricing for unknown ids
        )
        return (self._total_input_tokens * in_price + self._total_output_tokens * out_price) / 1_000_000

    @property
    def token_usage(self) -> dict:
        return {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "estimated_cost_usd": self.estimated_cost,
        }
