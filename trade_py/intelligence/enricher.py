"""LLM enrichment logic: Bronze rows → Silver rows.

Extracted from sentiment_pipeline.py so it can be reused by enrich.py
independently of the old monolithic pipeline.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

from trade_py.intelligence.base_factors import analyze_article

logger = logging.getLogger(__name__)

_ASHARE_PATTERN = re.compile(r"\b([036]\d{5})\b")
_COMPANY_SUFFIXES = (
    "股份有限公司", "集团股份有限公司", "有限责任公司",
    "集团有限公司", "有限公司", "股份", "集团",
)
_SW_BY_INDUSTRY = [
    "SW_Agriculture", "SW_Mining", "SW_Chemical", "SW_Steel",
    "SW_NonFerrousMetal", "SW_Electronics", "SW_Auto",
    "SW_HouseholdAppliance", "SW_FoodBeverage", "SW_Textile",
    "SW_LightManufacturing", "SW_Medicine", "SW_Utilities",
    "SW_Transportation", "SW_RealEstate", "SW_Commerce",
    "SW_SocialService", "SW_Banking", "SW_NonBankFinancial",
    "SW_Construction", "SW_BuildingMaterial", "SW_MechanicalEquipment",
    "SW_Defense", "SW_Computer", "SW_Media", "SW_Telecom",
    "SW_Environment", "SW_ElectricalEquipment", "SW_Beauty",
    "SW_Coal", "SW_Petroleum",
]


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


@lru_cache(maxsize=8)
def _load_symbol_sector_map(db_path: str) -> dict[str, str]:
    path = Path(db_path)
    if not path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(path))
        rows = conn.execute(
            "SELECT symbol, industry FROM instruments WHERE symbol IS NOT NULL"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    out: dict[str, str] = {}
    for symbol, industry in rows:
        try:
            idx = int(industry)
        except (TypeError, ValueError):
            idx = 255
        out[str(symbol)] = _SW_BY_INDUSTRY[idx] if 0 <= idx < len(_SW_BY_INDUSTRY) else "SW_Unknown"
    return out


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
    semantic_mode: str = "hybrid",
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

    llm_enabled = client is not None and semantic_mode in {"hybrid", "llm"}
    to_analyze = (
        [r for r in bronze_rows if r.get("content_hash", "") not in already_enriched]
        if llm_enabled
        else list(bronze_rows)
    )
    skipped = len(bronze_rows) - len(to_analyze)
    if skipped:
        logger.info("Silver cache: skipping %d already-enriched articles", skipped)
    if not to_analyze:
        return pd.DataFrame(), []

    results = []
    if llm_enabled:
        logger.info("Analysing %d articles for %s via %s",
                    len(to_analyze), article_date, getattr(client, "provider", "llm"))
        articles = [{"title": r["title"], "text": r["text"]} for r in to_analyze]
        results = client.analyze_batch(articles, progress=True)
    else:
        results = [None] * len(to_analyze)

    db_path = str(__import__("trade_py.db.trade_db", fromlist=["_find_db_path"])._find_db_path(data_root))
    company_pairs = _load_company_symbol_pairs(db_path)
    symbol_sector_map = _load_symbol_sector_map(db_path)
    title_counts = Counter(_normalize_for_name_match(row.get("title", "")) for row in to_analyze)
    silver_rows = []
    newly_enriched: list[str] = []

    for row, result in zip(to_analyze, results):
        combined_text = row["title"] + " " + row["text"]
        symbols = extract_symbols_from_text(combined_text)
        symbols.extend(extract_symbols_from_company_names(combined_text, company_pairs))
        entities_text = " ".join(result.key_entities) if result is not None else ""
        if result is not None:
            symbols.extend(extract_symbols_from_text(entities_text))
            symbols.extend(extract_symbols_from_company_names(entities_text, company_pairs))
        symbols = list(set(symbols)) or ["_MARKET_"]
        symbol_sectors = sorted({
            symbol_sector_map.get(sym, "SW_Unknown")
            for sym in symbols
            if sym != "_MARKET_"
        })
        base = analyze_article(
            row["title"],
            row["text"],
            source=row.get("source", ""),
            symbols=symbols,
            symbol_sectors=symbol_sectors,
            title_frequency=title_counts.get(_normalize_for_name_match(row.get("title", "")), 1),
        )

        llm_conf = float(getattr(result, "confidence", 0.0) or 0.0) if result is not None else 0.0
        use_llm = semantic_mode != "base" and result is not None and llm_conf >= 0.6
        effective = result if use_llm else base
        llm_sectors = list(getattr(result, "affected_sectors", []) or []) if result is not None else []
        llm_entities = list(getattr(result, "key_entities", []) or []) if result is not None else []
        semantic_source = "llm" if use_llm else "base"

        for sym in symbols:
            silver_rows.append({
                "date": article_date.isoformat(),
                "symbol": sym,
                "source": row["source"],
                "content_hash": row["content_hash"],
                "title": row["title"],
                "text": row["text"],
                "sentiment_score": effective.sentiment_score,
                "sentiment_label": effective.sentiment_label,
                "event_type": effective.event_type,
                "event_magnitude": effective.event_magnitude,
                "affected_sectors": ",".join(effective.affected_sectors),
                "key_entities": ",".join(effective.key_entities),
                "summary": effective.summary,
                "confidence": effective.confidence,
                "published_at": row["published_at"],
                "policy_signal": effective.policy_signal,
                "market_impact_scope": effective.market_impact_scope,
                "time_sensitivity": effective.time_sensitivity,
                "event_chain": effective.event_chain,
                "semantic_mode": semantic_mode,
                "semantic_source": semantic_source,
                "base_sentiment_score": base.sentiment_score,
                "base_sentiment_label": base.sentiment_label,
                "base_event_type": base.event_type,
                "base_event_magnitude": base.event_magnitude,
                "base_affected_sectors": ",".join(base.affected_sectors),
                "base_key_entities": ",".join(base.key_entities),
                "base_summary": base.summary,
                "base_confidence": base.confidence,
                "base_policy_signal": base.policy_signal,
                "base_market_impact_scope": base.market_impact_scope,
                "base_time_sensitivity": base.time_sensitivity,
                "base_event_chain": base.event_chain,
                "base_entity_density": base.entity_density,
                "base_novelty_score": base.novelty_score,
                "base_noise_score": base.noise_score,
                "llm_sentiment_score": getattr(result, "sentiment_score", None),
                "llm_sentiment_label": getattr(result, "sentiment_label", None),
                "llm_event_type": getattr(result, "event_type", None),
                "llm_event_magnitude": getattr(result, "event_magnitude", None),
                "llm_affected_sectors": ",".join(llm_sectors),
                "llm_key_entities": ",".join(llm_entities),
                "llm_summary": getattr(result, "summary", None),
                "llm_confidence": getattr(result, "confidence", None),
                "llm_policy_signal": getattr(result, "policy_signal", None),
                "llm_market_impact_scope": getattr(result, "market_impact_scope", None),
                "llm_time_sensitivity": getattr(result, "time_sensitivity", None),
                "llm_event_chain": getattr(result, "event_chain", None),
            })
        if result is not None:
            newly_enriched.append(row["content_hash"])

    return pd.DataFrame(silver_rows) if silver_rows else pd.DataFrame(), newly_enriched
