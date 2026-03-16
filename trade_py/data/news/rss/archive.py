"""Archive-capable official source adapters used by the RSS ingestion lane."""

from __future__ import annotations

import html
import io
import logging
import re
import time as _time
from datetime import date, datetime, time, timezone
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from trade_py.data.source import RawRecord
from trade_py.utils.html import clean_html

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.I | re.S)
_TITLE_META_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
    re.I | re.S,
)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_FED_LINK_RE = re.compile(
    r'href=["\'](?P<href>/newsevents/(?P<section>speech|testimony|pressreleases)/(?P<ymd>\d{8})/[^"\']+\.htm)["\']',
    re.I,
)


def _http_read(url: str, timeout: int = 30, retries: int = 2) -> tuple[bytes, dict]:
    req = Request(url, headers={"User-Agent": "trade-bot/1.0"})
    last_exc: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            with urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
                headers = {
                    "status": getattr(resp, "status", None),
                    "content_type": resp.headers.get("Content-Type"),
                    "last_modified": resp.headers.get("Last-Modified"),
                }
                return payload, headers
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                wait_sec = min(5.0, 1.25 * (attempt + 1))
                logger.warning(
                    "archive http retry %s attempt %d/%d failed: %s; sleep %.1fs",
                    url,
                    attempt + 1,
                    retries + 1,
                    exc,
                    wait_sec,
                )
                _time.sleep(wait_sec)
            else:
                raise
    raise last_exc or RuntimeError(f"archive http read failed: {url}")


def _decode(payload: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="ignore")


def _article_title(article_html: str, fallback: str = "") -> str:
    for pattern in (_TITLE_META_RE, _TITLE_TAG_RE):
        match = pattern.search(article_html)
        if match:
            title = clean_html(html.unescape(match.group(1)))
            title = re.sub(r"\s*-\s*(Federal Reserve Board|European Central Bank|BIS|IMF|World Bank)\s*$", "", title, flags=re.I)
            if title:
                return title
    return fallback


def _article_text(article_html: str) -> str:
    body = _SCRIPT_RE.sub(" ", article_html)
    for pattern in (
        re.compile(r"<main\b.*?</main>", re.I | re.S),
        re.compile(r"<article\b.*?</article>", re.I | re.S),
        re.compile(r'<div[^>]+id=["\']article["\'][^>]*>.*?</div>', re.I | re.S),
        re.compile(r'<div[^>]+class=["\'][^"\']*article[^"\']*["\'][^>]*>.*?</div>', re.I | re.S),
        re.compile(r"<body\b.*?</body>", re.I | re.S),
    ):
        match = pattern.search(body)
        if match:
            body = match.group(0)
            break
    text = clean_html(html.unescape(_TAG_RE.sub(" ", body)))
    return re.sub(r"\s+", " ", text).strip()


def _published_at_from_day(day: date) -> datetime:
    return datetime.combine(day, time(12, 0), tzinfo=timezone.utc)


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        attr_map = {str(k).lower(): v for k, v in attrs}
        self._href = str(attr_map.get("href") or "").strip() or None
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        text = clean_html(" ".join(self._text_parts))
        if text:
            self.links.append((self._href, text))
        self._href = None
        self._text_parts = []


def _fetch_ecb_speeches_csv(feed_cfg: dict, since: date, until: date, timeout: int, retries: int) -> tuple[list[RawRecord], dict]:
    import pandas as pd

    url = str(feed_cfg.get("url") or "").strip()
    payload, headers = _http_read(url, timeout=timeout, retries=retries)
    df = pd.read_csv(io.BytesIO(payload), sep="|")
    if "date" not in df.columns:
        raise RuntimeError("ECB archive missing `date` column")
    df["date"] = df["date"].astype(str).str.slice(0, 10)
    df = df[(df["date"] >= since.isoformat()) & (df["date"] <= until.isoformat())].copy()
    records: list[RawRecord] = []
    for row in df.itertuples(index=False):
        day = date.fromisoformat(str(getattr(row, "date"))[:10])
        title = clean_html(str(getattr(row, "title", "") or getattr(row, "subtitle", "") or ""))
        subtitle = clean_html(str(getattr(row, "subtitle", "") or ""))
        speakers = clean_html(str(getattr(row, "speakers", "") or ""))
        contents = clean_html(str(getattr(row, "contents", "") or ""))
        text = " ".join(part for part in (subtitle, contents) if part).strip() or title
        records.append(
            RawRecord(
                source_id=str(feed_cfg["name"]),
                data_type="news",
                published_at=_published_at_from_day(day),
                title=title or subtitle or speakers or "ECB speech",
                text=text,
                url=url,
                meta={
                    "archive_driver": "ecb_speeches_csv",
                    "archive_mode": "archive",
                    "speakers": speakers,
                },
            )
        )
    diag = {
        "source": feed_cfg["name"],
        "url": url,
        "http_status": headers.get("status"),
        "entries": len(records),
        "error": "",
    }
    return records, diag


def _fed_year_urls(feed_cfg: dict, start_year: int, end_year: int) -> Iterable[str]:
    template = str(feed_cfg.get("archive_url_template") or "").strip()
    if not template:
        return []
    return [template.format(year=year) for year in range(start_year, end_year + 1)]


def _fetch_fed_archive(feed_cfg: dict, since: date, until: date, timeout: int, retries: int) -> tuple[list[RawRecord], dict]:
    urls = list(_fed_year_urls(feed_cfg, since.year, until.year))
    all_links: dict[str, tuple[date, str]] = {}
    fetched_pages = 0
    for page_url in urls:
        payload, _headers = _http_read(page_url, timeout=timeout, retries=retries)
        fetched_pages += 1
        html_text = _decode(payload)
        parser = _AnchorParser()
        parser.feed(html_text)
        for href, text in parser.links:
            match = _FED_LINK_RE.search(href)
            if not match:
                continue
            day = date.fromisoformat(
                f"{match.group('ymd')[:4]}-{match.group('ymd')[4:6]}-{match.group('ymd')[6:8]}"
            )
            if day < since or day > until:
                continue
            abs_url = urljoin(page_url, match.group("href"))
            all_links.setdefault(abs_url, (day, text))

    records: list[RawRecord] = []
    for article_url, (day, anchor_title) in sorted(all_links.items(), key=lambda item: item[1][0], reverse=True):
        try:
            payload, _headers = _http_read(article_url, timeout=timeout, retries=retries)
        except Exception as exc:
            logger.debug("fed archive article fetch failed %s: %s", article_url, exc)
            continue
        article_html = _decode(payload)
        title = _article_title(article_html, fallback=anchor_title)
        text = _article_text(article_html)
        records.append(
            RawRecord(
                source_id=str(feed_cfg["name"]),
                data_type="news",
                published_at=_published_at_from_day(day),
                title=title or anchor_title,
                text=text or title or anchor_title,
                url=article_url,
                meta={
                    "archive_driver": "fed_archive",
                    "archive_mode": "archive",
                    "archive_kind": str(feed_cfg.get("archive_kind") or ""),
                },
            )
        )

    diag = {
        "source": feed_cfg["name"],
        "url": urls[0] if urls else str(feed_cfg.get("url") or ""),
        "http_status": 200 if fetched_pages else None,
        "entries": len(records),
        "error": "",
        "archive_pages": fetched_pages,
    }
    return records, diag


def fetch_archive_records(
    feed_cfg: dict,
    since: date,
    until: date,
    timeout: int = 30,
    retries: int = 2,
) -> tuple[list[RawRecord], dict]:
    driver = str(feed_cfg.get("driver") or "").strip().lower()
    if driver == "ecb_speeches_csv":
        return _fetch_ecb_speeches_csv(feed_cfg, since, until, timeout, retries)
    if driver == "fed_archive":
        return _fetch_fed_archive(feed_cfg, since, until, timeout, retries)
    raise ValueError(f"Unsupported archive driver: {driver}")


def probe_archive_feed(feed_cfg: dict, timeout: int = 8) -> dict:
    driver = str(feed_cfg.get("driver") or "").strip().lower()
    if driver == "ecb_speeches_csv":
        url = str(feed_cfg.get("url") or "").strip()
        _payload, headers = _http_read(url, timeout=timeout, retries=0)
        return {
            "source": feed_cfg.get("name"),
            "url": url,
            "http_status": headers.get("status"),
            "entries": 0,
            "error": "",
            "bozo": False,
        }
    if driver == "fed_archive":
        urls = list(_fed_year_urls(feed_cfg, date.today().year, date.today().year))
        probe_url = urls[0] if urls else str(feed_cfg.get("url") or "").strip()
        _payload, headers = _http_read(probe_url, timeout=timeout, retries=0)
        return {
            "source": feed_cfg.get("name"),
            "url": probe_url,
            "http_status": headers.get("status"),
            "entries": 0,
            "error": "",
            "bozo": False,
        }
    raise ValueError(f"Unsupported archive driver: {driver}")
