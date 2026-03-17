"""Feed catalogue helpers: load layered feed catalogs and resolve selection."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from trade_py.infra.settings.catalogs import load_catalog_payload
from trade_py.utils.scoring import meta_score

logger = logging.getLogger(__name__)

_DEFAULT_FEED_CATALOGS = (
    "global_public.json",
    "china_public.json",
    "rss.json",
    "premium.json",
)


def _feed_index_paths() -> list[Path]:
    override = os.environ.get("TRADE_RSS_FEED_INDEX_PATH")
    if override:
        return [Path(part) for part in override.split(os.pathsep) if part.strip()]
    root = Path(__file__).resolve().parents[4] / "config"
    return [root / "feeds" / name for name in _DEFAULT_FEED_CATALOGS]


def _normalize_feed(feed: dict, catalog_name: str) -> dict:
    meta = dict(feed)
    path = str(meta.get("path") or meta.get("url") or "").strip()
    if "driver" not in meta:
        meta["driver"] = "rsshub" if path and not path.startswith(("http://", "https://")) else "rss"
    meta.setdefault("catalog", catalog_name)
    meta.setdefault("provider_kind", "public")
    meta.setdefault("provider_family", catalog_name)
    meta.setdefault("language", "zh" if str(meta.get("region", "")).upper().startswith("CN") else "en")
    meta.setdefault("auth_mode", "none")
    meta.setdefault("lane", "realtime")
    meta.setdefault("fetch_window_policy", "recent_only")
    meta.setdefault("supports_realtime", True)
    meta.setdefault("supports_incremental", True)
    meta.setdefault(
        "supports_archive",
        str(meta.get("fetch_window_policy", "recent_only")).lower() in {"paged_archive", "date_exact"},
    )
    return meta


def _load_catalog(path: Path) -> list[dict]:
    payload = load_catalog_payload(f"catalog.feeds.{path.stem}", str(path.relative_to(Path(__file__).resolve().parents[4])))
    if payload is None:
        return []
    feeds = payload.get("feeds", []) if isinstance(payload, dict) else payload
    if not isinstance(feeds, list):
        logger.warning("RSS feed config has unexpected shape: %s", path)
        return []
    catalog_name = path.stem
    return [
        _normalize_feed(feed, catalog_name)
        for feed in feeds
        if isinstance(feed, dict) and str(feed.get("name", "")).strip()
    ]


def _compute_url(feed: dict, base_url: str) -> str | None:
    raw = str(feed.get("url") or feed.get("path") or "").strip()
    if not raw:
        return None
    if raw.startswith(("http://", "https://")):
        return raw
    if str(feed.get("driver", "rsshub")).lower() != "rsshub":
        return None
    path = raw if raw.startswith("/") else f"/{raw}"
    return f"{base_url}{path}"


def load_feed_index() -> list[dict]:
    """Return merged feed entries from all configured catalogs."""
    feeds: list[dict] = []
    seen_names: set[str] = set()
    paths = _feed_index_paths()
    if not paths:
        return []
    for path in paths:
        loaded = _load_catalog(path)
        if not loaded and not path.exists():
            logger.debug("RSS feed catalog missing: %s", path)
        for feed in loaded:
            key = str(feed.get("name", "")).strip().lower()
            if not key or key in seen_names:
                continue
            seen_names.add(key)
            feeds.append(feed)
    return feeds


def build_feed_catalog(base_url: Optional[str] = None,
                       include_inactive: bool = True,
                       include_unrunnable: bool = True) -> list[dict]:
    """Build feed catalogue with computed URLs and quality scores."""
    base = (base_url or os.environ.get("TRADE_RSSHUB_BASE_URL", "http://127.0.0.1:1200")).rstrip("/")
    catalog = []
    for feed in load_feed_index():
        status = str(feed.get("status", "active"))
        if not include_inactive and status not in {"active", "trial"}:
            continue
        meta = dict(feed)
        meta["url"] = _compute_url(meta, base)
        meta["runnable"] = bool(meta["url"])
        meta["score"] = meta_score(feed)
        if not include_unrunnable and not meta["runnable"]:
            continue
        catalog.append(meta)
    return catalog


def _match_selector(feed: dict, token: str) -> bool:
    needle = token.strip().lower()
    if not needle:
        return False
    if ":" not in needle:
        return str(feed.get("name", "")).strip().lower() == needle
    field, value = needle.split(":", 1)
    if field in {"catalog", "region", "language", "driver", "provider", "provider_kind", "lane", "status"}:
        actual = str(feed.get("provider_kind" if field == "provider" else field, "")).strip().lower()
        return actual == value
    if field in {"default", "enabled"}:
        expected = value in {"1", "true", "yes", "on"}
        return bool(feed.get("enabled_default", False)) == expected
    return False


def resolve_feeds(selection: str = "auto",
                  base_url: Optional[str] = None) -> tuple[list[dict], list[dict]]:
    """Resolve selected feeds from a CLI selection string.

    Returns (selected_feeds, full_catalog).
    """
    catalog = build_feed_catalog(
        base_url=base_url,
        include_inactive=True,
        include_unrunnable=False,
    )
    by_name = {f["name"].lower(): f for f in catalog}
    key = selection.strip().lower()
    if key in {"", "auto"}:
        feeds = [
            {"name": f["name"], "url": f["url"], "meta": f}
            for f in catalog
            if bool(f.get("enabled_default", False))
            and str(f.get("status", "active")) in {"active", "trial"}
        ]
    elif key == "all":
        feeds = [
            {"name": f["name"], "url": f["url"], "meta": f}
            for f in catalog
            if str(f.get("status", "active")) in {"active", "trial"}
        ]
    else:
        req = [x.strip() for x in selection.split(",") if x.strip()]
        selected_names: set[str] = set()
        missing: list[str] = []
        for item in req:
            matches = [feed["name"] for feed in catalog if _match_selector(feed, item)]
            if matches:
                selected_names.update(matches)
                continue
            if item.lower() in by_name:
                selected_names.add(by_name[item.lower()]["name"])
            else:
                missing.append(item)
        if missing and not selected_names:
            raise ValueError(
                f"unknown rss feeds {missing}; available={[f['name'] for f in catalog]}"
            )
        feeds = [
            {"name": feed["name"], "url": feed["url"], "meta": feed}
            for feed in catalog
            if feed["name"] in selected_names
        ]
    return feeds, catalog
