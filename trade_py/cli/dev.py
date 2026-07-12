"""trade dev — developer debug utilities.

Usage:
    trade dev belief <symbol>       # print latest BeliefState for symbol
    trade dev attention <symbol>    # print top AttentionScores for symbol
    trade dev evidence <symbol>     # print Evidence rows for symbol
    trade dev rec <symbol>          # print latest Recommendation for symbol
    trade dev quality               # print QualityReport history
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
        prog="trade dev",
        description="开发调试工具（EBRT）",
        parents=[global_flag_parent()],
    )
    sub = parser.add_subparsers(dest="cmd", metavar="<命令>")

    for cmd in ["belief", "attention", "evidence", "rec"]:
        p = sub.add_parser(cmd, help=f"查看 {cmd}")
        p.add_argument("symbol", help="股票代码")
        p.add_argument("--date", default=None)
        p.add_argument("--data-root", default=_DATA_ROOT)
        p.add_argument("--json", dest="as_json", action="store_true", help="JSON 输出")

    sp_q = sub.add_parser("quality", help="QualityReport 历史")
    sp_q.add_argument("--data-root", default=_DATA_ROOT)
    sp_q.add_argument("-n", type=int, default=5)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)

    if not args.cmd:
        parser.print_help()
        return 1

    data_root = getattr(args, "data_root", _DATA_ROOT)
    today = getattr(args, "date", None) or date.today().isoformat()

    from trade_py.db.trade_db import TradeDB
    db = TradeDB(data_root)

    try:
        if args.cmd == "belief":
            symbol = args.symbol.upper()
            bs = db.belief_state_get(today, symbol)
            bt = db.belief_transition_get(symbol, today)
            if not bs:
                print(f"No BeliefState for {symbol} on {today}")
                return 0
            bv = bs.get("belief_vec") or {}
            delta = (bt.get("delta_vec") or {}).get("mu_delta", 0.0) if bt else 0.0
            if args.as_json:
                print(json.dumps(bs, ensure_ascii=False, indent=2))
            else:
                print(f"BeliefState {symbol} @ {today}:")
                print(f"  μ={bv.get('mu',0):+.4f}  σ={bv.get('sigma',0.3):.4f}")
                print(f"  Δμ={delta:+.4f}")
                print(f"  confidence={bs.get('confidence',0):.3f}  uncertainty={bs.get('uncertainty',0.3):.3f}")
                print(f"  version={bs.get('belief_version','-')}  updated={bs.get('updated_at','-')}")
            return 0

        if args.cmd == "attention":
            symbol = args.symbol.upper()
            rows = db.attention_list(symbol, today, top_n=10)
            if not rows:
                print(f"No AttentionScores for {symbol} on {today}")
                return 0
            if args.as_json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                print(f"Top AttentionScores {symbol} @ {today}:")
                for i, r in enumerate(rows, 1):
                    print(f"  {i:2d}. ev={r.get('evidence_id','?'):40s}"
                          f"  w={r.get('weight',0):.4f}  logit={r.get('logit',0):+.3f}")
            return 0

        if args.cmd == "evidence":
            symbol = args.symbol.upper()
            rows = db.evidence_list(symbol, today, lookback_days=3)
            if not rows:
                print(f"No Evidence for {symbol} around {today}")
                return 0
            if args.as_json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                print(f"Evidence {symbol} (last 3d):")
                for r in rows:
                    print(f"  {r.get('as_of_date','-')} [{r.get('evidence_type','-'):18s}]"
                          f"  str={r.get('strength',0):.3f}  dir={r.get('direction',0):+.2f}"
                          f"  rel={r.get('reliability',0):.2f}  nov={r.get('novelty',0):.2f}")
            return 0

        if args.cmd == "rec":
            symbol = args.symbol.upper()
            recs = db.recommendation_list(today)
            rec = next((r for r in recs if r.get("symbol") == symbol), None)
            if not rec:
                print(f"No Recommendation for {symbol} on {today}")
                return 0
            if args.as_json:
                print(json.dumps(rec, ensure_ascii=False, indent=2))
            else:
                print(f"Recommendation {symbol} @ {today}:")
                print(f"  action={rec.get('action')}  conviction={rec.get('conviction')}")
                print(f"  score={rec.get('score'):.4f}  risk={rec.get('risk'):.4f}")
                reasons = rec.get("reasons") or []
                for r in reasons[:3]:
                    print(f"  → {r.get('description','?')}")
            return 0

        if args.cmd == "quality":
            n = getattr(args, "n", 5)
            with db._conn_lock:
                rows = db._conn.execute(
                    "SELECT eval_date, operational_status, research_status, "
                    "brier_score, drift_mmd FROM QualityReport "
                    "ORDER BY eval_date DESC LIMIT ?",
                    (n,),
                ).fetchall()
            if not rows:
                print("No QualityReport rows found")
                return 0
            print("QualityReport history:")
            print(f"  {'date':<12} {'op':<10} {'research':<10} {'brier':>7} {'mmd':>7}")
            for r in rows:
                brier = f"{r[3]:.4f}" if r[3] is not None else "   -"
                mmd   = f"{r[4]:.4f}" if r[4] is not None else "   -"
                print(f"  {r[0]:<12} {r[1]:<10} {r[2]:<10} {brier:>7} {mmd:>7}")
            return 0

    finally:
        db.close()

    return 1
