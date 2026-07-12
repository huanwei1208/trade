"""trade daily — DEPRECATED shim. All functionality moved to ``trade run`` / ``trade status`` / ``trade show``.

Old commands map to:
  trade daily run        →  trade run daily
  trade daily belief     →  trade run belief
  trade daily recommend  →  trade run recommend
  trade daily picks      →  trade run picks
  trade daily status     →  trade status (overview)
"""
from __future__ import annotations

import argparse
import sys

from trade_py.cli import global_flag_parent
from trade_py.infra.settings import default_data_root

_DATA_ROOT = str(default_data_root())

_DEPRECATION_NOTE = (
    "DeprecationWarning: 'trade daily {old}' is deprecated and will be removed in a future release; "
    "use '{new}' instead."
)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade daily",
        description="[DEPRECATED] 每日流水线管理 — 请使用 trade run / trade status",
        parents=[global_flag_parent()],
    )
    parser.add_argument(
        "action",
        choices=["run", "belief", "recommend", "picks", "status"],
        help="操作类型",
    )
    parser.add_argument("--data-root", default=_DATA_ROOT, metavar="DIR")
    parser.add_argument("--date", default=None, help="日期（默认今日）")
    parser.add_argument("--top", type=int, default=10, help="显示条数（picks）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)

    # Build forwarded args and new command
    fwd = []
    if args.action in ("run",):
        new_cmd = "trade run daily"
        target = "daily"
    elif args.action == "belief":
        new_cmd = "trade run belief"
        target = "belief"
    elif args.action == "recommend":
        new_cmd = "trade run recommend"
        target = "recommend"
    elif args.action == "picks":
        new_cmd = "trade run picks"
        target = "picks"
    elif args.action == "status":
        new_cmd = "trade status"
        target = None
    else:
        new_cmd = "trade status"
        target = None

    print(_DEPRECATION_NOTE.format(old=args.action, new=new_cmd), file=sys.stderr)

    if args.action == "status":
        from trade_py.cli import status as status_cli
        return status_cli.main(["--data-root", args.data_root])

    # run/belief/recommend/picks → run module
    from trade_py.cli import run as run_cli
    run_argv = [target, "--data-root", args.data_root]
    if args.date:
        run_argv += ["--date", args.date]
    if args.top:
        run_argv += ["--top", str(args.top)]
    return run_cli.main(run_argv)
