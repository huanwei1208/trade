from __future__ import annotations

import argparse
import logging

from trade_py.config import default_data_root
from trade_py.data.cross_asset_fetcher import fetch_all, fetch_btc, fetch_fx_cnh, fetch_gold
from trade_py.data.kline_fetcher import KlineFetcher
from trade_py.db.instruments_db import InstrumentsDB

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    if argv and argv[0] == "sentiment":
        from trade_py.cli._sentiment import main as sentiment_main
        return sentiment_main(argv[1:])

    parser = argparse.ArgumentParser(prog="trade data")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sentiment", help="News sentiment pipeline")

    p_collector = sub.add_parser("collector", help="A-share kline collector")
    collector_sub = p_collector.add_subparsers(dest="collector_cmd", required=True)

    p_collect = collector_sub.add_parser("collect", help="Fetch bars for symbol list")
    p_collect.add_argument("--data-root", default=str(default_data_root()))
    p_collect.add_argument("--symbol", required=True)
    p_collect.add_argument("--start", required=True)
    p_collect.add_argument("--end", default=None)
    p_collect.add_argument("--adjust", choices=["hfq", "qfq", ""], default="hfq")

    p_update = collector_sub.add_parser("update", help="Incremental update for one symbol")
    p_update.add_argument("--data-root", default=str(default_data_root()))
    p_update.add_argument("--symbol", required=True)
    p_update.add_argument("--start", default="2020-01-01")

    p_update_all = collector_sub.add_parser("update-all", help="Incremental update for all symbols")
    p_update_all.add_argument("--data-root", default=str(default_data_root()))
    p_update_all.add_argument("--start", default="2025-01-01")
    p_update_all.add_argument("--delay-ms", type=int, default=200)

    p_instruments = collector_sub.add_parser("instruments", help="Refresh instrument list")
    p_instruments.add_argument("--data-root", default=str(default_data_root()))

    p_list = collector_sub.add_parser("list", help="List tracked symbols")
    p_list.add_argument("--data-root", default=str(default_data_root()))

    p_cross_asset = sub.add_parser("cross-asset", help="Cross-asset fetcher")
    p_cross_asset.add_argument("asset", nargs="?", choices=["all", "gold", "fx", "btc"], default="all")
    p_cross_asset.add_argument("--data-root", default=str(default_data_root()))

    args = parser.parse_args(argv)

    if args.command == "collector":
        fetcher = KlineFetcher(args.data_root)
        if args.collector_cmd == "collect":
            symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
            ok = True
            for symbol in symbols:
                df = fetcher.fetch(symbol, start=args.start, end=args.end, adjust=args.adjust)
                if df.empty:
                    logger.warning("No data returned for %s", symbol)
                    ok = False
                    continue
                fetcher.save_parquet(symbol, df)
                logger.info("Saved %d rows for %s", len(df), symbol)
            return 0 if ok else 1
        if args.collector_cmd == "update":
            fetcher.update(args.symbol.strip(), start_fallback=args.start)
            return 0
        if args.collector_cmd == "update-all":
            results = fetcher.update_all(start_fallback=args.start, delay_ms=args.delay_ms)
            errors = sum(1 for value in results.values() if value < 0)
            return 0 if errors == 0 else 1
        if args.collector_cmd == "instruments":
            instruments = fetcher.fetch_instruments()
            return 0 if instruments else 1
        if args.collector_cmd == "list":
            symbols = InstrumentsDB(args.data_root).get_all_symbols()
            for symbol in symbols:
                print(symbol)
            if symbols:
                print(f"\nTotal: {len(symbols)} symbols")
            return 0

    if args.command == "cross-asset":
        fn_map = {
            "gold": lambda: fetch_gold(args.data_root),
            "fx": lambda: fetch_fx_cnh(args.data_root),
            "btc": lambda: fetch_btc(args.data_root),
            "all": lambda: fetch_all(args.data_root),
        }
        fn_map[args.asset]()
        return 0

    return 1
