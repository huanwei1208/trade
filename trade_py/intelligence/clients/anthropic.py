"""Anthropic Claude API client for news sentiment analysis."""

from __future__ import annotations

import logging
import os
from typing import Optional

from trade_py.intelligence.clients.base import (
    BaseLLMClient, SYSTEM_PROMPT, SentimentResult,
)

logger = logging.getLogger(__name__)


class AnthropicClient(BaseLLMClient):
    """Calls Claude via the Anthropic Messages API."""

    MODEL = "claude-sonnet-5"

    @classmethod
    def factory_fields(cls) -> set[str]:
        return {"api_key", "model"}

    def __init__(self, api_key: Optional[str] = None,
                 model: Optional[str] = None) -> None:
        super().__init__()
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
            system=SYSTEM_PROMPT,
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

    @property
    def estimated_cost(self) -> float:
        # Claude Sonnet 5: $3.00/M input, $15.00/M output
        return (self._total_input_tokens * 3.00 + self._total_output_tokens * 15.00) / 1_000_000

    @property
    def token_usage(self) -> dict:
        return {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "estimated_cost_usd": self.estimated_cost,
        }
