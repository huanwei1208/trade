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
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def parse_date(s: str) -> date:
    from datetime import date as dt
    return dt.fromisoformat(s)


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
    parser = argparse.ArgumentParser(description="Run sentiment pipeline")
    parser.add_argument("--date", help="Single date (YYYY-MM-DD)")
    parser.add_argument("--start", help="Start date for range (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date for range (YYYY-MM-DD)")
    parser.add_argument("--data-root", default="data", help="Data directory")
    parser.add_argument("--source", default="rss", help="Data source (rss)")
    parser.add_argument(
        "--rss-feeds",
        default="CLS,WSJ,Gelonghui",
        help="Comma-separated RSS feed names to use (e.g. CLS,WSJ,Gelonghui)",
    )
    parser.add_argument(
        "--rsshub-base-url",
        default=None,
        help="Override RSSHub base URL (e.g. http://127.0.0.1:1200)",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch articles but skip Claude API")
    parser.add_argument("--api-key", default=None,
                        help="Anthropic API key (default: ANTHROPIC_API_KEY env)")
    parser.add_argument(
        "--llm-provider",
        default="anthropic",
        choices=["anthropic", "ollama"],
        help="LLM provider for sentiment analysis",
    )
    parser.add_argument("--llm-model", default=None, help="LLM model name override")
    parser.add_argument(
        "--ollama-base-url",
        default=None,
        help="Ollama base URL (default: http://127.0.0.1:11434)",
    )
    parser.add_argument(
        "--no-rss-prefetch",
        action="store_true",
        help="Disable range prefetch optimization (fetch RSS every date)",
    )
    parser.add_argument(
        "--rsshub-probe-timeout",
        type=float,
        default=3.0,
        help="RSSHub probe timeout seconds (default: 3.0)",
    )
    parser.add_argument(
        "--rsshub-probe-retries",
        type=int,
        default=2,
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
            },
            ensure_ascii=False,
        ),
    )

    from trade_py.intelligence.sentiment_pipeline import run, write_bronze
    from trade_py.intelligence.rss_fetcher import build_default_feeds

    selected_feeds = None
    if args.source == "rss":
        all_feeds = build_default_feeds(rsshub_base_url)
        by_name = {f["name"].lower(): f for f in all_feeds}
        requested = [x.strip() for x in args.rss_feeds.split(",") if x.strip()]
        missing = [x for x in requested if x.lower() not in by_name]
        if missing:
            print(
                f"ERROR: unknown --rss-feeds entries: {missing}. "
                f"available={[f['name'] for f in all_feeds]}",
                file=sys.stderr,
            )
            return 1
        selected_feeds = [by_name[x.lower()] for x in requested]

    use_rss_prefetch = (
        args.source == "rss" and len(dates) > 1 and not args.no_rss_prefetch
    )
    if use_rss_prefetch:
        from trade_py.intelligence.rss_fetcher import fetch_all

        prefetched_articles, prefetch_diag = fetch_all(
            feeds=selected_feeds,
            since=dates[0],
            return_diagnostics=True,
        )
        bronze_counts = write_bronze(prefetched_articles, Path(args.data_root), "rss")
        if prefetched_articles:
            available_dates = sorted({a.date for a in prefetched_articles})
            print(
                "RSS prefetch coverage:",
                json.dumps(
                    {
                        "requested_start": dates[0].isoformat(),
                        "requested_end": dates[-1].isoformat(),
                        "available_start": available_dates[0].isoformat(),
                        "available_end": available_dates[-1].isoformat(),
                    },
                    ensure_ascii=False,
                ),
            )
        print(
            "RSS prefetch:",
            json.dumps(
                {
                    "since": dates[0].isoformat(),
                    "articles": len(prefetched_articles),
                    "by_date": {str(k): v for k, v in bronze_counts.items()},
                    "diagnostics": prefetch_diag,
                },
                ensure_ascii=False,
            ),
        )

    total_stats = []
    has_fetch_failure = False
    for target_date in dates:
        print(f"\n=== {target_date} ===")
        stats = run(
            target_date=target_date,
            data_root=args.data_root,
            sources=[args.source],
            api_key=args.api_key,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            ollama_base_url=ollama_base_url,
            dry_run=args.dry_run,
            fetch=not use_rss_prefetch,
            rss_feeds=selected_feeds,
        )
        total_stats.append(stats)
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        if stats.get("mode") == "fetch_failed":
            has_fetch_failure = True
            print(
                "ERROR: RSS fetch failed (HTTP>=400 or parser error). "
                "Check rss_fetch/fetch_errors in the output.",
                file=sys.stderr,
            )

    return 2 if has_fetch_failure else 0


if __name__ == "__main__":
    sys.exit(main())
