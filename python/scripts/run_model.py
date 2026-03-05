#!/usr/bin/env python3
"""CLI script for the event propagation prediction model.

Commands:
  build-features   Build feature Parquet from events + kline data
  build-labels     Build label Parquet from kline forward returns
  train            Train LightGBM models and save to disk
  predict          Predict for a single (event_type, symbol) pair
  report           Generate and print a full decision report

Example usage:
  python run_model.py build-features --data data --events data/events/historical_events.parquet
  python run_model.py build-labels   --data data
  python run_model.py train          --data data --cv 5
  python run_model.py predict        --data data --event-type semiconductor_policy --symbol 600703.SH
  python run_model.py report         --data data --event-type geopolitical_risk    --symbol 600388.SH
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from datetime import date

# Ensure the python/ package is importable when running from project root
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
from config_context import default_data_root

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_model")


# ── build-features ─────────────────────────────────────────────────────────────

def cmd_build_features(args: argparse.Namespace) -> int:
    from trade_py.db.event_db import EventDatabase
    from trade_py.analysis.feature_builder import FeatureBuilder
    import duckdb, pandas as pd

    data_root = Path(args.data)
    db = EventDatabase(data_root)
    events = db.events
    if not events:
        logger.error("No events found in %s", data_root / "events")
        return 1

    logger.info("Building features for %d events", len(events))

    # Get universe: all symbols from kline data
    kline_glob = str(data_root / "kline" / "**" / "*.parquet")
    try:
        con = duckdb.connect()
        sym_df = con.execute(f"""
            SELECT DISTINCT symbol, industry
            FROM read_parquet('{kline_glob}', union_by_name=true)
            LIMIT 5000
        """).df()
        con.close()
    except Exception as exc:
        logger.error("Cannot load kline universe: %s", exc)
        return 1

    # Build symbol → sector map (requires industry column)
    symbol_sector: dict[str, str] = {}
    for _, row in sym_df.iterrows():
        sym = str(row["symbol"])
        ind = int(row.get("industry", 0)) if "industry" in row.index else 0
        sector_names = [
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
        symbol_sector[sym] = sector_names[ind] if 0 <= ind < len(sector_names) else "SW_Unknown"

    builder = FeatureBuilder(data_root)
    df = builder.build_batch(events, symbol_sector)

    if df.empty:
        logger.error("No features built – check kline data coverage")
        return 1

    out_path = data_root / "events" / "features.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    logger.info("Saved %d feature rows to %s", len(df), out_path)
    return 0


# ── build-labels ───────────────────────────────────────────────────────────────

def cmd_build_labels(args: argparse.Namespace) -> int:
    from trade_py.db.event_db import EventDatabase
    from trade_py.analysis.label_builder import LabelBuilder
    import duckdb

    data_root = Path(args.data)
    db = EventDatabase(data_root)
    events = db.events
    if not events:
        logger.error("No events found")
        return 1

    kline_glob = str(data_root / "kline" / "**" / "*.parquet")
    try:
        con = duckdb.connect()
        sym_df = con.execute(f"""
            SELECT DISTINCT symbol
            FROM read_parquet('{kline_glob}', union_by_name=true)
        """).df()
        con.close()
        symbols = sym_df["symbol"].tolist()
    except Exception as exc:
        logger.error("Cannot load symbol universe: %s", exc)
        return 1

    logger.info("Building labels for %d events × %d symbols", len(events), len(symbols))
    builder = LabelBuilder(data_root)
    df = builder.build_batch(events, symbols)

    if df.empty:
        logger.error("No labels built")
        return 1

    path = builder.save(df)
    logger.info("Saved %d label rows to %s", len(df), path)
    return 0


# ── train ──────────────────────────────────────────────────────────────────────

def cmd_train(args: argparse.Namespace) -> int:
    from trade_py.analysis.model_trainer import PropagationModel

    data_root = Path(args.data)
    model = PropagationModel(data_root)
    model.load_data()
    cv_scores = model.train(n_cv_splits=args.cv)

    logger.info("Training complete. CV scores:")
    for target, score in cv_scores.items():
        logger.info("  %-25s %.4f", target, score)

    model_dir = model.save()
    logger.info("Models saved to %s", model_dir)
    return 0


# ── predict ────────────────────────────────────────────────────────────────────

def cmd_predict(args: argparse.Namespace) -> int:
    from trade_py.db.event_db import HistoricalEvent, EventType, ActorType
    from trade_py.analysis.feature_builder import FeatureBuilder
    from trade_py.analysis.model_trainer import PropagationModel

    data_root = Path(args.data)

    # Create a synthetic event for prediction
    event = HistoricalEvent(
        event_date=date.today(),
        event_type=EventType(args.event_type),
        magnitude=args.magnitude,
        actor_type=ActorType(args.actor_type),
        primary_sector=args.sector or "SW_Unknown",
        breadth="sector",
        sentiment_score=0.5,
        news_volume=5,
        summary=f"Event type: {args.event_type}",
    )

    builder = FeatureBuilder(data_root)
    feat_row = builder.build(event, args.symbol, args.sector or "SW_Unknown")
    if feat_row is None:
        logger.error("Cannot build features for %s (insufficient kline data?)", args.symbol)
        return 1

    model = PropagationModel(data_root)
    model.load()
    preds = model.predict(feat_row.features)

    print(f"\n=== Predictions for {args.symbol} ===")
    for target, val in preds.items():
        print(f"  {target:<25s}: {val:+.4f}")
    return 0


# ── report ─────────────────────────────────────────────────────────────────────

def cmd_report(args: argparse.Namespace) -> int:
    from trade_py.db.event_db import HistoricalEvent, EventType, ActorType
    from trade_py.analysis.feature_builder import FeatureBuilder
    from trade_py.analysis.model_trainer import PropagationModel
    from trade_py.journal.report_generator import ReportGenerator

    data_root = Path(args.data)
    sector = args.sector or "SW_Unknown"

    event = HistoricalEvent(
        event_date=date.today(),
        event_type=EventType(args.event_type),
        magnitude=args.magnitude,
        actor_type=ActorType(args.actor_type),
        primary_sector=sector,
        breadth="sector",
        sentiment_score=0.5,
        news_volume=5,
        summary=f"Event type: {args.event_type}",
    )

    builder = FeatureBuilder(data_root)
    feat_row = builder.build(event, args.symbol, sector)
    if feat_row is None:
        logger.error("Cannot build features for %s", args.symbol)
        return 1

    model = PropagationModel(data_root)
    model.load()
    gen = ReportGenerator(model)
    report = gen.generate(event, args.symbol, feat_row.features, sector=sector)
    print(gen.format_markdown(report))
    return 0


# ── Argument parsing ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Event propagation prediction model CLI")
    parser.add_argument("--data", default=str(default_data_root()),
                        help="Root data directory (default: data)")

    sub = parser.add_subparsers(dest="command", required=True)

    # build-features
    p_bf = sub.add_parser("build-features", help="Build feature Parquet")
    p_bf.set_defaults(func=cmd_build_features)

    # build-labels
    p_bl = sub.add_parser("build-labels", help="Build label Parquet")
    p_bl.set_defaults(func=cmd_build_labels)

    # train
    p_tr = sub.add_parser("train", help="Train models")
    p_tr.add_argument("--cv", type=int, default=5,
                       help="Number of CV folds (default: 5)")
    p_tr.set_defaults(func=cmd_train)

    # predict
    p_pr = sub.add_parser("predict", help="Predict for a single pair")
    p_pr.add_argument("--event-type", required=True,
                       help="Event type (e.g. semiconductor_policy)")
    p_pr.add_argument("--symbol", required=True,
                       help="Stock code (e.g. 600703.SH)")
    p_pr.add_argument("--sector", default="",
                       help="SW sector (e.g. SW_Electronics)")
    p_pr.add_argument("--magnitude", type=float, default=0.7)
    p_pr.add_argument("--actor-type", default="unknown")
    p_pr.set_defaults(func=cmd_predict)

    # report
    p_rp = sub.add_parser("report", help="Generate decision report")
    p_rp.add_argument("--event-type", required=True)
    p_rp.add_argument("--symbol", required=True)
    p_rp.add_argument("--sector", default="")
    p_rp.add_argument("--magnitude", type=float, default=0.7)
    p_rp.add_argument("--actor-type", default="unknown")
    p_rp.set_defaults(func=cmd_report)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
