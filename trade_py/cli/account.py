from __future__ import annotations

import argparse

from trade_py.config import default_data_root
from trade_py.data.account.repository import AccountRepository
from trade_py.data.account.service import AccountService


def make_parser() -> argparse.ArgumentParser:
    from trade_py.cli import epilog_from_subparsers

    parser = argparse.ArgumentParser(
        prog="trade account",
        description="账户与自选股管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data-root", default=str(default_data_root()))
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser(
        "watch-add",
        description="添加股票到自选股",
        epilog='trade account watch-add 600000.SH --note "浦发银行"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_add.add_argument("symbol")
    p_add.add_argument("--note", default="")

    p_rm = sub.add_parser(
        "watch-remove",
        description="从自选股删除股票",
        epilog="trade account watch-remove 600000.SH",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_rm.add_argument("symbol")

    sub.add_parser(
        "watch-list",
        description="列出自选股",
        epilog="trade account watch-list",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p_set = sub.add_parser(
        "setting-set",
        description="设置配置项",
        epilog="trade account setting-set llm_provider ollama",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_set.add_argument("key")
    p_set.add_argument("value")

    p_get = sub.add_parser(
        "setting-get",
        description="读取配置项",
        epilog="trade account setting-get llm_provider",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_get.add_argument("key")

    parser.epilog = epilog_from_subparsers(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    service = AccountService(AccountRepository(args.data_root))

    if args.command == "watch-add":
        from trade_py.data.market.kline.providers import ensure_symbol
        sym = ensure_symbol(args.symbol.strip())
        info = service.lookup_instrument(args.symbol)
        if info is None:
            print(f"错误：未找到 {sym}，instruments 库中无此标的。")
            print("请先运行: trade data kline instruments")
            return 1
        print(f"找到: {sym}  {info['name']}  ({info['market_name']})")
        try:
            ans = input("确认添加到自选股? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return 1
        if ans != "y":
            print("已取消")
            return 1
        service.add_watch(args.symbol, args.note)
        print(f"已添加: {sym}  {info['name']}")
        return 0
    if args.command == "watch-remove":
        service.remove_watch(args.symbol)
        return 0
    if args.command == "watch-list":
        rows = service.list_watch_with_names()
        if not rows:
            print("自选股为空")
            return 0
        name_w = max(len(r["name"]) for r in rows) if rows else 4
        for r in rows:
            print(f"{r['symbol']:<14}  {r['name']:<{name_w}}  {r['market_name']}")
        return 0
    if args.command == "setting-set":
        service.set_setting(args.key, args.value)
        return 0
    if args.command == "setting-get":
        val = service.get_setting(args.key)
        print(val)
        return 0
    return 1
