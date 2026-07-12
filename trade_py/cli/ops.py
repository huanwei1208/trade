"""trade ops — DEPRECATED shim. Functionality moved to ``trade status`` / ``trade run`` / ``trade show``.

Old commands map to:
  trade ops status       →  trade status
  trade ops freshness    →  trade status freshness
  trade ops backfill     →  trade run <job> (or event backfill)
  trade ops inspect      →  show via db directly (kept for back-compat, prints warning)
"""
from __future__ import annotations

import argparse
import sys

from trade_py.cli import global_flag_parent
from trade_py.infra.settings import default_data_root

_DATA_ROOT = str(default_data_root())


def _warn(old: str, new: str) -> None:
    msg = (
        f"DeprecationWarning: 'trade ops {old}' is deprecated and will be removed in a future release; "
        f"use '{new}' instead."
    )
    print(msg, file=sys.stderr)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade ops",
        description="[DEPRECATED] 运营检查与维护 — 请使用 trade status / trade run / trade show",
        parents=[global_flag_parent()],
    )
    sub = parser.add_subparsers(dest="action", metavar="<操作>")

    sp_status = sub.add_parser("status", help="系统整体健康 → trade status")
    sp_status.add_argument("--data-root", default=_DATA_ROOT)

    sp_backfill = sub.add_parser("backfill", help="回填指定 job → trade run <job>")
    sp_backfill.add_argument("job", help="job 名称")
    sp_backfill.add_argument("--date-from", default=None)
    sp_backfill.add_argument("--date-to", default=None)
    sp_backfill.add_argument("--data-root", default=_DATA_ROOT)

    sp_inspect = sub.add_parser("inspect", help="检查 EBRT 表 → 保留向后兼容")
    sp_inspect.add_argument("table", nargs="?", default=None)
    sp_inspect.add_argument("--data-root", default=_DATA_ROOT)

    sp_fresh = sub.add_parser("freshness", help="打印数据新鲜度 → trade status freshness")
    sp_fresh.add_argument("--data-root", default=_DATA_ROOT)
    sp_fresh.add_argument("--date", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)

    if not args.action or args.action == "status":
        _warn("status", "trade status")
        from trade_py.cli import status as status_cli
        return status_cli.main(["--data-root", getattr(args, "data_root", _DATA_ROOT)])

    if args.action == "freshness":
        _warn("freshness", "trade status freshness")
        from trade_py.cli import status as status_cli
        fr_argv = ["freshness", "--data-root", args.data_root]
        if args.date:
            fr_argv += ["--date", args.date]
        return status_cli.main(fr_argv)

    if args.action == "backfill":
        _warn("backfill", f"trade event backfill or trade run {args.job}")
        from trade_py.cli import event as event_cli
        bf_argv = ["backfill", "--data-root", args.data_root]
        if args.date_from:
            bf_argv += ["--from", args.date_from]
        if args.date_to:
            bf_argv += ["--to", args.date_to]
        return event_cli.main(bf_argv)

    if args.action == "inspect":
        _warn("inspect", "trade show (read-only views)")
        # Keep the original inspect behavior for back-compat (table row counts).
        from datetime import date as _date
        from trade_py.db.trade_db import TradeDB
        db = TradeDB(args.data_root)
        ebrt_tables = [
            "ArticleEvent", "InfluenceSignal", "Evidence", "BeliefState",
            "AttentionScore", "BeliefTransition", "Recommendation",
            "QualityReport", "FreshnessStatus", "RecommendationTrace",
        ]
        tables = [args.table] if args.table else ebrt_tables
        for t in tables:
            try:
                cnt = db._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                print(f"{t:<30}: {cnt:>8} rows")
            except Exception as exc:
                print(f"{t:<30}: ERROR {exc}")
        db.close()
        return 0

    parser.print_help()
    return 1
