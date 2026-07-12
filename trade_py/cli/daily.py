"""trade daily — run the full daily pipeline or a specific phase.

Usage:
    trade daily run              # run all stages (fetch→compute→train)
    trade daily belief           # run belief_update job
    trade daily recommend        # run recommend job
    trade daily picks            # show today's top picks from Recommendation table
    trade daily status           # show today's QualityReport / TrustGate
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from trade_py.cli import global_flag_parent
from trade_py.infra.settings import default_data_root

logger = logging.getLogger(__name__)
_DATA_ROOT = str(default_data_root())


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade daily",
        description="每日流水线管理（EBRT）",
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
    parser = make_parser()
    args = parser.parse_args(argv)
    data_root = str(args.data_root)
    asof = args.date or date.today().isoformat()

    if args.action == "run":
        from trade_py.engine import run_daily
        result = run_daily(data_root)
        ok = len(result.get("ok", []))
        err = len(result.get("error", []))
        print(f"Daily pipeline done: ok={ok} error={err}")
        for e in result.get("error", []):
            print(f"  ERROR {e['job']}: {e['error']}")
        return 0 if err == 0 else 1

    if args.action == "belief":
        from trade_py.engine import update_belief
        result = update_belief(asof, data_root)
        print(f"Belief update: {result}")
        return 0

    if args.action == "recommend":
        from trade_py.engine import produce_picks
        recs = produce_picks(asof, data_root)
        print(f"Recommendations for {asof}: {len(recs)} total")
        for r in recs[:args.top]:
            print(f"  {r['symbol']:12s} {r['action']:5s} [{r['conviction']}] "
                  f"score={r['score']:.3f} risk={r['risk']:.3f} "
                  f"μ={r.get('belief_mu', 0):+.3f}")
        return 0

    if args.action == "picks":
        from trade_py.db.trade_db import TradeDB
        db = TradeDB(data_root)
        recs = db.recommendation_list(asof)
        db.close()
        print(f"Top picks for {asof}: {len(recs)} total")
        for r in recs[:args.top]:
            print(f"  {r['symbol']:12s} {r['action']:5s} [{r['conviction']}] "
                  f"score={r['score']:.3f}")
        return 0

    if args.action == "status":
        from trade_py.db.trade_db import TradeDB
        db = TradeDB(data_root)
        qr = db.quality_report_get(asof) or db.quality_report_latest()
        fresh = db.freshness_status_list(asof)
        db.close()
        if qr:
            print(f"QualityReport {qr.get('eval_date', asof)}:")
            print(f"  operational_status : {qr.get('operational_status', '-')}")
            print(f"  research_status    : {qr.get('research_status', '-')}")
            brier = qr.get("brier_score")
            print(f"  brier_score        : {brier:.4f}" if brier is not None else "  brier_score        : -")
            mmd = qr.get("drift_mmd")
            print(f"  drift_mmd          : {mmd:.4f}" if mmd is not None else "  drift_mmd          : -")
        else:
            print(f"No QualityReport for {asof}")
        if fresh:
            print("Freshness:")
            for f in fresh:
                print(f"  {f['dataset']:20s} lag={f.get('lag_days', '-'):>3} status={f.get('status', '-')}")
        return 0

    return 1
