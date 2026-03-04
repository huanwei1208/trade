"""Sentiment data pipeline (Python-side).

Flow:
  1. Fetch news articles from RSS feeds (Bronze)
  2. Call Claude Haiku API for structured sentiment extraction (Silver)
  3. Compute sentiment factors per symbol per day (Gold)
  4. Write results to Parquet files

Paths follow the C++ StoragePath convention:
  Bronze: data/raw/sentiment/{source}/YYYY/MM/YYYY-MM-DD.parquet
  Silver: data/sentiment/silver/YYYY/MM/YYYY-MM-DD.parquet
  Gold:   data/sentiment/gold/YYYY/MM/YYYY-MM-DD.parquet
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Symbol linking: simple regex-based A-share code detection
# ---------------------------------------------------------------------------

_ASHARE_PATTERN = re.compile(r"\b([036]\d{5})\b")


def extract_symbols_from_text(text: str) -> list[str]:
    """Extract A-share stock codes mentioned in text.

    Returns codes formatted as '600000.SH' / '000001.SZ' etc.
    (Simple regex approach - for production use the C++ SymbolLinker.)
    """
    codes = _ASHARE_PATTERN.findall(text)
    result = []
    for code in set(codes):
        if code.startswith("6"):
            result.append(f"{code}.SH")
        elif code.startswith("0") or code.startswith("3"):
            result.append(f"{code}.SZ")
    return result


# ---------------------------------------------------------------------------
# Parquet I/O helpers
# ---------------------------------------------------------------------------

def _bronze_path(data_root: Path, source: str, article_date: date) -> Path:
    y, m, d = article_date.year, article_date.month, article_date.day
    return data_root / "raw" / "sentiment" / source / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{d:02d}.parquet"


def _silver_path(data_root: Path, article_date: date) -> Path:
    y, m, d = article_date.year, article_date.month, article_date.day
    return data_root / "sentiment" / "silver" / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{d:02d}.parquet"


def _gold_path(data_root: Path, article_date: date) -> Path:
    y, m, d = article_date.year, article_date.month, article_date.day
    return data_root / "sentiment" / "gold" / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{d:02d}.parquet"


def _upsert_parquet(path: Path, new_df: pd.DataFrame, key_cols: list[str]) -> None:
    """Merge new_df into existing parquet file (upsert by key_cols)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=key_cols, keep="last")
    else:
        combined = new_df
    combined.to_parquet(path, index=False)


# ---------------------------------------------------------------------------
# Bronze layer: raw news articles
# ---------------------------------------------------------------------------

def write_bronze(articles, data_root: Path, source: str) -> dict[date, int]:
    """Write raw news articles to Bronze layer Parquet.

    Args:
        articles: List of NewsArticle objects
        data_root: Root data directory
        source: Source name (e.g. 'rss', 'xueqiu')

    Returns:
        Dict mapping date -> article count written
    """
    by_date: dict[date, list] = defaultdict(list)
    for a in articles:
        by_date[a.date].append({
            "source": a.source,
            "url": a.url,
            "title": a.title,
            "text": a.text,
            "published_at": a.published_at.isoformat(),
            "content_hash": a.content_hash,
        })

    counts = {}
    for d, rows in by_date.items():
        df = pd.DataFrame(rows)
        path = _bronze_path(data_root, source, d)
        _upsert_parquet(path, df, key_cols=["content_hash"])
        counts[d] = len(rows)
        logger.info("Bronze %s: wrote %d articles to %s", source, len(rows), path)
    return counts


# ---------------------------------------------------------------------------
# Silver layer: Claude sentiment analysis
# ---------------------------------------------------------------------------

def analyze_bronze_day(data_root: Path, article_date: date,
                        sources: list[str], claude_client) -> pd.DataFrame:
    """Read Bronze Parquet for a date, call LLM client, return Silver DataFrame.

    Args:
        data_root: Root data directory
        article_date: Date to process
        sources: List of source names to read from Bronze
        claude_client: ClaudeClient instance

    Returns:
        DataFrame with sentiment columns per article
    """
    rows = []
    for source in sources:
        path = _bronze_path(data_root, source, article_date)
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            rows.append({
                "content_hash": row.get("content_hash", ""),
                "source": row.get("source", source),
                "title": str(row.get("title", "")),
                "text": str(row.get("text", "")),
                "published_at": str(row.get("published_at", "")),
            })

    if not rows:
        logger.info("No Bronze articles for %s", article_date)
        return pd.DataFrame()

    logger.info("Analyzing %d articles for %s via %s", len(rows), article_date, getattr(claude_client, "provider", "llm"))
    articles = [{"title": r["title"], "text": r["text"]} for r in rows]
    results = claude_client.analyze_batch(articles, progress=True)

    silver_rows = []
    for row, result in zip(rows, results):
        # Extract symbols mentioned in title + text
        combined_text = row["title"] + " " + row["text"]
        symbols = extract_symbols_from_text(combined_text)

        # Also try to get symbols from key_entities (fallback)
        entities_text = " ".join(result.key_entities)
        symbols.extend(extract_symbols_from_text(entities_text))
        symbols = list(set(symbols)) or ["_MARKET_"]  # fallback: market-level

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

    return pd.DataFrame(silver_rows) if silver_rows else pd.DataFrame()


def write_silver(df: pd.DataFrame, data_root: Path, article_date: date) -> None:
    """Write Silver DataFrame to Parquet."""
    if df.empty:
        return
    path = _silver_path(data_root, article_date)
    _upsert_parquet(path, df, key_cols=["date", "symbol", "source", "content_hash"])
    logger.info("Silver: wrote %d rows to %s", len(df), path)


# ---------------------------------------------------------------------------
# Gold layer: daily sentiment factors per symbol
# ---------------------------------------------------------------------------

def compute_gold_factors(data_root: Path, target_date: date,
                          lookback_days: int = 5) -> pd.DataFrame:
    """Compute Gold sentiment factors from Silver layer.

    Factors computed:
      - net_sentiment: (pos - neg) / total, normalized [-1, 1]
      - sentiment_score: mean Claude score [-1, 1]
      - neg_shock: neg_t - EMA(neg, 5d) [predictive factor]
      - sent_velocity: change vs 5d average
      - article_count: number of articles
      - event_magnitude: max event magnitude

    Args:
        data_root: Root data directory
        target_date: Date to compute factors for
        lookback_days: Days of history for momentum factors

    Returns:
        DataFrame with one row per symbol
    """
    import duckdb

    # Load Silver data for target_date + lookback
    silver_glob = str(data_root / "sentiment" / "silver" / "**" / "*.parquet")
    try:
        con = duckdb.connect()
        # Get target date data
        target_df = con.execute(f"""
            SELECT symbol, date, sentiment_score, sentiment_label,
                   event_magnitude, confidence
            FROM read_parquet('{silver_glob}', union_by_name=true)
            WHERE date = '{target_date.isoformat()}'
        """).df()

        if target_df.empty:
            return pd.DataFrame()

        # Get lookback data for momentum calculation
        from_date = pd.Timestamp(target_date) - pd.Timedelta(days=lookback_days)
        history_df = con.execute(f"""
            SELECT symbol, date, sentiment_score, sentiment_label
            FROM read_parquet('{silver_glob}', union_by_name=true)
            WHERE date >= '{from_date.date().isoformat()}'
            AND date <= '{target_date.isoformat()}'
        """).df()
        con.close()
    except Exception as e:
        logger.warning("DuckDB query failed: %s", e)
        return pd.DataFrame()

    # Compute per-symbol factors for target_date
    gold_rows = []
    for symbol in target_df["symbol"].unique():
        if symbol == "_MARKET_":
            continue

        sym_today = target_df[target_df["symbol"] == symbol]
        sym_hist = history_df[history_df["symbol"] == symbol]

        scores = sym_today["sentiment_score"].values
        labels = sym_today["sentiment_label"].values

        pos = (labels == "positive").sum()
        neg = (labels == "negative").sum()
        total = len(labels)

        net_sentiment = float((pos - neg) / total) if total > 0 else 0.0
        mean_score = float(np.mean(scores)) if len(scores) > 0 else 0.0

        # Historical mean for velocity
        hist_scores = sym_hist["sentiment_score"].values
        hist_mean = float(np.mean(hist_scores)) if len(hist_scores) > 0 else 0.0
        sent_velocity = mean_score - hist_mean

        # Neg shock: negative fraction today vs. historical
        neg_frac_today = float(neg / total) if total > 0 else 0.0
        hist_labels = sym_hist["sentiment_label"].values
        hist_neg_frac = float((hist_labels == "negative").sum() / len(hist_labels)) if len(hist_labels) > 0 else 0.0
        neg_shock = neg_frac_today - hist_neg_frac

        gold_rows.append({
            "date": target_date.isoformat(),
            "symbol": symbol,
            "net_sentiment": net_sentiment,
            "sentiment_score": mean_score,
            "sent_velocity": sent_velocity,
            "neg_shock": neg_shock,
            "article_count": total,
            "event_magnitude": float(sym_today["event_magnitude"].max()),
            "confidence": float(sym_today["confidence"].mean()),
        })

    return pd.DataFrame(gold_rows) if gold_rows else pd.DataFrame()


def write_gold(df: pd.DataFrame, data_root: Path, target_date: date) -> None:
    """Write Gold factors to Parquet."""
    if df.empty:
        return
    path = _gold_path(data_root, target_date)
    _upsert_parquet(path, df, key_cols=["date", "symbol"])
    logger.info("Gold: wrote %d rows to %s", len(df), path)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(target_date: Optional[date] = None,
        data_root: str = "data",
        sources: Optional[list[str]] = None,
        rss_feeds: Optional[list[dict]] = None,
        api_key: Optional[str] = None,
        llm_provider: str = "anthropic",
        llm_model: Optional[str] = None,
        ollama_base_url: Optional[str] = None,
        dry_run: bool = False,
        fetch: bool = True) -> dict:
    """Run the full sentiment pipeline for a given date.

    Args:
        target_date: Date to process (default: today)
        data_root: Path to data directory
        sources: Source names to process (default: ['rss'])
        rss_feeds: RSS feed configs (default: DEFAULT_FEEDS)
        api_key: Anthropic API key (default: ANTHROPIC_API_KEY env var)
        llm_provider: "anthropic" or "ollama"
        llm_model: model name override
        ollama_base_url: local ollama endpoint
        dry_run: If True, fetch articles but skip Claude API
        fetch: If False, skip RSS fetch and only process existing Bronze data

    Returns:
        Stats dict with article counts and file paths
    """
    if target_date is None:
        target_date = date.today()
    if sources is None:
        sources = ["rss"]

    root = Path(data_root)
    stats: dict = {"date": target_date.isoformat(), "sources": {}}

    # 1. Fetch news (Bronze) or read existing Bronze
    rss_diagnostics = []
    articles = []
    bronze_rows = 0
    bronze_by_date = {}
    if fetch:
        from trade_py.intelligence.rss_fetcher import fetch_all, DEFAULT_FEEDS
        feeds = rss_feeds or DEFAULT_FEEDS
        articles, rss_diagnostics = fetch_all(
            feeds=feeds,
            since=target_date,
            return_diagnostics=True,
        )
        articles = [a for a in articles if a.date == target_date]
        bronze_counts = write_bronze(articles, root, "rss")
        bronze_rows = len(articles)
        bronze_by_date = {str(k): v for k, v in bronze_counts.items()}
    else:
        path = _bronze_path(root, "rss", target_date)
        if path.exists():
            bronze_rows = len(pd.read_parquet(path))
            bronze_by_date = {target_date.isoformat(): bronze_rows} if bronze_rows else {}

    stats["rss_fetch"] = rss_diagnostics
    stats["sources"]["rss"] = {"articles_fetched": bronze_rows, "by_date": bronze_by_date}

    if dry_run:
        stats["mode"] = "dry_run"
        return stats

    if bronze_rows == 0:
        failed_sources = [
            d for d in rss_diagnostics
            if d.get("error") or ((d.get("http_status") or 0) >= 400)
        ]
        if failed_sources:
            stats["mode"] = "fetch_failed"
            stats["fetch_errors"] = failed_sources
        else:
            stats["mode"] = "no_articles"
        return stats

    # 2. Analyze via Claude (Silver)
    from trade_py.intelligence.claude_client import ClaudeClient
    try:
        client = ClaudeClient(
            api_key=api_key,
            provider=llm_provider,
            model=llm_model,
            ollama_base_url=ollama_base_url,
        )
        silver_df = analyze_bronze_day(root, target_date, sources, client)
        write_silver(silver_df, root, target_date)
        stats["silver_rows"] = len(silver_df)
        stats["api_cost_usd"] = client.estimated_cost
        stats["token_usage"] = client.token_usage
    except (ValueError, ImportError) as e:
        logger.warning("Skipping Claude analysis: %s", e)
        stats["silver_skipped"] = str(e)
        return stats

    # 3. Compute factors (Gold)
    gold_df = compute_gold_factors(root, target_date)
    write_gold(gold_df, root, target_date)
    stats["gold_rows"] = len(gold_df)

    return stats
