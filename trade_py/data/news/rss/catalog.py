"""Feed catalogue helpers: load feed index, build catalog, resolve feed selection."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from trade_py.utils.scoring import meta_score

logger = logging.getLogger(__name__)


def _feed_index_path() -> Path:
    override = os.environ.get("TRADE_RSS_FEED_INDEX_PATH")
    if override:
        return Path(override)
    root = Path(__file__).resolve().parents[4] / "config"
    return root / "feeds" / "rss.json"


def load_feed_index() -> list[dict]:
    """Return raw feed entries from feed index config."""
    path = _feed_index_path()
    if not path.exists():
        logger.warning("RSS feed index not found: %s", path)
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    feeds = payload.get("feeds", []) if isinstance(payload, dict) else payload
    return [f for f in feeds if isinstance(f, dict) and f.get("name")]


def build_feed_catalog(base_url: Optional[str] = None,
                       include_inactive: bool = True) -> list[dict]:
    """Build feed catalogue with computed URLs and quality scores."""
    base = (base_url or os.environ.get("TRADE_RSSHUB_BASE_URL", "http://127.0.0.1:1200")).rstrip("/")
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
