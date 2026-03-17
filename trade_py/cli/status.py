from __future__ import annotations

import argparse
from datetime import date, timedelta

from trade_py.config import default_data_root

_DATA_ROOT = str(default_data_root())


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade status",
        description="统一状态总览：质量门禁 / 未来事件 / agenda / 最近执行",
    )
    parser.add_argument("--data-root", default=_DATA_ROOT)
    parser.add_argument("--limit", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    from trade_py.db.trade_db import TradeDB

    args = make_parser().parse_args(argv or [])
    db = TradeDB(args.data_root)
    stale_count = db.job_runs_mark_stale_by_policy()
    stale_events = db.event_log_mark_stale()
    today = date.today().isoformat()
    gate = db.quality_gate_get()
    due = db.agenda_queue_due(limit=args.limit)
    recent_jobs = [
        row for row in db.job_runs_recent(limit=args.limit * 3)
        if (row.get("result_summary") or "") != "aborted local scheduler validation"
    ][:args.limit]
    recent_events = [
        row for row in db.event_log_recent(limit=args.limit * 3)
        if "aborted local scheduler validation" not in str(row.get("error") or "")
    ][:args.limit]
    upcoming = db.planned_events_list(
        start_date=today,
        end_date=(date.today() + timedelta(days=7)).isoformat(),
        limit=args.limit,
    )

    print(f"日期: {today}")
    if gate:
        print(f"质量门禁: {gate.get('status')}  ({gate.get('eval_date')})")
        if gate.get("reason_summary"):
            print(f"原因: {gate.get('reason_summary')}")
    else:
        print("质量门禁: <暂无>")
    if stale_count:
        print(f"运行态修复: 已收敛 {stale_count} 条 stale jobs")
    if stale_events:
        print(f"事件态修复: 已收敛 {stale_events} 条 stale events")

    print(f"\n到期 agenda: {len(due)}")
    for row in due:
        print(
            f"  {row.get('run_at')}  {row.get('phase'):<5}  "
            f"{row.get('job_name') or row.get('trigger_topic') or '-':<20}  {row.get('title') or ''}"
        )

    print(f"\n未来 7 天 planned events: {len(upcoming)}")
    for row in upcoming:
        print(
            f"  {row.get('scheduled_at')}  {row.get('event_type'):<20}  "
            f"{row.get('importance'):<6}  {row.get('title') or ''}"
        )

    print(f"\n最近 jobs:")
    for row in recent_jobs:
        print(
            f"  {row.get('started_at')}  {row.get('job_name'):<20}  "
            f"{row.get('status'):<8}  {(row.get('result_summary') or '')[:60]}"
        )

    print(f"\n最近 events:")
    for row in recent_events:
        print(
            f"  {row.get('created_at')}  {row.get('topic'):<28}  {row.get('status')}"
        )
    return 0
