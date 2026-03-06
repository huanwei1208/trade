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

from trade_py.config import default_data_root, resolve_repo_path
from trade_py.config.defaults import load_defaults

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
        base = Path(data_root) / "raw" / "sentiment" / src
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
                        choices=["rss", "cls"],
                        help="Data source")
    parser.add_argument("--rss-feeds", default=d("rss_feeds", "auto"),
                        help="RSS feed names (comma-sep) or 'auto'")
    parser.add_argument("--show-rss-feed-index",
                        action=argparse.BooleanOptionalAction,
                        default=d("show_rss_feed_index", False))
    parser.add_argument("--rsshub-base-url", default=d("rsshub_base_url", None))
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction,
                        default=d("dry_run", False))
    parser.add_argument("--api-key", default=d("api_key", None))
    parser.add_argument("--llm-provider", default=d("llm_provider", "anthropic"),
                        choices=["anthropic", "ollama"])
    parser.add_argument("--llm-model", default=d("llm_model", None))
    parser.add_argument("--ollama-base-url", default=d("ollama_base_url", None))
    parser.add_argument("--no-rss-prefetch", action="store_true",
                        default=d("no_rss_prefetch", False))
    parser.add_argument("--fetch-mode", default=d("fetch_mode", "incremental"),
                        choices=["incremental", "full", "none"])
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
        cur, dates = start, []
        while cur <= end:
            dates.append(cur)
            cur += timedelta(days=1)
    else:
        dates = [date.today()]

    if args.start and not args.date and args.fetch_mode != "none":
        if args.fetch_mode != "full":
            args.fetch_mode = "full"
            setattr(args, "_fetch_mode_auto_switched", True)
            setattr(args, "_fetch_mode_switch_reason", "date_range_requires_full_backfill")
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
                      dates: list[date], db) -> list[dict]:
    from trade_py.data.pipeline.ingest import ingest

    data_root = Path(args.data_root)
    source_key = args.source

    if args.fetch_mode == "full":
        since_date = dates[0]
    else:
        latest = db.latest_date(source_key)
        lookback = args.rss_incremental_lookback_days
        floor = date.today() - timedelta(days=max(2, lookback))
        since_date = max(latest - timedelta(days=lookback), floor) if latest else floor

    since_dt = datetime(since_date.year, since_date.month, since_date.day, tzinfo=CST)
    until_dt = datetime(dates[-1].year, dates[-1].month, dates[-1].day, 23, 59, 59, tzinfo=CST)

    if args.source == "rss":
        from trade_py.data.news.rss import RssSource
        primary = RssSource(feeds=selected_feeds or [])
    elif args.source == "cls":
        from trade_py.data.news.cls_source import ClsSource
        primary = ClsSource()
    else:
        raise ValueError(f"Unknown source: {args.source}")

    def _pcb(msg: str) -> None:
        print(msg, flush=True)

    diagnostics: list[dict] = []
    primary_summary = ingest(primary, since_dt, until_dt, data_root, db,
                             diagnostics_out=diagnostics, progress_cb=_pcb)

    backfill_summary = None
    if args.source == "rss" and args.fetch_mode == "full" and args.enable_backfill:
        from trade_py.data.news.gdelt.source import GdeltSource
        gdelt = GdeltSource(selection=args.backfill_channels,
                            max_records_per_channel=args.backfill_max_records_per_channel)
        gdelt_diag: list[dict] = []
        gdelt_summary = ingest(gdelt, since_dt, until_dt, data_root, db,
                               diagnostics_out=gdelt_diag, progress_cb=_pcb)
        backfill_summary = {"ingest": gdelt_summary, "diagnostics": gdelt_diag}

    print("Source prefetch:", json.dumps({
        "source": args.source,
        "mode": args.fetch_mode,
        "prefetch_since": since_date.isoformat(),
        "articles": primary_summary.get("records_fetched", 0),
        "new": primary_summary.get("records_new", 0),
        "by_date": primary_summary.get("by_date", {}),
        "diagnostics": diagnostics,
        "backfill": backfill_summary,
        "coverage": db.coverage_report(),
    }, ensure_ascii=False))
    return diagnostics


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

    if not args.dry_run:
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
                                  db=db, dry_run=False)
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

        bronze_pre = (data_root / "raw" / "sentiment" / args.source
                      / f"{target.year:04d}" / f"{target.month:02d}"
                      / f"{target.year:04d}-{target.month:02d}-{target.day:02d}.parquet")
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
            dest = (data_root / "raw" / "sentiment" / args.source
                    / f"{target.year:04d}" / f"{target.month:02d}"
                    / f"{target.year:04d}-{target.month:02d}-{target.day:02d}.parquet")
            dest.parent.mkdir(parents=True, exist_ok=True)
            new_df = pd.DataFrame([{
                "source": r.source_id, "url": r.url, "title": r.title,
                "text": r.text, "published_at": r.published_at.isoformat(),
                "content_hash": r.content_hash,
            } for r in records])
            if dest.exists():
                combined = pd.concat([pd.read_parquet(dest), new_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["content_hash"], keep="last")
            else:
                combined = new_df
            combined.to_parquet(dest, index=False)
            print(f"Saved {len(combined)} articles → {dest}")

    y, m, day = target.year, target.month, target.day
    bronze_path = (data_root / "raw" / "sentiment" / args.source
                   / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{day:02d}.parquet")
    if not bronze_path.exists():
        print(f"No Bronze data: {bronze_path}")
        if not args.fetch:
            print("Tip: add --fetch to download first")
        return 0

    df = pd.read_parquet(bronze_path)
    if args.feed:
        df = df[df["source"].str.lower() == args.feed.lower()]
        if df.empty:
            feeds = sorted(pd.read_parquet(bronze_path)["source"].unique())
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
Usage: trade data sentiment [subcommand] [args...]

子命令:
  (无子命令)           运行完整情绪流水线 (fetch → LLM → Gold)
  status               显示各 Feed 的质量评分
  inspect <src> <date> 查看指定日期的 Bronze/Silver 文章
  sample               随机抽样 Silver 文章（人工核查）
  apply-corrections    将 .corrections/ 中的校正写回 Silver + 重算 Gold

示例:
  trade data sentiment --date 2026-03-05 --llm-provider ollama
  trade data sentiment --fetch-mode none --start 2026-01-01 --end 2026-03-05
  trade data sentiment status
  trade data sentiment inspect rss 2026-03-05 --silver
  trade data sentiment sample --date 2026-03-05 --label negative -n 20
  trade data sentiment apply-corrections --date 2026-03-05\
""")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        _print_sentiment_help()
        return 0
    if argv[0] == "status":
        return _cmd_status(argv[1:])
    if argv[0] == "inspect":
        return _cmd_inspect(argv[1:])
    if argv[0] == "sample":
        return _cmd_sample(argv[1:])
    if argv[0] == "apply-corrections":
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

    # Service health checks
    if args.source == "rss" and args.fetch_mode != "none":
        try:
            _probe_rsshub(rsshub_base_url,
                          timeout=args.rsshub_probe_timeout,
                          retries=args.rsshub_probe_retries)
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return 3
    elif args.source == "cls":
        from trade_py.data.news.cls_source import ClsSource
        hc = ClsSource().health_check()
        if not hc.get("healthy"):
            print(f"ERROR: CLS unhealthy: {hc.get('error', 'unknown')}")
            return 3
    if args.llm_provider == "ollama" and not args.dry_run:
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

    selected_feeds = None
    if args.source == "rss":
        from trade_py.data.news.rss import resolve_feeds
        try:
            selected_feeds, feed_catalog = resolve_feeds(args.rss_feeds, rsshub_base_url)
        except ValueError as e:
            print(f"ERROR: {e}")
            return 1
        if args.show_rss_feed_index:
            print(json.dumps({
                "selected": [f["name"] for f in selected_feeds],
                "catalog": feed_catalog,
            }, ensure_ascii=False, indent=2))
            return 0
        print("RSS feed profile:", json.dumps([{
            "name": f["name"],
            "status": f["meta"].get("status"),
            "score":  f["meta"].get("score"),
            "category": f["meta"].get("category"),
        } for f in selected_feeds], ensure_ascii=False))

    backfill_enabled = (args.source == "rss" and args.fetch_mode == "full"
                        and getattr(args, "enable_backfill", True))
    enrich_sources = [args.source, "gdelt"] if backfill_enabled else [args.source]

    from trade_py.db.pipeline_db import PipelineDb
    with PipelineDb(Path(args.data_root)) as db:
        if not args.no_rss_prefetch and args.fetch_mode != "none":
            _prefetch_sources(args, selected_feeds, dates, db)
        else:
            print("Source prefetch: skipped")

        if len(dates) > 1 and not args.all_range_dates:
            local_dates = _local_bronze_dates(args.data_root, enrich_sources,
                                              dates[0], dates[-1])
            print("Local bronze coverage:", json.dumps({
                "requested_days": len(dates),
                "available_days": len(local_dates),
                "missing_days": len(dates) - len(local_dates),
                "sources": enrich_sources,
            }, ensure_ascii=False))
            dates = local_dates
            if not dates:
                print("No local Bronze data in range; nothing to process.")
                return 0

        return _run_pipeline_loop(args, dates, selected_feeds,
                                  ollama_base_url, db, enrich_sources)
