from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass

from trade_py.config import default_data_root
from trade_py.db.trade_db import TradeDB
from trade_py.evaluation.service import (
    EvalOutcome,
    evaluate_daily,
    evaluate_events,
    evaluate_gate,
    evaluate_models,
    evaluate_sources,
)

logger = logging.getLogger(__name__)

_DATA_ROOT = str(default_data_root())


@dataclass
class EvalRunResult:
    summary: str
    status: str
    exit_code: int = 0


def _track_eval_run(data_root: str, job_name: str, runner, *, stage: str = "compute") -> int:
    db = TradeDB(data_root)
    run_id = db.job_run_start(job_name, stage=stage)
    started = time.time()
    try:
        result = runner()
        db.job_run_finish(
            run_id,
            result.status,
            result_summary=result.summary[:500],
            elapsed_ms=int((time.time() - started) * 1000),
        )
        return result.exit_code
    except KeyboardInterrupt:
        db.job_run_finish(
            run_id,
            "error",
            result_summary="interrupted by user",
            elapsed_ms=int((time.time() - started) * 1000),
        )
        return 130
    except Exception as exc:
        db.job_run_finish(
            run_id,
            "error",
            result_summary=str(exc)[:500],
            elapsed_ms=int((time.time() - started) * 1000),
        )
        logger.error("evaluate command failed job=%s: %s", job_name, exc, exc_info=True)
        return 1


def _render_source(outcome: EvalOutcome, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(outcome.payload, ensure_ascii=False, indent=2))
        return
    print(outcome.summary)
    print()
    rows = outcome.payload.get("eval_rows", [])
    health = {row["source_name"]: row for row in outcome.payload.get("health_rows", [])}
    if not rows:
        print("暂无 source 评估结果")
        return
    print(f"{'source':<24} {'healthy':<8} {'bronze':>6} {'silver':>6} {'yield/100':>10} {'rank_ic':>8}")
    print("-" * 72)
    for row in rows:
        h = health.get(row["source_name"], {})
        ic = row.get("rank_ic_5d")
        print(
            f"{row['source_name'][:24]:<24} "
            f"{str(bool(h.get('healthy', 0))):<8} "
            f"{int(h.get('bronze_days', 0)):>6} "
            f"{int(row.get('silver_rows', 0)):>6} "
            f"{float(row.get('event_yield_per_100', 0.0)):>10.2f} "
            f"{(f'{float(ic):.4f}' if ic is not None else '—'):>8}"
        )


def _render_event(outcome: EvalOutcome, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(outcome.payload, ensure_ascii=False, indent=2))
        return
    payload = outcome.payload
    print(outcome.summary)
    print()
    print(f"status: {outcome.status}")
    print(f"range:  {payload['start_date']} -> {payload['end_date']}")
    print(f"events: {payload['event_count']}")
    print(f"effective_event_rate:     {payload['effective_event_rate']:.2%}")
    print(f"sw_unknown_ratio:         {payload['sw_unknown_ratio']:.2%}")
    print(f"propagations_per_event:   {payload['propagations_per_event']:.2f}")
    print(f"labeled_propagation_ratio:{payload['labeled_propagation_ratio']:.2%}")
    if payload.get("avg_actual_return_5d") is not None:
        print(f"avg_actual_return_5d:     {payload['avg_actual_return_5d']:.4f}")
    if payload.get("avg_actual_return_20d") is not None:
        print(f"avg_actual_return_20d:    {payload['avg_actual_return_20d']:.4f}")
    dist = payload.get("event_type_distribution", {})
    if dist:
        print()
        print("event_type_distribution:")
        for name, count in list(dist.items())[:10]:
            print(f"  {name:<24} {count}")


def _render_model(outcome: EvalOutcome, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(outcome.payload, ensure_ascii=False, indent=2))
        return
    print(outcome.summary)
    print()
    rows = outcome.payload.get("rows", [])
    if not rows:
        print("暂无 model 评估结果")
        return
    print(f"{'model':<18} {'target':<16} {'status':<10} {'rank_ic':>8} {'mae':>8} {'topk':>8}")
    print("-" * 78)
    for row in rows:
        print(
            f"{row['model_name']:<18} {row['target_name']:<16} {row['status']:<10} "
            f"{(f'{float(row['rank_ic']):.4f}' if row.get('rank_ic') is not None else '—'):>8} "
            f"{(f'{float(row['mae']):.4f}' if row.get('mae') is not None else '—'):>8} "
            f"{(f'{float(row['topk_hit_rate']):.2%}' if row.get('topk_hit_rate') is not None else '—'):>8}"
        )


def _render_gate(outcome: EvalOutcome, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(outcome.payload, ensure_ascii=False, indent=2))
        return
    payload = outcome.payload
    print(outcome.summary)
    metrics = payload.get("metrics", {})
    print(f"overall_status:    {metrics.get('overall_status', outcome.status)}")
    print(f"operational_status:{metrics.get('operational_status', '—')}")
    print(f"research_status:   {metrics.get('research_status', '—')}")
    latest_reasons = metrics.get("latest_reasons") or []
    matured_reasons = metrics.get("matured_reasons") or []
    reasons = payload.get("reasons", [])
    if reasons and not latest_reasons and not matured_reasons:
        print("reasons:")
        for reason in reasons:
            print(f"  - {reason}")
    if latest_reasons:
        print("latest_reasons:")
        for reason in latest_reasons:
            print(f"  - {reason}")
    if matured_reasons:
        print("matured_reasons:")
        for reason in matured_reasons:
            print(f"  - {reason}")
    if metrics:
        print()
        print("metrics:")
        for key in [
            "fund_flow_coverage",
            "fundamental_coverage",
            "source_healthy_ratio",
            "event_count",
            "labeled_propagation_ratio",
            "model_rank_ic_5d",
            "model_baseline_delta",
        ]:
            if key not in metrics or metrics[key] is None:
                continue
            value = metrics[key]
            if isinstance(value, float):
                if "coverage" in key or "ratio" in key:
                    print(f"  {key}: {value:.2%}")
                else:
                    print(f"  {key}: {value:.4f}")
            else:
                print(f"  {key}: {value}")


def make_parser() -> argparse.ArgumentParser:
    from trade_py.cli import epilog_from_subparsers

    parser = argparse.ArgumentParser(
        prog="trade evaluate",
        description="评估层与质量门禁",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser(
        "daily",
        description="跑 source/event/model/gate 全链路评估",
        epilog="trade evaluate daily\ntrade evaluate daily --date 2026-03-12",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_daily.add_argument("--data-root", default=_DATA_ROOT)
    p_daily.add_argument("--date", default=None)
    p_daily.add_argument("--lookback", type=int, default=30)
    p_daily.add_argument("--refresh", action="store_true", help="忽略缓存，强制重算")
    p_daily.add_argument("--json", action="store_true")

    p_source = sub.add_parser(
        "source",
        description="评估情绪源质量与产出",
        epilog="trade evaluate source\ntrade evaluate source --lookback 30",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_source.add_argument("--data-root", default=_DATA_ROOT)
    p_source.add_argument("--date", default=None)
    p_source.add_argument("--lookback", type=int, default=30)
    p_source.add_argument("--refresh", action="store_true", help="忽略缓存，强制重算")
    p_source.add_argument("--json", action="store_true")

    p_event = sub.add_parser(
        "event",
        description="评估 market_events / event_propagations 质量",
        epilog="trade evaluate event\ntrade evaluate event --lookback 30",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_event.add_argument("--data-root", default=_DATA_ROOT)
    p_event.add_argument("--date", default=None)
    p_event.add_argument("--lookback", type=int, default=30)
    p_event.add_argument("--refresh", action="store_true", help="忽略缓存，强制重算")
    p_event.add_argument("--json", action="store_true")

    p_model = sub.add_parser(
        "model",
        description="评估当前活跃模型与 baseline",
        epilog="trade evaluate model\ntrade evaluate model --date 2026-03-12",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_model.add_argument("--data-root", default=_DATA_ROOT)
    p_model.add_argument("--date", default=None)
    p_model.add_argument("--start", default=None)
    p_model.add_argument("--refresh", action="store_true", help="忽略缓存，强制重算")
    p_model.add_argument("--json", action="store_true")

    p_gate = sub.add_parser(
        "gate",
        description="计算或查看当日质量门禁",
        epilog="trade evaluate gate\ntrade evaluate gate --date 2026-03-12",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_gate.add_argument("--data-root", default=_DATA_ROOT)
    p_gate.add_argument("--date", default=None)
    p_gate.add_argument("--refresh", action="store_true", help="忽略缓存，强制重算")
    p_gate.add_argument("--json", action="store_true")

    parser.epilog = epilog_from_subparsers(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)

    if args.command == "daily":
        def _runner() -> EvalRunResult:
            outcome = evaluate_daily(
                args.data_root,
                eval_date=args.date,
                lookback_days=args.lookback,
                use_cache=not args.refresh,
            )
            if args.json:
                print(json.dumps(outcome.payload, ensure_ascii=False, indent=2))
            else:
                print(outcome.summary)
                print(json.dumps({"gate": outcome.payload["gate"]}, ensure_ascii=False, indent=2))
            return EvalRunResult(outcome.summary, outcome.status, outcome.exit_code)
        return _track_eval_run(args.data_root, "evaluate_daily", _runner)

    if args.command == "source":
        def _runner() -> EvalRunResult:
            outcome = evaluate_sources(
                args.data_root,
                eval_date=args.date,
                lookback_days=args.lookback,
                persist=True,
                use_cache=not args.refresh,
            )
            _render_source(outcome, as_json=args.json)
            return EvalRunResult(outcome.summary, outcome.status, outcome.exit_code)
        return _track_eval_run(args.data_root, "evaluate_source", _runner)

    if args.command == "event":
        def _runner() -> EvalRunResult:
            outcome = evaluate_events(
                args.data_root,
                eval_date=args.date,
                lookback_days=args.lookback,
                persist=True,
                use_cache=not args.refresh,
            )
            _render_event(outcome, as_json=args.json)
            return EvalRunResult(outcome.summary, outcome.status, outcome.exit_code)
        return _track_eval_run(args.data_root, "evaluate_event", _runner)

    if args.command == "model":
        def _runner() -> EvalRunResult:
            outcome = evaluate_models(
                args.data_root,
                eval_date=args.date,
                start_date=args.start,
                persist=True,
                use_cache=not args.refresh,
            )
            _render_model(outcome, as_json=args.json)
            return EvalRunResult(outcome.summary, outcome.status, outcome.exit_code)
        return _track_eval_run(args.data_root, "evaluate_model", _runner, stage="train")

    if args.command == "gate":
        def _runner() -> EvalRunResult:
            outcome = evaluate_gate(
                args.data_root,
                eval_date=args.date,
                persist=True,
                use_cache=not args.refresh,
            )
            _render_gate(outcome, as_json=args.json)
            return EvalRunResult(outcome.summary, outcome.status, outcome.exit_code)
        return _track_eval_run(args.data_root, "evaluate_gate", _runner)

    return 1
