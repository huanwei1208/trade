"""CLS (财联社) news source: DataSource implementation for real-time flash news.

Fetches from the public 财联社 telegraph (电报) API.
No API key required; rate-limit friendly (paginated, cached).

API endpoint: https://www.cls.cn/nodeapi/updateTelegraphList
Response shape:
  {
    "data": {
      "roll_data": [
        {
          "id": int,
          "title": str,
          "brief": str,
          "content": str,
          "share_url": str,
          "ctime": int,   # unix timestamp (UTC+8)
          "level": str,   # "A"=重点, "B"=普通
          "stock": [...], # linked stocks
        },
        ...
      ]
    }
  }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date, timezone, timedelta
from typing import Literal
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from trade_py.data.source import RawRecord

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

_API_BASE = "https://www.cls.cn/nodeapi/updateTelegraphList"
_PAGE_SIZE = 20
_REQUEST_TIMEOUT = 15
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.cls.cn/telegraph",
    "Accept": "application/json, text/plain, */*",
}


def _make_url(last_time: int = 0) -> str:
    return (
        f"{_API_BASE}?app=CLS&os=web&sv=7.7.5"
        f"&last_time={last_time}&rn={_PAGE_SIZE}&refresh_type=1"
    )


def _parse_article(item: dict) -> RawRecord | None:
    """Parse a single telegraph item into a RawRecord. Returns None on bad data."""
    ctime = item.get("ctime")
    if not ctime:
        return None
    try:
        pub = datetime.fromtimestamp(int(ctime), tz=CST).astimezone(timezone.utc)
    except (ValueError, OSError):
        return None

    title = str(item.get("title", "")).strip()
    brief = str(item.get("brief", "")).strip()
    content = str(item.get("content", "")).strip()
    text = brief or content or title
    if not title and not text:
        return None

    # Append linked stock codes to text for symbol extraction
    stocks = item.get("stock", [])
    if isinstance(stocks, list) and stocks:
        codes = [str(s.get("StockID", "")).strip() for s in stocks if s.get("StockID")]
        if codes:
            text += " " + " ".join(codes)

    url = str(item.get("share_url", "")).strip()
    level = str(item.get("level", "")).strip()

    return RawRecord(
        source_id="cls",
        data_type="news",
        published_at=pub,
        title=title,
        text=text,
        url=url,
        meta={"level": level, "id": item.get("id")},
    )


class ClsSource:
    """Fetches real-time flash news (电报) from 财联社 (CLS).

    Supports the DataSource protocol. Paginates backward in time until
    the `since` boundary is reached.
    """

    source_id: str = "cls"
    data_type: Literal["news"] = "news"

    def __init__(self, max_pages: int = 50, allow_known_hash_early_stop: bool = True) -> None:
        """
        Args:
            max_pages: Safety cap on pagination depth (each page = 20 articles).
        """
        self._max_pages = max_pages
        self._allow_known_hash_early_stop = allow_known_hash_early_stop

    def fetch(self, since: datetime, until: datetime,
              known_hashes: set[str] | None = None,
              progress_cb=None) -> list[RawRecord]:
        since_utc = since.astimezone(timezone.utc)
        until_utc = until.astimezone(timezone.utc)

        records: list[RawRecord] = []
        seen_ids: set[int] = set()
        last_time = 0        # API cursor: 0 = latest page

        for page in range(self._max_pages):
            if progress_cb:
                progress_cb(f"[cls] page {page + 1}: {len(records)} articles so far…")
            url = _make_url(last_time)
            req = Request(url, headers=_HEADERS)
            try:
                with urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except (HTTPError, URLError, json.JSONDecodeError) as exc:
                logger.error("CLS fetch error (page %d): %s", page, exc)
                if progress_cb:
                    progress_cb(f"[cls] page {page + 1}: ERROR {exc}")
                break

            items = (
                payload.get("data", {}).get("roll_data", [])
                if isinstance(payload.get("data"), dict)
                else []
            )
            if not items:
                logger.debug("CLS: empty page at cursor %d, stopping", last_time)
                break

            page_oldest: int | None = None
            for item in items:
                item_id = item.get("id")
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                r = _parse_article(item)
                if r is None:
                    continue

                # Track oldest ctime for next-page cursor
                ctime = int(item.get("ctime", 0))
                if page_oldest is None or ctime < page_oldest:
                    page_oldest = ctime

                if r.published_at > until_utc:
                    continue
                if r.published_at < since_utc:
                    # Older than requested window — stop pagination
                    records.sort(key=lambda x: x.published_at, reverse=True)
                    if progress_cb:
                        progress_cb(f"[cls] reached since boundary — "
                                    f"{len(records)} articles in {page + 1} pages")
                    return records

                # Early stop: if this hash is already in bronze, all older ones will be too
                if self._allow_known_hash_early_stop and known_hashes and r.content_hash in known_hashes:
                    records.sort(key=lambda x: x.published_at, reverse=True)
                    if progress_cb:
                        progress_cb(f"[cls] hit known article on page {page + 1} — "
                                    f"stopping early with {len(records)} new articles")
                    return records

                records.append(r)

            if page_oldest is None:
                break
            last_time = page_oldest

        records.sort(key=lambda x: x.published_at, reverse=True)
        if progress_cb:
            progress_cb(f"[cls] done: {len(records)} articles across {page + 1} pages")
        logger.info("CLS: fetched %d articles across %d pages", len(records), page + 1)
        return records

    def health_check(self) -> dict:
        url = _make_url(0)
        req = Request(url, headers=_HEADERS)
        try:
            with urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            items = (
                payload.get("data", {}).get("roll_data", [])
                if isinstance(payload.get("data"), dict)
                else []
            )
            return {
                "source_id": self.source_id,
                "healthy": True,
                "latest_articles": len(items),
            }
        except Exception as exc:
            return {"source_id": self.source_id, "healthy": False, "error": str(exc)}
