"""LLM client factory for sentiment analysis."""

from __future__ import annotations

from trade_py.intelligence.clients.anthropic import AnthropicClient
from trade_py.intelligence.clients.base import (
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    SentimentResult,
    content_hash,
    parse_result,
)
from trade_py.intelligence.clients.ollama import OllamaClient

__all__ = [
    "SentimentResult", "content_hash", "parse_result",
    "SYSTEM_PROMPT", "USER_TEMPLATE",
    "AnthropicClient", "OllamaClient", "create_client",
]


def create_client(provider: str = "anthropic", **kwargs):
    """Factory: returns AnthropicClient or OllamaClient based on provider."""
    registry = {
        "anthropic": AnthropicClient,
        "ollama": OllamaClient,
    }
    client_cls = registry.get(provider)
    if client_cls is not None:
        return client_cls.from_factory_kwargs(**kwargs)
    raise ValueError(f"Unknown provider: {provider!r}. Use 'anthropic' or 'ollama'.")
