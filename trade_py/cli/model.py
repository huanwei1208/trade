from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from trade_py.infra.settings import default_data_root
from trade_py.signals.window_scorer import score_watchlist

logger = logging.getLogger(__name__)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _events_from_sqlite(data_root: str) -> list:
    """Load HistoricalEvent list from SQLite events table."""
    from trade_py.db.settings_db import SettingsDB
    from trade_py.db.event_db import HistoricalEvent

    rows = SettingsDB(data_root).get_events(limit=10000)
    events = []
    for r in rows:
        d = {k: v for k, v in r.items() if k not in ("affected_stocks", "created_at")}
        d.setdefault("actor_type", "unknown")
        try:
            events.append(HistoricalEvent.from_dict(d))
        except Exception as exc:
            logger.debug("Skip event %s: %s", r.get("event_id"), exc)
    return events


def _cmd_build_features(args: argparse.Namespace) -> int:
    from trade_py.analysis.propagation_runtime import build_training_feature_frame, save_feature_maps

    data_root = Path(args.data_root)
    df, maps, _trust = build_training_feature_frame(args.data_root)
    if df.empty:
        logger.error("No features built — check event_propagations / signals / gold coverage")
        return 1
    out = data_root / "events" / "features.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    save_feature_maps(args.data_root, maps)
    logger.info("Saved %d feature rows to %s", len(df), out)
    return 0


def _cmd_build_labels(args: argparse.Namespace) -> int:
    from trade_py.event import backfill_events

    result = backfill_events(args.data_root)
    logger.info("Label backfill result: %s", result)
    return 0


def _cmd_train(args: argparse.Namespace) -> int:
    from trade_py.analysis.propagation_training import train_models

    try:
        rows = train_models(
            args.data_root,
            backend=args.backend,
            cv_splits=args.cv,
            activate_backend=(args.activate_backend or "").replace("-", "_") or None,
        )
    except Exception as exc:
        logger.error("Model training failed: %s", exc)
        return 1

    if not rows:
        logger.warning("No models were trained")
        return 0

    for row in rows:
        metrics = row.get("metrics", {})
        promo = metrics.get("promotion_check", {}) if isinstance(metrics, dict) else {}
        logger.info(
            "trained id=%s target=%s backend=%s state=%s metric=%s eligible=%s",
            row.get("id"),
            row.get("target_name"),
            row.get("backend"),
            row.get("promotion_state"),
            metrics.get("cv_metric"),
            promo.get("eligible"),
        )
    return 0


def _cmd_model_list(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(args.data_root)
    rows = db.model_registry_list()
    if args.target:
        rows = [row for row in rows if str(row.get("target_name") or row.get("model_name")) == args.target]
    if args.backend:
        rows = [row for row in rows if str(row.get("backend") or "") == args.backend]
    if not rows:
        print("No models found")
        return 0

    print(f"{'id':<6} {'target':<18} {'backend':<12} {'state':<10} {'eligible':<8} {'trained_at':<20} file")
    print("-" * 108)
    for row in rows:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        promo = metrics.get("promotion_check", {}) if isinstance(metrics, dict) else {}
        print(
            f"{str(row.get('id')):<6} "
            f"{str(row.get('target_name') or row.get('model_name')):<18} "
            f"{str(row.get('backend') or ''):<12} "
            f"{str(row.get('promotion_state') or ('active' if row.get('is_active') else 'candidate')):<10} "
            f"{str(bool(promo.get('eligible')) if promo else '—'):<8} "
            f"{str(row.get('trained_at') or ''):<20} "
            f"{str(row.get('file_path') or '')}"
        )
    return 0


def _cmd_model_compare(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(args.data_root)
    rows = db.model_registry_list()
    if args.target:
        rows = [row for row in rows if str(row.get("target_name") or row.get("model_name")) == args.target]
    if args.backend:
        rows = [row for row in rows if str(row.get("backend") or "") == args.backend]
    if not rows:
        print("No models found")
        return 0

    eval_rows = db.model_eval_list(args.eval_date)
    eval_by_name = {
        str(row.get("model_name") or ""): row
        for row in eval_rows
    }

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        target_name = str(row.get("target_name") or row.get("model_name") or "unknown")
        grouped.setdefault(target_name, []).append(row)

    for target_name in sorted(grouped):
        print(f"[{target_name}]")
        target_rows = grouped[target_name]
        target_rows.sort(
            key=lambda row: (
                0 if str(row.get("promotion_state") or "") == "active" else 1,
                -float((row.get("metrics") or {}).get("cv_metric") or -9999),
                str(row.get("backend") or ""),
                -int(row.get("id") or 0),
            )
        )
        print(f"{'id':<6} {'backend':<12} {'state':<10} {'cv_metric':>10} {'cv_mae':>10} {'eligible':<8} trained_at")
        print("-" * 86)
        for row in target_rows:
            metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
            promo = metrics.get("promotion_check", {}) if isinstance(metrics, dict) else {}
            cv_metric = metrics.get("cv_metric")
            cv_mae = metrics.get("cv_mae")
            print(
                f"{str(row.get('id')):<6} {str(row.get('backend') or ''):<12} "
                f"{str(row.get('promotion_state') or ''):<10} "
                f"{('—' if cv_metric is None else f'{float(cv_metric):.4f}'):>10} "
                f"{('—' if cv_mae is None else f'{float(cv_mae):.4f}'):>10} "
                f"{str(bool(promo.get('eligible')) if promo else '—'):<8} "
                f"{str(row.get('trained_at') or '')}"
            )
        eval_row = eval_by_name.get(target_name)
        if eval_row:
            baseline = eval_row.get("baseline_json") if isinstance(eval_row.get("baseline_json"), dict) else {}
            baseline_delta = baseline.get("baseline_delta") if isinstance(baseline, dict) else None
            rank_ic = eval_row.get("rank_ic")
            mae = eval_row.get("mae")
            topk = eval_row.get("topk_hit_rate")
            brier = eval_row.get("risk_brier_score")
            print(
                "active_eval:"
                f" status={eval_row.get('status')}"
                f" rank_ic={('—' if rank_ic is None else f'{float(rank_ic):.4f}')}"
                f" mae={('—' if mae is None else f'{float(mae):.4f}')}"
                f" topk={('—' if topk is None else f'{float(topk):.2%}')}"
                f" brier={('—' if brier is None else f'{float(brier):.4f}')}"
                f" baseline_delta={('—' if baseline_delta is None else f'{float(baseline_delta):.4f}')}"
            )
        print()
    return 0


def _cmd_model_promote(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(args.data_root)
    candidate = db.model_registry_get(args.model_id)
    if candidate is None:
        logger.error("Model id %s not found", args.model_id)
        return 1
    metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
    promo = metrics.get("promotion_check", {}) if isinstance(metrics, dict) else {}
    if not args.force and not bool(promo.get("eligible")):
        logger.error(
            "Model id=%s is not promotion-eligible. pass_current=%s consecutive_passes=%s eligible=%s",
            args.model_id,
            promo.get("pass_current"),
            promo.get("consecutive_passes"),
            promo.get("eligible"),
        )
        return 1
    row = db.model_registry_promote(args.model_id)
    if row is None:
        logger.error("Model id %s not found", args.model_id)
        return 1
    logger.info(
        "Promoted model id=%s target=%s backend=%s",
        row.get("id"),
        row.get("target_name") or row.get("model_name"),
        row.get("backend"),
    )
    return 0


def _cmd_sync_factors(args: argparse.Namespace) -> int:
    from trade_py.analysis.propagation_runtime import materialize_inference_factors

    target_date, symbols, feature_cols, _freshness = materialize_inference_factors(args.data_root, args.date)
    if not target_date:
        logger.error("No signals found; cannot materialize factors")
        return 1
    logger.info(
        "Materialized %d symbols into factors for %s (%d features)",
        symbols,
        target_date,
        len(feature_cols),
    )
    return 0


def _cmd_sync_signals(args: argparse.Namespace) -> int:
    from trade_py.analysis.propagation_runtime import sync_signal_predictions

    target_date, updated = sync_signal_predictions(args.data_root, args.date)
    if not target_date:
        logger.error("No signals found; cannot sync model scores")
        return 1
    logger.info("Updated model scores for %d symbols on %s", updated, target_date)
    return 0


def _make_event(args):
    from trade_py.db.event_db import HistoricalEvent, EventType, ActorType
    return HistoricalEvent(
        event_date=date.today(),
        event_type=EventType(args.event_type),
        magnitude=args.magnitude,
        actor_type=ActorType(args.actor_type),
        primary_sector=args.sector or "SW_Unknown",
        breadth="sector", sentiment_score=0.5, news_volume=5,
        summary=f"Event type: {args.event_type}",
    )


def _cmd_predict(args: argparse.Namespace) -> int:
    from trade_py.analysis.feature_builder import FeatureBuilder
    from trade_py.analysis.model_trainer import PropagationModel

    feat_row = FeatureBuilder(Path(args.data_root)).build(
        _make_event(args), args.symbol, args.sector or "SW_Unknown"
    )
    if feat_row is None:
        logger.error("Cannot build features for %s", args.symbol)
        return 1
    model = PropagationModel(Path(args.data_root))
    model.load()
    preds = model.predict(feat_row.features)
    print(f"\n=== Predictions for {args.symbol} ===")
    for t, v in preds.items():
        print(f"  {t:<25s}: {v:+.4f}")
    return 0


def _cmd_sentiment_ic(args: argparse.Namespace) -> int:
    import json
    from trade_py.analysis.sentiment_ic import compute_ic, format_ic_report

    result = compute_ic(
        data_root=args.data_root,
        lookback=args.lookback,
        forward_days=args.forward_days,
        by_source=args.by_source,
    )
    print(format_ic_report(result))
    if args.json:
        print("\nRaw JSON:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if "error" not in result or result.get("valid_days", 0) >= 1 else 1


def _cmd_nlp_train(args: argparse.Namespace) -> int:
    from trade_py.intelligence.nlp_train import finetune_sentiment
    try:
        finetune_sentiment(
            base_model=args.base_model,
            train_data=args.train_data,
            output_onnx=args.output,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lookback_days=args.lookback,
        )
        return 0
    except ImportError as e:
        logger.error("NLP dependencies missing (install trade-py[nlp]): %s", e)
        return 1
    except Exception as e:
        logger.error("NLP training failed: %s", e)
        return 1


def make_parser() -> argparse.ArgumentParser:
    from trade_py.cli import epilog_from_subparsers, global_flag_parent

    parser = argparse.ArgumentParser(
        prog="trade model",
        description="模型与信号分析 — 窗口得分/情绪IC/预测/训练",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flag_parent()],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser(
        "score",
        description="计算自选股窗口得分",
        epilog="trade model score\ntrade model score --date 2026-03-05",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_score.add_argument("--data-root", default=str(default_data_root()))
    p_score.add_argument("--date", default=None)

    p_ic = sub.add_parser(
        "sentiment-ic",
        description="情绪 IC 检验（信号质量评估）",
        epilog=(
            "trade model sentiment-ic --lookback 60\n"
            "trade model sentiment-ic --by-source\n"
            "trade model sentiment-ic --lookback 90 --forward-days 10 --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ic.add_argument("--data-root", default=str(default_data_root()))
    p_ic.add_argument("--lookback", type=int, default=60, help="Lookback window in calendar days")
    p_ic.add_argument("--forward-days", type=int, default=5, help="Forward return horizon in trading days")
    p_ic.add_argument("--by-source", action="store_true", help="Break down IC by data source")
    p_ic.add_argument("--json", action="store_true", help="Also print raw JSON output")

    p_bf = sub.add_parser(
        "build-features",
        description="从 K线+事件构建 feature Parquet（从 SQLite 读取事件）",
        epilog="trade model build-features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_bf.add_argument("--data-root", default=str(default_data_root()))

    p_bl = sub.add_parser(
        "build-labels",
        description="从前向收益构建 label Parquet（从 SQLite 读取事件）",
        epilog="trade model build-labels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_bl.add_argument("--data-root", default=str(default_data_root()))

    p_tr = sub.add_parser(
        "train",
        description="训练传播模型（LightGBM / XGBoost / CatBoost / tabular NN）",
        epilog="trade model train\ntrade model train --backend all\ntrade model train --backend xgboost\ntrade model train --backend catboost",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_tr.add_argument("--data-root", default=str(default_data_root()))
    p_tr.add_argument("--cv", type=int, default=5)
    p_tr.add_argument("--backend", default="all", choices=["all", "lgbm", "xgboost", "catboost", "tabular-nn"])
    p_tr.add_argument("--activate-backend", default=None, choices=["lgbm", "xgboost", "catboost", "tabular_nn", "tabular-nn"])

    p_ml = sub.add_parser(
        "list",
        description="列出已注册模型及状态",
        epilog="trade model list\ntrade model list --target kg_return_5d",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ml.add_argument("--data-root", default=str(default_data_root()))
    p_ml.add_argument("--target", default=None)
    p_ml.add_argument("--backend", default=None)

    p_cmp = sub.add_parser(
        "compare",
        description="对比 active / candidate 模型及最新评估",
        epilog="trade model compare\ntrade model compare --target kg_return_5d",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_cmp.add_argument("--data-root", default=str(default_data_root()))
    p_cmp.add_argument("--target", default=None)
    p_cmp.add_argument("--backend", default=None)
    p_cmp.add_argument("--eval-date", default=None)

    p_mp = sub.add_parser(
        "promote",
        description="将候选模型提升为 active",
        epilog="trade model promote --model-id 12",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_mp.add_argument("--data-root", default=str(default_data_root()))
    p_mp.add_argument("--model-id", type=int, required=True)
    p_mp.add_argument("--force", action="store_true", help="忽略晋级门槛，强制切换 active")

    p_sf = sub.add_parser(
        "sync-factors",
        description="把推理所需的传播特征落到 factors 表",
        epilog="trade model sync-factors\ntrade model sync-factors --date 2026-03-12",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_sf.add_argument("--data-root", default=str(default_data_root()))
    p_sf.add_argument("--date", default=None)

    p_ss = sub.add_parser(
        "sync-signals",
        description="用当前活跃模型批量回写 signals.model_*",
        epilog="trade model sync-signals\ntrade model sync-signals --date 2026-03-12",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ss.add_argument("--data-root", default=str(default_data_root()))
    p_ss.add_argument("--date", default=None)

    p_nlp = sub.add_parser(
        "nlp-train",
        description="微调情绪 NLP 模型并导出 ONNX (FinBERT)",
        epilog=(
            "trade model nlp-train\n"
            "trade model nlp-train --epochs 5 --batch-size 32"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_nlp.add_argument("--base-model", default="yiyanghkust/finbert-tone-chinese")
    p_nlp.add_argument("--train-data", default=str(default_data_root() / "sentiment" / "bronze"))
    p_nlp.add_argument("--output", default=str(default_data_root() / "models" / "sentiment" / "finbert_zh.onnx"))
    p_nlp.add_argument("--epochs", type=int, default=3)
    p_nlp.add_argument("--batch-size", type=int, default=16)
    p_nlp.add_argument("--lookback", type=int, default=30)

    for name, desc, example in [
        ("predict", "预测股票对事件的反应",
         "trade model predict --symbol 600000.SH --event-type policy_easing --magnitude 0.8"),
    ]:
        p = sub.add_parser(name, description=desc, epilog=example,
                           formatter_class=argparse.RawDescriptionHelpFormatter)
        p.add_argument("--data-root",  default=str(default_data_root()))
        p.add_argument("--event-type", required=True)
        p.add_argument("--symbol",     required=True)
        p.add_argument("--sector",     default="")
        p.add_argument("--magnitude",  type=float, default=0.7)
        p.add_argument("--actor-type", default="unknown")

    parser.epilog = epilog_from_subparsers(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    args = make_parser().parse_args(argv)

    if args.command == "score":
        scores = score_watchlist(args.data_root, args.date)
        if not scores:
            print("No scores computed (watchlist empty or no data)")
            return 0
        print(f"\nWindow Scores - {args.date or 'today'}")
        print("-" * 30)
        for sym, sc in sorted(scores.items(), key=lambda x: -x[1]):
            print(f"  {sym:<15} {sc:3d}")
        return 0

    if args.command == "sentiment-ic":
        return _cmd_sentiment_ic(args)

    if args.command == "nlp-train":
        return _cmd_nlp_train(args)

    return {
        "build-features": _cmd_build_features,
        "build-labels":   _cmd_build_labels,
        "train":          _cmd_train,
        "list":           _cmd_model_list,
        "compare":        _cmd_model_compare,
        "promote":        _cmd_model_promote,
        "sync-factors":   _cmd_sync_factors,
        "sync-signals":   _cmd_sync_signals,
        "predict":        _cmd_predict,
    }.get(args.command, lambda _: 1)(args)
