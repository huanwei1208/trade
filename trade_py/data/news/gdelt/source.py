"""GDELT news source: DataSource implementation for historical backfill.

Reads channel config from DB-first settings (with file baseline fallback) and
calls the GDELT v2 Doc API to fetch articles for a date range.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Literal, Optional
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from trade_py.data.source import RawRecord
from trade_py.infra.settings.catalogs import load_catalog_payload
from trade_py.utils.scoring import meta_score

logger = logging.getLogger(__name__)

def _channels_config_path() -> Path:
    root = Path(__file__).resolve().parents[4] / "config"
    return root / "feeds" / "gdelt.json"


@dataclass
class _Channel:
    name: str
    kind: str
    priority: int
    query: str
    languages: list[str]
    meta: dict


def _load_channels(selection: str = "auto") -> list[_Channel]:
    cfg = _channels_config_path()
    payload = load_catalog_payload("catalog.feeds.gdelt", "config/feeds/gdelt.json")
    if payload is None:
        return []
    raw_channels = payload.get("channels", []) if isinstance(payload, dict) else []
    req = None
    if selection.strip().lower() not in {"", "auto"}:
        req = {x.strip().lower() for x in selection.split(",") if x.strip()}
    channels: list[_Channel] = []
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
        channels.append(_Channel(
            name=str(raw.get("name", "")).strip(),
            kind=str(raw.get("type", "gdelt")).strip().lower(),
            priority=int(raw.get("priority", 50)),
            query=str(raw.get("query", "")).strip(),
            languages=[str(x) for x in raw.get("languages", []) if str(x).strip()],
            meta=dict(raw),
        ))
    return [c for c in channels if c.name and c.query]


def _parse_gdelt_dt(raw: str) -> datetime:
    dt = datetime.strptime(raw, "%Y%m%d%H%M%S")
    return dt.replace(tzinfo=timezone.utc)


_GDELT_RETRY_DELAYS = (5, 15, 30)   # seconds between retries on 429


def _fetch_gdelt_channel(channel: _Channel, since: date, until: date,
                         max_records: int,
                         progress_cb=None) -> tuple[list[RawRecord], dict]:
    start = f"{since:%Y%m%d}000000"
    end = f"{until:%Y%m%d}235959"
    query = quote_plus(channel.query)
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc"
        f"?query={query}&mode=ArtList&format=json&maxrecords={max_records}"
        f"&startdatetime={start}&enddatetime={end}&sort=datedesc"
    )
    req = Request(url, headers={"User-Agent": "trade-bot/1.0"})
    diag = {"channel": channel.name, "type": channel.kind, "url": url,
            "error": "", "fetched": 0}

    if progress_cb:
        progress_cb(f"[gdelt] {channel.name}: fetching {since}~{until}…")

    payload = None
    for attempt, delay in enumerate((*_GDELT_RETRY_DELAYS, None), start=1):
        try:
            with urlopen(req, timeout=30) as resp:
                payload = json.loads((resp.read() or b"{}").decode("utf-8"))
            break
        except HTTPError as exc:
            if exc.code == 429 and delay is not None:
                msg = (f"[gdelt] {channel.name}: 429 rate-limited — "
                       f"waiting {delay}s (attempt {attempt}/{len(_GDELT_RETRY_DELAYS)+1})")
                logger.warning(msg)
                if progress_cb:
                    progress_cb(msg)
                time.sleep(delay)
                continue
            diag["error"] = f"HTTPError: {exc}"
            if progress_cb:
                progress_cb(f"[gdelt] {channel.name}: ERROR {exc}")
            return [], diag
        except Exception as exc:
            diag["error"] = f"{type(exc).__name__}: {exc}"
            if progress_cb:
                progress_cb(f"[gdelt] {channel.name}: ERROR {exc}")
            return [], diag

    if payload is None:
        diag["error"] = "429 Too Many Requests after retries"
        if progress_cb:
            progress_cb(f"[gdelt] {channel.name}: gave up after retries")
        return [], diag

    arts = payload.get("articles", []) if isinstance(payload, dict) else []
    records: list[RawRecord] = []
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
        local_d = pub.date()
        if local_d < since or local_d > until:
            continue
        title = str(a.get("title", "")).strip()
        if not title:
            continue
        text = " ".join(x for x in [
            str(a.get("domain", "")).strip(),
            str(a.get("sourcecountry", "")).strip(),
            str(a.get("language", "")).strip(),
            title,
        ] if x)
        records.append(RawRecord(
            source_id=channel.name,
            data_type="news",
            published_at=pub,
            title=title,
            text=text,
            url=str(a.get("url", "")).strip(),
        ))

    diag["fetched"] = len(records)
    return records, diag


def scan_bronze_channel_offsets(data_root) -> dict[str, datetime]:
    """Scan all bronze/gdelt parquets and return max published_at per channel name.

    Channel name is the value in the `source` column (e.g. 'GDELT_CN_MACRO').
    Used to bootstrap per-channel cursor when no sync_state entry exists yet.
    """
    import pandas as pd
    from pathlib import Path as _Path
    from trade_py.data.pipeline.paths import bronze_root

    root = bronze_root(data_root) / "gdelt"
    offsets: dict[str, datetime] = {}
    if not root.exists():
        return offsets
    for p in root.rglob("*.parquet"):
        try:
            df = pd.read_parquet(p, columns=["source", "published_at"])
            for ch, grp in df.groupby("source"):
                ts = pd.to_datetime(grp["published_at"], utc=True).max()
                if pd.notna(ts):
                    dt = ts.to_pydatetime()
                    existing = offsets.get(str(ch))
                    if existing is None or dt > existing:
                        offsets[str(ch)] = dt
        except Exception:
            continue
    return offsets


def channel_daily_stats(data_root) -> list[dict]:
    """Return per-(channel, date) article counts from bronze/gdelt.

    Each entry: {channel, date, articles, avg_per_day, useless}.
    useless=True when the channel averages < 2 articles/day — good signal
    that the channel query returns nothing relevant and can be disabled.
    """
    import pandas as pd
    from trade_py.data.pipeline.paths import bronze_root

    root = bronze_root(data_root) / "gdelt"
    frames = []
    if not root.exists():
        return []
    for p in root.rglob("*.parquet"):
        try:
            df = pd.read_parquet(p, columns=["source", "published_at"])
            df["date"] = pd.to_datetime(df["published_at"], utc=True).dt.date.astype(str)
            frames.append(df[["source", "date"]])
        except Exception:
            continue
    if not frames:
        return []
    combined = pd.concat(frames, ignore_index=True)
    counts = (
        combined.groupby(["source", "date"])
        .size()
        .reset_index(name="articles")
        .sort_values(["source", "date"])
    )
    avg = counts.groupby("source")["articles"].mean().round(1)
    result = []
    for _, row in counts.iterrows():
        ch = str(row["source"])
        result.append({
            "channel": ch,
            "date": row["date"],
            "articles": int(row["articles"]),
            "avg_per_day": float(avg[ch]),
            "useless": float(avg[ch]) < 2.0,
        })
    return result


class GdeltSource:
    """Fetches historical news articles from GDELT v2 API."""

    source_id: str = "gdelt"
    data_type: Literal["news"] = "news"

    def __init__(self, selection: str = "auto",
                 max_records_per_channel: int = 250) -> None:
        self._selection = selection
        self._max_records = max_records_per_channel

    def fetch(self, since: datetime, until: datetime,
              known_hashes: set[str] | None = None,
              progress_cb=None) -> list[RawRecord]:
        records, _diag = self.fetch_with_diagnostics(since, until,
                                                      known_hashes=known_hashes,
                                                      progress_cb=progress_cb)
        return records

    def fetch_with_diagnostics(self, since: datetime, until: datetime,
                               known_hashes: set[str] | None = None,
                               progress_cb=None) -> tuple[list[RawRecord], dict]:
        channels = _load_channels(self._selection)
        if not channels:
            return [], {"channels": [], "diagnostics": [], "total_articles": 0}

        # Rank channels by meta quality score + priority
        ranking = sorted(
            channels,
            key=lambda c: meta_score(c.meta) * 0.75 + min(c.priority, 100) * 0.25,
            reverse=True,
        )

        since_date = since.date()
        until_date = until.date()
        all_records: list[RawRecord] = []
        diagnostics: list[dict] = []

        for i, ch in enumerate(ranking):
            if i > 0:
                if progress_cb:
                    progress_cb(f"[gdelt] waiting 3s before next channel…")
                time.sleep(3)   # avoid consecutive requests triggering 429
            # if ch.kind == "gdelt":
            #     arts, diag = _fetch_gdelt_channel(
            #         ch, since=since_date, until=until_date,
            #         max_records=self._max_records,
            #         progress_cb=progress_cb,
            #     )
            #     if progress_cb:
            #         n_skip = sum(1 for r in arts
            #                      if known_hashes and r.content_hash in known_hashes)
            #         progress_cb(f"[gdelt] {ch.name}: {len(arts)} articles"
            #                     + (f", {n_skip} already in bronze" if n_skip else ""))
            else:
                diag = {"channel": ch.name, "type": ch.kind,
                        "error": f"unsupported: {ch.kind}", "fetched": 0}
                arts = []
            diagnostics.append(diag)
            all_records.extend(arts)

        # Deduplicate across channels
        uniq: list[RawRecord] = []
        seen: set[str] = set()
        for r in sorted(all_records, key=lambda x: x.published_at, reverse=True):
            if r.content_hash not in seen:
                seen.add(r.content_hash)
                uniq.append(r)

        summary = {
            "channels": [c.name for c in ranking],
            "diagnostics": diagnostics,
            "total_articles": len(uniq),
        }
        return uniq, summary

    def fetch_streaming(self, data_root, db, *,
                        until: datetime | None = None,
                        progress_cb=None) -> dict:
        """Incremental per-channel fetch driven by per-channel timestamp cursors.

        For each active channel:
          1. Read last-fetched timestamp from sync_state (cursor.last_ts).
             If none, bootstrap from the latest published_at in bronze for
             that channel; if bronze is also empty, default to yesterday.
          2. Fetch articles from GDELT covering [since_date, today].
          3. Filter in-memory to keep only articles with published_at > last_ts.
          4. Deduplicate against known hashes already in bronze for that channel.
          5. Append new articles to the per-date bronze parquets.
          6. Advance the cursor to max(new published_at).

        Returns:
          {
            "channels": [{channel, new_articles, fetched_total, offset_before,
                          error}, …],
            "new_articles": int,          # total across all channels
            "stats": channel_daily_stats  # full per-(channel,date) breakdown
          }
        """
        import pandas as pd
        from datetime import timedelta
        from trade_py.data.pipeline.paths import bronze_path, bronze_root
        from trade_py.data.pipeline.ingest import _record_to_row

        now = until or datetime.now(timezone.utc)
        channels = _load_channels(self._selection)
        if not channels:
            return {"channels": [], "new_articles": 0, "stats": []}

        # Bootstrap offsets from bronze for channels with no sync_state yet.
        bronze_offsets = scan_bronze_channel_offsets(data_root)
        # Precompute known hashes per channel from all bronze files (one scan).
        channel_hashes: dict[str, set[str]] = {}
        gdelt_root = bronze_root(data_root) / "gdelt"
        if gdelt_root.exists():
            for p in gdelt_root.rglob("*.parquet"):
                try:
                    df = pd.read_parquet(p, columns=["source", "content_hash"])
                    for ch_name, grp in df.groupby("source"):
                        channel_hashes.setdefault(str(ch_name), set()).update(
                            grp["content_hash"].dropna()
                        )
                except Exception:
                    continue

        total_new = 0
        channel_results = []

        for ch_idx, ch in enumerate(channels):
            # ── 1. Resolve offset ──────────────────────────────────────────
            cursor = db.sync_state_get_cursor("gdelt_channel", ch.name)
            last_ts: datetime | None = None
            if cursor.get("last_ts"):
                try:
                    last_ts = datetime.fromisoformat(cursor["last_ts"])
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            if last_ts is None:
                last_ts = bronze_offsets.get(ch.name)
            if last_ts is None:
                last_ts = (now - timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )

            since_date = last_ts.date()
            until_date = now.date()

            if progress_cb:
                progress_cb(
                    f"[streaming] {ch.name}: {since_date}→{until_date}"
                    f" (cursor {last_ts.strftime('%Y-%m-%dT%H:%M')})"
                )

            # ── 2. Fetch ────────────────────────────────────────────────────
            if ch_idx > 0:
                time.sleep(3)   # rate-limit guard between channels
            arts, diag = _fetch_gdelt_channel(
                ch, since=since_date, until=until_date,
                max_records=self._max_records,
                progress_cb=progress_cb,
            )

            # ── 3+4. Timestamp filter + dedup ───────────────────────────────
            known = channel_hashes.get(ch.name, set())
            new_arts = [
                r for r in arts
                if r.published_at > last_ts and r.content_hash not in known
            ]

            # ── 5. Write to bronze (grouped by published date) ──────────────
            if new_arts:
                by_date: dict[date, list] = {}
                for r in new_arts:
                    by_date.setdefault(r.published_at.date(), []).append(r)

                for d, recs in by_date.items():
                    dest = bronze_path(data_root, "gdelt", d)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    new_df = pd.DataFrame([_record_to_row(r) for r in recs])
                    if dest.exists():
                        existing = pd.read_parquet(dest)
                        combined = pd.concat([existing, new_df], ignore_index=True)
                        combined = combined.drop_duplicates(
                            subset=["content_hash"], keep="last"
                        )
                    else:
                        combined = new_df
                    combined.to_parquet(dest, index=False)

                # ── 6. Advance cursor ────────────────────────────────────────
                new_offset = max(r.published_at for r in new_arts)
                db.sync_state_set(
                    "gdelt_channel", ch.name, "",
                    last_date=new_offset.date(),
                    cursor={"last_ts": new_offset.isoformat()},
                )
                # Update local hash cache so later channels see correct state
                channel_hashes.setdefault(ch.name, set()).update(
                    r.content_hash for r in new_arts
                )

            total_new += len(new_arts)
            channel_results.append({
                "channel": ch.name,
                "new_articles": len(new_arts),
                "fetched_total": diag.get("fetched", 0),
                "offset_before": last_ts.isoformat(),
                "error": diag.get("error", ""),
            })

        return {
            "channels": channel_results,
            "new_articles": total_new,
            "stats": channel_daily_stats(data_root),
        }

    def health_check(self) -> dict:
        channels = _load_channels(self._selection)
        return {
            "source_id": self.source_id,
            "healthy": True,
            "channels": len(channels),
            "note": "GDELT API is external; no upfront probe performed",
        }
