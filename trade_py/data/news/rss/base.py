"""RSS news source: DataSource implementation for RSSHub-proxied feeds."""

from __future__ import annotations

import logging
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timezone, timedelta
from typing import Literal, Optional
from urllib.request import Request, urlopen

from trade_py.data.source import RawRecord
from trade_py.data.news.rss.archive import fetch_archive_records, probe_archive_feed
from trade_py.utils.html import clean_html

# Errors that indicate a network-level failure (DNS, no route, etc.).
# Retrying won't help — fail fast instead of burning the retry budget.
_NO_RETRY_ERRNOS = frozenset({
    -3,    # EAI_AGAIN: DNS temp failure (most common in firewalled envs)
    -2,    # EAI_NONAME: DNS name not found
    11001, # WSAHOST_NOT_FOUND (Windows)
    111,   # ECONNREFUSED
    113,   # EHOSTUNREACH / no route to host
})

CST = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)


def _fetch_feed(feed_url: str, source_name: str,
                since: Optional[date] = None,
                record_meta: dict | None = None,
                timeout: int = 15,
                retries: int = 2) -> tuple[list[RawRecord], dict]:
    """Fetch a single RSS/Atom feed. Returns (records, status_dict)."""
    try:
        import feedparser
    except ImportError:
        raise ImportError("Install feedparser: pip install feedparser>=6.0")

    fetch_status = {
        "source": source_name, "url": feed_url,
        "http_status": None, "bozo": False, "error": "", "entries": 0,
        "driver": "rss", "attempts": 0,
    }
    t0 = _time.perf_counter()
    try:
        req = Request(feed_url, headers={"User-Agent": "trade-bot/1.0"})
        payload = b""
        for attempt in range(max(1, retries + 1)):
            fetch_status["attempts"] = attempt + 1
            try:
                with urlopen(req, timeout=timeout) as resp:
                    payload = resp.read()
                    fetch_status["http_status"] = getattr(resp, "status", None)
                break
            except Exception as e:
                fetch_status["error"] = str(e)
                errno = getattr(e, "errno", None) or getattr(
                    getattr(e, "reason", None), "errno", None
                )
                if errno in _NO_RETRY_ERRNOS:
                    logger.warning(
                        "RSS %s: network unreachable (errno %s) — skipping retries",
                        source_name, errno,
                    )
                    fetch_status["duration_ms"] = int((_time.perf_counter() - t0) * 1000)
                    return [], fetch_status
                if attempt < retries:
                    wait_sec = min(5.0, 1.25 * (attempt + 1))
                    logger.warning(
                        "RSS retry %s attempt %d/%d failed: %s; sleep %.1fs",
                        source_name,
                        attempt + 1,
                        retries + 1,
                        e,
                        wait_sec,
                    )
                    _time.sleep(wait_sec)
                else:
                    logger.error("Failed to fetch %s: %s", feed_url, e)
                    fetch_status["duration_ms"] = int((_time.perf_counter() - t0) * 1000)
                    return [], fetch_status
        feed = feedparser.parse(payload)
    except Exception as e:
        logger.error("Failed to fetch %s: %s", feed_url, e)
        fetch_status["error"] = str(e)
        fetch_status["duration_ms"] = int((_time.perf_counter() - t0) * 1000)
        return [], fetch_status

    status_code = fetch_status["http_status"]
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
            meta=dict(record_meta or {}),
        ))

    fetch_status["duration_ms"] = int((_time.perf_counter() - t0) * 1000)
    logger.info("Fetched %d articles from %s", len(records), source_name)
    return records, fetch_status


def _fetch_from_feed_cfg(
    feed_cfg: dict,
    since_date: date,
    until_date: date,
    *,
    timeout: int = 15,
    retries: int = 2,
) -> tuple[list[RawRecord], dict]:
    meta = feed_cfg.get("meta") if isinstance(feed_cfg.get("meta"), dict) else {}
    driver = str(feed_cfg.get("driver") or meta.get("driver") or "rss").strip().lower()
    supports_archive = bool(feed_cfg.get("supports_archive", meta.get("supports_archive", False)))
    merged_feed = {**meta, **feed_cfg}
    if driver in {"rss", "rsshub"}:
        records, status = _fetch_feed(
            feed_url=feed_cfg["url"],
            source_name=feed_cfg["name"],
            since=since_date,
            record_meta=feed_cfg.get("meta"),
            timeout=timeout,
            retries=retries,
        )
        status["driver"] = driver
        return records, status
    if supports_archive:
        records, status = fetch_archive_records(
            merged_feed,
            since_date,
            until_date,
            timeout=timeout,
            retries=retries,
        )
        status["driver"] = driver
        return records, status
    raise ValueError(f"Unsupported feed driver: {driver}")


class RssSource:
    """Fetches news from a list of RSSHub-proxied feeds."""

    source_id: str = "rss"
    data_type: Literal["news"] = "news"

    def __init__(
        self,
        feeds: list[dict],
        *,
        max_workers: int = 4,
        request_timeout: int = 15,
        request_retries: int = 2,
    ) -> None:
        self._feeds = feeds
        self._max_workers = max(1, int(max_workers))
        self._request_timeout = max(1, int(request_timeout))
        self._request_retries = max(0, int(request_retries))

    def fetch(self, since: datetime, until: datetime,
              known_hashes: set[str] | None = None,
              progress_cb=None) -> list[RawRecord]:
        records, _diag = self.fetch_with_diagnostics(since, until,
                                                      known_hashes=known_hashes,
                                                      progress_cb=progress_cb)
        return records

    def fetch_with_diagnostics(self, since: datetime, until: datetime,
                               known_hashes: set[str] | None = None,
                               progress_cb=None) -> tuple[list[RawRecord], list[dict]]:
        """Like fetch() but also returns per-feed diagnostics."""
        since_date = since.astimezone(CST).date()
        until_date = until.astimezone(CST).date()
        all_records: list[RawRecord] = []
        diagnostics: list[dict] = []
        seen: set[str] = set()
        n_feeds = len(self._feeds)

        def _fetch_one(feed_cfg: dict) -> tuple[list[RawRecord], dict]:
            merged = {**feed_cfg, "meta": self._feed_record_meta(feed_cfg)}
            started = _time.perf_counter()
            records, status = _fetch_from_feed_cfg(
                merged,
                since_date,
                until_date,
                timeout=self._request_timeout,
                retries=self._request_retries,
            )
            status["duration_ms"] = int((_time.perf_counter() - started) * 1000)
            if "meta" in feed_cfg:
                status["meta"] = feed_cfg["meta"]
            return records, status

        def _consume(feed_cfg: dict, records: list[RawRecord], status: dict) -> None:
            diagnostics.append(status)
            n_new = 0
            for r in records:
                if r.published_at.astimezone(CST).date() > until_date:
                    continue
                r = self._post_process_record(r)
                if r.content_hash not in seen:
                    seen.add(r.content_hash)
                    all_records.append(r)
                    n_new += 1
            n_dup = max(0, len(records) - n_new)
            status["records_raw"] = len(records)
            status["records_kept"] = n_new
            status["records_deduped"] = n_dup
            if progress_cb:
                if status.get("error"):
                    progress_cb(
                        f"[rss] {feed_cfg['name']}: ERROR driver={status.get('driver')} "
                        f"time={status.get('duration_ms', 0)}ms | {status.get('error')}"
                    )
                else:
                    progress_cb(
                        f"[rss] {feed_cfg['name']}: kept={n_new} raw={len(records)} dup={n_dup} "
                        f"driver={status.get('driver')} time={status.get('duration_ms', 0)}ms"
                    )

        if self._max_workers <= 1 or n_feeds <= 1:
            for i, feed_cfg in enumerate(self._feeds, 1):
                if progress_cb:
                    progress_cb(f"[rss] {feed_cfg['name']} ({i}/{n_feeds}) fetching…")
                records, status = _fetch_one(feed_cfg)
                _consume(feed_cfg, records, status)
        else:
            with ThreadPoolExecutor(
                max_workers=min(self._max_workers, n_feeds),
                thread_name_prefix="rss",
            ) as pool:
                future_map = {}
                for i, feed_cfg in enumerate(self._feeds, 1):
                    if progress_cb:
                        progress_cb(f"[rss] {feed_cfg['name']} ({i}/{n_feeds}) queued…")
                    future_map[pool.submit(_fetch_one, feed_cfg)] = feed_cfg
                for future in as_completed(future_map):
                    feed_cfg = future_map[future]
                    try:
                        records, status = future.result()
                    except Exception as exc:
                        records = []
                        status = {
                            "source": feed_cfg["name"],
                            "url": feed_cfg.get("url"),
                            "http_status": None,
                            "bozo": False,
                            "error": str(exc),
                            "entries": 0,
                            "driver": str(feed_cfg.get("driver", "rss")).strip().lower(),
                            "duration_ms": 0,
                            "attempts": self._request_retries + 1,
                        }
                    _consume(feed_cfg, records, status)

        all_records.sort(key=lambda r: r.published_at, reverse=True)
        return all_records, diagnostics

    def _post_process_record(self, record: RawRecord) -> RawRecord:
        """Override in subclasses for provider-specific record customization."""
        return record

    def _feed_record_meta(self, feed_cfg: dict) -> dict:
        meta = dict(feed_cfg.get("meta") or {})
        for key in (
            "catalog",
            "driver",
            "provider_kind",
            "provider_family",
            "region",
            "language",
            "auth_mode",
            "lane",
            "fetch_window_policy",
            "supports_realtime",
            "supports_archive",
            "supports_incremental",
            "category",
        ):
            if key in feed_cfg and key not in meta:
                meta[key] = feed_cfg[key]
        meta.setdefault("feed_name", str(feed_cfg.get("name", "")).strip())
        return meta

    def health_check(self) -> dict:
        import os
        from urllib.request import Request, urlopen
        archive_only = self._feeds and all(str(feed.get("driver", "rss")).lower() not in {"rss", "rsshub"} for feed in self._feeds)
        if archive_only:
            healthy = 0
            errors: list[str] = []
            for feed in self._feeds:
                try:
                    status = probe_archive_feed(feed)
                    if int(status.get("http_status") or 0) < 400:
                        healthy += 1
                    elif status.get("error"):
                        errors.append(str(status["error"]))
                except Exception as exc:
                    errors.append(str(exc))
            return {
                "source_id": self.source_id,
                "healthy": healthy == len(self._feeds) and healthy > 0,
                "feeds": len(self._feeds),
                "archive_feeds": healthy,
                "error": "; ".join(errors[:3]) if errors else "",
            }
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
