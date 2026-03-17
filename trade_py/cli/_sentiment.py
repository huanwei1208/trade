"""Native implementation of `trade data sentiment` subcommand.

Replaces python/scripts/run_sentiment.py — no sys.path manipulation,
reads defaults from config/defaults.json, calls pipeline modules directly.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from trade_py.infra.settings import default_data_root, resolve_repo_path, load_defaults
from trade_py.data.pipeline.paths import bronze_path, bronze_root
from trade_py.db.settings_db import SettingsDB

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))

_DATE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.parquet$")


# ---------------------------------------------------------------------------
# Health probes
# ---------------------------------------------------------------------------

def _probe_rsshub(base_url: str, timeout: float = 3.0, retries: int = 2) -> None:
    probe = f"{base_url.rstrip('/')}/healthz"
    req = Request(probe, headers={"User-Agent": "trade-bot/1.0"})
    last_err: Exception | None = None
    for i in range(max(1, retries + 1)):
        try:
            with urlopen(req, timeout=timeout) as resp:
                if getattr(resp, "status", 200) >= 400:
                    raise RuntimeError(f"RSSHub probe HTTP {resp.status}: {probe}")
                return
        except (HTTPError, URLError, RuntimeError) as e:
            last_err = RuntimeError(
                f"RSSHub not reachable at {base_url} ({type(e).__name__}: {e}). "
                "Start: cd deployment/rsshub && docker compose up -d"
            )
        if i < retries:
            time.sleep(1.0)
    raise last_err  # type: ignore[misc]


def _probe_ollama(base_url: str, timeout: float = 3.0) -> None:
    probe = f"{base_url.rstrip('/')}/api/version"
    req = Request(probe, headers={"User-Agent": "trade-bot/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode() or "{}")
            if not payload.get("version"):
                raise RuntimeError(f"Ollama unexpected response: {payload}")
    except (HTTPError, URLError) as e:
        raise RuntimeError(
            f"Ollama not reachable at {base_url}: {e}. Run: ollama serve"
        ) from e


# ---------------------------------------------------------------------------
# Local Bronze date listing (for enrich loop filtering)
# ---------------------------------------------------------------------------

def _local_bronze_dates(data_root: str, sources: list[str],
                        start: date, end: date) -> list[date]:
    dates: list[date] = []
    for src in sources:
        base = bronze_root(data_root) / src
        if not base.exists():
            continue
        for p in base.rglob("*.parquet"):
            if not _DATE_FILE_RE.match(p.name):
                continue
            try:
                d = date.fromisoformat(p.stem)
            except ValueError:
                continue
            if start <= d <= end:
                dates.append(d)
    return sorted(set(dates))


def _bronze_path(data_root: str | Path, source_id: str, d: date) -> Path:
    return bronze_path(data_root, source_id, d)


def _silver_path(data_root: str | Path, d: date) -> Path:
    root = Path(data_root)
    return (root / "sentiment" / "silver"
            / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.isoformat()}.parquet")


def _gold_path(data_root: str | Path, d: date) -> Path:
    root = Path(data_root)
    return (root / "sentiment" / "gold"
            / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.isoformat()}.parquet")


def _sentiment_setting(data_root: str, key: str, fallback):
    try:
        return SettingsDB(data_root).get(key, fallback)
    except Exception:
        return fallback


def _sentiment_start_date(data_root: str) -> date:
    value = str(_sentiment_setting(data_root, "sentiment.start", "2024-01-01"))
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return date(2024, 1, 1)


def _sentiment_settle_window_days(data_root: str) -> int:
    value = _sentiment_setting(data_root, "sentiment.settle_window_days", 7)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 7


def _date_span(start: date, end: date) -> list[date]:
    cur = start
    out: list[date] = []
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _contiguous_windows(dates: list[date]) -> list[tuple[date, date]]:
    if not dates:
        return []
    ordered = sorted(set(dates))
    windows: list[tuple[date, date]] = []
    start = end = ordered[0]
    for d in ordered[1:]:
        if d == end + timedelta(days=1):
            end = d
        else:
            windows.append((start, end))
            start = end = d
    windows.append((start, end))
    return windows


def _month_windows(start: date, end: date) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        month_end = date(cur.year + (1 if cur.month == 12 else 0), 1 if cur.month == 12 else cur.month + 1, 1) - timedelta(days=1)
        window_end = min(month_end, end)
        windows.append((cur, window_end))
        cur = window_end + timedelta(days=1)
    return windows


def _build_fetch_windows(dates: list[date], chunk: str, fetch_mode: str) -> list[tuple[date, date]]:
    if not dates:
        return []
    contiguous = _contiguous_windows(dates)
    if chunk == "none":
        return contiguous
    if chunk == "month" or (chunk == "auto" and fetch_mode == "archive"):
        windows: list[tuple[date, date]] = []
        for start, end in contiguous:
            windows.extend(_month_windows(start, end))
        return windows
    return contiguous


def _feed_uses_rsshub(feed: dict) -> bool:
    meta = feed.get("meta") if isinstance(feed.get("meta"), dict) else feed
    return str(meta.get("driver", "rss")).strip().lower() == "rsshub"


def _filter_feed_catalog(
    catalog: list[dict],
    *,
    catalog_name: str | None = None,
    region: str | None = None,
    language: str | None = None,
    active_only: bool = True,
    default_only: bool = False,
    runnable_only: bool = False,
) -> list[dict]:
    feeds = list(catalog)
    if catalog_name:
        want = catalog_name.strip().lower()
        feeds = [feed for feed in feeds if str(feed.get("catalog", "")).strip().lower() == want]
    if region:
        want = region.strip().lower()
        feeds = [feed for feed in feeds if want in str(feed.get("region", "")).strip().lower()]
    if language:
        want = language.strip().lower()
        feeds = [feed for feed in feeds if str(feed.get("language", "")).strip().lower() == want]
    if active_only:
        feeds = [feed for feed in feeds if str(feed.get("status", "active")).lower() in {"active", "trial"}]
    if default_only:
        feeds = [feed for feed in feeds if bool(feed.get("enabled_default", False))]
    if runnable_only:
        feeds = [feed for feed in feeds if bool(feed.get("runnable", False))]
    return feeds


def _bronze_feed_coverage(data_root: Path, feed_name: str, lookback: int) -> dict[str, int]:
    import pandas as pd

    days = 0
    articles = 0
    for offset in range(max(0, lookback)):
        target = date.today() - timedelta(days=offset)
        path = bronze_path(data_root, "rss", target)
        if not path.exists():
            continue
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if "feed_name" in df.columns:
            source_col = df["feed_name"].fillna(df.get("source"))
        else:
            source_col = df.get("source")
        if source_col is None:
            continue
        count = int((source_col.astype(str).str.lower() == feed_name.lower()).sum())
        if count > 0:
            days += 1
            articles += count
    return {"days": days, "articles": articles}


def _prepare_rss_feeds(args, rsshub_base_url: str) -> tuple[list[dict], list[dict]]:
    from trade_py.data.news.rss import resolve_feeds

    try:
        selected_feeds, feed_catalog = resolve_feeds(args.rss_feeds, rsshub_base_url)
    except ValueError as e:
        print(f"ERROR: {e}")
        return [], []

    if getattr(args, "show_rss_feed_index", False):
        print(json.dumps({
            "selected": [f["name"] for f in selected_feeds],
            "catalog": feed_catalog,
        }, ensure_ascii=False, indent=2))
        return selected_feeds, feed_catalog

    if getattr(args, "fetch_mode", "range") != "archive":
        archive_lane = [
            feed for feed in selected_feeds
            if str((feed.get("meta") or {}).get("lane", "")).strip().lower() == "archive"
        ]
        if archive_lane:
            print(
                "WARNING: dropping archive-only feeds from realtime/incremental run:",
                json.dumps([feed["name"] for feed in archive_lane], ensure_ascii=False),
            )
            selected_feeds = [feed for feed in selected_feeds if feed not in archive_lane]

    if getattr(args, "fetch_mode", "range") == "archive":
        requested = str(getattr(args, "rss_feeds", "auto") or "auto").strip().lower()
        if requested in {"", "auto"}:
            selected_feeds = [
                {"name": feed["name"], "url": feed["url"], "meta": feed}
                for feed in feed_catalog
                if bool(feed.get("supports_archive"))
                and str(feed.get("status", "active")).lower() in {"active", "trial"}
            ]
        else:
            archive_only = [feed for feed in selected_feeds if bool(feed.get("meta", {}).get("supports_archive"))]
            dropped = [feed["name"] for feed in selected_feeds if not bool(feed.get("meta", {}).get("supports_archive"))]
            if dropped:
                print("WARNING: archive mode ignores non-archive feeds:", json.dumps(dropped, ensure_ascii=False))
            selected_feeds = archive_only
        if not selected_feeds:
            print("ERROR: archive mode selected no archive-capable feeds")
            return [], []

    rsshub_feeds = [feed for feed in selected_feeds if _feed_uses_rsshub(feed)]
    direct_feeds = [feed for feed in selected_feeds if not _feed_uses_rsshub(feed)]
    if rsshub_feeds and getattr(args, "fetch_mode", "range") != "none":
        try:
            _probe_rsshub(
                rsshub_base_url,
                timeout=args.rsshub_probe_timeout,
                retries=args.rsshub_probe_retries,
            )
        except RuntimeError as e:
            if direct_feeds:
                print(f"WARNING: {e}")
                print(
                    "WARNING: disabling RSSHub-backed feeds for this run:",
                    json.dumps([feed["name"] for feed in rsshub_feeds], ensure_ascii=False),
                )
                selected_feeds = direct_feeds
            else:
                print(f"ERROR: {e}")
                return [], []
    return selected_feeds, feed_catalog


def _range_fetch_and_process_dates(
    data_root: str,
    source_id: str,
    dates: list[date],
    settle_window_days: int,
) -> tuple[list[date], list[date]]:
    if not dates:
        return [], []
    latest = dates[-1]
    recent_floor = latest - timedelta(days=max(0, settle_window_days - 1))
    fetch_dates: list[date] = []
    process_dates: list[date] = []
    for d in dates:
        bronze_exists = _bronze_path(data_root, source_id, d).exists()
        silver_exists = _silver_path(data_root, d).exists()
        gold_exists = _gold_path(data_root, d).exists()
        if d >= recent_floor or not bronze_exists:
            fetch_dates.append(d)
        if not silver_exists or not gold_exists:
            process_dates.append(d)
    return sorted(set(fetch_dates)), sorted(set(process_dates))


# ---------------------------------------------------------------------------
# Argument parser (reads defaults from config/defaults.json)
# ---------------------------------------------------------------------------

def _build_parser(argv: list[str]) -> tuple[argparse.Namespace, bool]:
    """Parse sentiment args with defaults from config/defaults.json.

    Returns (args, fetch_mode_explicit).
    """
    fetch_mode_explicit = any(
        a == "--fetch-mode" or a.startswith("--fetch-mode=") for a in argv
    )
    defs = load_defaults().get("sentiment", {})

    def d(key: str, fallback):
        return defs.get(key, fallback)

    parser = argparse.ArgumentParser(prog="trade data sentiment",
                                     description="News sentiment pipeline")
    parser.add_argument("--date", default=None, help="Single date (YYYY-MM-DD)")
    parser.add_argument("--start", default=None, help="Range start (YYYY-MM-DD)")
    parser.add_argument("--end",   default=None, help="Range end (YYYY-MM-DD)")
    parser.add_argument("--data-root", default=str(default_data_root()),
                        help="Data directory")
    parser.add_argument("--source", default=d("source", "rss"),
                        choices=["rss", "cls", "cctv"],
                        help="Data source")
    parser.add_argument("--rss-feeds", default=d("rss_feeds", "auto"),
                        help="RSS feed names (comma-sep) or 'auto'")
    parser.add_argument("--show-rss-feed-index",
                        action=argparse.BooleanOptionalAction,
                        default=d("show_rss_feed_index", False))
    parser.add_argument("--rsshub-base-url", default=d("rsshub_base_url", None))
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction,
                        default=d("dry_run", False))
    parser.add_argument("--force-enrich", action=argparse.BooleanOptionalAction,
                        default=False, help="忽略 enrichment cache，强制重算 Silver")
    parser.add_argument("--semantic-mode", default=d("semantic_mode", "hybrid"),
                        choices=["hybrid", "base", "llm"],
                        help="情绪语义层模式：hybrid=LLM优先回退base，base=纯规则，llm=保留base但优先LLM")
    parser.add_argument("--api-key", default=d("api_key", None))
    parser.add_argument("--llm-provider", default=d("llm_provider", "anthropic"),
                        choices=["anthropic", "ollama"])
    parser.add_argument("--llm-model", default=d("llm_model", None))
    parser.add_argument("--ollama-base-url", default=d("ollama_base_url", None))
    parser.add_argument("--no-rss-prefetch", action="store_true",
                        default=d("no_rss_prefetch", False))
    parser.add_argument("--fetch-mode", default=d("fetch_mode", "range"),
                        choices=["incremental", "range", "full", "archive", "none"])
    parser.add_argument("--chunk", default=d("chunk", "auto"),
                        choices=["auto", "none", "month"],
                        help="回补抓取分块方式：archive 默认按月，其余默认不分块")
    parser.add_argument("--rss-incremental-lookback-days", type=int,
                        default=int(d("rss_incremental_lookback_days", 2)))
    parser.add_argument("--all-range-dates",
                        action=argparse.BooleanOptionalAction,
                        default=d("all_range_dates", True))
    parser.add_argument("--enable-backfill",
                        action=argparse.BooleanOptionalAction,
                        default=d("enable_backfill", True))
    parser.add_argument("--backfill-channels",
                        default=d("backfill_channels", "auto"))
    parser.add_argument("--backfill-max-records-per-channel", type=int,
                        default=int(d("backfill_max_records_per_channel", 250)))
    parser.add_argument("--rsshub-probe-timeout", type=float,
                        default=float(d("rsshub_probe_timeout", 3.0)))
    parser.add_argument("--rsshub-probe-retries", type=int,
                        default=int(d("rsshub_probe_retries", 2)))
    parser.add_argument("--rss-max-workers", type=int,
                        default=int(d("rss_max_workers", 6)),
                        help="RSS/Archive feed 并发抓取 worker 数")
    parser.add_argument("--rss-fetch-timeout", type=int,
                        default=int(d("rss_fetch_timeout", 20)),
                        help="单个 RSS/Archive 请求超时秒数")
    parser.add_argument("--rss-fetch-retries", type=int,
                        default=int(d("rss_fetch_retries", 2)),
                        help="单个 RSS/Archive 请求失败重试次数")
    parser.add_argument("--show-source-diagnostics",
                        action=argparse.BooleanOptionalAction,
                        default=bool(d("show_source_diagnostics", False)),
                        help="打印完整 source diagnostics 明细")

    args = parser.parse_args(argv)
    setattr(args, "fetch_mode_requested", args.fetch_mode)
    return args, fetch_mode_explicit


# ---------------------------------------------------------------------------
# Date resolution
# ---------------------------------------------------------------------------

def _resolve_dates(args, fetch_mode_explicit: bool) -> list[date] | int:
    if args.date and (args.start or args.end):
        print("ERROR: --date cannot be used with --start/--end")
        return 1
    if args.end and not args.start:
        print("ERROR: --end requires --start")
        return 1

    if args.date:
        dates = [date.fromisoformat(args.date)]
    elif args.start:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else date.today()
        if start > end:
            print(f"ERROR: start ({start}) > end ({end})")
            return 1
        dates = _date_span(start, end)
    else:
        if args.fetch_mode in {"range", "archive"}:
            dates = _date_span(_sentiment_start_date(args.data_root), date.today())
        else:
            dates = [date.today()]

    if args.start and not args.date and args.fetch_mode != "none":
        if args.fetch_mode not in {"full", "range", "archive"}:
            args.fetch_mode = "range"
            setattr(args, "_fetch_mode_auto_switched", True)
            setattr(args, "_fetch_mode_switch_reason", "date_range_requires_range_backfill")
        else:
            setattr(args, "_fetch_mode_auto_switched", False)
            setattr(args, "_fetch_mode_switch_reason", "")
    else:
        setattr(args, "_fetch_mode_auto_switched", False)
        setattr(args, "_fetch_mode_switch_reason", "")

    return dates


# ---------------------------------------------------------------------------
# Source prefetch (Bronze ingestion)
# ---------------------------------------------------------------------------

def _prefetch_sources(args, selected_feeds: list[dict] | None,
                      fetch_dates: list[date], db) -> tuple[list[dict], list[date]]:
    from trade_py.data.pipeline.ingest import ingest

    data_root = Path(args.data_root)
    diagnostics: list[dict] = []
    changed_dates: set[date] = set()
    if not fetch_dates:
        return diagnostics, []

    def _pcb(msg: str) -> None:
        print(msg, flush=True)

    settle_window_days = _sentiment_settle_window_days(args.data_root)
    today = date.today()
    recent_floor = today - timedelta(days=max(0, settle_window_days - 1))
    summaries: list[dict] = []

    def _compact_ingest_summary(summary: dict | None) -> dict | None:
        if not summary:
            return None
        changed_dates = list(summary.get("changed_dates", []) or [])
        return {
            "records_fetched": int(summary.get("records_fetched", 0) or 0),
            "records_new": int(summary.get("records_new", 0) or 0),
            "records_skipped": int(summary.get("records_skipped", 0) or 0),
            "changed_dates": len(changed_dates),
            "first_changed_date": changed_dates[0] if changed_dates else None,
            "last_changed_date": changed_dates[-1] if changed_dates else None,
            "error": str(summary.get("error") or ""),
        }

    def _diagnostic_overview(diags: list[dict]) -> dict:
        rss_like = [d for d in diags if str(d.get("source") or "").strip()]
        failed = [d for d in rss_like if str(d.get("error") or "").strip()]
        slow = sorted(
            rss_like,
            key=lambda d: int(d.get("duration_ms") or 0),
            reverse=True,
        )[:5]
        return {
            "feeds_total": len(rss_like),
            "feeds_failed": len(failed),
            "feeds_slow_top5": [
                {
                    "source": d.get("source"),
                    "driver": d.get("driver"),
                    "duration_ms": int(d.get("duration_ms") or 0),
                    "records_kept": int(d.get("records_kept") or 0),
                    "error": str(d.get("error") or ""),
                }
                for d in slow
            ],
            "failed_sources": [
                {
                    "source": d.get("source"),
                    "driver": d.get("driver"),
                    "error": str(d.get("error") or ""),
                }
                for d in failed[:10]
            ],
        }

    for window_start, window_end in _build_fetch_windows(fetch_dates, args.chunk, args.fetch_mode):
        since_dt = datetime(window_start.year, window_start.month, window_start.day, tzinfo=CST)
        until_dt = datetime(window_end.year, window_end.month, window_end.day, 23, 59, 59, tzinfo=CST)

        if args.source == "rss":
            from trade_py.data.news.rss import RssSource
            primary = RssSource(
                feeds=selected_feeds or [],
                max_workers=int(getattr(args, "rss_max_workers", 6)),
                request_timeout=int(getattr(args, "rss_fetch_timeout", 20)),
                request_retries=int(getattr(args, "rss_fetch_retries", 2)),
            )
        elif args.source == "cls":
            from trade_py.data.news.cls_source import ClsSource
            allow_early_stop = not (args.fetch_mode == "range" and window_end >= recent_floor)
            primary = ClsSource(allow_known_hash_early_stop=allow_early_stop)
        elif args.source == "cctv":
            from trade_py.data.news.akshare_news import CctvNewsSource
            primary = CctvNewsSource()
        else:
            raise ValueError(f"Unknown source: {args.source}")

        primary_diag: list[dict] = []
        primary_summary = ingest(primary, since_dt, until_dt, data_root, db,
                                 diagnostics_out=primary_diag, progress_cb=_pcb)
        diagnostics.extend(primary_diag)
        changed_dates.update(date.fromisoformat(d) for d in primary_summary.get("changed_dates", []))

        backfill_summary = None
        is_recent_window = window_end >= recent_floor
        is_single_day_window = window_start == window_end
        should_backfill = (
            args.source == "rss"
            and args.fetch_mode in {"full", "range"}
            and args.enable_backfill
            and not is_recent_window
            and not is_single_day_window
        )
        if args.source == "rss" and args.fetch_mode in {"full", "range"} and args.enable_backfill and not should_backfill:
            reason = "recent_window" if is_recent_window else "single_day_window"
            print(f"[gdelt] skip backfill for {window_start}~{window_end}: {reason}", flush=True)
        if should_backfill:
            from trade_py.data.news.gdelt.source import GdeltSource
            gdelt = GdeltSource(selection=args.backfill_channels,
                                max_records_per_channel=args.backfill_max_records_per_channel)
            gdelt_diag: list[dict] = []
            gdelt_summary = ingest(gdelt, since_dt, until_dt, data_root, db,
                                   diagnostics_out=gdelt_diag, progress_cb=_pcb)
            diagnostics.extend(gdelt_diag)
            changed_dates.update(date.fromisoformat(d) for d in gdelt_summary.get("changed_dates", []))
            backfill_summary = {"ingest": gdelt_summary, "diagnostics": gdelt_diag}

        summaries.append({
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "primary": _compact_ingest_summary(primary_summary),
            "backfill": {
                "ingest": _compact_ingest_summary(backfill_summary.get("ingest") if backfill_summary else None),
            } if backfill_summary else None,
        })

    prefetch_summary = {
        "source": args.source,
        "mode": args.fetch_mode,
        "fetch_window_count": len(summaries),
        "fetch_windows": summaries,
        "changed_dates": {
            "count": len(changed_dates),
            "first": min(changed_dates).isoformat() if changed_dates else None,
            "last": max(changed_dates).isoformat() if changed_dates else None,
        },
        "diagnostics_summary": _diagnostic_overview(diagnostics),
    }
    print("Source prefetch:", json.dumps(prefetch_summary, ensure_ascii=False))
    if getattr(args, "show_source_diagnostics", False):
        print("Source diagnostics:", json.dumps(diagnostics, ensure_ascii=False))
    return diagnostics, sorted(changed_dates)


# ---------------------------------------------------------------------------
# Pipeline loop (Silver → Gold)
# ---------------------------------------------------------------------------

def _run_pipeline_loop(args, dates: list[date],
                       selected_feeds: list[dict] | None,
                       ollama_base_url: str, db,
                       enrich_sources: list[str] | None = None) -> int:
    from trade_py.data.pipeline.enrich import enrich, _bronze_path
    from trade_py.data.pipeline.aggregate import aggregate

    sources = enrich_sources or [args.source]

    if not args.dry_run and args.semantic_mode != "base":
        from trade_py.intelligence.clients import create_client
        try:
            client = create_client(
                provider=args.llm_provider,
                api_key=args.api_key if args.llm_provider == "anthropic" else None,
                model=args.llm_model or None,
                **({"base_url": ollama_base_url} if args.llm_provider == "ollama" else {}),
            )
        except (ValueError, ImportError) as e:
            print(f"ERROR: Cannot init LLM client: {e}")
            return 4
    else:
        client = None

    skipped_empty = 0
    for target_date in dates:
        if not args.dry_run and client is not None:
            enrich_stats = enrich(data_root=Path(args.data_root),
                                  article_date=target_date,
                                  sources=sources, client=client,
                                  db=db, semantic_mode=args.semantic_mode, dry_run=False,
                                  force=bool(getattr(args, "force_enrich", False)))
        elif not args.dry_run:
            enrich_stats = enrich(data_root=Path(args.data_root),
                                  article_date=target_date,
                                  sources=sources,
                                  client=None,
                                  db=db,
                                  semantic_mode=args.semantic_mode,
                                  dry_run=False,
                                  force=bool(getattr(args, "force_enrich", False)))
        else:
            import pandas as pd
            bronze_rows = sum(
                len(pd.read_parquet(p)) if (p := _bronze_path(
                    Path(args.data_root), src, target_date)).exists() else 0
                for src in sources
            )
            enrich_stats = {"bronze_rows": bronze_rows, "skipped": 0,
                            "analysed": 0, "silver_rows": 0, "mode": "dry_run"}

        if enrich_stats.get("bronze_rows", 0) <= 0:
            skipped_empty += 1
            continue

        gold_stats: dict = {}
        if not args.dry_run:
            gold_stats = aggregate(Path(args.data_root), target_date)

        print(f"\n=== {target_date} ===")
        print(json.dumps({
            "date": target_date.isoformat(),
            "enrich": enrich_stats,
            "gold": gold_stats,
            "api_cost_usd": getattr(client, "estimated_cost", 0.0) if client else 0.0,
            "token_usage": getattr(client, "token_usage", {}) if client else {},
            "semantic_mode": args.semantic_mode,
        }, indent=2, ensure_ascii=False))

    if skipped_empty > 0:
        print("Daily summary:", json.dumps({
            "empty_days_skipped": skipped_empty,
            "non_empty_days": len(dates) - skipped_empty,
            "total_days": len(dates),
            "enrichment_cache": db.enrichment_stats(),
        }, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# Status subcommand — Feed Quality Scores
# ---------------------------------------------------------------------------

def _cmd_status(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="trade data sentiment status")
    p.add_argument("--data-root", default=str(default_data_root()))
    p.add_argument("--lookback", type=int, default=30, help="Lookback window in days")
    args = p.parse_args(argv)

    from trade_py.intelligence.feed_scorer import score_all_sources
    scores = score_all_sources(Path(args.data_root))

    if not scores:
        print("No Bronze data found. Run `trade data sentiment` first.")
        return 0

    print(f"\nFeed Quality Scores (last {args.lookback}d):")
    for s in sorted(scores, key=lambda x: -x.composite):
        print(
            f"  {s.feed_name:<10} "
            f"coverage={s.coverage_30d:.2f}  "
            f"uniqueness={s.uniqueness:.2f}  "
            f"signal_density={s.signal_density:.2f}  "
            f"composite={s.composite:.2f}"
        )
    return 0


def _cmd_sources(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="trade data sentiment sources")
    p.add_argument("--rsshub-base-url", default=None)
    p.add_argument("--catalog", default=None, help="Filter by catalog name")
    p.add_argument("--region", default=None, help="Filter by region")
    p.add_argument("--language", default=None, help="Filter by language")
    p.add_argument("--active-only", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--default-only", action="store_true", help="Only show enabled_default feeds")
    p.add_argument("--runnable-only", action="store_true", help="Only show feeds with a runnable URL")
    p.add_argument("--json", action="store_true", dest="as_json")
    args = p.parse_args(argv)

    rsshub_base_url = (args.rsshub_base_url or
                       os.environ.get("TRADE_RSSHUB_BASE_URL", "http://127.0.0.1:1200")).rstrip("/")

    from trade_py.data.news.rss import build_feed_catalog

    catalog = build_feed_catalog(
        base_url=rsshub_base_url,
        include_inactive=not args.active_only,
        include_unrunnable=not args.runnable_only,
    )
    selected = _filter_feed_catalog(
        catalog,
        catalog_name=args.catalog,
        region=args.region,
        language=args.language,
        active_only=args.active_only,
        default_only=args.default_only,
        runnable_only=args.runnable_only,
    )

    if args.as_json:
        print(json.dumps(selected, ensure_ascii=False, indent=2))
        return 0

    if not selected:
        print("No feeds match the filters.")
        return 0

    print(
        f"{'name':<24} {'catalog':<14} {'region':<8} {'lang':<6} "
        f"{'driver':<8} {'status':<8} {'default':<7} {'modes':<7} url"
    )
    print("-" * 110)
    for feed in selected:
        modes = "".join([
            "R" if feed.get("supports_realtime") else "-",
            "I" if feed.get("supports_incremental") else "-",
            "A" if feed.get("supports_archive") else "-",
        ])
        url = str(feed.get("url") or "")
        print(
            f"{feed['name'][:24]:<24} "
            f"{str(feed.get('catalog', ''))[:14]:<14} "
            f"{str(feed.get('region', ''))[:8]:<8} "
            f"{str(feed.get('language', ''))[:6]:<6} "
            f"{str(feed.get('driver', ''))[:8]:<8} "
            f"{str(feed.get('status', ''))[:8]:<8} "
            f"{str(bool(feed.get('enabled_default', False))):<7} "
            f"{modes:<7} "
            f"{url}"
        )
    print()
    print(f"total={len(selected)}")
    return 0


def _cmd_doctor(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="trade data sentiment doctor")
    p.add_argument("--rss-feeds", default="auto", help="Feed names or selectors like catalog:global_public")
    p.add_argument("--catalog", default=None, help="Filter by catalog when --rss-feeds=auto")
    p.add_argument("--region", default=None, help="Filter by region when --rss-feeds=auto")
    p.add_argument("--language", default=None, help="Filter by language when --rss-feeds=auto")
    p.add_argument("--include-inactive", action="store_true")
    p.add_argument("--include-unrunnable", action="store_true")
    p.add_argument("--lookback", type=int, default=7, help="Inspect Bronze coverage over recent N days")
    p.add_argument("--timeout", type=int, default=8)
    p.add_argument("--rsshub-base-url", default=None)
    p.add_argument("--data-root", default=str(default_data_root()))
    p.add_argument("--json", action="store_true", dest="as_json")
    args = p.parse_args(argv)

    rsshub_base_url = (args.rsshub_base_url or
                       os.environ.get("TRADE_RSSHUB_BASE_URL", "http://127.0.0.1:1200")).rstrip("/")
    from trade_py.data.news.rss import build_feed_catalog, resolve_feeds
    from trade_py.data.news.rss.archive import probe_archive_feed
    from trade_py.data.news.rss.base import _fetch_feed

    full_catalog = build_feed_catalog(
        base_url=rsshub_base_url,
        include_inactive=args.include_inactive,
        include_unrunnable=args.include_unrunnable,
    )
    if args.rss_feeds.strip().lower() in {"", "auto"}:
        feeds = _filter_feed_catalog(
            full_catalog,
            catalog_name=args.catalog,
            region=args.region,
            language=args.language,
            active_only=not args.include_inactive,
            default_only=True,
            runnable_only=not args.include_unrunnable,
        )
    else:
        try:
            selected, _ = resolve_feeds(args.rss_feeds, rsshub_base_url)
        except ValueError as e:
            print(f"ERROR: {e}")
            return 1
        feeds = [feed["meta"] for feed in selected]
        feeds = _filter_feed_catalog(
            feeds,
            catalog_name=args.catalog,
            region=args.region,
            language=args.language,
            active_only=not args.include_inactive,
            default_only=False,
            runnable_only=not args.include_unrunnable,
        )

    if not feeds:
        print("No feeds selected.")
        return 0

    rsshub_error = ""
    if any(_feed_uses_rsshub(feed) for feed in feeds):
        try:
            _probe_rsshub(rsshub_base_url, timeout=float(args.timeout), retries=0)
        except RuntimeError as e:
            rsshub_error = str(e)

    results: list[dict] = []
    cutoff = date.today() - timedelta(days=max(0, args.lookback - 1))
    data_root = Path(args.data_root)
    for feed in feeds:
        coverage = _bronze_feed_coverage(data_root, feed["name"], args.lookback)
        result = {
            "name": feed["name"],
            "catalog": feed.get("catalog"),
            "region": feed.get("region"),
            "language": feed.get("language"),
            "driver": feed.get("driver"),
            "status": feed.get("status"),
            "url": feed.get("url"),
            "healthy": False,
            "http_status": None,
            "entries": 0,
            "bozo": False,
            "error": "",
            "bronze_days": coverage["days"],
            "bronze_articles": coverage["articles"],
            "supports_archive": bool(feed.get("supports_archive", False)),
            "supports_incremental": bool(feed.get("supports_incremental", True)),
        }
        if not feed.get("url"):
            result["error"] = "not runnable"
            results.append(result)
            continue
        if _feed_uses_rsshub(feed) and rsshub_error:
            result["error"] = rsshub_error
            results.append(result)
            continue
        driver = str(feed.get("driver", "rss")).strip().lower()
        if driver in {"rss", "rsshub"}:
            _, status = _fetch_feed(
                str(feed["url"]),
                str(feed["name"]),
                since=cutoff,
                record_meta=None,
                timeout=max(1, int(args.timeout)),
            )
        else:
            status = probe_archive_feed(feed, timeout=max(1, int(args.timeout)))
        result.update({
            "healthy": bool(status.get("http_status")) and int(status["http_status"]) < 400 and not status.get("error"),
            "http_status": status.get("http_status"),
            "entries": status.get("entries", 0),
            "bozo": bool(status.get("bozo", False)),
            "error": status.get("error", ""),
        })
        results.append(result)

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    print(
        f"{'name':<24} {'catalog':<14} {'drv':<7} {'http':<6} {'entries':<8} "
        f"{'bronze7d':<9} {'healthy':<8} error"
    )
    print("-" * 100)
    for result in results:
        print(
            f"{result['name'][:24]:<24} "
            f"{str(result.get('catalog', ''))[:14]:<14} "
            f"{str(result.get('driver', ''))[:7]:<7} "
            f"{str(result.get('http_status', ''))[:6]:<6} "
            f"{str(result.get('entries', 0))[:8]:<8} "
            f"{str(result.get('bronze_days', 0)) + '/' + str(args.lookback):<9} "
            f"{str(result.get('healthy', False)):<8} "
            f"{str(result.get('error', ''))[:80]}"
        )
    healthy = sum(1 for result in results if result.get("healthy"))
    print()
    print(f"healthy={healthy}/{len(results)}")
    return 0


# ---------------------------------------------------------------------------
# Inspect subcommand
# ---------------------------------------------------------------------------

def _cmd_inspect(argv: list[str]) -> int:
    import textwrap
    import pandas as pd

    p = argparse.ArgumentParser(prog="trade data sentiment inspect")
    p.add_argument("source", help="Bronze source: rss, gdelt, cls")
    p.add_argument("date",   help="Date (YYYY-MM-DD)")
    p.add_argument("--feed",          default=None,  help="Filter by feed name")
    p.add_argument("--fetch",         action="store_true", help="Download before display")
    p.add_argument("--rss-feeds",     default="auto")
    p.add_argument("--rsshub-base-url", default=None)
    p.add_argument("--show-text",     action="store_true")
    p.add_argument("--silver",        action="store_true", help="Show Silver rows too")
    p.add_argument("--data-root",     default=str(default_data_root()))
    args = p.parse_args(argv)

    data_root = Path(args.data_root)
    try:
        target = date.fromisoformat(args.date)
    except ValueError:
        print(f"ERROR: invalid date '{args.date}'")
        return 1

    if args.fetch:
        since_dt = datetime(target.year, target.month, target.day, 0, 0, 0, tzinfo=CST)
        until_dt = datetime(target.year, target.month, target.day, 23, 59, 59, tzinfo=CST)

        if args.source == "rss":
            rsshub_url = (args.rsshub_base_url or
                          os.environ.get("TRADE_RSSHUB_BASE_URL", "http://127.0.0.1:1200")).rstrip("/")
            os.environ["TRADE_RSSHUB_BASE_URL"] = rsshub_url
            from trade_py.data.news.rss import RssSource, resolve_feeds
            feeds, _ = resolve_feeds(args.rss_feeds, rsshub_url)
            src_obj = RssSource(feeds=feeds)
        elif args.source == "gdelt":
            from trade_py.data.news.gdelt.source import GdeltSource
            src_obj = GdeltSource()
        elif args.source == "cls":
            from trade_py.data.news.cls_source import ClsSource
            src_obj = ClsSource()
        else:
            print(f"ERROR: unknown source '{args.source}'")
            return 1

        bronze_pre = bronze_path(data_root, args.source, target)
        known: set[str] = set()
        if bronze_pre.exists():
            known = set(pd.read_parquet(bronze_pre, columns=["content_hash"])
                        ["content_hash"].dropna())
            print(f"{len(known)} articles already in bronze")

        import inspect as _insp
        extra: dict = {}
        params = set(_insp.signature(src_obj.fetch).parameters)
        if "known_hashes" in params:
            extra["known_hashes"] = known
        if "progress_cb" in params:
            extra["progress_cb"] = lambda msg: print(msg, flush=True)

        records = src_obj.fetch(since_dt, until_dt, **extra)
        print(f"Fetched: {len(records)} articles")

        if records:
            from trade_py.data.pipeline.ingest import _record_to_row

            dest = bronze_path(data_root, args.source, target)
            dest.parent.mkdir(parents=True, exist_ok=True)
            new_df = pd.DataFrame([_record_to_row(r) for r in records])
            if dest.exists():
                combined = pd.concat([pd.read_parquet(dest), new_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["content_hash"], keep="last")
            else:
                combined = new_df
            combined.to_parquet(dest, index=False)
            print(f"Saved {len(combined)} articles → {dest}")

    y, m, day = target.year, target.month, target.day
    bronze_file = bronze_path(data_root, args.source, target)
    if not bronze_file.exists():
        print(f"No Bronze data: {bronze_file}")
        if not args.fetch:
            print("Tip: add --fetch to download first")
        return 0

    df = pd.read_parquet(bronze_file)
    if args.feed:
        df = df[df["source"].str.lower() == args.feed.lower()]
        if df.empty:
            feeds = sorted(pd.read_parquet(bronze_file)["source"].unique())
            print(f"No articles for feed '{args.feed}'. Available: {feeds}")
            return 0

    feed_counts = df["source"].value_counts().to_dict()
    print(f"\n{'─'*60}")
    print(f"  Bronze  source={args.source}  date={args.date}")
    print(f"  Total articles : {len(df)}")
    print(f"  Feeds          : {json.dumps(feed_counts, ensure_ascii=False)}")
    print(f"{'─'*60}")

    for i, row in df.iterrows():
        pub = str(row.get("published_at", ""))[:19]
        print(f"\n[{i+1}] [{row.get('source','')}] {pub}")
        print(f"  {row.get('title','')}")
        if url := str(row.get("url", "")):
            print(f"  {url}")
        if args.show_text:
            print(f"  {textwrap.shorten(str(row.get('text','')), 200)}")

    if args.silver:
        silver_path = (data_root / "sentiment" / "silver"
                       / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{day:02d}.parquet")
        print(f"\n{'─'*60}")
        if not silver_path.exists():
            print(f"  No Silver data for {args.date}")
        else:
            sdf = pd.read_parquet(silver_path)
            if args.feed:
                sdf = sdf[sdf["source"].str.lower() == args.feed.lower()]
            print(f"  Silver  date={args.date}  rows={len(sdf)}")
            print(f"{'─'*60}")
            cols = [c for c in ["symbol", "source", "sentiment", "score",
                                 "policy_signal", "market_impact_scope",
                                 "time_sensitivity", "title"] if c in sdf.columns]
            print(sdf[cols].to_string(index=False, max_colwidth=60))
    return 0


# ---------------------------------------------------------------------------
# Sample subcommand — random spot-check of Silver articles
# ---------------------------------------------------------------------------

def _cmd_sample(argv: list[str]) -> int:
    import textwrap
    import pandas as pd

    p = argparse.ArgumentParser(prog="trade data sentiment sample")
    p.add_argument("--date", default=None, help="Date to sample (YYYY-MM-DD, default: today)")
    p.add_argument("--label", default=None,
                   choices=["positive", "negative", "neutral"],
                   help="Filter by sentiment label")
    p.add_argument("--source", default=None, help="Filter by source (e.g. rss, cls)")
    p.add_argument("--symbol", default=None, help="Filter by stock symbol")
    p.add_argument("-n", type=int, default=20, help="Number of articles to show")
    p.add_argument("--data-root", default=str(default_data_root()))
    p.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    args = p.parse_args(argv)

    target = date.fromisoformat(args.date) if args.date else date.today()
    data_root = Path(args.data_root)
    y, m, d = target.year, target.month, target.day
    silver_path = (data_root / "sentiment" / "silver"
                   / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{d:02d}.parquet")

    if not silver_path.exists():
        print(f"No Silver data for {target.isoformat()} at {silver_path}")
        print("Tip: run `trade data sentiment --date {date}` first")
        return 1

    df = pd.read_parquet(silver_path)
    if args.label:
        df = df[df["sentiment_label"] == args.label]
    if args.source:
        df = df[df["source"].str.lower() == args.source.lower()]
    if args.symbol:
        df = df[df["symbol"] == args.symbol]

    if df.empty:
        print("No articles match the given filters.")
        return 0

    sample = df.sample(min(args.n, len(df)), random_state=args.seed)

    print(f"\n{'─'*65}")
    print(f"  Silver sample  date={target.isoformat()}  "
          f"label={args.label or 'all'}  n={len(sample)}/{len(df)}")
    print(f"{'─'*65}")

    label_dist = df["sentiment_label"].value_counts().to_dict()
    print(f"  Label distribution: {label_dist}")
    print(f"{'─'*65}\n")

    for i, (_, row) in enumerate(sample.iterrows(), 1):
        label = row.get("sentiment_label", "?")
        conf  = row.get("confidence", float("nan"))
        sym   = row.get("symbol", "?")
        src   = row.get("source", "?")
        pub   = str(row.get("published_at", ""))[:19]
        hash_ = str(row.get("content_hash", ""))[:8]
        title = str(row.get("title", ""))
        print(f"[{i:02d}] [{label.upper():8s} conf={conf:.2f}] {sym}  src={src}  {pub}  #{hash_}")
        print(f"      {textwrap.shorten(title, 80)}")
        print()

    print(f"\nTo correct a label, create data/.corrections/{target.isoformat()}.json")
    print("Then run: trade data sentiment apply-corrections --date", target.isoformat())
    return 0


# ---------------------------------------------------------------------------
# Apply-corrections subcommand — write human labels back to Silver + re-Gold
# ---------------------------------------------------------------------------

def _cmd_apply_corrections(argv: list[str]) -> int:
    import json as _json
    import pandas as pd
    from datetime import datetime as _dt

    p = argparse.ArgumentParser(prog="trade data sentiment apply-corrections")
    p.add_argument("--date", required=True, help="Date to apply corrections (YYYY-MM-DD)")
    p.add_argument("--data-root", default=str(default_data_root()))
    p.add_argument("--dry-run", action="store_true", help="Show what would change without saving")
    args = p.parse_args(argv)

    target = date.fromisoformat(args.date)
    data_root = Path(args.data_root)
    y, m, d = target.year, target.month, target.day

    corrections_path = data_root / ".corrections" / f"{target.isoformat()}.json"
    if not corrections_path.exists():
        print(f"No corrections file: {corrections_path}")
        print("Create it with entries like:")
        print('  [{"content_hash": "a3f9c2d1", "corrected_label": "neutral", "note": "..."}]')
        return 1

    with open(corrections_path) as f:
        corrections: list[dict] = _json.load(f)
    if not corrections:
        print("Corrections file is empty, nothing to apply.")
        return 0

    silver_path = (data_root / "sentiment" / "silver"
                   / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{d:02d}.parquet")
    if not silver_path.exists():
        print(f"No Silver data at {silver_path}")
        return 1

    df = pd.read_parquet(silver_path)
    applied = 0
    training_rows: list[dict] = []

    now_iso = _dt.now(tz=timezone.utc).isoformat()
    for corr in corrections:
        hash_ = corr.get("content_hash", "")
        new_label = corr.get("corrected_label", "")
        if not hash_ or new_label not in ("positive", "negative", "neutral"):
            print(f"  SKIP invalid correction: {corr}")
            continue

        mask = df["content_hash"].str.startswith(hash_)
        if not mask.any():
            print(f"  SKIP hash not found in Silver: {hash_}")
            continue

        orig = df.loc[mask, "sentiment_label"].iloc[0]
        if orig == new_label:
            print(f"  SKIP {hash_}: label already '{new_label}'")
            continue

        if args.dry_run:
            print(f"  DRY  {hash_}: '{orig}' → '{new_label}'  note={corr.get('note','')}")
        else:
            df.loc[mask, "sentiment_label"] = new_label
            # Also update sentiment_score to match label direction
            score_map = {"positive": 0.8, "neutral": 0.0, "negative": -0.8}
            df.loc[mask, "sentiment_score"] = score_map[new_label]
            print(f"  OK   {hash_}: '{orig}' → '{new_label}'")

        applied += 1
        training_rows.append({
            "content_hash": hash_,
            "date": target.isoformat(),
            "original_label": orig,
            "corrected_label": new_label,
            "note": corr.get("note", ""),
            "corrected_by": corr.get("corrected_by", "human"),
            "corrected_at": corr.get("corrected_at", now_iso),
        })

    print(f"\nApplied {applied}/{len(corrections)} corrections"
          + (" (DRY RUN)" if args.dry_run else ""))

    if args.dry_run or applied == 0:
        return 0

    # Write updated Silver parquet
    df.to_parquet(silver_path, index=False)
    print(f"Silver updated: {silver_path}")

    # Append to training corpus
    training_dir = data_root / "training"
    training_dir.mkdir(parents=True, exist_ok=True)
    training_file = training_dir / "human_labels.parquet"
    new_train_df = pd.DataFrame(training_rows)
    if training_file.exists():
        existing = pd.read_parquet(training_file)
        combined = pd.concat([existing, new_train_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["content_hash", "corrected_at"], keep="last")
    else:
        combined = new_train_df
    combined.to_parquet(training_file, index=False)
    print(f"Training corpus: {len(combined)} total corrections at {training_file}")

    # Re-aggregate Gold for the corrected date
    print(f"\nRe-aggregating Gold for {target.isoformat()} ...")
    from trade_py.data.pipeline.aggregate import aggregate
    gold_stats = aggregate(data_root, target)
    print(f"Gold re-aggregated: {gold_stats}")
    return 0


# ---------------------------------------------------------------------------
# Main entry point for `trade data sentiment`
# ---------------------------------------------------------------------------

def _print_sentiment_help() -> None:
    print("""\
Usage: trade data sentiment [subcommand] [options]

新闻情绪流水线：从 RSS/CLS 抓取原文 (Bronze) → LLM 分析 (Silver) → 聚合评分 (Gold)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  主流水线（无子命令）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  --date DATE               只处理单天 (YYYY-MM-DD)
  --start DATE              范围开始日期
  --end DATE                范围结束日期（与 --start 配合，默认今天）
  --source {rss,cls}        数据源，默认 rss
  --fetch-mode MODE         抓取策略：
                              range       仅抓缺失日期，近期数据重抓（默认）
                              incremental 仅抓今天
                              full        强制全量重抓
                              archive     仅抓 archive-capable 官方历史源
                              none        跳过抓取，只跑 LLM 分析
  --chunk {auto,none,month} 历史回补分块；archive 默认按月
  --semantic-mode MODE      语义层模式：hybrid/base/llm，默认 hybrid
  --llm-provider {anthropic,ollama}   LLM 服务，默认 anthropic
  --llm-model MODEL         指定模型（不填用默认）
  --api-key KEY             Anthropic API Key（也可用环境变量 ANTHROPIC_API_KEY）
  --ollama-base-url URL     Ollama 地址，默认 http://127.0.0.1:11434
  --rsshub-base-url URL     RSSHub 地址，默认 http://127.0.0.1:1200
  --rss-feeds FEEDS         RSS feed 名列表（逗号分隔）或 'auto'（默认）
  --no-rss-prefetch         跳过 RSS 抓取阶段，直接用已有 Bronze
  --dry-run                 只统计 Bronze 行数，不调 LLM
  --force-enrich            忽略 enrichment cache，强制重算 Silver
  --data-root DIR           数据目录，默认 data/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  子命令
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  status                    显示各 Feed 的覆盖率/唯一性/信号密度评分
    --lookback N              统计最近 N 天，默认 30
    --data-root DIR

  sources                   显示当前注册的情绪源 catalog
    --catalog NAME            只看某个 catalog，例如 global_public
    --region REGION           按地区过滤，例如 CN / US / EU
    --default-only            只显示默认启用源
    --runnable-only           只显示可直接抓取的源

  doctor                    连通性/近端覆盖诊断
    --rss-feeds FEEDS         源名列表或 selector，例如 catalog:global_public
    --lookback N              检查最近 N 天 Bronze 覆盖
    --json                    输出 JSON

  inspect <source> <date>   查看指定日期的 Bronze 文章列表
    source: rss | gdelt | cls
    --fetch                   先下载再展示
    --feed NAME               只看某个 feed
    --show-text               显示正文摘要
    --silver                  同时展示 Silver 分析结果

  sample                    随机抽样 Silver 文章（人工核查用）
    --date DATE               默认今天
    --label {positive,negative,neutral}  只看某类标签
    --source SOURCE           按来源过滤
    --symbol SYMBOL           按股票代码过滤
    -n N                      显示条数，默认 20

  apply-corrections         将人工校正写回 Silver 并重算 Gold
    --date DATE               必填
    --dry-run                 预览改动但不写入
    校正文件格式 data/.corrections/YYYY-MM-DD.json：
      [{"content_hash": "a3f9c2d1", "corrected_label": "neutral", "note": "..."}]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  常用示例
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  # 跑今天（用 Anthropic，需设置 API Key）
  trade data sentiment

  # 跑指定单天（本地 Ollama）
  trade data sentiment --date 2026-03-05 --llm-provider ollama
  trade data sentiment --date 2026-03-05 --semantic-mode base

  # 补历史范围（只抓缺失天，不重跑已有 Gold）
  trade data sentiment --start 2026-01-01 --end 2026-03-05

  # 跑官方 archive 历史源（默认自动选 archive-capable feeds）
  trade data sentiment --fetch-mode archive --semantic-mode base --start 2025-01-01 --end 2025-12-31

  # 只跑 LLM，不重新抓取（Bronze 已存在）
  trade data sentiment --fetch-mode none --start 2026-01-01 --end 2026-03-05

  # 重算历史 Silver（事件类型升级后用这个）
  trade data sentiment --fetch-mode none --start 2026-01-01 --end 2026-03-05 --force-enrich

  # 用 CLS 数据源
  trade data sentiment --source cls --date 2026-03-05

  # 先预演再正式跑
  trade data sentiment --date 2026-03-05 --dry-run

  # 查看各 feed 质量
  trade data sentiment status

  # 查看已注册的情绪源
  trade data sentiment sources --default-only
  trade data sentiment sources --catalog global_public

  # 检查全球官方源是否可抓
  trade data sentiment doctor --rss-feeds catalog:global_public

  # 检查某天 Bronze + Silver 内容
  trade data sentiment inspect rss 2026-03-05 --silver

  # 现场拉取并查看
  trade data sentiment inspect rss 2026-03-05 --fetch --show-text

  # 人工抽查负面情绪文章
  trade data sentiment sample --date 2026-03-05 --label negative -n 20

  # 写回人工校正
  trade data sentiment apply-corrections --date 2026-03-05 --dry-run
  trade data sentiment apply-corrections --date 2026-03-05
""")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        _print_sentiment_help()
        return 0
    if argv and argv[0] == "status":
        return _cmd_status(argv[1:])
    if argv and argv[0] == "sources":
        return _cmd_sources(argv[1:])
    if argv and argv[0] == "doctor":
        return _cmd_doctor(argv[1:])
    if argv and argv[0] == "inspect":
        return _cmd_inspect(argv[1:])
    if argv and argv[0] == "sample":
        return _cmd_sample(argv[1:])
    if argv and argv[0] == "apply-corrections":
        return _cmd_apply_corrections(argv[1:])

    args, fetch_mode_explicit = _build_parser(argv)

    dates_or_code = _resolve_dates(args, fetch_mode_explicit)
    if isinstance(dates_or_code, int):
        return dates_or_code
    dates: list[date] = dates_or_code

    rsshub_base_url = (args.rsshub_base_url or
                       os.environ.get("TRADE_RSSHUB_BASE_URL", "http://127.0.0.1:1200")).rstrip("/")
    os.environ["TRADE_RSSHUB_BASE_URL"] = rsshub_base_url
    ollama_base_url = (args.ollama_base_url or
                       os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
    os.environ["OLLAMA_BASE_URL"] = ollama_base_url

    selected_feeds = None
    feed_catalog = None
    if args.source == "rss":
        selected_feeds, feed_catalog = _prepare_rss_feeds(args, rsshub_base_url)
        if args.show_rss_feed_index:
            return 0
        if not selected_feeds:
            return 3

    # Service health checks
    if args.source == "cls":
        from trade_py.data.news.cls_source import ClsSource
        hc = ClsSource().health_check()
        if not hc.get("healthy"):
            print(f"ERROR: CLS unhealthy: {hc.get('error', 'unknown')}")
            return 3
    elif args.source == "cctv":
        from trade_py.data.news.akshare_news import CctvNewsSource
        hc = CctvNewsSource().health_check()
        if not hc.get("healthy"):
            print(f"ERROR: CCTV source unhealthy: {hc.get('error', 'unknown')}")
            return 3
    if args.llm_provider == "ollama" and not args.dry_run and args.semantic_mode != "base":
        try:
            _probe_ollama(ollama_base_url)
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return 4

    print("Run config:", json.dumps({
        "llm_provider": args.llm_provider,
        "llm_model": args.llm_model,
        "date_count": len(dates),
        "start": dates[0].isoformat(),
        "end": dates[-1].isoformat(),
        "fetch_mode": args.fetch_mode,
        "fetch_mode_requested": args.fetch_mode_requested,
        "fetch_mode_explicit": fetch_mode_explicit,
        "fetch_mode_auto_switched": getattr(args, "_fetch_mode_auto_switched", False),
        "all_range_dates": bool(args.all_range_dates),
        "enable_backfill": bool(args.enable_backfill),
    }, ensure_ascii=False))

    if args.source == "rss":
        print("RSS feed profile:", json.dumps([{
            "name": f["name"],
            "status": f["meta"].get("status"),
            "score":  f["meta"].get("score"),
            "catalog": f["meta"].get("catalog"),
            "driver": f["meta"].get("driver"),
            "category": f["meta"].get("category"),
        } for f in selected_feeds], ensure_ascii=False))

    backfill_enabled = (args.source == "rss" and args.fetch_mode in {"full", "range"}
                        and getattr(args, "enable_backfill", True))
    enrich_sources = [args.source, "gdelt"] if backfill_enabled else [args.source]

    from trade_py.db.pipeline_db import PipelineDb
    with PipelineDb(Path(args.data_root)) as db:
        process_dates = list(dates)
        fetch_dates = list(dates)
        if args.fetch_mode == "range":
            fetch_dates, process_dates = _range_fetch_and_process_dates(
                args.data_root,
                args.source,
                dates,
                _sentiment_settle_window_days(args.data_root),
            )
        if not args.no_rss_prefetch and args.fetch_mode != "none":
            _, changed_dates = _prefetch_sources(args, selected_feeds, fetch_dates, db)
            process_dates = sorted(set(process_dates).union(changed_dates))
        else:
            print("Source prefetch: skipped")

        if len(process_dates) > 1 and not args.all_range_dates:
            local_dates = _local_bronze_dates(args.data_root, enrich_sources,
                                              process_dates[0], process_dates[-1])
            print("Local bronze coverage:", json.dumps({
                "requested_days": len(process_dates),
                "available_days": len(local_dates),
                "missing_days": len(process_dates) - len(local_dates),
                "sources": enrich_sources,
            }, ensure_ascii=False))
            process_dates = [d for d in process_dates if d in set(local_dates)]
            if not process_dates:
                print("No local Bronze data in range; nothing to process.")
                return 0

        return _run_pipeline_loop(args, process_dates, selected_feeds,
                                  ollama_base_url, db, enrich_sources)
