from __future__ import annotations

import argparse

from trade_py.config import default_data_root
from trade_py.data.account.repository import AccountRepository
from trade_py.data.account.service import AccountService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trade account")
    parser.add_argument("--data-root", default=str(default_data_root()))
    sub = parser.add_subparsers(dest="command", required=True)

    p_watch_add = sub.add_parser("watch-add", help="Add symbol to watchlist")
    p_watch_add.add_argument("symbol")
    p_watch_add.add_argument("--note", default="")

    p_watch_rm = sub.add_parser("watch-remove", help="Remove symbol from watchlist")
    p_watch_rm.add_argument("symbol")

    sub.add_parser("watch-list", help="List watchlist symbols")

    p_set = sub.add_parser("setting-set", help="Set a settings key")
    p_set.add_argument("key")
    p_set.add_argument("value")

    p_get = sub.add_parser("setting-get", help="Get a settings key")
    p_get.add_argument("key")

    args = parser.parse_args(argv)
    service = AccountService(AccountRepository(args.data_root))

    if args.command == "watch-add":
        service.add_watch(args.symbol, args.note)
        return 0
    if args.command == "watch-remove":
        service.remove_watch(args.symbol)
        return 0
    if args.command == "watch-list":
        for sym in service.list_watch():
            print(sym)
        return 0
    if args.command == "setting-set":
        service.set_setting(args.key, args.value)
        return 0
    if args.command == "setting-get":
        val = service.get_setting(args.key)
        print(val)
        return 0
    return 1
