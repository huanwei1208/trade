"""Historical backfill fetcher with channel prioritization and runtime scoring."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from trade_py.intelligence.rss_fetcher import NewsArticle

logger = logging.getLogger(__name__)

_WEIGHTS = {
    "officialness": 0.30,
    "authority": 0.25,
    "quality": 0.20,
    "coverage": 0.15,
    "value": 0.10,
}


@dataclass
class BackfillChannel:
    name: str
    kind: str
    priority: int
    query: str
    languages: list[str]
    meta: dict


def _channels_config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "sentiment_backfill_channels.json"


def _stats_path(data_root: Path) -> Path:
    return data_root / ".metadata" / "backfill_channel_stats.json"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _meta_score(meta: dict) -> float:
    total = 0.0
    for k, w in _WEIGHTS.items():
        total += _clamp(float(meta.get(k, 0.0)), 0.0, 5.0) * w
    return total / 5.0 * 100.0


def _load_stats(data_root: Path) -> dict:
    p = _stats_path(data_root)
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_stats(data_root: Path, stats: dict) -> None:
    p = _stats_path(data_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def _reliability_score(channel_stats: dict) -> float:
    runs = int(channel_stats.get("runs", 0))
    failures = int(channel_stats.get("failures", 0))
    if runs <= 0:
        return 50.0
    return _clamp((1.0 - failures / runs) * 100.0, 0.0, 100.0)


def _rank_score(ch: BackfillChannel, channel_stats: dict) -> float:
    meta_part = _meta_score(ch.meta)
    reliability = _reliability_score(channel_stats)
    priority = _clamp(float(ch.priority), 0.0, 100.0)
    return round(meta_part * 0.60 + reliability * 0.25 + priority * 0.15, 1)


def load_channels(selection: str = "auto") -> list[BackfillChannel]:
    path = _channels_config_path()
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_channels = payload.get("channels", []) if isinstance(payload, dict) else []
    channels: list[BackfillChannel] = []
    req = None
    if selection.strip().lower() not in {"", "auto"}:
        req = {x.strip().lower() for x in selection.split(",") if x.strip()}
    for raw in raw_channels:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status", "active"))
        enabled = bool(raw.get("enabled_default", False))
        if req is None:
            if status not in {"active", "trial"} or not enabled:
                continue
        else:
            if str(raw.get("name", "")).lower() not in req:
                continue
        channels.append(
            BackfillChannel(
                name=str(raw.get("name", "")).strip(),
                kind=str(raw.get("type", "gdelt")).strip().lower(),
                priority=int(raw.get("priority", 50)),
                query=str(raw.get("query", "")).strip(),
                languages=[str(x) for x in raw.get("languages", []) if str(x).strip()],
                meta=dict(raw),
            )
        )
    return [c for c in channels if c.name and c.query]


def _parse_gdelt_dt(raw: str) -> datetime:
    # Example: 20260305112200
    dt = datetime.strptime(raw, "%Y%m%d%H%M%S")
    return dt.replace(tzinfo=timezone.utc)


def _fetch_gdelt(channel: BackfillChannel, since: date, until: date, max_records: int) -> tuple[list[NewsArticle], dict]:
    start = f"{since:%Y%m%d}000000"
    end = f"{until:%Y%m%d}235959"
    query = quote_plus(channel.query)
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc"
        f"?query={query}&mode=ArtList&format=json&maxrecords={max_records}"
        f"&startdatetime={start}&enddatetime={end}&sort=datedesc"
    )
    req = Request(url, headers={"User-Agent": "trade-bot/1.0"})
    diag = {"channel": channel.name, "type": channel.kind, "url": url, "error": "", "fetched": 0}
    try:
        with urlopen(req, timeout=30) as resp:
            payload = json.loads((resp.read() or b"{}").decode("utf-8"))
    except Exception as exc:
        diag["error"] = f"{type(exc).__name__}: {exc}"
        return [], diag

    arts = payload.get("articles", []) if isinstance(payload, dict) else []
    out: list[NewsArticle] = []
    allowed_langs = {x.lower() for x in channel.languages} if channel.languages else set()
    for a in arts:
        if not isinstance(a, dict):
            continue
        lang = str(a.get("language", "")).strip().lower()
        if allowed_langs and lang and lang not in allowed_langs:
            continue
        try:
            pub = _parse_gdelt_dt(str(a.get("seendate", "")))
        except ValueError:
            pub = datetime.now(timezone.utc)
        local_d = pub.astimezone(timezone.utc).date()
        if local_d < since or local_d > until:
            continue
        title = str(a.get("title", "")).strip()
        if not title:
            continue
        url_v = str(a.get("url", "")).strip()
        source = channel.name
        text = " ".join(
            x for x in [
                str(a.get("domain", "")).strip(),
                str(a.get("sourcecountry", "")).strip(),
                str(a.get("language", "")).strip(),
                title,
            ] if x
        )
        out.append(NewsArticle(title=title, text=text, url=url_v, source=source, published_at=pub))
    diag["fetched"] = len(out)
    return out, diag


def fetch_backfill(
    data_root: Path,
    since: date,
    until: date,
    selection: str = "auto",
    max_records_per_channel: int = 250,
) -> tuple[list[NewsArticle], dict]:
    channels = load_channels(selection)
    if not channels:
        return [], {"channels": [], "ranking": [], "diagnostics": [], "total_articles": 0}

    stats = _load_stats(data_root)
    ranking = []
    for ch in channels:
        ch_stats = stats.get(ch.name, {}) if isinstance(stats, dict) else {}
        ranking.append(
            {
                "name": ch.name,
                "type": ch.kind,
                "rank_score": _rank_score(ch, ch_stats),
                "meta_score": round(_meta_score(ch.meta), 1),
                "reliability": round(_reliability_score(ch_stats), 1),
                "priority": ch.priority,
            }
        )
    ranking.sort(key=lambda x: x["rank_score"], reverse=True)
    ranked_name_to_channel = {c.name: c for c in channels}

    all_articles: list[NewsArticle] = []
    diagnostics: list[dict] = []
    for r in ranking:
        ch = ranked_name_to_channel[r["name"]]
        if ch.kind == "gdelt":
            arts, diag = _fetch_gdelt(ch, since=since, until=until, max_records=max_records_per_channel)
        else:
            diag = {"channel": ch.name, "type": ch.kind, "error": f"unsupported channel type: {ch.kind}", "fetched": 0}
            arts = []
        diagnostics.append(diag)
        all_articles.extend(arts)

        st = stats.get(ch.name, {}) if isinstance(stats, dict) else {}
        st["runs"] = int(st.get("runs", 0)) + 1
        if diag.get("error"):
            st["failures"] = int(st.get("failures", 0)) + 1
        st["last_run_at"] = datetime.now(timezone.utc).isoformat()
        st["last_fetched"] = int(diag.get("fetched", 0))
        st["total_articles"] = int(st.get("total_articles", 0)) + int(diag.get("fetched", 0))
        stats[ch.name] = st

    # Deduplicate across channels by content_hash (title/text-based hash)
    uniq: list[NewsArticle] = []
    seen: set[str] = set()
    for a in sorted(all_articles, key=lambda x: x.published_at, reverse=True):
        if a.content_hash in seen:
            continue
        seen.add(a.content_hash)
        uniq.append(a)

    _save_stats(data_root, stats)
    summary = {
        "channels": [r["name"] for r in ranking],
        "ranking": ranking,
        "diagnostics": diagnostics,
        "total_articles": len(uniq),
    }
    return uniq, summary
