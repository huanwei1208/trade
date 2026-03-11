"""trade run — unified execution entry point."""
from __future__ import annotations

import argparse
import hashlib
import logging
import time
from datetime import date

from trade_py.config import default_data_root
from trade_py.event import backfill_events, sync_events
from trade_py.jobs import JOB_REGISTRY, run_job

logger = logging.getLogger(__name__)

_DATA_ROOT = str(default_data_root())

_VALID_TYPES = [
    "semiconductor_policy", "new_energy_policy", "real_estate_easing",
    "real_estate_tightening", "rate_cut", "rate_hike", "commodity_surge",
    "commodity_slump", "defense_spending_up", "macro_recovery",
    "macro_slowdown", "geopolitical_risk", "earnings_beat", "earnings_miss",
    "merger_acquisition", "regulatory_tightening", "supply_disruption", "other",
]
_VALID_ACTORS = [
    "china_policy", "dovish_central", "hawkish_central", "trump_style",
    "elon_style", "regulator", "corporate_mgmt", "unknown",
]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade run",
        description="统一执行入口 — 调度器 / 单 job / 事件管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "固定子命令:\n"
            "  start        启动调度器 daemon（阻塞运行）\n"
            "  dry-run      立即执行所有 job（测试）\n"
            "  status       查看最近 job 执行记录\n"
            "  plan         查看调度计划（下次执行时间）\n"
            "  event        事件管理（sync/add/list/backfill）\n\n"
            "Job 子命令（立即执行单个 job）:\n"
            + "".join(f"  {name:<22} {jd.desc}\n" for name, jd in JOB_REGISTRY.items()) +
            "\n示例:\n"
            "  trade run start\n"
            "  trade run kline_update\n"
            "  trade run event list --limit 20\n"
            "  trade run event sync --from 2026-01-01\n"
            "  trade run status --limit 50\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    # ── fixed subcommands ──────────────────────────────────────────────────────
    p_start = sub.add_parser("start", description="启动调度器 daemon（阻塞运行）")
    p_start.add_argument("--data-root", default=_DATA_ROOT)

    p_dry = sub.add_parser("dry-run", description="立即执行所有 job（测试用）")
    p_dry.add_argument("--data-root", default=_DATA_ROOT)

    p_status = sub.add_parser("status", description="查看最近 job 执行记录")
    p_status.add_argument("--data-root", default=_DATA_ROOT)
    p_status.add_argument("--limit", type=int, default=30, help="显示条数（默认 30）")

    p_plan = sub.add_parser("plan", description="查看调度计划（下次执行时间）")
    p_plan.add_argument("--data-root", default=_DATA_ROOT)

    # ── dynamic job subcommands ────────────────────────────────────────────────
    for job_def in JOB_REGISTRY.values():
        p_j = sub.add_parser(job_def.name, description=job_def.desc)
        p_j.add_argument("--data-root", default=_DATA_ROOT)

    # ── event subcommand group ─────────────────────────────────────────────────
    p_event = sub.add_parser(
        "event",
        description="事件管理（补齐/新增/列表/回填）",
        epilog=(
            "trade run event sync --from 2026-01-01\n"
            "trade run event add --type semiconductor_policy --magnitude 0.8\n"
            "trade run event list --limit 50\n"
            "trade run event backfill\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    event_sub = p_event.add_subparsers(dest="event_cmd", required=True)

    p_ev_sync = event_sub.add_parser(
        "sync",
        description="按缺口补齐事件库和 KG 传导",
        epilog=(
            "trade run event sync\n"
            "trade run event sync --from 2026-01-01\n"
            "trade run event sync --from 2026-01-01 --to 2026-03-10\n"
            "trade run event sync --failed-only"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ev_sync.add_argument("--data-root", default=_DATA_ROOT)
    p_ev_sync.add_argument("--from", default=None, dest="start", help="起始日期 YYYY-MM-DD")
    p_ev_sync.add_argument("--to",   default=None, dest="end",   help="结束日期 YYYY-MM-DD")
    p_ev_sync.add_argument("--failed-only", action="store_true", help="只补已有事件但缺少 KG 传导的缺口")
    p_ev_sync.add_argument("--force", action="store_true", help="强制重跑范围内事件与传导")

    p_ev_extract = event_sub.add_parser(
        "extract",
        description="已弃用：等价于 sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ev_extract.add_argument("--data-root", default=_DATA_ROOT)
    p_ev_extract.add_argument("--from", default=None, dest="start", help="起始日期 YYYY-MM-DD")
    p_ev_extract.add_argument("--to", default=None, dest="end", help="结束日期 YYYY-MM-DD")
    p_ev_extract.add_argument("--failed-only", action="store_true", help="只补已有事件但缺少 KG 传导的缺口")
    p_ev_extract.add_argument("--force", action="store_true", help="强制重跑范围内事件与传导")

    p_ev_add = event_sub.add_parser(
        "add",
        description="手工创建事件 → 写库 → 自动KG传导",
        epilog=(
            "trade run event add --type semiconductor_policy --magnitude 0.8\n"
            "trade run event add --type rate_cut --magnitude 0.7 --sector SW_Banking"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ev_add.add_argument("--data-root",  default=_DATA_ROOT)
    p_ev_add.add_argument("--type",       required=True, dest="event_type", choices=_VALID_TYPES, help="事件类型")
    p_ev_add.add_argument("--magnitude",  type=float, required=True, help="事件强度 [0, 1]")
    p_ev_add.add_argument("--sector",     default=None, help="主要行业 (如 SW_Electronics)")
    p_ev_add.add_argument("--actor",      default="unknown", choices=_VALID_ACTORS, dest="actor_type")
    p_ev_add.add_argument("--summary",    default="", help="事件摘要")
    p_ev_add.add_argument("--date",       default=None, help="事件日期 YYYY-MM-DD，默认今天")

    p_ev_list = event_sub.add_parser(
        "list",
        description="查看 SQLite 事件列表及传导状态",
        epilog=(
            "trade run event list --limit 50\n"
            "trade run event list --failed\n"
            "trade run event list --from 2026-02-01 --to 2026-03-10"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ev_list.add_argument("--data-root", default=_DATA_ROOT)
    p_ev_list.add_argument("--from",   default=None, dest="from_date", help="起始日期 YYYY-MM-DD")
    p_ev_list.add_argument("--to",     default=None, dest="to_date",   help="结束日期 YYYY-MM-DD")
    p_ev_list.add_argument("--failed", action="store_true", help="只显示无传导记录的事件")
    p_ev_list.add_argument("--limit",  type=int, default=30, help="最大显示条数（默认 30）")

    p_ev_backfill = event_sub.add_parser(
        "backfill",
        description="回填事件传导的 5d/20d 实际收益",
        epilog=(
            "trade run event backfill\n"
            "trade run event backfill --from 2026-02-01 --to 2026-03-10"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ev_backfill.add_argument("--data-root", default=_DATA_ROOT)
    p_ev_backfill.add_argument("--from", default=None, dest="from_date", help="起始日期 YYYY-MM-DD")
    p_ev_backfill.add_argument("--to",   default=None, dest="to_date",   help="结束日期 YYYY-MM-DD")

    p_ev_retry = event_sub.add_parser(
        "retry",
        description="已弃用：等价于 sync --failed-only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ev_retry.add_argument("--data-root", default=_DATA_ROOT)
    p_ev_retry.add_argument("--from", default=None, dest="start", help="起始日期 YYYY-MM-DD")
    p_ev_retry.add_argument("--to",   default=None, dest="end",   help="结束日期 YYYY-MM-DD")

    return parser


def _cmd_event_sync(args: argparse.Namespace) -> int:
    if args.command == "event" and args.event_cmd == "extract":
        print("warning: `trade run event extract` 已弃用，请改用 `trade run event sync`")
    if args.command == "event" and args.event_cmd == "retry":
        print("warning: `trade run event retry` 已弃用，请改用 `trade run event sync --failed-only`")
        args.failed_only = True
    summary = sync_events(
        args.data_root,
        start=args.start,
        end=args.end,
        failed_only=bool(getattr(args, "failed_only", False)),
        force=bool(getattr(args, "force", False)),
    )
    print(summary.format())
    return 0


def _cmd_event_add(args: argparse.Namespace) -> int:
    from trade_py.report.event_pipeline import run_event_pipeline_for

    event_date = args.date or date.today().isoformat()
    primary_sector = args.sector or "SW_Unknown"
    raw = f"{event_date}|{args.event_type}|{primary_sector}"
    event_id = hashlib.sha1(raw.encode()).hexdigest()[:12]
    event_dict = {
        "event_id": event_id,
        "event_date": event_date,
        "event_type": args.event_type,
        "magnitude": args.magnitude,
        "actor_type": args.actor_type,
        "primary_sector": primary_sector,
        "breadth": "market" if primary_sector == "SW_Unknown" else "sector",
        "sentiment_score": 0.5,
        "news_volume": 1,
        "summary": args.summary or f"手工创建: {args.event_type}",
    }
    msg = run_event_pipeline_for(event_dict, args.data_root)
    print(f"事件已写入并传导: event_id={event_id}  type={args.event_type}  magnitude={args.magnitude}")
    print(msg)
    return 0


def _cmd_event_list(args: argparse.Namespace) -> int:
    from trade_py.db.settings_db import SettingsDB

    db = SettingsDB(args.data_root)
    rows = db.get_events(
        from_date=args.from_date,
        to_date=args.to_date,
        failed_only=args.failed,
        limit=args.limit,
    )
    if not rows:
        print("无事件记录" + (" (无传导)" if args.failed else ""))
        return 0

    header = f"{'date':<12}{'type':<25}{'mag':>5}  {'sector':<22}{'stocks':>6}"
    print(header)
    print("-" * len(header))
    for r in rows:
        stocks = r.get("affected_stocks", 0) or 0
        flag = "  ← 无传导" if stocks == 0 else ""
        print(
            f"{str(r['event_date']):<12}"
            f"{str(r['event_type']):<25}"
            f"{float(r['magnitude']):>5.2f}  "
            f"{str(r['primary_sector']):<22}"
            f"{stocks:>6}"
            f"{flag}"
        )
    print(f"\n共 {len(rows)} 条事件")
    return 0


def _cmd_event_backfill(args: argparse.Namespace) -> int:
    print(backfill_events(args.data_root, start=args.from_date, end=args.to_date))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    args = make_parser().parse_args(argv)

    if args.command == "start":
        from trade_py.report.scheduler import register_jobs
        import schedule as _schedule
        register_jobs(args.data_root)
        logger.info("Scheduler running (CST). Press Ctrl+C to stop.")
        try:
            while True:
                _schedule.run_pending()
                time.sleep(30)
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
        return 0

    if args.command == "dry-run":
        from trade_py.report.scheduler import run_all_once
        run_all_once(args.data_root)
        return 0

    if args.command == "status":
        from trade_py.db.settings_db import SettingsDB
        rows = SettingsDB(args.data_root).job_runs_recent(args.limit)
        if not rows:
            print("暂无执行记录。")
            return 0
        _STATUS_ICON = {"success": "✅", "failure": "❌", "running": "🔄"}
        print(f"{'#':<5} {'job':<22} {'状态':<10} {'开始时间':<20} {'耗时(s)':>8}  {'摘要'}")
        print("-" * 90)
        for r in rows:
            icon = _STATUS_ICON.get(r["status"], " ")
            dur = f"{r['duration_s']:.1f}" if r["duration_s"] is not None else "-"
            msg = (r["message"] or "")[:50]
            print(f"{r['id']:<5} {r['job_name']:<22} {icon} {r['status']:<8} {r['started_at']:<20} {dur:>8}  {msg}")
        return 0

    if args.command == "plan":
        from trade_py.db.settings_db import SettingsDB
        rows = SettingsDB(args.data_root).job_schedule_all()
        if not rows:
            print("计划表为空，请先启动调度器: trade run start")
            return 0
        _ICON = {"success": "✅", "failure": "❌", None: " "}
        print(f"{'job':<22} {'计划时间':<22} {'下次运行':<20} {'上次状态':<10} {'上次执行'}")
        print("-" * 100)
        for r in rows:
            icon = _ICON.get(r["last_status"], " ")
            next_run = r["next_run"] or "(未启动)"
            last_at = r["last_run_at"] or "-"
            last_st = f"{icon} {r['last_status'] or '-'}"
            print(f"{r['job_name']:<22} {r['cron_desc']:<22} {next_run:<20} {last_st:<10} {last_at}")
        return 0

    if args.command in JOB_REGISTRY:
        print(f"Running job: {args.command} ...")
        try:
            result = run_job(args.command, args.data_root)
            print(result)
        except Exception as exc:
            logger.error("Job %s failed: %s", args.command, exc, exc_info=True)
            return 1
        return 0

    if args.command == "event":
        dispatch = {
            "sync":    _cmd_event_sync,
            "extract": _cmd_event_sync,
            "add":     _cmd_event_add,
            "list":    _cmd_event_list,
            "backfill": _cmd_event_backfill,
            "retry":   _cmd_event_sync,
        }
        fn = dispatch.get(args.event_cmd)
        if fn is None:
            return 1
        return fn(args)

    return 1
