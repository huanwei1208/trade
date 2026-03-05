"""RSS feed fetcher for Chinese financial news.

Fetches news from configured RSS feeds (财联社, 新浪财经, etc.).
Uses feedparser for parsing. No API key required for public RSS feeds.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
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


def _feed_index_path() -> Path:
    override = os.environ.get("TRADE_RSS_FEED_INDEX_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "config" / "rss_feed_index.json"


def load_feed_index() -> list[dict]:
    """Load RSS feed catalog metadata from config file."""
    path = _feed_index_path()
    if not path.exists():
        logger.warning("RSS feed index not found: %s", path)
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    feeds = payload.get("feeds", []) if isinstance(payload, dict) else payload
    return [f for f in feeds if isinstance(f, dict) and f.get("name")]


def _feed_score(meta: dict) -> float:
    weights = {
        "officialness": 0.30,
        "authority": 0.25,
        "quality": 0.20,
        "coverage": 0.15,
        "value": 0.10,
    }
    total = 0.0
    for key, w in weights.items():
        v = float(meta.get(key, 0.0))
        total += max(0.0, min(5.0, v)) * w
    return round(total / 5.0 * 100.0, 1)


def build_feed_catalog(base_url: Optional[str] = None,
                       include_inactive: bool = True) -> list[dict]:
    """Build feed catalog with computed URLs and metadata scores."""
    base = _normalize_base_url(
        base_url or os.environ.get("TRADE_RSSHUB_BASE_URL", "http://127.0.0.1:1200")
    )
    catalog = []
    for feed in load_feed_index():
        status = str(feed.get("status", "active"))
        if not include_inactive and status not in {"active", "trial"}:
            continue
        path = str(feed.get("path") or feed.get("url") or "").strip()
        if not path:
            continue
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            path = path if path.startswith("/") else f"/{path}"
            url = f"{base}{path}"
        meta = dict(feed)
        meta["url"] = url
        meta["score"] = _feed_score(feed)
        catalog.append(meta)
    return catalog


def build_default_feeds(base_url: Optional[str] = None) -> list[dict]:
    """Build default, enabled feeds for production runs."""
    return [
        {"name": f["name"], "url": f["url"], "meta": f}
        for f in build_feed_catalog(base_url=base_url, include_inactive=False)
        if bool(f.get("enabled_default", False))
    ]


def resolve_feeds(selection: str = "auto", base_url: Optional[str] = None) -> tuple[list[dict], list[dict]]:
    """Resolve selected feeds from `selection` and return (feeds, catalog)."""
    catalog = build_feed_catalog(base_url=base_url, include_inactive=True)
    by_name = {f["name"].lower(): f for f in catalog}
    if selection.strip().lower() in {"", "auto"}:
        feeds = [
            {"name": f["name"], "url": f["url"], "meta": f}
            for f in catalog
            if bool(f.get("enabled_default", False)) and str(f.get("status", "active")) in {"active", "trial"}
        ]
    else:
        req = [x.strip() for x in selection.split(",") if x.strip()]
        missing = [x for x in req if x.lower() not in by_name]
        if missing:
            raise ValueError(
                f"unknown rss feeds {missing}; available={[f['name'] for f in catalog]}"
            )
        feeds = [{"name": by_name[x.lower()]["name"], "url": by_name[x.lower()]["url"], "meta": by_name[x.lower()]}
                 for x in req]
    return feeds, catalog


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
    if not articles:
        has_failure = bool(fetch_status["error"]) or ((status_code or 0) >= 400)
        log_fn = logger.error if has_failure else logger.info
        log_fn(
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
        if "meta" in feed_cfg:
            status["meta"] = feed_cfg["meta"]
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
