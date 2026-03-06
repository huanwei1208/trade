"""Ollama local LLM client for news sentiment analysis."""

from __future__ import annotations

import json
import logging
import os
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from trade_py.intelligence.clients.base import BaseLLMClient, SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class OllamaClient(BaseLLMClient):
    """Calls a local Ollama server for offline inference."""

    MODEL = "qwen2.5:7b-instruct"

    @classmethod
    def factory_fields(cls) -> set[str]:
        return {"model", "base_url"}

    def __init__(self, model: Optional[str] = None,
                 base_url: Optional[str] = None) -> None:
        super().__init__()
        self.model = model or os.environ.get("OLLAMA_MODEL", self.MODEL)
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        logger.info("OllamaClient model=%s base_url=%s", self.model, self.base_url)
        self._ensure_model_ready()

    def _ensure_model_ready(self) -> None:
        req = Request(
            f"{self.base_url}/api/show",
            data=json.dumps({"model": self.model}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=8) as resp:
                if getattr(resp, "status", 200) >= 400:
                    raise ValueError(f"Ollama model check failed. model={self.model}")
        except HTTPError as e:
            if e.code == 404:
                raise ValueError(
                    f"Ollama model not found: {self.model}. Run: ollama pull {self.model}"
                ) from e
            raise ValueError(f"Ollama API error HTTP {e.code}") from e
        except URLError as e:
            raise ValueError(
                f"Ollama not reachable at {self.base_url}. Run: ollama serve"
            ) from e
        except TimeoutError as e:
            raise ValueError(f"Ollama timeout at {self.base_url}") from e

    def _call_llm(self, prompt: str) -> tuple[str, int, int]:
        payload = {
            "model": self.model,
            "prompt": f"{SYSTEM_PROMPT}\n\n{prompt}",
            "stream": False,
            "format": "json",
        }
        req = Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        raw = str(body.get("response", "")).strip()
        return raw, 0, 0
