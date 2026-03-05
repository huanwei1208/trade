#!/usr/bin/env python3
"""CLI: run daily sentiment pipeline.

Usage:
    python -m scripts.run_sentiment --date 2026-02-24
    python -m scripts.run_sentiment --date 2026-02-24 --dry-run
    python -m scripts.run_sentiment --start 2026-02-01 --end 2026-02-24
    python -m scripts.run_sentiment --start 2026-02-01 --end 2026-02-24 --llm-provider ollama
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from config_context import resolve_repo_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def parse_date(s: str) -> date:
    from datetime import date as dt
    return dt.fromisoformat(s)


_DATE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.parquet$")


def _rss_watermark_path(data_root: str) -> Path:
    return Path(data_root) / ".metadata" / "rss_feed_watermarks.json"


def _load_rss_watermarks(data_root: str) -> dict:
    path = _rss_watermark_path(data_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_rss_watermarks(data_root: str, wm: dict) -> None:
    path = _rss_watermark_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(wm, ensure_ascii=False, indent=2), encoding="utf-8")


def _list_local_bronze_dates(data_root: str, source: str, start: date, end: date) -> list[date]:
    base = Path(data_root) / "raw" / "sentiment" / source
    if not base.exists():
        return []
    dates = []
    for p in base.rglob("*.parquet"):
        if not _DATE_FILE_RE.match(p.name):
            continue
        try:
            d = parse_date(p.stem)
        except ValueError:
            continue
        if start <= d <= end:
            dates.append(d)
    return sorted(set(dates))


def _compute_incremental_since(
    selected_feeds: list[dict],
    watermarks: dict,
    lookback_days: int,
) -> date:
    today = date.today()
    recent_floor = today - timedelta(days=max(2, lookback_days))
    candidates = []
    for f in selected_feeds:
        v = watermarks.get(str(f["name"]))
        if not v:
            continue
        try:
            d = parse_date(str(v))
        except ValueError:
            continue
        candidates.append(d - timedelta(days=lookback_days))
    if not candidates:
        return recent_floor
    return max(min(candidates), recent_floor)


def _load_cli_defaults(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def ensure_rsshub_running(
    base_url: str,
    timeout: float = 3.0,
    retries: int = 2,
    retry_delay: float = 1.0,
) -> None:
    """Raise RuntimeError when RSSHub endpoint is unreachable."""
    probe_url = f"{base_url.rstrip('/')}/healthz"
    req = Request(probe_url, headers={"User-Agent": "trade-bot/1.0"})
    last_error: Exception | None = None
    for i in range(max(1, retries + 1)):
        try:
            with urlopen(req, timeout=timeout) as resp:
                if getattr(resp, "status", 200) >= 400:
                    raise RuntimeError(f"RSSHub probe failed with HTTP {resp.status}: {probe_url}")
                return
        except HTTPError as e:
            last_error = RuntimeError(f"RSSHub probe failed with HTTP {e.code}: {probe_url}")
        except (URLError, TimeoutError) as e:
            last_error = RuntimeError(
                f"RSSHub is not reachable at {base_url} ({type(e).__name__}). "
                f"Start service first (example: cd deployment/rsshub && docker compose up -d)."
            )
        except RuntimeError as e:
            last_error = e

        if i < retries:
            time.sleep(retry_delay)

    raise last_error  # type: ignore[misc]


def ensure_ollama_running(base_url: str, timeout: float = 3.0) -> None:
    """Raise RuntimeError when Ollama endpoint is unreachable."""
    probe_url = f"{base_url.rstrip('/')}/api/version"
    req = Request(probe_url, headers={"User-Agent": "trade-bot/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status >= 400:
                raise RuntimeError(f"Ollama probe failed with HTTP {status}: {probe_url}")
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            if not payload.get("version"):
                raise RuntimeError(
                    f"Ollama probe succeeded but invalid response at {probe_url}: {payload}"
                )
    except HTTPError as e:
        raise RuntimeError(f"Ollama probe failed with HTTP {e.code}: {probe_url}") from e
    except URLError as e:
        raise RuntimeError(
            f"Ollama is not reachable at {base_url}. Start service first "
            f"(example: ollama serve)."
        ) from e
    except TimeoutError as e:
        raise RuntimeError(
            f"Ollama probe timeout at {base_url}. Start/restart service first "
            f"(example: ollama serve)."
        ) from e


def main() -> int:
    raw_argv = sys.argv[1:]
    fetch_mode_explicit = any(
        a == "--fetch-mode" or a.startswith("--fetch-mode=") for a in raw_argv
    )
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--defaults-file",
        default="config/sentiment_cli_defaults.json",
        help="Path to CLI defaults json",
    )
    pre_parser.add_argument(
        "--no-defaults",
        action="store_true",
        help="Ignore defaults file",
    )
    pre_args, _ = pre_parser.parse_known_args()
    cli_defaults = {} if pre_args.no_defaults else _load_cli_defaults(pre_args.defaults_file)

    def d(key: str, fallback):
        return cli_defaults.get(key, fallback)

    parser = argparse.ArgumentParser(
        description="Run sentiment pipeline",
        parents=[pre_parser],
    )
    parser.add_argument("--date", help="Single date (YYYY-MM-DD)")
    parser.add_argument("--start", help="Start date for range (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date for range (YYYY-MM-DD)")
    parser.add_argument(
        "--data-root",
        default=str(resolve_repo_path(d("data_root", "data"))),
        help="Data directory",
    )
    parser.add_argument("--source", default=d("source", "rss"), help="Data source (rss)")
    parser.add_argument(
        "--rss-feeds",
        default=d("rss_feeds", "auto"),
        help="RSS feed names (comma-separated) or 'auto' (default)",
    )
    parser.add_argument(
        "--show-rss-feed-index",
        action=argparse.BooleanOptionalAction,
        default=d("show_rss_feed_index", False),
        help="Print RSS feed index and exit",
    )
    parser.add_argument(
        "--rsshub-base-url",
        default=d("rsshub_base_url", None),
        help="Override RSSHub base URL (e.g. http://127.0.0.1:1200)",
    )
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=d("dry_run", False),
                        help="Fetch articles but skip Claude API")
    parser.add_argument("--api-key", default=d("api_key", None),
                        help="Anthropic API key (default: ANTHROPIC_API_KEY env)")
    parser.add_argument(
        "--llm-provider",
        default=d("llm_provider", "anthropic"),
        choices=["anthropic", "ollama"],
        help="LLM provider for sentiment analysis",
    )
    parser.add_argument("--llm-model", default=d("llm_model", None), help="LLM model name override")
    parser.add_argument(
        "--ollama-base-url",
        default=d("ollama_base_url", None),
        help="Ollama base URL (default: http://127.0.0.1:11434)",
    )
    parser.add_argument(
        "--no-rss-prefetch",
        action="store_true",
        default=d("no_rss_prefetch", False),
        help="Disable range prefetch optimization (fetch RSS every date)",
    )
    parser.add_argument(
        "--fetch-mode",
        default=d("fetch_mode", "incremental"),
        choices=["incremental", "full", "none"],
        help="RSS fetch mode: incremental (default), full (from start), none (local only)",
    )
    parser.add_argument(
        "--rss-incremental-lookback-days",
        type=int,
        default=int(d("rss_incremental_lookback_days", 2)),
        help="Incremental fetch lookback window in days (default: 2)",
    )
    parser.add_argument(
        "--all-range-dates",
        action=argparse.BooleanOptionalAction,
        default=d("all_range_dates", False),
        help="Process all requested range dates (default only local-existing Bronze dates)",
    )
    parser.add_argument(
        "--enable-backfill",
        action=argparse.BooleanOptionalAction,
        default=d("enable_backfill", True),
        help="Enable historical backfill channels in full mode",
    )
    parser.add_argument(
        "--backfill-channels",
        default=d("backfill_channels", "auto"),
        help="Backfill channels (comma-separated) or 'auto'",
    )
    parser.add_argument(
        "--backfill-max-records-per-channel",
        type=int,
        default=int(d("backfill_max_records_per_channel", 250)),
        help="Max records fetched per backfill channel",
    )
    parser.add_argument(
        "--rsshub-probe-timeout",
        type=float,
        default=float(d("rsshub_probe_timeout", 3.0)),
        help="RSSHub probe timeout seconds (default: 3.0)",
    )
    parser.add_argument(
        "--rsshub-probe-retries",
        type=int,
        default=int(d("rsshub_probe_retries", 2)),
        help="RSSHub probe retries on failure (default: 2)",
    )
    args = parser.parse_args()

    # Determine date range
    if args.date and (args.start or args.end):
        print("ERROR: --date cannot be used with --start/--end", file=sys.stderr)
        return 1

    if args.end and not args.start:
        print("ERROR: --end requires --start", file=sys.stderr)
        return 1

    if args.date:
        dates = [parse_date(args.date)]
    elif args.start:
        start = parse_date(args.start)
        end = parse_date(args.end) if args.end else date.today()
        if start > end:
            print(
                f"ERROR: invalid range: start ({start.isoformat()}) > end ({end.isoformat()})",
                file=sys.stderr,
            )
            return 1
        dates = []
        d = start
        while d <= end:
            dates.append(d)
            d += timedelta(days=1)
    else:
        dates = [date.today()]

    # If user requested a historical range but didn't explicitly set fetch mode,
    # prefer full backfill instead of incremental mode from defaults file.
    if args.start and not args.date and not fetch_mode_explicit and args.fetch_mode == "incremental":
        args.fetch_mode = "full"

    # Ensure we can import from project root
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root / "python"))
    rsshub_base_url = (args.rsshub_base_url or os.environ.get("TRADE_RSSHUB_BASE_URL") or
                       "http://127.0.0.1:1200").rstrip("/")
    os.environ["TRADE_RSSHUB_BASE_URL"] = rsshub_base_url
    ollama_base_url = (args.ollama_base_url or os.environ.get("OLLAMA_BASE_URL") or
                       "http://127.0.0.1:11434").rstrip("/")
    os.environ["OLLAMA_BASE_URL"] = ollama_base_url

    if args.source == "rss":
        try:
            ensure_rsshub_running(
                rsshub_base_url,
                timeout=args.rsshub_probe_timeout,
                retries=args.rsshub_probe_retries,
            )
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 3
    if args.llm_provider == "ollama" and not args.dry_run:
        try:
            ensure_ollama_running(ollama_base_url)
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 4

    print(
        "Run config:",
            json.dumps(
                {
                    "llm_provider": args.llm_provider,
                    "llm_model": args.llm_model,
                    "date_count": len(dates),
                    "start": dates[0].isoformat(),
                    "end": dates[-1].isoformat(),
                    "fetch_mode": args.fetch_mode,
                    "fetch_mode_explicit": fetch_mode_explicit,
                    "all_range_dates": bool(args.all_range_dates),
                    "enable_backfill": bool(args.enable_backfill),
                },
                ensure_ascii=False,
            ),
        )

    from trade_py.intelligence.rss_fetcher import resolve_feeds

    selected_feeds = None
    if args.source == "rss":
        try:
            selected_feeds, feed_catalog = resolve_feeds(args.rss_feeds, rsshub_base_url)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if args.show_rss_feed_index:
            print(
                json.dumps(
                    {
                        "selected": [f["name"] for f in selected_feeds],
                        "catalog": feed_catalog,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(
            "RSS feed profile:",
            json.dumps(
                [
                    {
                        "name": f["name"],
                        "status": f["meta"].get("status"),
                        "score": f["meta"].get("score"),
                        "category": f["meta"].get("category"),
                        "authority": f["meta"].get("authority"),
                        "officialness": f["meta"].get("officialness"),
                        "quality": f["meta"].get("quality"),
                        "coverage": f["meta"].get("coverage"),
                        "value": f["meta"].get("value"),
                    }
                    for f in selected_feeds
                ],
                ensure_ascii=False,
            ),
        )

    # Fetch once, then process from local Bronze cache.
    # This avoids one-RSS-request-per-day scans for range analysis.
    use_rss_prefetch = args.source == "rss" and not args.no_rss_prefetch
    if use_rss_prefetch and args.fetch_mode != "none":
        from trade_py.intelligence.sentiment_pipeline import write_bronze
        from trade_py.intelligence.rss_fetcher import fetch_all

        feed_watermarks = _load_rss_watermarks(args.data_root)
        if args.fetch_mode == "full":
            prefetch_since = dates[0]
        else:
            prefetch_since = _compute_incremental_since(
                selected_feeds=selected_feeds or [],
                watermarks=feed_watermarks,
                lookback_days=args.rss_incremental_lookback_days,
            )

        prefetched_articles, prefetch_diag = fetch_all(
            feeds=selected_feeds,
            since=prefetch_since,
            return_diagnostics=True,
        )
        backfill_summary = None
        if args.fetch_mode == "full" and args.enable_backfill:
            from trade_py.intelligence.backfill_fetcher import fetch_backfill
            backfill_articles, backfill_summary = fetch_backfill(
                data_root=Path(args.data_root),
                since=dates[0],
                until=dates[-1],
                selection=args.backfill_channels,
                max_records_per_channel=args.backfill_max_records_per_channel,
            )
            prefetched_articles.extend(backfill_articles)

            # Cross-source dedupe by content hash
            uniq = []
            seen_hash = set()
            for a in sorted(prefetched_articles, key=lambda x: x.published_at, reverse=True):
                if a.content_hash in seen_hash:
                    continue
                seen_hash.add(a.content_hash)
                uniq.append(a)
            prefetched_articles = uniq

        bronze_counts = write_bronze(prefetched_articles, Path(args.data_root), "rss")
        latest_by_source: dict[str, date] = {}
        for a in prefetched_articles:
            prev = latest_by_source.get(a.source)
            if prev is None or a.date > prev:
                latest_by_source[a.source] = a.date
        if latest_by_source:
            for name, d in latest_by_source.items():
                feed_watermarks[name] = d.isoformat()
            _save_rss_watermarks(args.data_root, feed_watermarks)

        if prefetched_articles:
            available_dates = sorted({a.date for a in prefetched_articles})
            print(
                "RSS prefetch coverage:",
                json.dumps(
                    {
                        "mode": args.fetch_mode,
                        "prefetch_since": prefetch_since.isoformat(),
                        "requested_start": dates[0].isoformat(),
                        "requested_end": dates[-1].isoformat(),
                        "fetched_start": available_dates[0].isoformat(),
                        "fetched_end": available_dates[-1].isoformat(),
                        "requested_days": len(dates),
                        "fetched_days": len(available_dates),
                    },
                    ensure_ascii=False,
                ),
            )
        print(
            "RSS prefetch:",
            json.dumps(
                {
                    "mode": args.fetch_mode,
                    "prefetch_since": prefetch_since.isoformat(),
                    "articles": len(prefetched_articles),
                    "by_date": {str(k): v for k, v in bronze_counts.items()},
                    "diagnostics": prefetch_diag,
                    "watermarks": _load_rss_watermarks(args.data_root),
                    "backfill": backfill_summary,
                },
                ensure_ascii=False,
            ),
        )
    elif args.source == "rss" and args.fetch_mode == "none":
        print("RSS prefetch: skipped (fetch_mode=none, local bronze only)")

    if args.source == "rss" and len(dates) > 1 and not args.all_range_dates:
        local_dates = _list_local_bronze_dates(args.data_root, "rss", dates[0], dates[-1])
        missing = len(dates) - len(local_dates)
        print(
            "Local bronze coverage:",
            json.dumps(
                {
                    "requested_days": len(dates),
                    "available_days": len(local_dates),
                    "missing_days": missing,
                    "mode": "process_existing_only",
                },
                ensure_ascii=False,
            ),
        )
        dates = local_dates
        if not dates:
            print("No local Bronze data in requested range; nothing to process.")
            return 0

    total_stats = []
    has_fetch_failure = False
    skipped_empty_days = 0
    from trade_py.intelligence.sentiment_pipeline import run
    for target_date in dates:
        fetch_in_run = (
            args.source == "rss" and args.no_rss_prefetch and args.fetch_mode != "none"
        )
        stats = run(
            target_date=target_date,
            data_root=args.data_root,
            sources=[args.source],
            api_key=args.api_key,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            ollama_base_url=ollama_base_url,
            dry_run=args.dry_run,
            fetch=fetch_in_run if args.source == "rss" else not use_rss_prefetch,
            rss_feeds=selected_feeds,
        )
        total_stats.append(stats)
        day_articles = int(stats.get("sources", {}).get("rss", {}).get("articles_fetched", 0))
        if day_articles <= 0:
            skipped_empty_days += 1
        else:
            print(f"\n=== {target_date} ===")
            print(json.dumps(stats, indent=2, ensure_ascii=False))
        if stats.get("mode") == "fetch_failed":
            has_fetch_failure = True
            print(
                "ERROR: RSS fetch failed (HTTP>=400 or parser error). "
                "Check rss_fetch/fetch_errors in the output.",
                file=sys.stderr,
            )

    if skipped_empty_days > 0:
        print(
            "Daily summary:",
            json.dumps(
                {
                    "empty_days_skipped": skipped_empty_days,
                    "non_empty_days": len(dates) - skipped_empty_days,
                    "total_days": len(dates),
                },
                ensure_ascii=False,
            ),
        )

    return 2 if has_fetch_failure else 0


if __name__ == "__main__":
    sys.exit(main())
