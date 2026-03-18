"""trade ops — operational inspection and maintenance commands.

Usage:
    trade ops status             # overall system health (DB + freshness + quality gate)
    trade ops backfill <job>     # backfill a specific job
    trade ops inspect <table>    # inspect an EBRT table row count
    trade ops freshness          # print FreshnessStatus for today
"""
from __future__ import annotations

import argparse
import logging
from datetime import date

from trade_py.infra.settings import default_data_root

logger = logging.getLogger(__name__)
_DATA_ROOT = str(default_data_root())


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade ops",
        description="运营检查与维护（EBRT）",
    )
    sub = parser.add_subparsers(dest="action", metavar="<操作>")

    sp_status = sub.add_parser("status", help="系统整体健康")
    sp_status.add_argument("--data-root", default=_DATA_ROOT)

    sp_backfill = sub.add_parser("backfill", help="回填指定 job")
    sp_backfill.add_argument("job", help="job 名称")
    sp_backfill.add_argument("--date-from", default=None)
    sp_backfill.add_argument("--date-to", default=None)
    sp_backfill.add_argument("--data-root", default=_DATA_ROOT)

    sp_inspect = sub.add_parser("inspect", help="检查 EBRT 表")
    sp_inspect.add_argument("table", nargs="?", default=None)
    sp_inspect.add_argument("--data-root", default=_DATA_ROOT)

    sp_fresh = sub.add_parser("freshness", help="打印数据新鲜度")
    sp_fresh.add_argument("--data-root", default=_DATA_ROOT)
    sp_fresh.add_argument("--date", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)

    if not args.action or args.action == "status":
        data_root = getattr(args, "data_root", _DATA_ROOT)
        from trade_py.db.trade_db import TradeDB
        db = TradeDB(data_root)
        today = date.today().isoformat()

        print("=== Trade System Status ===")
        # Schema migrations
        try:
            versions = [r[0] for r in db._conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 5"
            ).fetchall()]
            print(f"Schema: v{versions[0] if versions else '?'} applied")
        except Exception:
            pass

        # EBRT table counts
        ebrt_tables = [
            "BeliefState", "Evidence", "Recommendation",
            "RecommendationTrace", "QualityReport", "FreshnessStatus",
        ]
        for t in ebrt_tables:
            try:
                cnt = db._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                print(f"  {t:<25}: {cnt:>6} rows")
            except Exception:
                print(f"  {t:<25}: (table missing)")

        # Latest QualityReport
        qr = db.quality_report_latest()
        if qr:
            print(f"\nLatest QualityReport ({qr.get('eval_date', '?')}):")
            print(f"  op={qr.get('operational_status')} research={qr.get('research_status')}")
        db.close()
        return 0

    if args.action == "backfill":
        data_root = args.data_root
        from trade_py.engine import run_node
        result = run_node(args.job, data_root,
                          date_from=args.date_from, date_to=args.date_to)
        print(result)
        return 0

    if args.action == "inspect":
        data_root = args.data_root
        from trade_py.db.trade_db import TradeDB
        db = TradeDB(data_root)
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

    if args.action == "freshness":
        data_root = args.data_root
        today = args.date or date.today().isoformat()
        from trade_py.db.trade_db import TradeDB
        db = TradeDB(data_root)
        rows = db.freshness_status_list(today)
        db.close()
        if not rows:
            print(f"No FreshnessStatus for {today}")
            return 0
        print(f"Freshness for {today}:")
        for r in rows:
            lag = r.get("lag_days")
            lag_str = f"{lag}d" if lag is not None else "-"
            print(f"  {r['dataset']:<22} last={r.get('freshness_date','-'):>12}"
                  f" lag={lag_str:>4} status={r.get('status','-')}")
        return 0

    parser.print_help()
    return 1
