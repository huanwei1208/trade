from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from trade_py.config import default_data_root
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
    from trade_py.analysis.feature_builder import FeatureBuilder

    data_root = Path(args.data_root)
    events = _events_from_sqlite(str(data_root))
    if not events:
        logger.error("No events in SQLite — run `trade run event sync` first")
        return 1

    import sqlite3 as _sqlite3
    _SECTORS = [
        "SW_Agriculture", "SW_Mining", "SW_Chemical", "SW_Steel",
        "SW_NonFerrousMetal", "SW_Electronics", "SW_Auto",
        "SW_HouseholdAppliance", "SW_FoodBeverage", "SW_Textile",
        "SW_LightManufacturing", "SW_Medicine", "SW_Utilities",
        "SW_Transportation", "SW_RealEstate", "SW_Commerce",
        "SW_SocialService", "SW_Banking", "SW_NonBankFinancial",
        "SW_Construction", "SW_BuildingMaterial", "SW_MechanicalEquipment",
        "SW_Defense", "SW_Computer", "SW_Media", "SW_Telecom",
        "SW_Environment", "SW_ElectricalEquipment", "SW_Beauty",
        "SW_Coal", "SW_Petroleum",
    ]
    symbol_sector: dict[str, str] = {}
    from trade_py.db.trade_db import _find_db_path
    db_path = _find_db_path(data_root)
    if db_path.exists():
        try:
            conn = _sqlite3.connect(str(db_path))
            rows = conn.execute("SELECT symbol, industry FROM instruments").fetchall()
            conn.close()
            for sym, ind in rows:
                idx = int(ind) if ind is not None else 0
                symbol_sector[str(sym)] = _SECTORS[idx] if 0 <= idx < len(_SECTORS) else "SW_Unknown"
        except Exception as exc:
            logger.warning("Could not load industry from instruments DB: %s", exc)
    if not symbol_sector:
        logger.warning("No symbol→sector mapping found; all sectors will be SW_Unknown")

    builder = FeatureBuilder(data_root)
    df = builder.build_batch(events, symbol_sector)
    if df.empty:
        logger.error("No features built — check kline data coverage")
        return 1
    out = data_root / "events" / "features.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    logger.info("Saved %d feature rows to %s", len(df), out)
    return 0


def _cmd_build_labels(args: argparse.Namespace) -> int:
    from trade_py.analysis.label_builder import LabelBuilder
    import duckdb

    data_root = Path(args.data_root)
    events = _events_from_sqlite(str(data_root))
    if not events:
        logger.error("No events in SQLite — run `trade run event sync` first")
        return 1
    kline_glob = str(data_root / "kline" / "**" / "*.parquet")
    try:
        con = duckdb.connect()
        symbols = con.execute(
            f"SELECT DISTINCT symbol FROM read_parquet('{kline_glob}', union_by_name=true)"
        ).df()["symbol"].tolist()
        con.close()
    except Exception as exc:
        logger.error("Cannot load symbol universe: %s", exc)
        return 1
    builder = LabelBuilder(data_root)
    df = builder.build_batch(events, symbols)
    if df.empty:
        logger.error("No labels built")
        return 1
    logger.info("Saved %d label rows to %s", len(df), builder.save(df))
    return 0


def _cmd_train(args: argparse.Namespace) -> int:
    from trade_py.analysis.model_trainer import PropagationModel
    model = PropagationModel(Path(args.data_root))
    model.load_data()
    for target, score in model.train(n_cv_splits=args.cv).items():
        logger.info("  %-25s %.4f", target, score)
    logger.info("Models saved to %s", model.save())
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


def _cmd_model_report(args: argparse.Namespace) -> int:
    from trade_py.analysis.feature_builder import FeatureBuilder
    from trade_py.analysis.model_trainer import PropagationModel
    from trade_py.report.report_generator import ReportGenerator

    sector = args.sector or "SW_Unknown"
    event = _make_event(args)
    feat_row = FeatureBuilder(Path(args.data_root)).build(event, args.symbol, sector)
    if feat_row is None:
        logger.error("Cannot build features for %s", args.symbol)
        return 1
    model = PropagationModel(Path(args.data_root))
    model.load()
    gen = ReportGenerator(model)
    print(gen.format_markdown(gen.generate(event, args.symbol, feat_row.features, sector=sector)))
    return 0


def make_parser() -> argparse.ArgumentParser:
    from trade_py.cli import epilog_from_subparsers

    parser = argparse.ArgumentParser(
        prog="trade model",
        description="模型与信号分析 — 窗口得分/情绪IC/预测/训练",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        description="训练 LightGBM 传导模型",
        epilog="trade model train\ntrade model train --cv 10",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_tr.add_argument("--data-root", default=str(default_data_root()))
    p_tr.add_argument("--cv", type=int, default=5)

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
        ("report",  "生成决策报告 (Markdown)",
         "trade model report --symbol 600000.SH --event-type policy_easing --magnitude 0.8"),
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
        "predict":        _cmd_predict,
        "report":         _cmd_model_report,
    }.get(args.command, lambda _: 1)(args)
