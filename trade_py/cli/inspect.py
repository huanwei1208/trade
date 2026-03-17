from __future__ import annotations

import argparse
from datetime import date, timedelta

from trade_py.config import default_data_root

_DATA_ROOT = str(default_data_root())


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade inspect",
        description="统一查看入口：dag / calendar / agenda / kg / factors / models / events / health",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_dag = sub.add_parser("dag", description="查看 DAG")
    p_dag.add_argument("--data-root", default=_DATA_ROOT)
    p_dag.add_argument("--all", action="store_true")

    p_calendar = sub.add_parser("calendar", description="查看交易日历与未来事件")
    p_calendar.add_argument("--data-root", default=_DATA_ROOT)
    p_calendar.add_argument("--date", default=date.today().isoformat())
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
    from trade_py.cli import backup as backup_cli
    from trade_py.cli import event as event_cli
    from trade_py.cli import factor as factor_cli
    from trade_py.cli import kg as kg_cli
    from trade_py.cli import model as model_cli
    from trade_py.db.trade_db import TradeDB

    args = make_parser().parse_args(argv or [])

    if args.command == "dag":
        call_args = ["dag", "--data-root", args.data_root]
        if args.all:
            call_args.append("--all")
        return event_cli.main(call_args)

    if args.command == "kg":
        return kg_cli.main(["evaluate", "--data-root", args.data_root, "--top", str(args.top)])

    if args.command == "factors":
        return factor_cli.main(["status", "--data-root", args.data_root])

    if args.command == "models":
        return model_cli.main(["compare", "--data-root", args.data_root])

    if args.command == "events":
        return event_cli.main(["list", "--data-root", args.data_root, "--limit", str(args.limit)])

    if args.command in {"health", "hive"}:
        from trade_py.utils.data_inspector import get_data_status

        status = get_data_status(args.data_root, sample_limit=args.sample_limit)
        kline = status.get("kline", {})
        coverage = status.get("kline_coverage", {})
        freshness = status.get("kline_freshness", {})
        sentiment = status.get("sentiment", {})
        events = status.get("events", {})
        instruments = status.get("instruments", {})
        print("data_health:")
        print(
            f"  kline: max_date={kline.get('max_date')} symbols={kline.get('symbols')} "
            f"coverage={coverage.get('coverage_pct')}% missing={coverage.get('missing_symbols')}"
        )
        print(
            f"  freshness: stale>=1d={freshness.get('stale_ge_1')} "
            f"stale>=5d={freshness.get('stale_ge_5')} max={freshness.get('max_stale_days')}"
        )
        print(
            f"  sentiment: silver_max={sentiment.get('silver', {}).get('max_date')} "
            f"gold_max={sentiment.get('gold', {}).get('max_date')}"
        )
        print(
            f"  events: max_date={events.get('max_date')} "
            f"event_count={events.get('event_count')} propagations={events.get('propagation_count')}"
        )
        print(
            f"  instruments: total={instruments.get('total_symbols')} "
            f"coverage={instruments.get('coverage_pct')}% unmapped={instruments.get('unmapped')}"
        )
        return 0

    if args.command == "workflows":
        db = TradeDB(args.data_root)
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

    if args.command == "backups":
        return backup_cli.main(["--data-root", args.data_root, "list", "--limit", str(args.limit)])

    db = TradeDB(args.data_root)

    if args.command == "calendar":
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

    if args.command == "agenda":
        for row in db.agenda_queue_recent(limit=args.limit, status=args.status):
            print(
                f"{row.get('agenda_id'):>4}  {row.get('run_at')}  {row.get('phase'):<5}  "
                f"{row.get('status'):<8}  {row.get('job_name') or row.get('trigger_topic') or '-':<20}  "
                f"{row.get('title') or ''}"
            )
        return 0

    return 0
