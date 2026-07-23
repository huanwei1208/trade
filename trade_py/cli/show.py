"""trade show — unified read-only view for DAG / calendar / agenda / events / backups / dev dumps.

This is the NEW read-only domain (post CLI convergence). It absorbs view/read
commands previously scattered across ``inspect``, ``event``, and ``dev``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from trade_py.cli import epilog_from_subparsers, global_flag_parent
from trade_py.infra.settings import default_data_root

_DATA_ROOT = str(default_data_root())


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade show",
        description="只读视图：dag / calendar / agenda / events / runs / backups / 内部调试转储",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flag_parent()],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── dag ────────────────────────────────────────────────────────────────────
    p_dag = sub.add_parser("dag", description="查看 pipeline DAG",
                           epilog="trade show dag\ntrade show dag --all",
                           formatter_class=argparse.RawDescriptionHelpFormatter)
    p_dag.add_argument("--data-root", default=_DATA_ROOT)
    p_dag.add_argument("--all", action="store_true", help="显示已禁用的节点")

    # ── calendar ───────────────────────────────────────────────────────────────
    p_cal = sub.add_parser("calendar", description="查看交易日历与未来事件",
                           epilog="trade show calendar --days 7",
                           formatter_class=argparse.RawDescriptionHelpFormatter)
    p_cal.add_argument("--data-root", default=_DATA_ROOT)
    p_cal.add_argument("--date", default=date.today().isoformat())
    p_cal.add_argument("--days", type=int, default=5)

    # ── agenda ─────────────────────────────────────────────────────────────────
    p_agenda = sub.add_parser("agenda", description="查看 agenda 队列",
                              epilog="trade show agenda --limit 20",
                              formatter_class=argparse.RawDescriptionHelpFormatter)
    p_agenda.add_argument("--data-root", default=_DATA_ROOT)
    p_agenda.add_argument("--limit", type=int, default=20)
    p_agenda.add_argument("--status", default=None)

    # ── events ─────────────────────────────────────────────────────────────────
    p_events = sub.add_parser("events", description="查看最近事件日志",
                              epilog="trade show events --limit 30",
                              formatter_class=argparse.RawDescriptionHelpFormatter)
    p_events.add_argument("--data-root", default=_DATA_ROOT)
    p_events.add_argument("--limit", type=int, default=20)
    p_events.add_argument("--topic", default=None, help="按 topic 过滤")

    # ── runs ───────────────────────────────────────────────────────────────────
    p_runs = sub.add_parser("runs", description="查看最近 job_runs 执行历史",
                            epilog="trade show runs --stage compute",
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    p_runs.add_argument("--data-root", default=_DATA_ROOT)
    p_runs.add_argument("--limit", type=int, default=30)
    p_runs.add_argument("--stage", default=None, choices=["fetch", "compute", "train"],
                        help="按 stage 过滤")

    # ── backups ────────────────────────────────────────────────────────────────
    p_backups = sub.add_parser("backups", description="查看最近备份",
                               epilog="trade show backups --limit 20",
                               formatter_class=argparse.RawDescriptionHelpFormatter)
    p_backups.add_argument("--data-root", default=_DATA_ROOT)
    p_backups.add_argument("--limit", type=int, default=20)

    # ── workflows ──────────────────────────────────────────────────────────────
    p_wf = sub.add_parser("workflows", description="查看最近 workflow 运行轨迹",
                          epilog="trade show workflows --limit 10",
                          formatter_class=argparse.RawDescriptionHelpFormatter)
    p_wf.add_argument("--data-root", default=_DATA_ROOT)
    p_wf.add_argument("--limit", type=int, default=10)

    # ── belief / attention / evidence / rec / quality (from dev) ──────────────
    for cmd, desc, ex in [
        ("belief", "查看 BeliefState for symbol", "trade show belief 600000.SH"),
        ("attention", "查看 top AttentionScores for symbol", "trade show attention 600000.SH"),
        ("evidence", "查看 Evidence rows for symbol", "trade show evidence 600000.SH"),
        ("rec", "查看 Recommendation for symbol", "trade show rec 600000.SH"),
    ]:
        p = sub.add_parser(cmd, description=desc, epilog=ex,
                           formatter_class=argparse.RawDescriptionHelpFormatter)
        p.add_argument("symbol", help="股票代码")
        p.add_argument("--date", default=None)
        p.add_argument("--data-root", default=_DATA_ROOT)
        p.add_argument("--json", dest="as_json", action="store_true", help="JSON 输出")

    p_q = sub.add_parser("quality", description="QualityReport 历史",
                         epilog="trade show quality -n 10",
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    p_q.add_argument("--data-root", default=_DATA_ROOT)
    p_q.add_argument("-n", type=int, default=5)

    parser.epilog = epilog_from_subparsers(parser)
    return parser


def _cmd_dag(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    rows = db.pipeline_dag_all(enabled_only=not args.all)
    if not rows:
        print("pipeline_dag 为空（请运行 migration v5）")
        return 0
    stage_order = {"fetch": 0, "compute": 1, "train": 2}
    rows.sort(key=lambda r: (stage_order.get(r["stage"], 9), r["id"]))
    current_stage = None
    for r in rows:
        if r["stage"] != current_stage:
            current_stage = r["stage"]
            print(f"\n{'─'*60}")
            print(f"  STAGE: {current_stage.upper()}")
            print(f"{'─'*60}")
        enabled = "" if r["enabled"] else "  [disabled]"
        emits = f"  → {r['emits']}" if r["emits"] else ""
        print(f"  [{r['id']:>3}] {r['source']:<32} → {r['job_name']:<20}{emits}{enabled}")
        if r.get("description"):
            print(f"         {r['description']}")
    print()
    return 0


def _cmd_events(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    db.job_runs_mark_stale_by_policy()
    db.event_log_mark_stale()
    rows = db.event_log_recent(args.limit, args.topic)
    if not rows:
        print("无事件日志")
        return 0
    _ICON = {"ok": "✓", "error": "✗", "pending": "…", "skipped": "-"}
    print(f"{'id':<6} {'status':<8} {'topic':<32} {'handler':<28} {'created_at'}")
    print("-" * 100)
    for r in rows:
        icon = _ICON.get(r["status"], " ")
        handler = (r.get("handler") or "")[:27]
        created = (r.get("created_at") or "")[:19]
        print(f"{r['id']:<6} {icon} {r['status']:<6} {r['topic']:<32} {handler:<28} {created}")
    print(f"\n共 {len(rows)} 条")
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    db.job_runs_mark_stale_by_policy()
    db.event_log_mark_stale()
    rows = db.job_runs_recent(args.limit, stage=args.stage)
    if not rows:
        print("暂无执行记录")
        return 0
    _ICON = {"ok": "✓", "error": "✗", "running": "…"}
    print(f"{'id':<6} {'job':<22} {'stage':<8} {'status':<8} {'started_at':<20} {'ms':>7}  {'摘要'}")
    print("-" * 100)
    for r in rows:
        icon = _ICON.get(r["status"], " ")
        ms = str(r["elapsed_ms"]) if r["elapsed_ms"] is not None else "-"
        summary = (r["result_summary"] or "")[:40]
        stage = (r["stage"] or "")[:7]
        print(f"{r['id']:<6} {r['job_name']:<22} {stage:<8} {icon} {r['status']:<6} "
              f"{r['started_at']:<20} {ms:>7}  {summary}")
    return 0


def _cmd_calendar(args: argparse.Namespace, db) -> int:
    start = args.date
    end = (date.fromisoformat(args.date) + timedelta(days=args.days)).isoformat()
    print("trading_calendar:")
    for offset in range(args.days + 1):
        d = (date.fromisoformat(args.date) + timedelta(days=offset)).isoformat()
        row = db.trading_calendar_get(d, exchange="SSE")
        print(f"  {d}: {row.get('is_open') if row else None}  pre={row.get('pretrade_date') if row else None}")
    print("\nplanned_events:")
    for row in db.planned_events_list(start_date=start, end_date=end, limit=20):
        print(
            f"  {row.get('scheduled_at')}  {row.get('event_type'):<20}  "
            f"{row.get('importance'):<6}  {row.get('title') or ''}"
        )
    return 0


def _cmd_agenda(args: argparse.Namespace, db) -> int:
    for row in db.agenda_queue_recent(limit=args.limit, status=args.status):
        print(
            f"{row.get('agenda_id'):>4}  {row.get('run_at')}  {row.get('phase'):<5}  "
            f"{row.get('status'):<8}  {row.get('job_name') or row.get('trigger_topic') or '-':<20}  "
            f"{row.get('title') or ''}"
        )
    return 0


def _cmd_backups(args: argparse.Namespace) -> int:
    from trade_py.cli import backup as backup_cli
    return backup_cli.main(["list", "--data-root", args.data_root, "--limit", str(args.limit)])


def _cmd_workflows(args: argparse.Namespace, db) -> int:
    rows = db.event_workflow_recent(limit=args.limit)
    for row in rows:
        root_cause = row.get("root_cause") or {}
        cause = str(root_cause.get("message") or "").strip()
        print(
            f"{row.get('root_event_id'):>4}  {str(row.get('status') or '-'):8}  "
            f"{str(row.get('topic') or '-'):<24}  "
            f"{str(row.get('progress', {}).get('completed', 0))}/{str(row.get('progress', {}).get('total', 0)):<5}  "
            f"{str(row.get('title') or '-')}"
        )
        if cause:
            print(f"      cause: {cause[:180]}")
    return 0


def _cmd_dev_dump(args: argparse.Namespace) -> int:
    """Delegate belief/attention/evidence/rec/quality to dev module (internal dumps)."""
    from trade_py.cli import dev as dev_cli
    dev_argv = [args.command]
    if args.command != "quality":
        dev_argv.append(args.symbol)
        if args.date:
            dev_argv += ["--date", args.date]
    else:
        dev_argv += ["-n", str(getattr(args, "n", 5))]
    dev_argv += ["--data-root", args.data_root]
    if getattr(args, "as_json", False):
        dev_argv.append("--json")
    return dev_cli.main(dev_argv)


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv or [])

    if args.command == "dag":
        return _cmd_dag(args)
    if args.command == "events":
        return _cmd_events(args)
    if args.command == "runs":
        return _cmd_runs(args)
    if args.command == "backups":
        return _cmd_backups(args)
    if args.command in ("belief", "attention", "evidence", "rec", "quality"):
        return _cmd_dev_dump(args)

    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    try:
        if args.command == "calendar":
            return _cmd_calendar(args, db)
        if args.command == "agenda":
            return _cmd_agenda(args, db)
        if args.command == "workflows":
            return _cmd_workflows(args, db)
    finally:
        db.close()

    return 0
