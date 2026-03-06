from __future__ import annotations

import argparse
import logging

from trade_py.config import default_data_root, load_defaults
from trade_py.data.market.cross_asset import fetch_all, fetch_btc, fetch_fx_cnh, fetch_gold
from trade_py.data.market.kline import KlineSyncOptions, KlineSyncService

logger = logging.getLogger(__name__)


def make_parser() -> argparse.ArgumentParser:
    from trade_py.cli import epilog_from_subparsers

    all_defaults = load_defaults()
    defaults = all_defaults.get("kline", {}) if isinstance(all_defaults, dict) else {}

    def d(name: str, fallback):
        return defaults.get(name, fallback)

    parser = argparse.ArgumentParser(
        prog="trade data",
        description="数据采集 — K线/情绪/跨资产",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "sentiment",
        description="新闻情绪流水线 (fetch → LLM → Gold)",
        epilog=(
            "trade data sentiment --date 2026-03-05\n"
            "trade data sentiment --fetch-mode none --start 2026-01-01 --end 2026-03-05\n"
            "trade data sentiment status\n"
            "trade data sentiment sample --date 2026-03-05 --label negative -n 20\n"
            "trade data sentiment apply-corrections --date 2026-03-05"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p_kline = sub.add_parser(
        "kline",
        description="A-share K线数据同步",
        epilog=(
            "trade data kline sync\n"
            "trade data kline sync --mode full --start 2025-01-01\n"
            "trade data kline status\n"
            "trade data kline instruments"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    kline_sub = p_kline.add_subparsers(dest="kline_cmd", required=True)

    p_sync = kline_sub.add_parser("sync", description="K线同步 (incremental/range/full)")
    p_sync.add_argument("--data-root", default=str(default_data_root()))
    p_sync.add_argument("--mode", choices=["incremental", "range", "full"], default=d("mode", "incremental"))
    p_sync.add_argument("--symbols", default=None, help="Comma-separated symbols. Empty means all instruments.")
    p_sync.add_argument("--start", default=d("start", "2020-01-01"))
    p_sync.add_argument("--end", default=None)
    p_sync.add_argument("--adjust", choices=["hfq", "qfq", "none"], default=d("adjust", "hfq"))
    p_sync.add_argument("--provider", choices=["auto", "akshare", "baostock"], default=d("provider", "auto"))
    p_sync.add_argument("--delay-ms", type=int, default=int(d("delay_ms", 300)))
    p_sync.add_argument("--fail-fast", action="store_true")

    p_instruments = kline_sub.add_parser("instruments", description="刷新标的列表")
    p_instruments.add_argument("--data-root", default=str(default_data_root()))

    p_status = kline_sub.add_parser("status", description="显示 K线同步状态")
    p_status.add_argument("--data-root", default=str(default_data_root()))
    p_status.add_argument("--stale-days", type=int, default=None, help="Only show symbols stale >= N days")
    p_status.add_argument("--limit", type=int, default=50)

    p_cross = sub.add_parser(
        "cross-asset",
        description="跨资产行情抓取 (gold/btc/fx/cnh)",
        epilog=(
            "trade data cross-asset all\n"
            "trade data cross-asset gold"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_cross.add_argument("asset", nargs="?", choices=["all", "gold", "fx", "btc"], default="all")
    p_cross.add_argument("--data-root", default=str(default_data_root()))

    parser.epilog = epilog_from_subparsers(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    if argv and argv[0] == "sentiment":
        from trade_py.cli._sentiment import main as sentiment_main
        return sentiment_main(argv[1:])

    args = make_parser().parse_args(argv)

    if args.command == "kline":
        service = KlineSyncService(args.data_root)
        if args.kline_cmd == "sync":
            symbols = None
            if args.symbols:
                symbols = [s.strip() for s in str(args.symbols).split(",") if s.strip()]
            opts = KlineSyncOptions(
                mode=args.mode,
                symbols=symbols,
                start=args.start,
                end=args.end,
                adjust=args.adjust,
                provider=args.provider,
                delay_ms=args.delay_ms,
                fail_fast=args.fail_fast,
            )
            summary = service.sync(opts)
            logger.info(
                "kline sync summary: total=%d succeeded=%d failed=%d empty=%d rows=%d",
                summary.total_symbols, summary.succeeded, summary.failed, summary.empty, summary.total_rows,
            )
            if summary.failed > 0:
                for symbol, res in summary.results.items():
                    if not res.ok:
                        logger.error(
                            "kline sync failed symbol=%s kind=%s error=%s",
                            symbol, res.error_kind, res.error_message,
                        )
            return 0 if summary.failed == 0 else 1
        if args.kline_cmd == "instruments":
            instruments = service.refresh_instruments()
            return 0 if instruments else 1
        if args.kline_cmd == "status":
            rows = service.status(stale_days=args.stale_days, limit=args.limit)
            if not rows:
                print("No symbols found.")
                return 0
            print(f"{'symbol':<12} {'watermark':<12} {'last_download':<12} {'stale_days':>10} {'last_error':<20}")
            print("-" * 72)
            for row in rows:
                print(
                    f"{row['symbol']:<12} {row['watermark']:<12} {row['last_download']:<12} "
                    f"{row['stale_days']:>10} {row['last_error_kind']:<20}"
                )
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
