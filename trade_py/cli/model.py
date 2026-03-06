from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from trade_py.config import default_data_root
from trade_py.signals.window_scorer import score_watchlist

logger = logging.getLogger(__name__)


def _cmd_build_features(args: argparse.Namespace) -> int:
    from trade_py.db.event_db import EventDatabase
    from trade_py.analysis.feature_builder import FeatureBuilder
    import duckdb

    data_root = Path(args.data_root)
    db = EventDatabase(data_root)
    events = db.events
    if not events:
        logger.error("No events found in %s", data_root / "events")
        return 1

    kline_glob = str(data_root / "kline" / "**" / "*.parquet")
    try:
        con = duckdb.connect()
        sym_df = con.execute(
            f"SELECT DISTINCT symbol, industry "
            f"FROM read_parquet('{kline_glob}', union_by_name=true) LIMIT 5000"
        ).df()
        con.close()
    except Exception as exc:
        logger.error("Cannot load kline universe: %s", exc)
        return 1

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
    for _, row in sym_df.iterrows():
        ind = int(row.get("industry", 0)) if "industry" in row.index else 0
        symbol_sector[str(row["symbol"])] = _SECTORS[ind] if 0 <= ind < len(_SECTORS) else "SW_Unknown"

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
    from trade_py.db.event_db import EventDatabase
    from trade_py.analysis.label_builder import LabelBuilder
    import duckdb

    data_root = Path(args.data_root)
    db = EventDatabase(data_root)
    events = db.events
    if not events:
        logger.error("No events found")
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


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    parser = argparse.ArgumentParser(prog="trade model")
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="Compute watchlist window scores")
    p_score.add_argument("--data-root", default=str(default_data_root()))
    p_score.add_argument("--date", default=None)

    p_bf = sub.add_parser("build-features", help="Build feature Parquet from kline + events")
    p_bf.add_argument("--data-root", default=str(default_data_root()))

    p_bl = sub.add_parser("build-labels", help="Build label Parquet from forward returns")
    p_bl.add_argument("--data-root", default=str(default_data_root()))

    p_tr = sub.add_parser("train", help="Train LightGBM propagation models")
    p_tr.add_argument("--data-root", default=str(default_data_root()))
    p_tr.add_argument("--cv", type=int, default=5)

    for name, hlp in [("predict", "Predict for a symbol+event pair"),
                      ("report",  "Generate decision report")]:
        p = sub.add_parser(name, help=hlp)
        p.add_argument("--data-root",  default=str(default_data_root()))
        p.add_argument("--event-type", required=True)
        p.add_argument("--symbol",     required=True)
        p.add_argument("--sector",     default="")
        p.add_argument("--magnitude",  type=float, default=0.7)
        p.add_argument("--actor-type", default="unknown")

    args = parser.parse_args(argv)

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

    return {
        "build-features": _cmd_build_features,
        "build-labels":   _cmd_build_labels,
        "train":          _cmd_train,
        "predict":        _cmd_predict,
        "report":         _cmd_model_report,
    }.get(args.command, lambda _: 1)(args)
