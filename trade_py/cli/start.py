"""trade start — daemon entry point.

Starts the EventBus with all handlers registered via pipeline_dag,
then runs the scheduler loop.

Usage:
  trade start                     # run daemon (blocking)
  trade start --dry-run           # publish all gate events once, then exit
  trade start --data-root /path   # use custom data root
"""
from __future__ import annotations

import argparse
import logging
import time

from trade_py.infra.settings import default_data_root

logger = logging.getLogger(__name__)

_DATA_ROOT = str(default_data_root())


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade start",
        description="启动 EventBus daemon（DAG bootstrap + 调度器）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  trade start                   # 启动 daemon（阻塞运行）\n"
            "  trade start --dry-run         # 发布所有 gate 事件一次，验证响应链\n"
        ),
    )
    parser.add_argument("--data-root", default=_DATA_ROOT, help="数据根目录")
    parser.add_argument("--dry-run", action="store_true",
                        help="顺序发布所有 gate 事件后退出（调试用）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv or [])

    from trade_py.db.trade_db import TradeDB
    from trade_py.bus import Topic, get_bus, bootstrap_from_dag
    from trade_py.bus.scheduler import register_schedule
    import schedule

    db = TradeDB(args.data_root)
    bus = get_bus(db)

    # Bootstrap handlers from pipeline_dag (replaces hardcoded handler registration)
    bootstrap_from_dag(db, args.data_root)

    if args.dry_run:
        logger.info("=== DRY RUN: publishing all gate events ===")
        for topic in Topic.ALL_GATES:
            logger.info("Publishing %s", topic)
            bus.publish(topic)
            time.sleep(1)
        bus.shutdown(wait=True)
        logger.info("=== DRY RUN complete ===")
        return 0

    # Normal daemon mode
    register_schedule(bus, db)
    logger.info("Daemon running (CST). Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Daemon stopped.")
    finally:
        bus.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
