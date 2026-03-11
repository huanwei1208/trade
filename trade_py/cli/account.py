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

    p_suggest = sub.add_parser(
        "suggest",
        description="按 model_score（或 window_score）推荐候选股票",
        epilog="trade account suggest --limit 20 --by model_score",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_suggest.add_argument("--limit", type=int, default=20, help="最多推荐数量（默认 20）")
    p_suggest.add_argument(
        "--by",
        choices=["model_score", "window_score"],
        default="model_score",
        help="排序依据（默认 model_score）",
    )
    p_suggest.add_argument(
        "--sector-limit",
        type=int,
        default=3,
        metavar="N",
        help="每个板块最多推荐数量（默认 3）",
    )

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
    if args.command == "suggest":
        from trade_py.db.settings_db import SettingsDB
        from trade_py.data.market.index.tushare import SW_SECTOR_INDICES
        db = SettingsDB(args.data_root)
        rows = db.signal_cache_suggest(
            limit=args.limit,
            by=args.by,
            sector_limit=args.sector_limit,
        )
        if not rows:
            score_label = "model_score" if args.by == "model_score" else "window_score"
            print(f"暂无候选（{score_label} 为空）。请先运行模型推理或窗口评分。")
            return 0
        # Build sw_idx → name map
        sw_idx_name: dict[int, str] = {sw_idx: name for _, (name, sw_idx) in SW_SECTOR_INDICES.items()}
        score_label = "模型评分" if args.by == "model_score" else "窗口质量"
        print(f"\n{'股票':<14}  {score_label:>8}  {'风险%':>6}  {'窗口质量':>8}  {'板块'}")
        print("─" * 60)
        for r in rows:
            sym   = r.get("symbol", "—")
            ms    = r.get("model_score")
            mr    = r.get("model_risk")
            ws    = r.get("window_score")
            ind   = r.get("industry", 255)
            sector_name = sw_idx_name.get(ind, "未知")
            ms_str = f"{ms:.1f}" if ms is not None else "  —  "
            mr_str = f"{mr:.1%}" if mr is not None else " — "
            ws_str = f"{ws}" if ws is not None else "—"
            print(f"{sym:<14}  {ms_str:>8}  {mr_str:>6}  {ws_str:>8}  {sector_name}")
        print(f"\n共 {len(rows)} 只候选（按 {args.by} 排序，每板块最多 {args.sector_limit} 只）")
        return 0
    return 1
