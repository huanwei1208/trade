from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from trade_py.data.warehouse.catalog import import_rss_catalog_rows
from trade_py.utils.html import clean_html


FetchCallable = Callable[[str, int], bytes]


def _default_fetch(url: str, timeout_seconds: int) -> bytes:
    req = Request(url, headers={"User-Agent": "trade-research-bot/1.0"})
    with urlopen(req, timeout=timeout_seconds) as resp:
        return resp.read()


def _stable_hash(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class ControlledFetchPolicy:
    min_interval_seconds: float = 1.0
    timeout_seconds: int = 10
    max_sources: int | None = None
    dry_run: bool = False


def _parse_feed_entries(payload: bytes, source_id: str, fetched_at: str) -> list[dict[str, Any]]:
    try:
        import feedparser
    except ImportError as exc:  # pragma: no cover - dependency exists in project env
        raise ImportError("feedparser is required for RSS parsing") from exc
    feed = feedparser.parse(payload)
    rows: list[dict[str, Any]] = []
    for idx, entry in enumerate(feed.entries):
        title = clean_html(getattr(entry, "title", "") or "")
        summary = clean_html(
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
            or ""
        )
        url = getattr(entry, "link", "") or ""
        published_at = None
        for attr in ("published_parsed", "updated_parsed", "created_parsed"):
            parsed = getattr(entry, attr, None)
            if parsed:
                published_at = datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
                break
        rows.append(
            {
                "source_id": source_id,
                "url": url,
                "title": title,
                "summary": summary,
                "published_at": published_at or fetched_at,
                "fetch_id": _stable_hash(source_id, fetched_at, idx),
            }
        )
    return rows


def controlled_fetch_rss_sources(
    catalog_rows: list[dict[str, Any]] | pd.DataFrame,
    *,
    policy: ControlledFetchPolicy | None = None,
    fetcher: FetchCallable | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch RSS sources serially with conservative rate controls.

    Returns:
        dim_data_source, ods_fetch_attempt, rss_entry_rows

    The output RSS rows are compatible with ``materialize_rss_research_loop``.
    """
    policy = policy or ControlledFetchPolicy()
    fetcher = fetcher or _default_fetch
    dim_data_source = import_rss_catalog_rows(catalog_rows)
    if policy.max_sources is not None:
        dim_data_source = dim_data_source.head(max(0, int(policy.max_sources))).copy()

    attempt_rows: list[dict[str, Any]] = []
    entry_rows: list[dict[str, Any]] = []
    last_request_at = 0.0
    for _, source in dim_data_source.iterrows():
        source_id = str(source["source_id"])
        url = str(source["url"])
        now_monotonic = time.monotonic()
        wait_seconds = max(0.0, float(policy.min_interval_seconds) - (now_monotonic - last_request_at))
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        requested_at = datetime.now(timezone.utc).isoformat()
        last_request_at = time.monotonic()
        started = time.perf_counter()
        status = "dry_run" if policy.dry_run else "ok"
        error_kind = ""
        error_message = ""
        bytes_read = 0
        entries = 0
        payload = b""
        if not policy.dry_run:
            try:
                payload = fetcher(url, int(policy.timeout_seconds))
                bytes_read = len(payload)
                parsed_rows = _parse_feed_entries(payload, source_id, requested_at)
                entries = len(parsed_rows)
                entry_rows.extend(parsed_rows)
            except HTTPError as exc:
                status = "error"
                error_kind = f"http_{exc.code}"
                error_message = str(exc)
            except URLError as exc:
                status = "error"
                error_kind = "url_error"
                error_message = str(exc.reason)
            except TimeoutError as exc:
                status = "error"
                error_kind = "timeout"
                error_message = str(exc)
            except Exception as exc:
                status = "error"
                error_kind = type(exc).__name__
                error_message = str(exc)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        attempt_rows.append(
            {
                "source_id": source_id,
                "url": url,
                "requested_at": requested_at,
                "status": status,
                "error_kind": error_kind,
                "error_message": error_message,
                "elapsed_ms": elapsed_ms,
                "bytes_read": bytes_read,
                "entries": entries,
                "min_interval_seconds": float(policy.min_interval_seconds),
                "timeout_seconds": int(policy.timeout_seconds),
                "payload_hash": _stable_hash(payload) if payload else "",
            }
        )
    return dim_data_source, pd.DataFrame(attempt_rows), pd.DataFrame(entry_rows)
