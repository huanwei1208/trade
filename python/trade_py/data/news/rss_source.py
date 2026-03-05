"""RSS news source: DataSource implementation for RSSHub-proxied feeds.

Also exposes catalogue helpers (load_feed_index, resolve_feeds) used by the CLI
to let operators select specific feeds via --rss-feeds.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Literal, Optional

from trade_py.data.source import RawRecord
from trade_py.intelligence._utils import meta_score, clean_html

CST = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feed catalogue helpers
# ---------------------------------------------------------------------------

def _feed_index_path() -> Path:
    override = os.environ.get("TRADE_RSS_FEED_INDEX_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[4] / "config" / "rss_feed_index.json"


def load_feed_index() -> list[dict]:
    """Return raw feed entries from config/rss_feed_index.json."""
    path = _feed_index_path()
    if not path.exists():
        logger.warning("RSS feed index not found: %s", path)
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    feeds = payload.get("feeds", []) if isinstance(payload, dict) else payload
    return [f for f in feeds if isinstance(f, dict) and f.get("name")]


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def build_feed_catalog(base_url: Optional[str] = None,
                       include_inactive: bool = True) -> list[dict]:
    """Build feed catalogue with computed URLs and quality scores."""
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
        meta["score"] = meta_score(feed)
        catalog.append(meta)
    return catalog


def resolve_feeds(selection: str = "auto",
                  base_url: Optional[str] = None) -> tuple[list[dict], list[dict]]:
    """Resolve selected feeds from a CLI selection string.

    Returns (selected_feeds, full_catalog).
    Each feed dict has keys: name, url, meta.
    """
    catalog = build_feed_catalog(base_url=base_url, include_inactive=True)
    by_name = {f["name"].lower(): f for f in catalog}
    if selection.strip().lower() in {"", "auto"}:
        feeds = [
            {"name": f["name"], "url": f["url"], "meta": f}
            for f in catalog
            if bool(f.get("enabled_default", False))
            and str(f.get("status", "active")) in {"active", "trial"}
        ]
    else:
        req = [x.strip() for x in selection.split(",") if x.strip()]
        missing = [x for x in req if x.lower() not in by_name]
        if missing:
            raise ValueError(
                f"unknown rss feeds {missing}; available={[f['name'] for f in catalog]}"
            )
        feeds = [
            {"name": by_name[x.lower()]["name"], "url": by_name[x.lower()]["url"],
             "meta": by_name[x.lower()]}
            for x in req
        ]
    return feeds, catalog


# ---------------------------------------------------------------------------
# Low-level fetch helpers
# ---------------------------------------------------------------------------

def _fetch_feed(feed_url: str, source_name: str,
                since: Optional[date] = None,
                timeout: int = 15) -> tuple[list[RawRecord], dict]:
    """Fetch a single RSS/Atom feed. Returns (records, status_dict)."""
    try:
        import feedparser
    except ImportError:
        raise ImportError("Install feedparser: pip install feedparser>=6.0")

    fetch_status = {
        "source": source_name, "url": feed_url,
        "http_status": None, "bozo": False, "error": "", "entries": 0,
    }
    try:
        feed = feedparser.parse(feed_url, request_headers={"User-Agent": "trade-bot/1.0"})
    except Exception as e:
        logger.error("Failed to fetch %s: %s", feed_url, e)
        fetch_status["error"] = str(e)
        return [], fetch_status

    status_code = getattr(feed, "status", None)
    fetch_status["http_status"] = status_code
    fetch_status["bozo"] = bool(getattr(feed, "bozo", False))
    fetch_status["entries"] = len(feed.entries)
    bozo_exc = getattr(feed, "bozo_exception", None)

    if status_code is not None and status_code >= 400:
        logger.error("RSS rejected %s: status=%s", source_name, status_code)
    if bozo_exc is not None:
        fetch_status["error"] = repr(bozo_exc)
        logger.error("RSS parse error %s: %s", source_name, bozo_exc)

    records: list[RawRecord] = []
    for entry in feed.entries:
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

        title = clean_html(getattr(entry, "title", "") or "")
        text_raw = (getattr(entry, "summary", "") or
                    getattr(entry, "description", "") or "")
        if hasattr(entry, "content"):
            for c in entry.content:
                text_raw += " " + (c.get("value", "") or "")
        text = clean_html(text_raw)
        url = getattr(entry, "link", "") or ""

        records.append(RawRecord(
            source_id=source_name,
            data_type="news",
            published_at=pub_time,
            title=title,
            text=text,
            url=url,
        ))

    logger.info("Fetched %d articles from %s", len(records), source_name)
    return records, fetch_status


# ---------------------------------------------------------------------------
# RssSource — DataSource implementation
# ---------------------------------------------------------------------------

class RssSource:
    """Fetches news from a list of RSSHub-proxied feeds."""

    source_id: str = "rss"
    data_type: Literal["news"] = "news"

    def __init__(self, feeds: list[dict]) -> None:
        """
        Args:
            feeds: List of feed dicts with 'name' and 'url' keys,
                   as returned by resolve_feeds().
        """
        self._feeds = feeds

    def fetch(self, since: datetime, until: datetime) -> list[RawRecord]:
        since_date = since.astimezone(CST).date()
        all_records: list[RawRecord] = []
        seen: set[str] = set()

        for feed_cfg in self._feeds:
            records, _status = _fetch_feed(
                feed_url=feed_cfg["url"],
                source_name=feed_cfg["name"],
                since=since_date,
            )
            for r in records:
                pub_date = r.published_at.astimezone(CST).date()
                if pub_date > until.astimezone(CST).date():
                    continue
                if r.content_hash not in seen:
                    seen.add(r.content_hash)
                    all_records.append(r)

        all_records.sort(key=lambda r: r.published_at, reverse=True)
        return all_records

    def fetch_with_diagnostics(self, since: datetime,
                               until: datetime) -> tuple[list[RawRecord], list[dict]]:
        """Like fetch() but also returns per-feed diagnostics."""
        since_date = since.astimezone(CST).date()
        until_date = until.astimezone(CST).date()
        all_records: list[RawRecord] = []
        diagnostics: list[dict] = []
        seen: set[str] = set()

        for feed_cfg in self._feeds:
            records, status = _fetch_feed(
                feed_url=feed_cfg["url"],
                source_name=feed_cfg["name"],
                since=since_date,
            )
            if "meta" in feed_cfg:
                status["meta"] = feed_cfg["meta"]
            diagnostics.append(status)
            for r in records:
                if r.published_at.astimezone(CST).date() > until_date:
                    continue
                if r.content_hash not in seen:
                    seen.add(r.content_hash)
                    all_records.append(r)

        all_records.sort(key=lambda r: r.published_at, reverse=True)
        return all_records, diagnostics

    def health_check(self) -> dict:
        from urllib.request import Request, urlopen
        from urllib.error import URLError
        base_url = os.environ.get("TRADE_RSSHUB_BASE_URL", "http://127.0.0.1:1200")
        probe = f"{base_url.rstrip('/')}/healthz"
        try:
            with urlopen(Request(probe, headers={"User-Agent": "trade-bot/1.0"}),
                         timeout=3) as resp:
                ok = getattr(resp, "status", 200) < 400
        except Exception as e:
            return {"source_id": self.source_id, "healthy": False, "error": str(e)}
        return {"source_id": self.source_id, "healthy": ok, "url": probe,
                "feeds": len(self._feeds)}
