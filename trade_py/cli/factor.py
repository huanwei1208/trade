from __future__ import annotations

import argparse

from trade_py.analysis.factor_evaluation import factor_metrics, factor_status
from trade_py.infra.settings import default_data_root


def _print_factor_rows(rows: list[dict], *, limit: int) -> None:
    if not rows:
        print("暂无因子评估结果")
        return
    print(
        f"{'factor':<30} {'type':<12} {'cover':>7} {'rows':>8} {'rank_ic':>8} "
        f"{'pearson':>8} {'days':>6} {'std':>8}"
    )
    print("-" * 100)
    for row in rows[:limit]:
        rank_ic = "—" if row["rank_ic"] is None else f"{float(row['rank_ic']):.4f}"
        pearson = "—" if row["pearson"] is None else f"{float(row['pearson']):.4f}"
        print(
            f"{row['factor_name']:<30} {row['factor_type']:<12} "
            f"{float(row['coverage']):>7.1%} {int(row['non_null_rows']):>8} "
            f"{rank_ic:>8} {pearson:>8} {int(row['valid_days']):>6} "
            f"{float(row['std']):>8.4f}"
        )


def _cmd_status(args: argparse.Namespace) -> int:
    payload = factor_status(args.data_root)
    print(f"latest_date:     {payload.get('latest_date') or '—'}")
    print(f"total_rows:      {payload.get('total_rows', 0)}")
    print(f"date_count:      {payload.get('date_count', 0)}")
    print(f"symbol_count:    {payload.get('symbol_count', 0)}")
    print(f"factor_count:    {payload.get('factor_count', 0)}")
    print(f"registry_count:  {payload.get('registry_count', 0)}")
    print()
    print("rows_by_type:")
    for row in payload.get("rows_by_type", []):
        print(
            f"  {row['factor_type']:<12} rows={int(row['row_count']):>8} "
            f"factors={int(row['factor_count']):>4} symbols={int(row['symbol_count']):>5}"
        )
    print()
    print("latest_rows_by_type:")
    for row in payload.get("latest_rows_by_type", []):
        print(
            f"  {row['factor_type']:<12} rows={int(row['row_count']):>8} "
            f"factors={int(row['factor_count']):>4} symbols={int(row['symbol_count']):>5}"
        )
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    rows = factor_metrics(
        args.data_root,
        target=args.target,
        start=args.start,
        end=args.end,
        factor_type=args.factor_type,
        factor_names=[args.factor] if args.factor else None,
    )
    _print_factor_rows(rows, limit=args.top)
    return 0


def make_parser() -> argparse.ArgumentParser:
    from trade_py.cli import epilog_from_subparsers

    parser = argparse.ArgumentParser(
        prog="trade factor",
        description="因子仓与因子评估",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser(
        "status",
        description="查看 factors / factor_registry 状态",
        epilog="trade factor status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_status.add_argument("--data-root", default=str(default_data_root()))

    p_eval = sub.add_parser(
        "evaluate",
        description="对训练特征中的因子做覆盖率与 IC 评估",
        epilog=(
            "trade factor evaluate\n"
            "trade factor evaluate --target actual_return_20d --type technical\n"
            "trade factor evaluate --factor tech_macd_hist"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_eval.add_argument("--data-root", default=str(default_data_root()))
    p_eval.add_argument("--target", default="actual_return_5d", choices=["actual_return_5d", "actual_return_20d", "risk_5pct"])
    p_eval.add_argument("--start", default=None)
    p_eval.add_argument("--end", default=None)
    p_eval.add_argument("--type", dest="factor_type", default=None)
    p_eval.add_argument("--factor", default=None)
    p_eval.add_argument("--top", type=int, default=20)

    p_ic = sub.add_parser(
        "ic",
        description="按 RankIC 排序查看因子效果",
        epilog="trade factor ic --type graph --top 10",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ic.add_argument("--data-root", default=str(default_data_root()))
    p_ic.add_argument("--target", default="actual_return_5d", choices=["actual_return_5d", "actual_return_20d", "risk_5pct"])
    p_ic.add_argument("--start", default=None)
    p_ic.add_argument("--end", default=None)
    p_ic.add_argument("--type", dest="factor_type", default=None)
    p_ic.add_argument("--factor", default=None)
    p_ic.add_argument("--top", type=int, default=20)

    parser.epilog = epilog_from_subparsers(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv or [])
    if args.command == "status":
        return _cmd_status(args)
    if args.command in {"evaluate", "ic"}:
        return _cmd_evaluate(args)
    raise SystemExit(2)
