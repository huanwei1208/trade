from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SectorProfile:
    sector: str
    label: str
    purpose: str
    keywords: tuple[str, ...]
    topics: tuple[str, ...]

    def sector_row(self) -> dict[str, Any]:
        return {
            "sector": self.sector,
            "label": self.label,
            "purpose": self.purpose,
            "keywords": ",".join(self.keywords),
            "topics": ",".join(self.topics),
        }


RESEARCH_SECTOR_PROFILES: tuple[SectorProfile, ...] = (
    SectorProfile(
        sector="crypto",
        label="Crypto",
        purpose="Analyze risk appetite, liquidity sensitivity, volatility regimes, regulation, and cross-asset relationships.",
        keywords=(
            "bitcoin", "btc", "ethereum", "eth", "crypto", "stablecoin",
            "defi", "binance", "coinbase", "加密", "比特币", "以太坊",
        ),
        topics=("btc", "eth", "regulation", "risk_appetite", "liquidity", "volatility"),
    ),
    SectorProfile(
        sector="ai",
        label="AI",
        purpose="Analyze technology trend, compute demand, cloud capex, semiconductor supply chain, and application adoption.",
        keywords=(
            "ai", "artificial intelligence", "llm", "openai", "google ai",
            "nvidia", "gpu", "cloud", "capex", "芯片", "算力", "大模型", "人工智能",
        ),
        topics=("llm", "gpu", "cloud_capex", "semiconductor", "application_adoption", "china_ai"),
    ),
    SectorProfile(
        sector="bank",
        label="Banks",
        purpose="Analyze rates, credit risk, real-estate exposure, policy changes, dividends, and defensive behavior.",
        keywords=(
            "bank", "banks", "loan", "credit", "rate", "deposit", "nim",
            "央行", "银行", "信贷", "息差", "地产", "信用", "利率",
        ),
        topics=("rates", "credit_risk", "real_estate", "policy", "dividend", "defensive"),
    ),
)


def build_dim_sector(profiles: tuple[SectorProfile, ...] = RESEARCH_SECTOR_PROFILES) -> pd.DataFrame:
    return pd.DataFrame([profile.sector_row() for profile in profiles])


def build_dim_topic(profiles: tuple[SectorProfile, ...] = RESEARCH_SECTOR_PROFILES) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for profile in profiles:
        for topic in profile.topics:
            rows.append(
                {
                    "sector": profile.sector,
                    "topic": topic,
                    "label": topic.replace("_", " ").title(),
                    "source": "research_profile_v1",
                }
            )
    return pd.DataFrame(rows)
