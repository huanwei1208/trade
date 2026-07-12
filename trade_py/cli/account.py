from __future__ import annotations

import argparse

from trade_py.infra.settings import default_data_root
from trade_py.data.account.repository import AccountRepository
from trade_py.data.account.service import AccountService
from trade_py.db.trade_db import TradeDB


def make_parser() -> argparse.ArgumentParser:
    from trade_py.cli import epilog_from_subparsers, global_flag_parent

    parser = argparse.ArgumentParser(
        prog="trade account",
        description="[DEPRECATED: watchlist moved to `trade config watch`] 账户与自选股管理 / 候选股推荐",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flag_parent()],
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
        description="按 model_score / window_score / event_kg_score 推荐候选股票",
        epilog="trade account suggest --limit 20 --by model_score",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_suggest.add_argument("--limit", type=int, default=20, help="最多推荐数量（默认 20）")
    p_suggest.add_argument(
        "--by",
        choices=["model_score", "window_score", "event_kg_score"],
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
    import sys as _sys
    args = make_parser().parse_args(argv)

    _DEPRECATED_NOTE = (
        "Note: 'trade account {old}' is deprecated; "
        "use 'trade config {new}' instead.\n"
    )

    if args.command in ("watch-add", "watch-remove", "watch-list"):
        print(_DEPRECATED_NOTE.format(
            old=args.command,
            new={"watch-add": "watch add", "watch-remove": "watch remove", "watch-list": "watch list"}[args.command],
        ), file=_sys.stderr)
        from trade_py.cli import config as config_cli
        if args.command == "watch-list":
            cfg_argv = ["watch", "list"]
        elif args.command == "watch-remove":
            cfg_argv = ["watch", "remove", args.symbol]
        else:
            cfg_argv = ["watch", "add", args.symbol]
            if getattr(args, "note", ""):
                cfg_argv += ["--note", args.note]
        cfg_argv += ["--data-root", args.data_root]
        return config_cli.main(cfg_argv)

    if args.command in ("setting-set", "setting-get"):
        print(_DEPRECATED_NOTE.format(
            old=args.command,
            new={"setting-set": "set", "setting-get": "get"}[args.command],
        ), file=_sys.stderr)
        from trade_py.cli import config as config_cli
        cfg_argv = [{"setting-set": "set", "setting-get": "get"}[args.command], args.key]
        if args.command == "setting-set":
            cfg_argv.append(args.value)
        cfg_argv += ["--data-root", args.data_root]
        return config_cli.main(cfg_argv)

    if args.command == "suggest":
        from trade_py.db.settings_db import SettingsDB
        from trade_py.data.market.index.tushare import SW_SECTOR_INDICES
        db = SettingsDB(args.data_root)
        gate_db = TradeDB(args.data_root)
        gate = gate_db.quality_gate_get()
        rows = db.signal_cache_suggest(
            limit=args.limit,
            by=args.by,
            sector_limit=args.sector_limit,
        )
        if not rows:
            score_label = {
                "model_score": "model_score",
                "window_score": "window_score",
                "event_kg_score": "event_kg_score",
            }.get(args.by, "model_score")
            print(f"暂无候选（{score_label} 为空）。请先运行模型推理或窗口评分。")
            return 0
        # Build sw_idx → name map
        sw_idx_name: dict[int, str] = {sw_idx: name for _, (name, sw_idx) in SW_SECTOR_INDICES.items()}
        score_label = {
            "model_score": "模型评分",
            "window_score": "窗口质量",
            "event_kg_score": "事件分数",
        }.get(args.by, "模型评分")
        if gate:
            status = gate.get("status", "unknown")
            eval_date = gate.get("eval_date", "—")
            metrics = gate.get("metrics_json") or {}
            latest_reasons = metrics.get("latest_reasons") or []
            matured_reasons = metrics.get("matured_reasons") or []
            print(
                f"质量状态: {status}  ({eval_date})"
                f"  operational={metrics.get('operational_status', '—')}"
                f"  research={metrics.get('research_status', '—')}"
            )
            if latest_reasons:
                print("最新链路: " + " | ".join(str(reason) for reason in latest_reasons[:2]))
            if matured_reasons:
                print("成熟窗口: " + " | ".join(str(reason) for reason in matured_reasons[:2]))
            print()
        else:
            print("质量状态: 未评估。建议先运行 `trade evaluate daily`。")
            print()
        print(f"\n{'股票':<14}  {score_label:>8}  {'风险%':>6}  {'窗口质量':>8}  {'板块'}")
        print("─" * 60)
        for r in rows:
            sym   = r.get("symbol", "—")
            ms    = r.get("model_score")
            mr    = r.get("model_risk")
            ws    = r.get("window_score")
            es    = r.get("event_kg_score")
            ind   = r.get("industry", 255)
            sector_name = sw_idx_name.get(ind, "未知")
            primary_score = {
                "model_score": ms,
                "window_score": ws,
                "event_kg_score": es,
            }.get(args.by)
            ms_str = (
                f"{float(primary_score):.3f}" if args.by == "event_kg_score" and primary_score is not None
                else f"{float(primary_score):.1f}" if primary_score is not None
                else "  —  "
            )
            mr_str = f"{mr:.1%}" if mr is not None else " — "
            ws_str = f"{ws}" if ws is not None else "—"
            print(f"{sym:<14}  {ms_str:>8}  {mr_str:>6}  {ws_str:>8}  {sector_name}")
        print(f"\n共 {len(rows)} 只候选（按 {args.by} 排序，每板块最多 {args.sector_limit} 只）")
        return 0
    return 1
