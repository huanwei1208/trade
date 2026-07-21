"""trade event — control-plane: trigger / run / sync / add / rebuild / backfill.

Post CLI convergence: list/runs/dag moved to ``trade show`` and enable/disable
moved to ``trade config dag``. Those subcommands remain here as deprecated shims
that print warnings and forward to the new locations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
import time
from dataclasses import dataclass
from datetime import date
from typing import NoReturn

from trade_py.cli import global_flag_parent
from trade_py.infra.settings.context import default_data_root

logger = logging.getLogger(__name__)

_DATA_ROOT = str(default_data_root())
_EXIT_TEMPFAIL = 75

_VALID_TYPES = [
    "policy_positive",
    "policy_negative",
    "earnings_beat",
    "earnings_miss",
    "macro_positive",
    "macro_negative",
    "supply_shock",
    "sector_rotation",
    # legacy types kept for compat
    "semiconductor_policy",
    "new_energy_policy",
    "real_estate_easing",
    "real_estate_tightening",
    "rate_cut",
    "rate_hike",
    "commodity_surge",
    "commodity_slump",
    "defense_spending_up",
    "macro_recovery",
    "macro_slowdown",
    "geopolitical_risk",
    "merger_acquisition",
    "regulatory_tightening",
    "supply_disruption",
    "other",
]


@dataclass
class EventRunResult:
    summary: str
    exit_code: int = 0
    rows_processed: int | None = None


def _reject_non_finite_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number is not allowed: {value}")
    return parsed


def _track_event_run(
    data_root: str,
    job_name: str,
    runner,
    *,
    stage: str = "compute",
) -> int:
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    run_id = db.job_run_start(job_name, stage=stage)
    started = time.time()
    try:
        result = runner()
        elapsed_ms = int((time.time() - started) * 1000)
        status = "ok" if result.exit_code == 0 else "error"
        db.job_run_finish(
            run_id,
            status,
            result_summary=result.summary[:500],
            symbols_processed=result.rows_processed,
            elapsed_ms=elapsed_ms,
        )
        return result.exit_code
    except KeyboardInterrupt:
        elapsed_ms = int((time.time() - started) * 1000)
        db.job_run_finish(
            run_id,
            "error",
            result_summary="interrupted by user",
            elapsed_ms=elapsed_ms,
        )
        logger.warning("event command interrupted job=%s", job_name)
        return 130
    except Exception as exc:
        elapsed_ms = int((time.time() - started) * 1000)
        db.job_run_finish(
            run_id,
            "error",
            result_summary=str(exc)[:500],
            elapsed_ms=elapsed_ms,
        )
        logger.error("event command failed job=%s: %s", job_name, exc, exc_info=True)
        return 1


def make_parser() -> argparse.ArgumentParser:
    from trade_py.jobs import JOB_REGISTRY

    parser = argparse.ArgumentParser(
        prog="trade event",
        description="事件控制平面 — 触发/运行/同步/新建/重建/回填 (list/runs/dag 已移至 show; enable/disable 已移至 config dag)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flag_parent()],
        epilog=(
            "示例:\n"
            "  trade event trigger gate.morning        # 触发晨盘 gate\n"
            "  trade event run kline_update            # 直接运行 job\n"
            "  trade event sync --from 2026-01-01      # 补齐事件库\n"
            "  trade event add --type policy_positive --magnitude 0.7\n"
            "  trade event backfill                    # 回填实际收益\n"
            "  trade event rebuild                     # 重建事件库\n"
            "  trade show dag                          # 查看 pipeline DAG (原 event dag)\n"
            "  trade show events                       # 查看最近事件日志 (原 event list)\n"
            "  trade show runs                         # 查看 job 执行历史 (原 event runs)\n"
            "  trade config dag enable kline_update    # 启用 DAG 节点 (原 event enable)\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    # ── trigger ────────────────────────────────────────────────────────────────
    p_trigger = sub.add_parser("trigger", description="向 EventBus 发布事件（触发 DAG）")
    p_trigger.add_argument("topic", help="事件 topic，如 gate.morning")
    p_trigger.add_argument("--data-root", default=_DATA_ROOT)
    p_trigger.add_argument("--payload", default="{}", help="JSON payload（默认 {}）")
    p_trigger.add_argument(
        "--timeout-sec", type=float, default=3600.0, help="等待级联收敛的最长秒数"
    )

    # ── run ────────────────────────────────────────────────────────────────────
    p_run = sub.add_parser("run", description="直接执行单个 job（绕开 bus，同步调试）")
    p_run.add_argument(
        "job",
        choices=list(JOB_REGISTRY),
        metavar="<job>",
        help="{" + " | ".join(JOB_REGISTRY) + "}",
    )
    p_run.add_argument("--data-root", default=_DATA_ROOT)

    # ── list ───────────────────────────────────────────────────────────────────
    p_list = sub.add_parser("list", description="查看最近 event_log 条目")
    p_list.add_argument("--data-root", default=_DATA_ROOT)
    p_list.add_argument("--limit", type=int, default=30)
    p_list.add_argument("--topic", default=None, help="按 topic 过滤")

    # ── runs ───────────────────────────────────────────────────────────────────
    p_runs = sub.add_parser("runs", description="查看最近 job_runs 执行历史")
    p_runs.add_argument("--data-root", default=_DATA_ROOT)
    p_runs.add_argument("--limit", type=int, default=30)
    p_runs.add_argument(
        "--stage", default=None, choices=["fetch", "compute", "train"], help="按 stage 过滤"
    )

    # ── dag ────────────────────────────────────────────────────────────────────
    p_dag = sub.add_parser("dag", description="查看 pipeline_dag 三段式 DAG")
    p_dag.add_argument("--data-root", default=_DATA_ROOT)
    p_dag.add_argument("--all", action="store_true", help="显示已禁用的节点")

    # ── enable / disable ───────────────────────────────────────────────────────
    p_enable = sub.add_parser("enable", description="启用 pipeline_dag 节点")
    p_enable.add_argument("job_name", help="job 名称")
    p_enable.add_argument("--data-root", default=_DATA_ROOT)

    p_disable = sub.add_parser("disable", description="禁用 pipeline_dag 节点")
    p_disable.add_argument("job_name", help="job 名称")
    p_disable.add_argument("--data-root", default=_DATA_ROOT)

    # ── sync ───────────────────────────────────────────────────────────────────
    p_sync = sub.add_parser(
        "sync",
        description="补齐事件库和 KG 传导",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_sync.add_argument("--data-root", default=_DATA_ROOT)
    p_sync.add_argument("--from", default=None, dest="start", help="起始日期 YYYY-MM-DD")
    p_sync.add_argument("--to", default=None, dest="end", help="结束日期 YYYY-MM-DD")
    p_sync.add_argument("--failed-only", action="store_true")
    p_sync.add_argument("--force", action="store_true")

    p_rebuild = sub.add_parser(
        "rebuild",
        description="按现有 Silver 重建 market_events 和 KG 传导",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_rebuild.add_argument("--data-root", default=_DATA_ROOT)
    p_rebuild.add_argument("--from", default=None, dest="start", help="起始日期 YYYY-MM-DD")
    p_rebuild.add_argument("--to", default=None, dest="end", help="结束日期 YYYY-MM-DD")
    p_rebuild.add_argument(
        "--with-propagation", action="store_true", help="同时重建 event_propagations（更慢）"
    )
    p_rebuild.add_argument(
        "--incremental-by-month", action="store_true", help="按月分块重建，适合历史长窗口"
    )

    # ── add ────────────────────────────────────────────────────────────────────
    p_add = sub.add_parser(
        "add",
        description="手工创建事件 → 写库 → KG传导",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_add.add_argument("--data-root", default=_DATA_ROOT)
    p_add.add_argument(
        "--type", required=True, dest="event_type", choices=_VALID_TYPES, help="事件类型"
    )
    p_add.add_argument("--magnitude", type=float, required=True, help="事件强度 [-1, 1]")
    p_add.add_argument("--entity", default=None, help="主体实体 ID（股票代码或板块代码）")
    p_add.add_argument("--summary", default="", help="事件摘要")
    p_add.add_argument("--date", default=None, help="事件日期 YYYY-MM-DD，默认今天")

    # ── backfill ───────────────────────────────────────────────────────────────
    p_backfill = sub.add_parser(
        "backfill",
        description="回填事件传播的 5d/20d 实际收益",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_backfill.add_argument("--data-root", default=_DATA_ROOT)
    p_backfill.add_argument("--from", default=None, dest="from_date")
    p_backfill.add_argument("--to", default=None, dest="to_date")

    return parser


# ── Command handlers ────────────────────────────────────────────────────────────


def _cmd_trigger(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(
            args.payload,
            parse_float=_parse_finite_json_float,
            parse_constant=_reject_non_finite_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        detail = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
        print(f"Invalid --payload JSON: {detail}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print(
            f"Invalid --payload: expected a JSON object, got {type(payload).__name__}",
            file=sys.stderr,
        )
        return 2

    from trade_py.bus import EventAdmissionError, bootstrap_from_dag, get_bus
    from trade_py.bus.models import AdmissionOutcome
    from trade_py.db.trade_db import TradeDB

    db = None
    bus = None
    exit_code = 1
    try:
        db = TradeDB(args.data_root)
        db.job_runs_mark_stale_by_policy()
        db.event_log_mark_stale()
        bus = get_bus(db)
        bootstrap_from_dag(db, args.data_root, bus=bus)
        try:
            result = bus.publish_with_outcome(args.topic, payload)
        except EventAdmissionError as exc:
            result = exc.result

        dispatch_status = "accepted" if result.accepted else "deferred"
        action = "none" if result.accepted else "replay_existing"
        accepted_handlers = sum(
            1 for handler in result.handlers if handler.outcome is AdmissionOutcome.ACCEPTED
        )
        verb = "Published" if result.accepted else "Deferred"
        print(
            f"{verb} event_id={result.event.id}  topic={args.topic} durable=true "
            f"outcome={result.outcome.value} dispatch_status={dispatch_status} "
            f"action={action} handlers_accepted={accepted_handlers}/{len(result.handlers)}"
        )
        if not result.accepted:
            exit_code = _EXIT_TEMPFAIL
        else:
            idle = bus.wait_for_idle(
                min_event_id=result.event.id,
                timeout_sec=float(args.timeout_sec),
            )
            if not idle:
                logger.warning(
                    "event trigger timeout waiting for cascade to settle topic=%s event_id=%s",
                    args.topic,
                    result.event.id,
                )
            exit_code = 0
    except Exception as exc:
        logger.error(
            "event trigger failed topic=%s: %s",
            args.topic,
            exc,
            exc_info=True,
        )
        print(
            f"Event trigger failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        exit_code = 1
    finally:
        cleanup_failed = False
        if bus is not None:
            try:
                bus.shutdown(wait=True)
            except Exception as exc:
                cleanup_failed = True
                logger.error("event trigger bus shutdown failed: %s", exc, exc_info=True)
        if db is not None:
            try:
                db.close()
            except Exception as exc:
                cleanup_failed = True
                logger.error("event trigger database close failed: %s", exc, exc_info=True)
        if cleanup_failed and exit_code == 0:
            exit_code = 1
    return exit_code


def _cmd_run(args: argparse.Namespace) -> int:
    from trade_py.jobs import run_job

    print(f"Running job: {args.job} ...")
    try:
        result = run_job(args.job, args.data_root)
        print(result)
        return 0
    except Exception as exc:
        logger.error("Job %s failed: %s", args.job, exc, exc_info=True)
        return 1


def _cmd_list(args: argparse.Namespace) -> int:
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
    print(
        f"{'id':<6} {'job':<22} {'stage':<8} {'status':<8} {'started_at':<20} {'ms':>7}  {'摘要'}"
    )
    print("-" * 100)
    for r in rows:
        icon = _ICON.get(r["status"], " ")
        ms = str(r["elapsed_ms"]) if r["elapsed_ms"] is not None else "-"
        summary = (r["result_summary"] or "")[:40]
        stage = (r["stage"] or "")[:7]
        print(
            f"{r['id']:<6} {r['job_name']:<22} {stage:<8} {icon} {r['status']:<6} "
            f"{r['started_at']:<20} {ms:>7}  {summary}"
        )
    return 0


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
            print(f"\n{'─' * 60}")
            print(f"  STAGE: {current_stage.upper()}")
            print(f"{'─' * 60}")
        enabled = "" if r["enabled"] else "  [disabled]"
        emits = f"  → {r['emits']}" if r["emits"] else ""
        print(f"  [{r['id']:>3}] {r['source']:<32} → {r['job_name']:<20}{emits}{enabled}")
        if r.get("description"):
            print(f"         {r['description']}")
    print()
    return 0


def _cmd_enable_disable(args: argparse.Namespace, enable: bool) -> int:
    import sys as _sys

    action_word = "enable" if enable else "disable"
    print(
        f"Note: 'trade event {action_word}' is deprecated; "
        f"use 'trade config dag {action_word} {args.job_name}' instead.",
        file=_sys.stderr,
    )
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(args.data_root)
    n = db.pipeline_dag_set_enabled_by_job(args.job_name, enable)
    action_cn = "启用" if enable else "禁用"
    print(f"已{action_cn} {n} 条 pipeline_dag 节点（job_name={args.job_name}）")
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    from trade_py.event import sync_events

    def _runner() -> EventRunResult:
        summary = sync_events(
            args.data_root,
            start=args.start,
            end=args.end,
            failed_only=getattr(args, "failed_only", False),
            force=getattr(args, "force", False),
        )
        text = summary.format()
        print(text)
        return EventRunResult(text, rows_processed=summary.synced_events)

    return _track_event_run(args.data_root, "event_sync", _runner)


def _cmd_rebuild(args: argparse.Namespace) -> int:
    from trade_py.event import rebuild_events

    def _runner() -> EventRunResult:
        summary = rebuild_events(
            args.data_root,
            start=args.start,
            end=args.end,
            propagate=args.with_propagation,
            incremental_by_month=getattr(args, "incremental_by_month", False),
        )
        text = "事件重建: " + summary.format()
        print(text)
        return EventRunResult(text, rows_processed=summary.synced_events)

    return _track_event_run(args.data_root, "event_rebuild", _runner)


def _cmd_add(args: argparse.Namespace) -> int:
    from trade_py.event.pipeline import run_event_pipeline_for

    event_date = args.date or date.today().isoformat()
    entity_id = args.entity or "market"
    raw = f"{event_date}|{args.event_type}|{entity_id}"
    event_id = hashlib.sha1(raw.encode()).hexdigest()[:12]
    event_dict = {
        "event_id": event_id,
        "event_date": event_date,
        "event_type": args.event_type,
        "magnitude": args.magnitude,
        "entity_id": entity_id,
        "breadth": "market" if entity_id == "market" else "company",
        "confidence": 1.0,
        "sentiment_score": 0.5,
        "news_volume": 1,
        "summary": args.summary or f"手工创建: {args.event_type}",
    }
    msg = run_event_pipeline_for(event_dict, args.data_root)
    print(f"事件已写入: event_id={event_id}  type={args.event_type}  mag={args.magnitude}")
    print(msg)
    return 0


def _cmd_backfill(args: argparse.Namespace) -> int:
    from trade_py.event import backfill_events

    print(backfill_events(args.data_root, start=args.from_date, end=args.to_date))
    return 0


# ── Main ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    args = make_parser().parse_args(argv)

    # Deprecated commands: still work but print warning
    if args.command == "list":
        print(
            "Note: 'trade event list' is deprecated; use 'trade show events' instead.",
            file=sys.stderr,
        )
        return _cmd_list(args)
    if args.command == "runs":
        print(
            "Note: 'trade event runs' is deprecated; use 'trade show runs' instead.",
            file=sys.stderr,
        )
        return _cmd_runs(args)
    if args.command == "dag":
        print(
            "Note: 'trade event dag' is deprecated; use 'trade show dag' instead.",
            file=sys.stderr,
        )
        return _cmd_dag(args)

    dispatch = {
        "trigger": _cmd_trigger,
        "run": _cmd_run,
        "enable": lambda a: _cmd_enable_disable(a, True),
        "disable": lambda a: _cmd_enable_disable(a, False),
        "sync": _cmd_sync,
        "rebuild": _cmd_rebuild,
        "add": _cmd_add,
        "backfill": _cmd_backfill,
    }
    fn = dispatch.get(args.command)
    if fn is None:
        return 1
    return fn(args)
