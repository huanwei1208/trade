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
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from config_context import resolve_repo_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CST = timezone(timedelta(hours=8))


def parse_date(s: str) -> date:
    from datetime import date as dt
    return dt.fromisoformat(s)


_DATE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.parquet$")


def _list_local_bronze_dates(data_root: str, source: str,
                              start: date, end: date) -> list[date]:
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


# ---------------------------------------------------------------------------
# main() split into 4 focused functions
# ---------------------------------------------------------------------------

def _build_parser() -> tuple[argparse.Namespace, dict, bool]:
    """Parse CLI arguments. Returns (args, cli_defaults, fetch_mode_explicit)."""
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
    pre_parser.add_argument("--no-defaults", action="store_true",
                            help="Ignore defaults file")
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
    parser.add_argument("--source", default=d("source", "rss"),
                        choices=["rss", "cls"],
                        help="Data source: rss (default) or cls (财联社)")
    parser.add_argument(
        "--rss-feeds",
        default=d("rss_feeds", "auto"),
        help="RSS feed names (comma-separated) or 'auto'",
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
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction,
                        default=d("dry_run", False),
                        help="Fetch articles but skip Claude API")
    parser.add_argument("--api-key", default=d("api_key", None),
                        help="Anthropic API key (default: ANTHROPIC_API_KEY env)")
    parser.add_argument(
        "--llm-provider",
        default=d("llm_provider", "anthropic"),
        choices=["anthropic", "ollama"],
        help="LLM provider for sentiment analysis",
    )
    parser.add_argument("--llm-model", default=d("llm_model", None),
                        help="LLM model name override")
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
        help="Process all requested range dates (default: only local Bronze dates)",
    )
    parser.add_argument(
        "--enable-backfill",
        action=argparse.BooleanOptionalAction,
        default=d("enable_backfill", True),
        help="Enable GDELT backfill channels in full mode",
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
    return args, cli_defaults, fetch_mode_explicit


def _resolve_dates(args, fetch_mode_explicit: bool) -> list[date] | int:
    """Compute the list of dates to process. Returns list[date] or int exit code on error."""
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
        cur = start
        while cur <= end:
            dates.append(cur)
            cur += timedelta(days=1)
    else:
        dates = [date.today()]

    # Historical range without explicit fetch-mode → prefer full backfill
    if args.start and not args.date and not fetch_mode_explicit and args.fetch_mode == "incremental":
        args.fetch_mode = "full"

    return dates


def _prefetch_sources(args, selected_feeds: list[dict] | None, dates: list[date],
                      db) -> list[dict]:
    """Ingest primary source + optional GDELT backfill into Bronze.

    Supports source=rss and source=cls. Returns diagnostics list.
    """
    from trade_py.data.pipeline.ingest import ingest

    data_root = Path(args.data_root)

    # Compute fetch window from DuckDB coverage or lookback floor
    source_key = args.source
    if args.fetch_mode == "full":
        since_date = dates[0]
    else:
        latest = db.latest_date(source_key)
        lookback = args.rss_incremental_lookback_days
        floor = date.today() - timedelta(days=max(2, lookback))
        since_date = max(latest - timedelta(days=lookback), floor) if latest else floor

    since_dt = datetime(since_date.year, since_date.month, since_date.day, tzinfo=CST)
    until_dt = datetime(dates[-1].year, dates[-1].month, dates[-1].day,
                        23, 59, 59, tzinfo=CST)

    # Build primary source
    if args.source == "rss":
        from trade_py.data.news.rss_source import RssSource
        primary_source = RssSource(feeds=selected_feeds or [])
    elif args.source == "cls":
        from trade_py.data.news.cls_source import ClsSource
        primary_source = ClsSource()
    else:
        raise ValueError(f"Unknown source: {args.source}")

    diagnostics: list[dict] = []
    primary_summary = ingest(primary_source, since_dt, until_dt, data_root, db,
                             diagnostics_out=diagnostics)

    backfill_summary = None
    if args.source == "rss" and args.fetch_mode == "full" and args.enable_backfill:
        from trade_py.data.news.gdelt_source import GdeltSource
        gdelt = GdeltSource(
            selection=args.backfill_channels,
            max_records_per_channel=args.backfill_max_records_per_channel,
        )
        gdelt_diag: list[dict] = []
        gdelt_summary = ingest(gdelt, since_dt, until_dt, data_root, db,
                               diagnostics_out=gdelt_diag)
        backfill_summary = {"ingest": gdelt_summary, "diagnostics": gdelt_diag}

    print(
        "Source prefetch:",
        json.dumps(
            {
                "source": args.source,
                "mode": args.fetch_mode,
                "prefetch_since": since_date.isoformat(),
                "articles": primary_summary.get("records_fetched", 0),
                "new": primary_summary.get("records_new", 0),
                "by_date": primary_summary.get("by_date", {}),
                "diagnostics": diagnostics,
                "backfill": backfill_summary,
                "coverage": db.coverage_report(),
            },
            ensure_ascii=False,
        ),
    )
    return diagnostics


def _run_pipeline_loop(
    args,
    dates: list[date],
    selected_feeds: list[dict] | None,
    use_rss_prefetch: bool,
    ollama_base_url: str,
    db,
) -> int:
    """Run Silver enrichment + Gold aggregation for each date. Returns exit code."""
    from trade_py.data.pipeline.enrich import enrich
    from trade_py.data.pipeline.aggregate import aggregate

    if not args.dry_run:
        from trade_py.intelligence.claude_client import ClaudeClient
        try:
            client = ClaudeClient(
                api_key=args.api_key,
                provider=args.llm_provider,
                model=args.llm_model,
                ollama_base_url=ollama_base_url,
            )
        except (ValueError, ImportError) as e:
            print(f"ERROR: Cannot initialise LLM client: {e}", file=sys.stderr)
            return 4
    else:
        client = None

    skipped_empty_days = 0
    has_fetch_failure = False

    for target_date in dates:
        # Silver enrichment
        enrich_stats: dict = {}
        if not args.dry_run and client is not None:
            enrich_stats = enrich(
                data_root=Path(args.data_root),
                article_date=target_date,
                sources=[args.source],
                client=client,
                db=db,
                dry_run=False,
            )
        else:
            # dry-run: just count bronze rows
            from trade_py.data.pipeline.enrich import _bronze_path
            import pandas as pd
            bronze_path = _bronze_path(Path(args.data_root), args.source, target_date)
            bronze_rows = len(pd.read_parquet(bronze_path)) if bronze_path.exists() else 0
            enrich_stats = {"bronze_rows": bronze_rows, "skipped": 0,
                            "analysed": 0, "silver_rows": 0, "mode": "dry_run"}

        bronze_rows = enrich_stats.get("bronze_rows", 0)
        if bronze_rows <= 0:
            skipped_empty_days += 1
            continue

        # Gold aggregation
        gold_stats: dict = {}
        if not args.dry_run:
            gold_stats = aggregate(Path(args.data_root), target_date)

        stats = {
            "date": target_date.isoformat(),
            "enrich": enrich_stats,
            "gold": gold_stats,
            "api_cost_usd": getattr(client, "estimated_cost", 0.0) if client else 0.0,
            "token_usage": getattr(client, "token_usage", {}) if client else {},
        }
        print(f"\n=== {target_date} ===")
        print(json.dumps(stats, indent=2, ensure_ascii=False))

    if skipped_empty_days > 0:
        print(
            "Daily summary:",
            json.dumps(
                {
                    "empty_days_skipped": skipped_empty_days,
                    "non_empty_days": len(dates) - skipped_empty_days,
                    "total_days": len(dates),
                    "enrichment_cache": db.enrichment_stats(),
                },
                ensure_ascii=False,
            ),
        )

    return 2 if has_fetch_failure else 0


def main() -> int:
    args, _cli_defaults, fetch_mode_explicit = _build_parser()

    dates_or_code = _resolve_dates(args, fetch_mode_explicit)
    if isinstance(dates_or_code, int):
        return dates_or_code
    dates: list[date] = dates_or_code

    # Ensure project root is on sys.path
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
    elif args.source == "cls":
        from trade_py.data.news.cls_source import ClsSource
        hc = ClsSource().health_check()
        if not hc.get("healthy"):
            print(f"ERROR: CLS source unhealthy: {hc.get('error', 'unknown')}", file=sys.stderr)
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

    from trade_py.data.news.rss_source import resolve_feeds

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

    from trade_py.db.pipeline_db import PipelineDb

    with PipelineDb(Path(args.data_root)) as db:
        use_prefetch = not args.no_rss_prefetch
        if use_prefetch and args.fetch_mode != "none":
            _prefetch_sources(args, selected_feeds, dates, db)
        elif args.fetch_mode == "none":
            print("Source prefetch: skipped (fetch_mode=none, local bronze only)")

        if len(dates) > 1 and not args.all_range_dates:
            local_dates = _list_local_bronze_dates(
                args.data_root, args.source, dates[0], dates[-1]
            )
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

        return _run_pipeline_loop(args, dates, selected_feeds, use_prefetch,
                                  ollama_base_url, db)


if __name__ == "__main__":
    sys.exit(main())
