from __future__ import annotations

import argparse
import logging

from trade_py.infra.settings import default_data_root
from trade_py.jobs import JOB_REGISTRY

logger = logging.getLogger(__name__)

_DATA_ROOT = str(default_data_root())

_TARGET_TOPICS = {
    "morning": "gate.morning",
    "intraday": "gate.intraday",
    "realtime": "gate.intraday",
    "pre-market": "gate.pre_market",
    "signal-am": "gate.signal_am",
    "market-close": "gate.market_close",
    "evening": "gate.evening",
    "event-extract": "gate.event_extract",
    "evaluate": "gate.evaluate_daily",
    "daily-eval": "gate.evaluate_daily",
    "sector-weekly": "gate.sector_weekly",
    "fundamental-weekly": "gate.fundamental_weekly",
    "macro-weekly": "gate.macro_weekly",
    "model-weekly": "gate.model_weekly",
}

_WORKFLOWS = {
    "open": ["morning", "pre-market", "signal-am"],
    "close": ["evening", "event-extract", "evaluate_daily", "market-close"],
    "sync": ["calendar_sync", "planned_event_sync", "agenda", "evaluate_daily"],
}

_OPTIONAL_WORKFLOW_STEPS = {
    "sync": {"calendar_sync", "planned_event_sync"},
}


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade run",
        description="统一触发入口：高层事件 / agenda / 单个 job",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  trade run morning\n"
            "  trade run intraday\n"
            "  trade run agenda\n"
            "  trade run open\n"
            "  trade run close\n"
            "  trade run sync\n"
            "  trade run evaluate\n"
            "  trade run calendar_sync\n"
            "  trade run planned_event_sync\n"
            "  trade run all"
        ),
    )
    parser.add_argument("target", help="高层事件名、agenda、all，或具体 job 名")
    parser.add_argument("--data-root", default=_DATA_ROOT)
    parser.add_argument("--payload", default="{}", help="触发 gate 时附带的 JSON payload")
    parser.add_argument("--limit", type=int, default=20, help="agenda 一次最多派发多少条")
    return parser


def main(argv: list[str] | None = None) -> int:
    from trade_py.cli import event as event_cli
    from trade_py.cli import start as start_cli
    from trade_py.bus import get_bus, bootstrap_from_dag
    from trade_py.db.trade_db import TradeDB
    from trade_py.bus.scheduler import drain_due_agenda

    args = make_parser().parse_args(argv or [])
    TradeDB(args.data_root).job_runs_mark_stale_by_policy()
    target = str(args.target).strip()

    def _run_one(name: str) -> int:
        if name == "all":
            return start_cli.main(["--data-root", args.data_root, "--dry-run"])

        if name == "agenda":
            db = TradeDB(args.data_root)
            bus = get_bus(db)
            bootstrap_from_dag(db, args.data_root)
            recent = db.event_log_recent(limit=1)
            min_event_id = (int(recent[0]["id"]) + 1) if recent else 1
            count = drain_due_agenda(bus, db, limit=args.limit)
            if count:
                bus.wait_for_idle(min_event_id=min_event_id, timeout_sec=300.0)
            bus.shutdown(wait=True)
            print(f"已派发 {count} 条到期 agenda")
            return 0

        topic = _TARGET_TOPICS.get(name)
        if topic:
            return event_cli.main([
                "trigger", topic,
                "--data-root", args.data_root,
                "--payload", args.payload,
                "--timeout-sec", "7200",
            ])

        if name in JOB_REGISTRY:
            return event_cli.main([
                "run", name,
                "--data-root", args.data_root,
            ])

        if "." in name:
            return event_cli.main([
                "trigger", name,
                "--data-root", args.data_root,
                "--payload", args.payload,
                "--timeout-sec", "7200",
            ])

        logger.error("Unknown run target: %s", name)
        print(
            "未知 target。可用高层事件: "
            + ", ".join(sorted(_TARGET_TOPICS))
            + "; workflow: "
            + ", ".join(sorted(_WORKFLOWS))
            + "; 特殊值: agenda, all; 或直接传 job 名"
        )
        return 2

    if target in _WORKFLOWS:
        failures: list[tuple[str, int]] = []
        for name in _WORKFLOWS[target]:
            rc = _run_one(name)
            if rc != 0:
                if name in _OPTIONAL_WORKFLOW_STEPS.get(target, set()):
                    logger.warning("workflow %s optional step %s failed with rc=%s; continuing", target, name, rc)
                    failures.append((name, rc))
                    continue
                return rc
        if failures:
            print("workflow completed with optional failures: " + ", ".join(f"{name}(rc={rc})" for name, rc in failures))
        return 0

    return _run_one(target)
