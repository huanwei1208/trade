"""trade inspect — DEPRECATED shim. Read-only views moved to ``trade show``; kg/factors/models moved to ``trade research`` / ``trade kg``.

Mappings:
  inspect dag         →  show dag
  inspect calendar    →  show calendar
  inspect agenda      →  show agenda
  inspect events      →  show events
  inspect backups     →  show backups
  inspect workflows   →  show workflows
  inspect health      →  status data
  inspect hive        →  status data (alias)
  inspect kg          →  kg evaluate
  inspect factors     →  research factor status
  inspect models      →  research model compare
"""
from __future__ import annotations

import argparse
import sys

from trade_py.cli import global_flag_parent
from trade_py.infra.settings import default_data_root

_DATA_ROOT = str(default_data_root())

_GENERIC_WARNED = False


def _warn_generic() -> None:
    global _GENERIC_WARNED
    if _GENERIC_WARNED:
        return
    print(
        "DeprecationWarning: 'trade inspect' is deprecated; "
        "use 'trade show' (or 'trade status' / 'trade research') instead.",
        file=sys.stderr,
    )
    _GENERIC_WARNED = True


def _warn(old: str, new: str) -> None:
    print(
        f"DeprecationWarning: 'trade inspect {old}' is deprecated; "
        f"use '{new}' instead.",
        file=sys.stderr,
    )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade inspect",
        description="[DEPRECATED] 数据/任务/DAG/事件浏览器 — 请使用 trade show / trade status / trade research",
        parents=[global_flag_parent()],
    )
    sub = parser.add_subparsers(dest="command", required=False)

    p_dag = sub.add_parser("dag", description="查看 DAG")
    p_dag.add_argument("--data-root", default=_DATA_ROOT)
    p_dag.add_argument("--all", action="store_true")

    p_calendar = sub.add_parser("calendar", description="查看交易日历与未来事件")
    p_calendar.add_argument("--data-root", default=_DATA_ROOT)
    p_calendar.add_argument("--date", default=__import__("datetime").date.today().isoformat())
    p_calendar.add_argument("--days", type=int, default=5)

    p_agenda = sub.add_parser("agenda", description="查看 agenda 队列")
    p_agenda.add_argument("--data-root", default=_DATA_ROOT)
    p_agenda.add_argument("--limit", type=int, default=20)
    p_agenda.add_argument("--status", default=None)

    p_kg = sub.add_parser("kg", description="查看 KG 当前状态")
    p_kg.add_argument("--data-root", default=_DATA_ROOT)
    p_kg.add_argument("--top", type=int, default=10)

    p_factors = sub.add_parser("factors", description="查看因子状态")
    p_factors.add_argument("--data-root", default=_DATA_ROOT)

    p_models = sub.add_parser("models", description="查看模型对比")
    p_models.add_argument("--data-root", default=_DATA_ROOT)

    p_events = sub.add_parser("events", description="查看最近事件日志")
    p_events.add_argument("--data-root", default=_DATA_ROOT)
    p_events.add_argument("--limit", type=int, default=20)

    p_health = sub.add_parser("health", description="查看数据健康状态")
    p_health.add_argument("--data-root", default=_DATA_ROOT)
    p_health.add_argument("--sample-limit", type=int, default=8)

    p_hive = sub.add_parser("hive", description="查看数据健康状态（兼容别名）")
    p_hive.add_argument("--data-root", default=_DATA_ROOT)
    p_hive.add_argument("--sample-limit", type=int, default=8)

    p_workflows = sub.add_parser("workflows", description="查看最近 workflow 运行轨迹")
    p_workflows.add_argument("--data-root", default=_DATA_ROOT)
    p_workflows.add_argument("--limit", type=int, default=10)

    p_backups = sub.add_parser("backups", description="查看最近备份")
    p_backups.add_argument("--data-root", default=_DATA_ROOT)
    p_backups.add_argument("--limit", type=int, default=20)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv or [])

    # No subcommand: print generic warning + show help
    if not args.command:
        _warn_generic()
        make_parser().print_help()
        return 0

    if args.command == "dag":
        _warn("dag", "trade show dag")
        from trade_py.cli import show as show_cli
        return show_cli.main(["dag", "--data-root", args.data_root] + (["--all"] if args.all else []))

    if args.command == "calendar":
        _warn("calendar", "trade show calendar")
        from trade_py.cli import show as show_cli
        return show_cli.main(["calendar", "--data-root", args.data_root, "--date", args.date, "--days", str(args.days)])

    if args.command == "agenda":
        _warn("agenda", "trade show agenda")
        from trade_py.cli import show as show_cli
        sa = ["agenda", "--data-root", args.data_root, "--limit", str(args.limit)]
        if args.status:
            sa += ["--status", args.status]
        return show_cli.main(sa)

    if args.command == "events":
        _warn("events", "trade show events")
        from trade_py.cli import show as show_cli
        return show_cli.main(["events", "--data-root", args.data_root, "--limit", str(args.limit)])

    if args.command == "backups":
        _warn("backups", "trade show backups")
        from trade_py.cli import show as show_cli
        return show_cli.main(["backups", "--data-root", args.data_root, "--limit", str(args.limit)])

    if args.command == "workflows":
        _warn("workflows", "trade show workflows")
        from trade_py.cli import show as show_cli
        return show_cli.main(["workflows", "--data-root", args.data_root, "--limit", str(args.limit)])

    if args.command in ("health", "hive"):
        _warn(args.command, "trade status data")
        from trade_py.cli import status as status_cli
        return status_cli.main(["data", "--data-root", args.data_root, "--limit", str(getattr(args, "sample_limit", 8))])

    if args.command == "kg":
        _warn("kg", "trade kg evaluate")
        from trade_py.cli import kg as kg_cli
        return kg_cli.main(["evaluate", "--data-root", args.data_root, "--top", str(args.top)])

    if args.command == "factors":
        _warn("factors", "trade research factor status")
        from trade_py.cli import research as research_cli
        return research_cli.main(["factor", "status", "--data-root", args.data_root])

    if args.command == "models":
        _warn("models", "trade research model compare")
        from trade_py.cli import research as research_cli
        return research_cli.main(["model", "compare", "--data-root", args.data_root])

    return 0
