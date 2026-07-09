from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


_CATEGORY_TO_SECTORS: dict[str, tuple[str, ...]] = {
    "科技 / AI / 工程": ("ai",),
    "财经 / 市场 / 商业": ("bank", "crypto"),
    "中文 / 中国相关": ("ai", "bank"),
    "工程博客 / 技术博客": ("ai",),
}

_CATEGORY_TO_TOPICS: dict[str, tuple[str, ...]] = {
    "科技 / AI / 工程": ("ai", "technology", "engineering"),
    "财经 / 市场 / 商业": ("finance", "market", "business"),
    "中文 / 中国相关": ("china", "policy", "market"),
    "工程博客 / 技术博客": ("engineering", "infrastructure", "technology"),
}


def _slug(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"https?://", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text or "source"


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


@dataclass(frozen=True)
class DataSourceCatalogEntry:
    source_id: str
    source_name: str
    url: str
    category: str
    language: str = "unknown"
    region: str = "global"
    sector_tags: tuple[str, ...] = field(default_factory=tuple)
    topic_tags: tuple[str, ...] = field(default_factory=tuple)
    freshness_sla_hours: int = 24
    min_interval_seconds: int = 3600
    value_hypothesis: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "url": self.url,
            "category": self.category,
            "language": self.language,
            "region": self.region,
            "sector_tags": ",".join(self.sector_tags),
            "topic_tags": ",".join(self.topic_tags),
            "freshness_sla_hours": self.freshness_sla_hours,
            "min_interval_seconds": self.min_interval_seconds,
            "value_hypothesis": self.value_hypothesis,
            "enabled": self.enabled,
        }


def _infer_language(name: str, category: str) -> str:
    if any("\u4e00" <= ch <= "\u9fff" for ch in name):
        return "zh"
    if "中文" in category or "中国相关" in category:
        return "zh"
    return "en"


def _infer_region(category: str) -> str:
    if "中国" in category or "中文" in category:
        return "china"
    if "财经" in category or "市场" in category:
        return "global"
    return "global"


def _value_hypothesis(category: str, name: str) -> str:
    if category == "科技 / AI / 工程":
        return f"{name} may surface AI or technology trend changes before they appear in sector-level market data."
    if category == "财经 / 市场 / 商业":
        return f"{name} may explain bank and crypto risk appetite through market, policy, or liquidity coverage."
    if category == "中文 / 中国相关":
        return f"{name} may add China-specific policy, industry, or sentiment context for watched assets."
    if category == "工程博客 / 技术博客":
        return f"{name} may provide slower-moving technical evidence for AI infrastructure and adoption hypotheses."
    return f"{name} is imported as a candidate source and needs value evaluation before promotion."


def import_rss_catalog_rows(rows: list[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    """Normalize a two-column Sheet-style RSS catalog into dim_data_source rows.

    The current Sheet uses category divider rows with only the name column set,
    followed by RSS rows containing name and url. Repeated rows are de-duplicated
    by URL while preserving the first category assignment.
    """
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=list(DataSourceCatalogEntry("", "", "", "").to_dict()))

    name_col = "名称" if "名称" in frame.columns else frame.columns[0]
    url_col = "rss link" if "rss link" in frame.columns else frame.columns[min(1, len(frame.columns) - 1)]

    entries: list[DataSourceCatalogEntry] = []
    current_category = "uncategorized"
    seen_urls: set[str] = set()
    for _, row in frame.iterrows():
        name = _cell_text(row.get(name_col)).rstrip(":")
        url = _cell_text(row.get(url_col))
        if not name and not url:
            continue
        if name and not url:
            current_category = name
            continue
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        sector_tags = _CATEGORY_TO_SECTORS.get(current_category, ())
        topic_tags = _CATEGORY_TO_TOPICS.get(current_category, ())
        entry = DataSourceCatalogEntry(
            source_id=f"rss_{_slug(name)}",
            source_name=name,
            url=url,
            category=current_category,
            language=_infer_language(name, current_category),
            region=_infer_region(current_category),
            sector_tags=sector_tags,
            topic_tags=topic_tags,
            value_hypothesis=_value_hypothesis(current_category, name),
        )
        entries.append(entry)

    return pd.DataFrame([entry.to_dict() for entry in entries])
