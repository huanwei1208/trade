"""Free crypto market data and sentiment indicators.

Data sources (all free, no API key required):
- Crypto Fear & Greed Index (alternative.me)
- Crypto news fetching (RSS + basic HTTP)
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

FEAR_GREED_URL = "https://api.alternative.me/fng/?limit={limit}&format=json"
BINANCE_ANNOUNCE_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=20"
REDDIT_CRYPTO_URL = "https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"

_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

CRYPTO_RSS_FEEDS = [
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
    ("decrypt", "https://decrypt.co/feed"),
    ("bitcoinmagazine", "https://bitcoinmagazine.com/feed"),
]


@dataclass
class FearGreedRecord:
    date: str
    value: int
    value_classification: str
    timestamp_unix: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "value": self.value,
            "classification": self.value_classification,
            "timestamp": self.timestamp_unix,
        }


@dataclass
class CryptoNewsItem:
    source: str
    title: str
    url: str
    published_at: str
    summary: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            import hashlib
            raw = f"{self.source}:{self.title}:{self.url}".encode("utf-8")
            self.content_hash = hashlib.sha256(raw).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "summary": self.summary,
            "content_hash": self.content_hash,
        }


def _http_get(url: str, timeout: int = 15) -> bytes | None:
    """Simple HTTP GET with User-Agent header."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.warning("HTTP GET failed for %s: %s", url, exc)
        return None


def fetch_fear_greed(limit: int = 30) -> list[FearGreedRecord]:
    """Fetch Crypto Fear & Greed Index history.

    Returns a list of FearGreedRecord sorted by date ascending.
    Free, no API key required. Data goes back to ~2018.
    """
    data = _http_get(FEAR_GREED_URL.format(limit=max(1, min(limit, 2000))))
    if data is None:
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        logger.warning("Fear & Greed JSON parse error: %s", exc)
        return []

    records: list[FearGreedRecord] = []
    for item in payload.get("data", []):
        try:
            ts = int(item.get("timestamp", 0))
            value = int(item.get("value", 50))
            classification = str(item.get("value_classification", "Neutral"))
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
            records.append(FearGreedRecord(
                date=dt,
                value=value,
                value_classification=classification,
                timestamp_unix=ts,
            ))
        except (ValueError, TypeError) as exc:
            logger.debug("Fear & Greed record parse error: %s", exc)
    records.sort(key=lambda r: r.timestamp_unix)
    return records


from email.utils import parsedate_to_datetime


def _parse_pub_date(raw: str) -> str:
    """Best-effort parse of a publication date string to ISO 8601 UTC."""
    raw = raw.strip()
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    for parser in (
        lambda s: parsedate_to_datetime(s),
        lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
    ):
        try:
            dt = parser(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            continue
    return datetime.now(timezone.utc).isoformat()


def _parse_rss_xml(source: str, xml_bytes: bytes) -> list[CryptoNewsItem]:
    """Parse RSS/Atom XML into CryptoNewsItem list."""
    items: list[CryptoNewsItem] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("RSS XML parse error for %s: %s", source, exc)
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}

    # RSS 2.0: <item> elements
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate") or item.find("dc:date", ns)
        desc_el = item.find("description")
        title = (title_el.text or "").strip() if title_el is not None and title_el.text else ""
        link = (link_el.text or "").strip() if link_el is not None and link_el.text else ""
        pub = _parse_pub_date((pub_el.text or "").strip() if pub_el is not None and pub_el.text else "")
        desc = (desc_el.text or "").strip() if desc_el is not None and desc_el.text else ""
        # Strip HTML tags from description
        desc = re.sub(r"<[^>]+>", "", desc)[:500]
        if title and link:
            items.append(CryptoNewsItem(
                source=source,
                title=title,
                url=link,
                published_at=pub,
                summary=desc,
            ))

    # Atom: <entry> elements
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title_el = entry.find("atom:title", ns)
        link_el = entry.find("atom:link", ns)
        pub_el = entry.find("atom:updated", ns) or entry.find("atom:published", ns)
        summary_el = entry.find("atom:summary", ns)
        title = (title_el.text or "").strip() if title_el is not None and title_el.text else ""
        link = ""
        if link_el is not None:
            link = link_el.get("href", "").strip()
        pub = _parse_pub_date((pub_el.text or "").strip() if pub_el is not None and pub_el.text else "")
        summary = ""
        if summary_el is not None and summary_el.text:
            summary = re.sub(r"<[^>]+>", "", summary_el.text)[:500]
        if title and link:
            items.append(CryptoNewsItem(
                source=source,
                title=title,
                url=link,
                published_at=pub,
                summary=summary,
            ))

    return items


def fetch_crypto_rss_news() -> list[CryptoNewsItem]:
    """Fetch crypto news from RSS feeds (CoinDesk, CoinTelegraph, Decrypt, BitcoinMagazine).

    Free, no API key required. Returns articles found across all feeds.
    """
    all_items: list[CryptoNewsItem] = []
    seen_hashes: set[str] = set()
    for source, url in CRYPTO_RSS_FEEDS:
        data = _http_get(url)
        if data is None:
            continue
        items = _parse_rss_xml(source, data)
        for item in items:
            if item.content_hash not in seen_hashes:
                seen_hashes.add(item.content_hash)
                all_items.append(item)
        time.sleep(0.5)
    return all_items


def fetch_binance_announcements() -> list[CryptoNewsItem]:
    """Fetch latest Binance announcements (new listings, delistings, upgrades).

    Uses the public JSON API that backs the Binance announcements page.
    Free, no API key required.
    """
    data = _http_get(BINANCE_ANNOUNCE_URL)
    if data is None:
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return []

    items: list[CryptoNewsItem] = []
    articles = payload.get("data", {}).get("articles", [])
    for art in articles:
        title = str(art.get("title", "")).strip()
        code = str(art.get("code", ""))
        release_date = art.get("releaseDate", 0)
        if not title or not code:
            continue
        url = f"https://www.binance.com/en/support/announcement/{code}"
        try:
            dt = datetime.fromtimestamp(release_date / 1000, tz=timezone.utc).isoformat()
        except (ValueError, OSError):
            dt = datetime.now(timezone.utc).isoformat()
        items.append(CryptoNewsItem(
            source="binance",
            title=title,
            url=url,
            published_at=dt,
            summary="",
        ))
    return items


def fetch_reddit_crypto(subreddit: str = "CryptoCurrency", limit: int = 25) -> list[CryptoNewsItem]:
    """Fetch hot posts from a crypto subreddit using Reddit's public .json API.

    Free, no API key required (100 req/min for non-commercial use).
    Set a descriptive User-Agent to avoid 429s.
    """
    url = REDDIT_CRYPTO_URL.format(subreddit=subreddit, limit=max(1, min(limit, 100)))
    data = _http_get(url)
    if data is None:
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return []

    items: list[CryptoNewsItem] = []
    posts = payload.get("data", {}).get("children", [])
    for post in posts:
        d = post.get("data", {})
        title = str(d.get("title", "")).strip()
        permalink = str(d.get("permalink", ""))
        created_utc = d.get("created_utc", 0)
        selftext = str(d.get("selftext", ""))[:300]
        score = d.get("score", 0)
        if not title:
            continue
        url = f"https://www.reddit.com{permalink}"
        try:
            dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc).isoformat()
        except (ValueError, TypeError, OSError):
            dt = datetime.now(timezone.utc).isoformat()
        items.append(CryptoNewsItem(
            source=f"reddit-{subreddit}",
            title=title,
            url=url,
            published_at=dt,
            summary=selftext,
        ))
    return items


def fetch_all_crypto_news() -> dict[str, list[CryptoNewsItem]]:
    """Fetch crypto news from all free sources.

    Returns a dict mapping source_name -> list[CryptoNewsItem].
    Sources: RSS feeds, Binance announcements, Reddit.
    """
    result: dict[str, list[CryptoNewsItem]] = {}

    rss_items = fetch_crypto_rss_news()
    for item in rss_items:
        result.setdefault(item.source, []).append(item)

    binance_items = fetch_binance_announcements()
    if binance_items:
        result["binance"] = binance_items

    for sub in ("CryptoCurrency", "bitcoin", "ethereum"):
        items = fetch_reddit_crypto(sub, limit=15)
        if items:
            result[f"reddit-{sub}"] = items
        time.sleep(1.0)

    return result


def save_fear_greed_parquet(records: list[FearGreedRecord], output_path: Path) -> None:
    """Save Fear & Greed records to parquet."""
    import pandas as pd
    if not records:
        return
    rows = [r.to_dict() for r in records]
    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)


def save_crypto_news_parquet(items: list[CryptoNewsItem], output_path: Path) -> None:
    """Save news items to parquet (append mode by date)."""
    import pandas as pd
    if not items:
        return
    rows = [item.to_dict() for item in items]
    df = pd.DataFrame(rows)
    df["fetched_at"] = datetime.now(timezone.utc).isoformat()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
