"""Shared types, prompts, and utilities for LLM clients."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是专业的A股市场金融情感分析助手。
分析新闻文本，提取结构化的情感和事件信息，只返回JSON，不要其他内容。"""

USER_TEMPLATE = """分析以下A股市场新闻：

标题：{title}
内容：{text}

返回JSON（只返回JSON对象，不要markdown）：
{{
  "sentiment_score": <float -1.0到1.0，-1.0极负面，1.0极正面>,
  "sentiment_label": <"positive"|"neutral"|"negative">,
  "event_type": <"policy"|"earnings"|"expansion"|"acquisition"|"regulation"|"macro"|"personnel"|"product"|"other">,
  "event_magnitude": <float 0.0到1.0，0.0微小影响，1.0重大影响>,
  "affected_sectors": <受影响行业列表，如["半导体","新能源"]>,
  "key_entities": <关键实体，公司/人物/政策名称列表>,
  "summary": <30字以内中文摘要>,
  "confidence": <float 0.0到1.0，分析置信度>,
  "policy_signal": <true|false，是否含监管/政策信号>,
  "market_impact_scope": <"individual"|"sector"|"market"，影响范围：个股/行业/全市场>,
  "time_sensitivity": <"immediate"|"short_term"|"medium_long"，时效性：即时/短期/中长期>,
  "event_chain": <与此事件相关的历史事件类型，如"rate_cut_cycle"|"trade_war"|"regulatory_crackdown"|""，无关联时留空>
}}"""


@dataclass
class SentimentResult:
    sentiment_score: float = 0.0
    sentiment_label: str = "neutral"
    event_type: str = "other"
    event_magnitude: float = 0.0
    affected_sectors: list = None
    key_entities: list = None
    summary: str = ""
    confidence: float = 0.5
    policy_signal: bool = False
    market_impact_scope: str = "individual"
    time_sensitivity: str = "short_term"
    event_chain: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self):
        if self.affected_sectors is None:
            self.affected_sectors = []
        if self.key_entities is None:
            self.key_entities = []

    def to_dict(self) -> dict:
        return asdict(self)


def content_hash(title: str, text: str) -> str:
    """SHA-256 dedup key for an article."""
    return hashlib.sha256(f"{title}\n{text}".encode("utf-8")).hexdigest()[:16]


def parse_result(data: dict, model: str,
                 input_tokens: int = 0, output_tokens: int = 0) -> SentimentResult:
    """Parse LLM JSON response dict into a SentimentResult."""
    scope = str(data.get("market_impact_scope", "individual"))
    if scope not in {"individual", "sector", "market"}:
        scope = "individual"
    sensitivity = str(data.get("time_sensitivity", "short_term"))
    if sensitivity not in {"immediate", "short_term", "medium_long"}:
        sensitivity = "short_term"
    return SentimentResult(
        sentiment_score=float(data.get("sentiment_score", 0.0)),
        sentiment_label=str(data.get("sentiment_label", "neutral")),
        event_type=str(data.get("event_type", "other")),
        event_magnitude=float(data.get("event_magnitude", 0.0)),
        affected_sectors=list(data.get("affected_sectors", [])),
        key_entities=list(data.get("key_entities", [])),
        summary=str(data.get("summary", "")),
        confidence=float(data.get("confidence", 0.5)),
        policy_signal=bool(data.get("policy_signal", False)),
        market_impact_scope=scope,
        time_sensitivity=sensitivity,
        event_chain=str(data.get("event_chain", "")),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class BaseLLMClient:
    """Shared analyze/analyze_batch logic for LLM providers."""

    MAX_TOKENS = 512
    RATE_LIMIT_DELAY = 0.5
    MAX_RETRIES = 3

    def __init__(self) -> None:
        self._last_call = 0.0

    def _call_llm(self, prompt: str) -> tuple[str, int, int]:
        """Call the underlying LLM. Returns (raw_text, input_tokens, output_tokens)."""
        raise NotImplementedError

    @property
    def estimated_cost(self) -> float:
        return 0.0

    @property
    def token_usage(self) -> dict:
        return {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}

    def analyze(self, title: str, text: str, max_text_chars: int = 800) -> SentimentResult:
        truncated = text[:max_text_chars] if len(text) > max_text_chars else text
        prompt = USER_TEMPLATE.format(title=title, text=truncated)
        elapsed = time.time() - self._last_call
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        for attempt in range(self.MAX_RETRIES):
            try:
                raw, in_tok, out_tok = self._call_llm(prompt)
                self._last_call = time.time()
                data = json.loads(raw)
                return parse_result(data, model=getattr(self, "model", ""),
                                    input_tokens=in_tok, output_tokens=out_tok)
            except json.JSONDecodeError as e:
                logger.warning("JSON parse error (attempt %d): %s", attempt + 1, e)
                if attempt == self.MAX_RETRIES - 1:
                    return SentimentResult(summary="[parse error]")
            except Exception as e:
                logger.warning("LLM error (attempt %d): %s", attempt + 1, e)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                else:
                    return SentimentResult(summary=f"[error: {e}]")
        return SentimentResult()

    def analyze_batch(self, articles: list[dict], progress: bool = True) -> list[SentimentResult]:
        results = []
        n = len(articles)
        for i, article in enumerate(articles):
            if progress:
                print(f"\r  [{i+1}/{n}] Analyzing... cost≈${self.estimated_cost:.3f}", end="")
            results.append(self.analyze(
                title=article.get("title", ""),
                text=article.get("text", ""),
            ))
        if progress:
            print(f"\r  Done {n} articles. Cost≈${self.estimated_cost:.4f}  ")
        return results
