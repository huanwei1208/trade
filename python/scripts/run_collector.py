#!/usr/bin/env python3
"""CLI replacement for the deprecated C++ 'trade_cli collect' command.

Uses akshare for A-share OHLCV data collection.

Sub-commands
------------
  collect      Fetch bars for one or more symbols over a date range
  update       Incremental update for one symbol (reads watermark)
  update-all   Incremental update for all symbols in the database
  instruments  Refresh the full A-share instrument list
  list         List symbols currently tracked in the database

Examples
--------
  uv run python python/scripts/run_collector.py instruments
  uv run python python/scripts/run_collector.py collect --symbol 600000.SH --start 2025-01-01
  uv run python python/scripts/run_collector.py collect --symbol 600000.SH,000001.SZ --start 2024-01-01 --end 2025-01-01
  uv run python python/scripts/run_collector.py update --symbol 600000.SH
  uv run python python/scripts/run_collector.py update-all --start 2020-01-01
  uv run python python/scripts/run_collector.py list
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure the python/ directory is on the path when run directly
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PY_ROOT = _REPO_ROOT / "python"
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

from trade_py.data.kline_fetcher import KlineFetcher
from trade_py.db.instruments_db import InstrumentsDB
from config_context import default_data_root

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_collector")


def _data_root(args: argparse.Namespace) -> str:
    return args.data_root


# ── Sub-command handlers ───────────────────────────────────────────────────


def cmd_collect(args: argparse.Namespace) -> int:
    """Fetch bars for one or more symbols (full range)."""
    if not args.symbol:
        logger.error("--symbol is required for 'collect'")
        return 1

    symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
    fetcher = KlineFetcher(_data_root(args))
    ok = True
    for sym in symbols:
        logger.info("Collecting %s from %s ...", sym, args.start)
        df = fetcher.fetch(sym, start=args.start, end=args.end, adjust=args.adjust)
        if df.empty:
            logger.warning("No data returned for %s", sym)
            ok = False
            continue
        fetcher.save_parquet(sym, df)
        logger.info("  Saved %d rows for %s", len(df), sym)
    return 0 if ok else 1


def cmd_update(args: argparse.Namespace) -> int:
    """Incremental update for a single symbol using the watermark."""
    if not args.symbol:
        logger.error("--symbol is required for 'update'")
        return 1
    fetcher = KlineFetcher(_data_root(args))
    n = fetcher.update(args.symbol.strip(), start_fallback=args.start)
    logger.info("update: fetched %d new rows for %s", n, args.symbol)
    return 0


def cmd_update_all(args: argparse.Namespace) -> int:
    """Incremental update for all symbols in the database."""
    fetcher = KlineFetcher(_data_root(args))
    results = fetcher.update_all(start_fallback=args.start, delay_ms=args.delay_ms)
    total = sum(v for v in results.values() if v > 0)
    errors = sum(1 for v in results.values() if v < 0)
    logger.info(
        "update-all complete: %d symbols, %d total new rows, %d errors",
        len(results), total, errors,
    )
    return 0 if errors == 0 else 1


def cmd_instruments(args: argparse.Namespace) -> int:
    """Refresh the full A-share instrument list from akshare."""
    fetcher = KlineFetcher(_data_root(args))
    instruments = fetcher.fetch_instruments()
    logger.info("Upserted %d instruments into database", len(instruments))
    return 0 if instruments else 1


def cmd_list(args: argparse.Namespace) -> int:
    """List all symbols currently tracked in the local database."""
    db = InstrumentsDB(_data_root(args))
    symbols = db.get_all_symbols()
    if not symbols:
        print("(no symbols in database)")
        return 0
    for sym in symbols:
        print(sym)
    print(f"\nTotal: {len(symbols)} symbols")
    return 0


# ── Argument parser ────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_collector",
        description="A-share data collector using akshare (replaces trade_cli collect)",
    )
    parser.add_argument(
        "--data-root", default=str(default_data_root()),
        help="Project data root directory (default: data)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # collect
    p_collect = sub.add_parser("collect", help="Fetch bars for given symbol(s)")
    p_collect.add_argument("--symbol", required=True,
                           help="Comma-separated list of symbols, e.g. 600000.SH,000001.SZ")
    p_collect.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p_collect.add_argument("--end", default=None, help="End date YYYY-MM-DD (default: today)")
    p_collect.add_argument("--adjust", default="hfq",
                           choices=["hfq", "qfq", ""],
                           help="Price adjustment type (default: hfq)")

    # update
    p_update = sub.add_parser("update", help="Incremental update for one symbol")
    p_update.add_argument("--symbol", required=True, help="Symbol e.g. 600000.SH")
    p_update.add_argument("--start", default="2020-01-01",
                          help="Fallback start if no watermark (default: 2020-01-01)")

    # update-all
    p_update_all = sub.add_parser("update-all", help="Incremental update for all symbols")
    p_update_all.add_argument("--start", default="2025-01-01",
                              help="Fallback start for symbols without watermark")
    p_update_all.add_argument("--delay-ms", type=int, default=200,
                              help="Delay in ms between requests (default: 200)")

    # instruments
    sub.add_parser("instruments", help="Refresh full A-share instrument list from akshare")

    # list
    sub.add_parser("list", help="List symbols in the local database")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "collect":     cmd_collect,
        "update":      cmd_update,
        "update-all":  cmd_update_all,
        "instruments": cmd_instruments,
        "list":        cmd_list,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
