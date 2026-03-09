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

    data_root = Path(args.data_root)
    db = EventDatabase(data_root)
    events = db.events
    if not events:
        logger.error("No events found in %s", data_root / "events")
        return 1

    # Load symbol→sector mapping from instruments DB (kline parquet has no industry col)
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
    db_path = data_root / ".metadata" / "trade.db"
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


def _cmd_extract_events(args: argparse.Namespace) -> int:
    """Derive HistoricalEvent records from Silver parquet files."""
    import glob as _glob
    from datetime import date as _date
    from trade_py.db.event_db import (
        EventDatabase, HistoricalEvent, EventType, ActorType,
    )

    data_root = Path(args.data_root)
    silver_root = data_root / "sentiment" / "silver"
    if not silver_root.exists():
        logger.error("No Silver data found at %s — run `trade data sentiment` first", silver_root)
        return 1

    # Collect all silver files in range
    all_files = sorted(_glob.glob(str(silver_root / "**" / "*.parquet"), recursive=True))
    if not all_files:
        logger.error("No Silver parquet files found under %s", silver_root)
        return 1

    import pandas as pd
    frames = []
    for fp in all_files:
        try:
            df = pd.read_parquet(fp, columns=[
                "date", "symbol", "event_type", "event_magnitude",
                "affected_sectors", "sentiment_score", "content_hash", "summary",
            ])
            # filter by date range if specified
            if args.start:
                df = df[df["date"] >= args.start]
            if args.end:
                df = df[df["date"] <= args.end]
            if not df.empty:
                frames.append(df)
        except Exception as exc:
            logger.debug("Skipping %s: %s", fp, exc)

    if not frames:
        logger.error("No Silver rows in the requested date range")
        return 1

    silver = pd.concat(frames, ignore_index=True)
    silver["event_magnitude"] = pd.to_numeric(silver["event_magnitude"], errors="coerce").fillna(0.0)
    silver["sentiment_score"] = pd.to_numeric(silver["sentiment_score"], errors="coerce").fillna(0.0)

    # Map EventType values; keep only valid ones
    valid_event_types = {e.value for e in EventType}

    events: list[HistoricalEvent] = []
    skipped = 0
    for (dt_str, ev_type), grp in silver.groupby(["date", "event_type"]):
        if ev_type not in valid_event_types:
            skipped += 1
            continue
        magnitude = float(grp["event_magnitude"].max())
        if ev_type == "other" and magnitude < args.min_magnitude:
            skipped += 1
            continue

        # Primary sector: most common non-empty sector from affected_sectors column
        all_sectors: list[str] = []
        for cell in grp["affected_sectors"].dropna():
            for s in str(cell).split(","):
                s = s.strip()
                if s:
                    all_sectors.append(s if s.startswith("SW_") else f"SW_{s}")
        if all_sectors:
            primary_sector = max(set(all_sectors), key=all_sectors.count)
        else:
            primary_sector = "SW_Unknown"

        breadth = "market" if (grp["symbol"] == "_MARKET_").all() else "sector"
        sentiment_score = float(grp["sentiment_score"].mean())
        news_volume = int(grp["content_hash"].nunique())
        summary = next(
            (str(s) for s in grp["summary"].dropna() if str(s).strip()), ""
        )

        try:
            event = HistoricalEvent(
                event_date=_date.fromisoformat(str(dt_str)),
                event_type=EventType(ev_type),
                magnitude=magnitude,
                actor_type=ActorType.unknown,
                primary_sector=primary_sector,
                breadth=breadth,
                sentiment_score=sentiment_score,
                news_volume=news_volume,
                summary=summary,
            )
            events.append(event)
        except (ValueError, KeyError) as exc:
            logger.debug("Skip event %s/%s: %s", dt_str, ev_type, exc)
            skipped += 1

    if not events:
        logger.error("No valid events extracted (skipped=%d)", skipped)
        return 1

    db = EventDatabase(data_root)
    db.load()
    existing = len(db)
    db.add_many(events)
    db.save()
    logger.info(
        "extract-events: extracted=%d  skipped=%d  existing_before=%d  total=%d  file=%s",
        len(events), skipped, existing, len(db),
        data_root / "events" / "historical_events.parquet",
    )
    print(f"Extracted {len(events)} events (skipped {skipped} low-signal rows)")
    print(f"EventDatabase now has {len(db)} total events")
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

    p_ee = sub.add_parser(
        "extract-events",
        description="从 Silver 层派生 HistoricalEvent 并写入 events/historical_events.parquet",
        epilog=(
            "trade model extract-events\n"
            "trade model extract-events --start 2025-01-01 --end 2026-03-05\n"
            "trade model extract-events --min-magnitude 0.3"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ee.add_argument("--data-root", default=str(default_data_root()))
    p_ee.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD（默认全量）")
    p_ee.add_argument("--end",   default=None, help="结束日期 YYYY-MM-DD（默认全量）")
    p_ee.add_argument("--min-magnitude", type=float, default=0.4,
                      help="event_type=other 的最低 magnitude 阈值（默认 0.4）")

    p_bf = sub.add_parser(
        "build-features",
        description="从 K线+事件构建 feature Parquet",
        epilog="trade model build-features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_bf.add_argument("--data-root", default=str(default_data_root()))

    p_bl = sub.add_parser(
        "build-labels",
        description="从前向收益构建 label Parquet",
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
    p_nlp.add_argument("--train-data", default=str(default_data_root() / "raw" / "sentiment"))
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
        "extract-events": _cmd_extract_events,
        "build-features": _cmd_build_features,
        "build-labels":   _cmd_build_labels,
        "train":          _cmd_train,
        "predict":        _cmd_predict,
        "report":         _cmd_model_report,
    }.get(args.command, lambda _: 1)(args)
