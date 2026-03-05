"""LLM enrichment logic: Bronze rows → Silver rows.

Extracted from sentiment_pipeline.py so it can be reused by enrich.py
independently of the old monolithic pipeline.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_ASHARE_PATTERN = re.compile(r"\b([036]\d{5})\b")
_COMPANY_SUFFIXES = (
    "股份有限公司", "集团股份有限公司", "有限责任公司",
    "集团有限公司", "有限公司", "股份", "集团",
)


def extract_symbols_from_text(text: str) -> list[str]:
    codes = _ASHARE_PATTERN.findall(text)
    result = []
    for code in set(codes):
        if code.startswith("6"):
            result.append(f"{code}.SH")
        elif code.startswith("0") or code.startswith("3"):
            result.append(f"{code}.SZ")
    return result


def _normalize_for_name_match(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).upper()


@lru_cache(maxsize=8)
def _load_company_symbol_pairs(db_path: str) -> tuple[tuple[str, str], ...]:
    path = Path(db_path)
    if not path.exists():
        return ()
    try:
        conn = sqlite3.connect(str(path))
        rows = conn.execute(
            "SELECT symbol, name FROM instruments"
            " WHERE status = 1 AND name IS NOT NULL AND name != ''"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return ()
    pairs: set[tuple[str, str]] = set()
    for symbol, name in rows:
        n = _normalize_for_name_match(name)
        if len(n) >= 3:
            pairs.add((n, symbol))
        for suffix in _COMPANY_SUFFIXES:
            if n.endswith(suffix):
                alias = n[: -len(suffix)]
                if len(alias) >= 3:
                    pairs.add((alias, symbol))
    return tuple(sorted(pairs, key=lambda x: len(x[0]), reverse=True))


def extract_symbols_from_company_names(
    text: str,
    name_symbol_pairs: tuple[tuple[str, str], ...],
    max_hits: int = 8,
) -> list[str]:
    normalized = _normalize_for_name_match(text)
    if not normalized or not name_symbol_pairs:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for cname, symbol in name_symbol_pairs:
        if cname in normalized and symbol not in seen:
            out.append(symbol)
            seen.add(symbol)
            if len(out) >= max_hits:
                break
    return out


def build_silver_rows(
    bronze_rows: list[dict],
    article_date: date,
    client,
    data_root: Path,
    already_enriched: set[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Call LLM on un-enriched bronze rows; return (silver_df, newly_enriched_hashes).

    Args:
        bronze_rows: List of dicts from Bronze parquet (title, text, content_hash, ...).
        article_date: Date being processed (for Silver row labelling).
        client: ClaudeClient instance.
        data_root: Root data dir (used for instruments DB lookup).
        already_enriched: Set of content_hashes to skip (incremental cache).

    Returns:
        (silver_df, newly_enriched_hashes)
        silver_df may be empty if all rows were already enriched or LLM failed.
        newly_enriched_hashes contains hashes of rows just analysed (status=ok).
    """
    if already_enriched is None:
        already_enriched = set()

    to_analyze = [r for r in bronze_rows if r.get("content_hash", "") not in already_enriched]
    skipped = len(bronze_rows) - len(to_analyze)
    if skipped:
        logger.info("Silver cache: skipping %d already-enriched articles", skipped)
    if not to_analyze:
        return pd.DataFrame(), []

    logger.info("Analysing %d articles for %s via %s",
                len(to_analyze), article_date, getattr(client, "provider", "llm"))
    articles = [{"title": r["title"], "text": r["text"]} for r in to_analyze]
    results = client.analyze_batch(articles, progress=True)

    company_pairs = _load_company_symbol_pairs(
        str(data_root / ".metadata" / "trade.db")
    )
    silver_rows = []
    newly_enriched: list[str] = []

    for row, result in zip(to_analyze, results):
        combined_text = row["title"] + " " + row["text"]
        symbols = extract_symbols_from_text(combined_text)
        symbols.extend(extract_symbols_from_company_names(combined_text, company_pairs))
        entities_text = " ".join(result.key_entities)
        symbols.extend(extract_symbols_from_text(entities_text))
        symbols.extend(extract_symbols_from_company_names(entities_text, company_pairs))
        symbols = list(set(symbols)) or ["_MARKET_"]

        for sym in symbols:
            silver_rows.append({
                "date": article_date.isoformat(),
                "symbol": sym,
                "source": row["source"],
                "content_hash": row["content_hash"],
                "title": row["title"],
                "sentiment_score": result.sentiment_score,
                "sentiment_label": result.sentiment_label,
                "event_type": result.event_type,
                "event_magnitude": result.event_magnitude,
                "affected_sectors": ",".join(result.affected_sectors),
                "key_entities": ",".join(result.key_entities),
                "summary": result.summary,
                "confidence": result.confidence,
                "published_at": row["published_at"],
            })
        newly_enriched.append(row["content_hash"])

    return pd.DataFrame(silver_rows) if silver_rows else pd.DataFrame(), newly_enriched
