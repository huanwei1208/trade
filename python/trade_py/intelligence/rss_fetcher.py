"""RSS feed fetcher for Chinese financial news.

Fetches news from configured RSS feeds (财联社, 新浪财经, etc.).
Uses feedparser for parsing. No API key required for public RSS feeds.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, date, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))  # China Standard Time

logger = logging.getLogger(__name__)


@dataclass
class NewsArticle:
    """A single news article from an RSS feed."""
    title: str
    text: str                   # cleaned body text
    url: str
    source: str                 # feed name, e.g. "CLS", "Sina"
    published_at: datetime      # UTC
    content_hash: str = ""      # dedup key

    def __post_init__(self):
        if not self.content_hash:
            raw = f"{self.title}\n{self.text}"
            self.content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def date(self) -> date:
        return self.published_at.astimezone(CST).date()


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def build_default_feeds(base_url: Optional[str] = None) -> list[dict]:
    """Build default RSS feeds from RSSHub base URL.

    `base_url` defaults to env `TRADE_RSSHUB_BASE_URL`, and falls back to
    `http://127.0.0.1:1200`.
    """
    base = _normalize_base_url(
        base_url or os.environ.get("TRADE_RSSHUB_BASE_URL", "http://127.0.0.1:1200")
    )
    return [
        {"name": "CLS", "url": f"{base}/cls/telegraph"},
        {"name": "WSJ", "url": f"{base}/wallstreetcn/news/articles"},
        {"name": "Gelonghui", "url": f"{base}/gelonghui/live"},
    ]


# Default RSS feeds (public, no auth required)
DEFAULT_FEEDS = build_default_feeds()


def _clean_html(text: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_feed(feed_url: str, source_name: str,
               since: Optional[date] = None,
               timeout: int = 15,
               include_status: bool = False):
    """Fetch articles from a single RSS/Atom feed.

    Args:
        feed_url: RSS feed URL
        source_name: Human-readable source name
        since: Only include articles published on or after this date
        timeout: HTTP timeout in seconds

    Returns:
        List of NewsArticle objects, most recent first
    """
    try:
        import feedparser
    except ImportError:
        raise ImportError("Install feedparser: pip install feedparser>=6.0")

    logger.debug("Fetching %s from %s", source_name, feed_url)
    fetch_status = {
        "source": source_name,
        "url": feed_url,
        "http_status": None,
        "bozo": False,
        "error": "",
        "entries": 0,
    }
    try:
        feed = feedparser.parse(feed_url, request_headers={"User-Agent": "trade-bot/1.0"})
    except Exception as e:
        logger.error("Failed to fetch %s: %s", feed_url, e)
        fetch_status["error"] = str(e)
        return ([], fetch_status) if include_status else []

    status_code = getattr(feed, "status", None)
    fetch_status["http_status"] = status_code
    fetch_status["bozo"] = bool(getattr(feed, "bozo", False))
    fetch_status["entries"] = len(feed.entries)
    bozo_exception = getattr(feed, "bozo_exception", None)

    if status_code is not None and status_code >= 400:
        logger.error(
            "RSS fetch rejected for %s: status=%s url=%s",
            source_name, status_code, feed_url
        )

    if bozo_exception is not None:
        fetch_status["error"] = repr(bozo_exception)
        logger.error("RSS parse error for %s: %s", source_name, bozo_exception)

    articles = []
    for entry in feed.entries:
        # Parse published time
        pub_time = None
        for attr in ("published_parsed", "updated_parsed", "created_parsed"):
            t = getattr(entry, attr, None)
            if t:
                pub_time = datetime(*t[:6], tzinfo=timezone.utc)
                break
        if pub_time is None:
            pub_time = datetime.now(timezone.utc)

        if since and pub_time.astimezone(CST).date() < since:
            continue

        title = _clean_html(getattr(entry, "title", "") or "")
        # Prefer summary over content for brevity
        text_raw = (getattr(entry, "summary", "") or
                    getattr(entry, "description", "") or "")
        # Also append full content if available
        if hasattr(entry, "content"):
            for c in entry.content:
                text_raw += " " + (c.get("value", "") or "")

        text = _clean_html(text_raw)
        url = getattr(entry, "link", "") or ""

        articles.append(NewsArticle(
            title=title,
            text=text,
            url=url,
            source=source_name,
            published_at=pub_time,
        ))

    logger.info("Fetched %d articles from %s", len(articles), source_name)
    if not articles and (status_code is not None or fetch_status["error"]):
        logger.error(
            "No articles from %s (status=%s, error=%s, url=%s)",
            source_name,
            status_code,
            fetch_status["error"] or "none",
            feed_url,
        )
    return (articles, fetch_status) if include_status else articles


def fetch_all(feeds: Optional[list[dict]] = None,
              since: Optional[date] = None,
              deduplicate: bool = True,
              return_diagnostics: bool = False):
    """Fetch from all configured feeds.

    Args:
        feeds: List of dicts with 'name' and 'url'. Defaults to DEFAULT_FEEDS.
        since: Only include articles on/after this date.
        deduplicate: Remove duplicate articles by content hash.

    Returns:
        All articles, sorted newest first.
    """
    if feeds is None:
        feeds = build_default_feeds()

    all_articles: list[NewsArticle] = []
    diagnostics: list[dict] = []
    for feed_cfg in feeds:
        articles, status = fetch_feed(
            feed_url=feed_cfg["url"],
            source_name=feed_cfg["name"],
            since=since,
            include_status=True,
        )
        all_articles.extend(articles)
        diagnostics.append(status)

    # Sort newest first
    all_articles.sort(key=lambda a: a.published_at, reverse=True)

    if deduplicate:
        seen: set[str] = set()
        unique = []
        for a in all_articles:
            if a.content_hash not in seen:
                seen.add(a.content_hash)
                unique.append(a)
        all_articles = unique

    if not all_articles and diagnostics:
        failed = [
            d for d in diagnostics
            if d.get("error") or ((d.get("http_status") or 0) >= 400)
        ]
        if failed:
            summary = ", ".join(
                f'{d["source"]}(status={d.get("http_status")}, error={d.get("error") or "none"})'
                for d in failed
            )
            logger.error("All RSS sources failed: %s", summary)

    if return_diagnostics:
        return all_articles, diagnostics
    return all_articles
