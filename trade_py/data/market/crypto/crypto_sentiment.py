"""Free crypto market data and sentiment indicators.

Data sources (all free, no API key required):
- Crypto Fear & Greed Index (alternative.me)
- Crypto news fetching (RSS + basic HTTP)
- CoinDesk RSS
- Cointelegraph RSS
- CryptoPanic free public API
- CryptoSlate RSS
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

import xml.etree.ElementTree as ET

import requests

from trade_py.utils.retry import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    create_retry_session,
)

logger = logging.getLogger(__name__)

FEAR_GREED_URL = "https://api.alternative.me/fng/?limit={limit}&format=json"
BINANCE_ANNOUNCE_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=20"
REDDIT_CRYPTO_URL = "https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
COINDESK_RSS_URL = "https://www.coindesk.com/arc/outboundfeeds/rss/"
COINTELEGRAPH_RSS_URL = "https://cointelegraph.com/rss/"
CRYPTOPANIC_FREE_URL = "https://cryptopanic.com/api/free/v1/posts/?auth_token=free&public=true"
CRYPTOSLATE_RSS_URL = "https://cryptoslate.com/feed/"
DECRYPT_RSS_URL = "https://decrypt.co/feed"
BITCOINMAGAZINE_RSS_URL = "https://bitcoinmagazine.com/feed"

_USER_AGENT = DEFAULT_USER_AGENT

# Default HTTP timeout in seconds for external fetches (connect, read).
_DEFAULT_TIMEOUT = DEFAULT_TIMEOUT  # (10s connect, 30s read)

# Minimum acceptable published_at timestamp (2010-01-01 UTC).
_MIN_PUBLISHED_TS = 1262304000

# Rate-limit floor: minimum seconds between HTTP requests to the same domain.
_DOMAIN_RATE_LIMIT_SEC = 1.0

# Track last-request time per domain for simple rate-limiting.
_last_request_time: dict[str, float] = {}


CRYPTO_RSS_FEEDS = [
    ("coindesk", COINDESK_RSS_URL),
    ("cointelegraph", COINTELEGRAPH_RSS_URL),
    ("cryptoslate", CRYPTOSLATE_RSS_URL),
    ("decrypt", DECRYPT_RSS_URL),
    ("bitcoinmagazine", BITCOINMAGAZINE_RSS_URL),
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
    source_type: str = "news"      # "news" | "social" | "announcement"
    category: str = ""

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
            "source_type": self.source_type,
            "category": self.category,
        }


def _rate_limit_wait(domain: str) -> None:
    """Simple per-domain rate limiting: sleep if last request was too recent."""
    now = time.monotonic()
    last = _last_request_time.get(domain, 0.0)
    elapsed = now - last
    if elapsed < _DOMAIN_RATE_LIMIT_SEC:
        time.sleep(_DOMAIN_RATE_LIMIT_SEC - elapsed)
    _last_request_time[domain] = time.monotonic()


def _domain_from_url(url: str) -> str:
    """Extract the domain/host from a URL for rate-limiting purposes."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc or url
    except Exception:
        return url


_SENTIMENT_SESSION: requests.Session | None = None


def _get_session() -> requests.Session:
    """Lazily build a shared ``requests.Session`` with connection-level retries,
    a non-default User-Agent, and connection pooling.

    The session uses ``urllib3.util.retry.Retry`` so that transient transport
    errors (``RemoteDisconnected``, reset connections, DNS blips, 5xx/429) are
    retried at the TCP/HTTP layer *before* we give up and return ``None``.
    The application-level retry/backoff inside ``_http_get`` is kept as a
    defense-in-depth second layer.
    """
    global _SENTIMENT_SESSION
    if _SENTIMENT_SESSION is None:
        _SENTIMENT_SESSION = create_retry_session(
            retries=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
        )
        _SENTIMENT_SESSION.headers.update({
            "User-Agent": _USER_AGENT,
            "Accept": (
                "application/json, application/rss+xml, application/xml, "
                "text/xml, */*;q=0.8"
            ),
        })
    return _SENTIMENT_SESSION


def _http_get(
    url: str,
    timeout: float | tuple[float, float] = _DEFAULT_TIMEOUT,
    max_retries: int = 2,
) -> bytes | None:
    """HTTP GET with User-Agent, per-domain rate limiting, connection-pool
    retries (via the shared session), and application-level retry/backoff.

    Args:
        url: Target URL.
        timeout: Per-request timeout — a scalar or ``(connect, read)`` tuple,
            defaulting to ``(10s, 30s)`` so datacenter egress blips don't
            permanently kill the sentiment ingest.
        max_retries: Number of *application-level* retries on top of the
            urllib3 Retry mounted on the shared session (default 2).
    """
    session = _get_session()
    domain = _domain_from_url(url)
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        _rate_limit_wait(domain)
        try:
            resp = session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
            return resp.content
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
            requests.exceptions.RequestException,
            OSError,
            ValueError,
        ) as exc:
            last_exc = exc
            logger.debug(
                "HTTP GET attempt %d failed for %s: %s: %s",
                attempt + 1, url, type(exc).__name__, exc,
            )
            if attempt < max_retries:
                time.sleep(min(2 ** attempt, 10))
                continue
            break
    logger.warning(
        "HTTP GET failed for %s after %d retries: %s: %s",
        url, max_retries,
        type(last_exc).__name__ if last_exc else "Unknown",
        last_exc,
    )
    return None


def _validate_published_at(iso_str: str | None) -> str | None:
    """Defense-in-depth validation of published_at ISO strings.

    Returns the ISO string if it parses to a datetime that is:
      - Not None/empty
      - After 2010-01-01 UTC
      - Not more than 1 day in the future (allowing minor clock skew)

    Returns None otherwise.
    """
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts = dt.timestamp()
        now_ts = datetime.now(timezone.utc).timestamp()
        if ts < _MIN_PUBLISHED_TS:
            return None
        if ts > now_ts + 86400:  # more than 1 day in the future
            return None
        return iso_str
    except (ValueError, OverflowError, OSError):
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
    skipped_bad_value = 0
    skipped_bad_ts = 0
    for item in payload.get("data", []):
        try:
            ts = int(item.get("timestamp", 0))
            value = int(item.get("value", 50))
            classification = str(item.get("value_classification", "Neutral"))
            # Validate timestamp: must be a reasonable Unix epoch (>= 2010-01-01).
            if ts <= 1262304000:
                skipped_bad_ts += 1
                continue
            # Validate Fear & Greed value: must be integer in [0, 100].
            if value < 0 or value > 100:
                skipped_bad_value += 1
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
            records.append(FearGreedRecord(
                date=dt,
                value=value,
                value_classification=classification,
                timestamp_unix=ts,
            ))
        except (ValueError, TypeError, OSError, OverflowError) as exc:
            logger.debug("Fear & Greed record parse error: %s", exc)
    if skipped_bad_value or skipped_bad_ts:
        logger.warning(
            "Skipped %d Fear & Greed records with out-of-range value and %d with invalid timestamp",
            skipped_bad_value, skipped_bad_ts,
        )
    records.sort(key=lambda r: r.timestamp_unix)
    return records


from email.utils import parsedate_to_datetime


def _parse_pub_date(raw: str) -> str | None:
    """Best-effort parse of a publication date string to ISO 8601 UTC.

    Returns None if the input is empty, unparseable, before 2010, or more
    than one day in the future. Callers MUST skip articles with None dates
    instead of fabricating "now" as a fallback, because silently
    timestamping old/broken articles as "now" poisons recency features and
    creates fake news spikes.
    """
    raw = raw.strip()
    if not raw:
        return None
    for parser in (
        lambda s: parsedate_to_datetime(s),
        lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
    ):
        try:
            dt = parser(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            iso = dt.astimezone(timezone.utc).isoformat()
            return _validate_published_at(iso)
        except Exception:
            continue
    return None


def _parse_rss_xml(source: str, xml_bytes: bytes,
                    source_type: str = "news") -> list[CryptoNewsItem]:
    """Parse RSS/Atom XML into CryptoNewsItem list.

    Items with an unparseable or out-of-range pubDate are SKIPPED (with a
    count-logged WARNING) rather than backfilled with "now", to avoid
    poisoning recency features.

    Extracts <category> elements (RSS 2.0) or <atom:category> (Atom) into
    the item's ``category`` field (comma-joined if multiple).
    """
    items: list[CryptoNewsItem] = []
    skipped_no_date = 0
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("RSS XML parse error for %s: %s", source, exc)
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}

    def _extract_categories(parent: ET.Element) -> str:
        """Extract comma-joined category text from RSS 2.0 or Atom parent."""
        cats: list[str] = []
        # RSS 2.0: multiple <category> elements
        for cat_el in parent.findall("category"):
            if cat_el.text:
                t = cat_el.text.strip()
                if t:
                    cats.append(t)
        # Atom: <atom:category term="..."/>
        for cat_el in parent.findall("atom:category", ns):
            term = cat_el.get("term", "").strip()
            if term:
                cats.append(term)
        return ", ".join(cats[:5])  # cap at 5 categories

    def _append(title: str, link: str, pub: str | None, desc: str, category: str = "") -> None:
        nonlocal skipped_no_date
        if not title or not link:
            return
        if not pub:
            skipped_no_date += 1
            return
        items.append(CryptoNewsItem(
            source=source,
            title=title,
            url=link,
            published_at=pub,
            summary=desc,
            source_type=source_type,
            category=category,
        ))

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
        category = _extract_categories(item)
        _append(title, link, pub, desc, category)

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
        category = _extract_categories(entry)
        _append(title, link, pub, summary, category)

    if skipped_no_date:
        logger.warning(
            "Skipped %d RSS items from %s due to unparseable or out-of-range publication date",
            skipped_no_date, source,
        )
    return items


def _fetch_single_rss(source: str, url: str, source_type: str = "news") -> list[CryptoNewsItem]:
    """Fetch and parse a single RSS/Atom feed.

    Helper used by both the generic feed loop and the individual named
    fetchers below.
    """
    data = _http_get(url, timeout=_DEFAULT_TIMEOUT)
    if data is None:
        return []
    return _parse_rss_xml(source, data, source_type=source_type)


def fetch_coindesk_rss() -> list[CryptoNewsItem]:
    """Fetch articles from the CoinDesk RSS feed.

    Free, no API key required. Standard RSS 2.0. Returns parsed
    CryptoNewsItem list with title, url, published_at, source="coindesk",
    summary, source_type="news", and category.
    """
    return _fetch_single_rss("coindesk", COINDESK_RSS_URL)


def fetch_cointelegraph_rss() -> list[CryptoNewsItem]:
    """Fetch articles from the Cointelegraph RSS feed.

    Free, no API key required. Standard RSS 2.0.
    """
    return _fetch_single_rss("cointelegraph", COINTELEGRAPH_RSS_URL)


def fetch_cryptoslate_rss() -> list[CryptoNewsItem]:
    """Fetch articles from the CryptoSlate RSS feed.

    Free, no API key required. Standard RSS 2.0.
    """
    return _fetch_single_rss("cryptoslate", CRYPTOSLATE_RSS_URL)


def fetch_decrypt_rss() -> list[CryptoNewsItem]:
    """Fetch articles from the Decrypt RSS feed."""
    return _fetch_single_rss("decrypt", DECRYPT_RSS_URL)


def fetch_bitcoinmagazine_rss() -> list[CryptoNewsItem]:
    """Fetch articles from the Bitcoin Magazine RSS feed."""
    return _fetch_single_rss("bitcoinmagazine", BITCOINMAGAZINE_RSS_URL)


def fetch_crypto_rss_news() -> list[CryptoNewsItem]:
    """Fetch crypto news from all configured RSS feeds.

    Free, no API key required. Returns deduplicated articles found across
    all feeds (CoinDesk, Cointelegraph, CryptoSlate, Decrypt, BitcoinMagazine).
    """
    all_items: list[CryptoNewsItem] = []
    seen_hashes: set[str] = set()
    for source, url in CRYPTO_RSS_FEEDS:
        items = _fetch_single_rss(source, url)
        for item in items:
            if item.content_hash not in seen_hashes:
                seen_hashes.add(item.content_hash)
                all_items.append(item)
    return all_items


def fetch_cryptopanic_free() -> list[CryptoNewsItem]:
    """Fetch public crypto posts from CryptoPanic free API.

    Uses the free "auth_token=free" public endpoint. If the endpoint starts
    requiring a real key (returns 401/403), this function returns an empty
    list gracefully — callers will simply not see cryptopanic articles.
    Free, no API key required for public posts.
    """
    data = _http_get(CRYPTOPANIC_FREE_URL, timeout=_DEFAULT_TIMEOUT)
    if data is None:
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        logger.warning("CryptoPanic JSON parse error: %s", exc)
        return []

    results = payload.get("results", []) if isinstance(payload, dict) else []
    items: list[CryptoNewsItem] = []
    skipped_no_date = 0
    for post in results:
        title = str(post.get("title", "")).strip()
        url = str(post.get("url", "")).strip()
        if not title or not url:
            continue
        # CryptoPanic provides published_at as ISO string directly
        published_raw = str(post.get("published_at", "")).strip()
        iso_date: str | None = None
        if published_raw:
            try:
                dt = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                iso_date = _validate_published_at(dt.astimezone(timezone.utc).isoformat())
            except (ValueError, OverflowError, OSError):
                iso_date = None
        # Fallback: try "created_at"
        if not iso_date:
            created_raw = str(post.get("created_at", "")).strip()
            if created_raw:
                try:
                    dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    iso_date = _validate_published_at(dt.astimezone(timezone.utc).isoformat())
                except (ValueError, OverflowError, OSError):
                    pass
        if not iso_date:
            skipped_no_date += 1
            continue
        # Extract domain as summary metadata, or use "kind"/"source"
        summary_parts: list[str] = []
        kind = str(post.get("kind", "")).strip()
        if kind:
            summary_parts.append(f"kind={kind}")
        source_info = post.get("source", {})
        if isinstance(source_info, dict):
            source_title = str(source_info.get("title", "")).strip()
            if source_title:
                summary_parts.append(f"via={source_title}")
        domain = str(post.get("domain", "")).strip()
        if domain:
            summary_parts.append(f"domain={domain}")
        currencies = post.get("currencies", [])
        if isinstance(currencies, list):
            codes = [str(c.get("code", "")).strip() for c in currencies if isinstance(c, dict)]
            codes = [c for c in codes if c]
            if codes:
                summary_parts.append(f"symbols={','.join(codes[:5])}")
        summary = "; ".join(summary_parts)
        category = ""
        if isinstance(currencies, list):
            codes = [str(c.get("code", "")).strip() for c in currencies if isinstance(c, dict)]
            codes = [c for c in codes if c]
            category = ", ".join(codes[:5])
        items.append(CryptoNewsItem(
            source="cryptopanic",
            title=title,
            url=url,
            published_at=iso_date,
            summary=summary[:500],
            source_type="news",
            category=category,
        ))
    if skipped_no_date:
        logger.warning(
            "Skipped %d CryptoPanic posts with unparseable or out-of-range published_at",
            skipped_no_date,
        )
    return items


def fetch_binance_announcements() -> list[CryptoNewsItem]:
    """Fetch latest Binance announcements (new listings, delistings, upgrades).

    Uses the public JSON API that backs the Binance announcements page.
    Free, no API key required.
    """
    data = _http_get(BINANCE_ANNOUNCE_URL, timeout=_DEFAULT_TIMEOUT)
    if data is None:
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return []

    items: list[CryptoNewsItem] = []
    skipped_no_date = 0
    skipped_bad_date = 0
    articles = payload.get("data", {}).get("articles", [])
    for art in articles:
        title = str(art.get("title", "")).strip()
        code = str(art.get("code", ""))
        release_date = art.get("releaseDate", 0)
        if not title or not code:
            continue
        url = f"https://www.binance.com/en/support/announcement/{code}"
        try:
            dt = datetime.fromtimestamp(release_date / 1000, tz=timezone.utc)
            iso = dt.isoformat()
            if _validate_published_at(iso) is None:
                skipped_bad_date += 1
                continue
        except (ValueError, OSError, OverflowError, TypeError):
            # Do NOT fall back to datetime.now() — that would timestamp
            # every broken article "now", poisoning recency features.
            skipped_no_date += 1
            continue
        items.append(CryptoNewsItem(
            source="binance",
            title=title,
            url=url,
            published_at=iso,
            summary="",
            source_type="announcement",
            category="exchange",
        ))
    if skipped_no_date or skipped_bad_date:
        logger.warning(
            "Skipped %d Binance announcements with unparseable releaseDate and %d with out-of-range dates",
            skipped_no_date, skipped_bad_date,
        )
    return items


def fetch_reddit_crypto(subreddit: str = "CryptoCurrency", limit: int = 25) -> list[CryptoNewsItem]:
    """Fetch hot posts from a crypto subreddit using Reddit's public .json API.

    Free, no API key required (100 req/min for non-commercial use).
    Set a descriptive User-Agent to avoid 429s.
    """
    url = REDDIT_CRYPTO_URL.format(subreddit=subreddit, limit=max(1, min(limit, 100)))
    data = _http_get(url, timeout=_DEFAULT_TIMEOUT)
    if data is None:
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return []

    items: list[CryptoNewsItem] = []
    skipped_no_date = 0
    skipped_bad_date = 0
    posts = payload.get("data", {}).get("children", [])
    for post in posts:
        d = post.get("data", {})
        title = str(d.get("title", "")).strip()
        permalink = str(d.get("permalink", ""))
        created_utc = d.get("created_utc", 0)
        selftext = str(d.get("selftext", ""))[:300]
        if not title:
            continue
        url = f"https://www.reddit.com{permalink}"
        try:
            dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
            iso = dt.isoformat()
            if _validate_published_at(iso) is None:
                skipped_bad_date += 1
                continue
        except (ValueError, TypeError, OSError, OverflowError):
            # Do NOT fall back to datetime.now() — backfills with broken
            # timestamps must not be silently stamped "now".
            skipped_no_date += 1
            continue
        # Build category from post flair if available
        flair = str(d.get("link_flair_text", "")).strip()
        category = flair[:50] if flair else ""
        items.append(CryptoNewsItem(
            source=f"reddit-{subreddit}",
            title=title,
            url=url,
            published_at=iso,
            summary=selftext,
            source_type="social",
            category=category,
        ))
    if skipped_no_date or skipped_bad_date:
        logger.warning(
            "Skipped %d Reddit posts from r/%s with unparseable created_utc and %d with out-of-range dates",
            skipped_no_date, subreddit, skipped_bad_date,
        )
    return items


def fetch_all_crypto_news() -> dict[str, list[CryptoNewsItem]]:
    """Fetch crypto news from all free sources.

    Returns a dict mapping source_name -> list[CryptoNewsItem].
    Sources: RSS feeds (CoinDesk, Cointelegraph, CryptoSlate, Decrypt,
    BitcoinMagazine), Binance announcements, Reddit, and CryptoPanic free API.
    """
    result: dict[str, list[CryptoNewsItem]] = {}

    # RSS feeds: coindesk, cointelegraph, cryptoslate, decrypt, bitcoinmagazine
    rss_items = fetch_crypto_rss_news()
    for item in rss_items:
        result.setdefault(item.source, []).append(item)

    # CryptoPanic free public API (keyless, gracefully degrades if blocked)
    cryptopanic_items = fetch_cryptopanic_free()
    if cryptopanic_items:
        result["cryptopanic"] = cryptopanic_items

    # Binance announcements
    binance_items = fetch_binance_announcements()
    if binance_items:
        result["binance"] = binance_items

    # Reddit subreddits
    for sub in ("CryptoCurrency", "bitcoin", "ethereum"):
        items = fetch_reddit_crypto(sub, limit=15)
        if items:
            result[f"reddit-{sub}"] = items
        time.sleep(_DOMAIN_RATE_LIMIT_SEC)

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
    """Save news items to parquet (append mode by date).

    URL-based deduplication is applied before writing so the same article
    fetched from multiple paths does not get duplicated rows in parquet.
    Articles without a parseable date are dropped here as a defense-in-depth
    guard (callers should already have filtered them out).
    """
    import pandas as pd
    if not items:
        return
    # Defense-in-depth: drop items with no published_at (shouldn't happen if
    # callers honor the contract, but do not let them hit parquet).
    clean: list[CryptoNewsItem] = []
    bad_date = 0
    for item in items:
        if not item.published_at:
            bad_date += 1
            continue
        clean.append(item)
    if bad_date:
        logger.warning(
            "Dropped %d news items with missing published_at before saving %s",
            bad_date, output_path,
        )
    if not clean:
        return
    rows = [item.to_dict() for item in clean]
    df = pd.DataFrame(rows)
    if "url" in df.columns:
        before = len(df)
        df = df.drop_duplicates(subset=["url"], keep="first")
        dropped = before - len(df)
        if dropped:
            logger.warning(
                "Dropped %d duplicate-URL news rows before saving %s",
                dropped, output_path,
            )
    df["fetched_at"] = datetime.now(timezone.utc).isoformat()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
