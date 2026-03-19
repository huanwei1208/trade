"""Feature materialization — thin orchestrator over factor group builders.

Public API (unchanged):
  build_training_feature_frame(data_root)
      → (DataFrame, maps, trust_weights)
  materialize_inference_factors(data_root, date_str)
      → (target_date, n_symbols, FEATURE_COLS, FreshnessReport)

The third return value of materialize_inference_factors changed from
``list[str]`` (cols only) to ``(list[str], FreshnessReport)`` — callers that
only unpack 3 values still work; the FreshnessReport is the 4th element.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from trade_py.data.contracts import (
    FreshnessReport,
    build_freshness_report,
    snapshot_from_sync_state,
)
from trade_py.db.trade_db import TradeDB
from trade_py.factors.definitions import (
    FEATURE_COLS,
    FACTOR_TYPE_MAP,
    factor_registry_rows,
)
from trade_py.factors.encoder import encode_with_maps, load_feature_maps, stable_code_map
from trade_py.factors.groups import (
    build_event_group,
    build_event_group_training,
    build_sentiment_group,
    build_technical_group,
    build_instrument_group,
    FactorGroupResult,
)
from trade_py.factors.registry import composite_trust_weights, load_registry_from_db

logger = logging.getLogger(__name__)


# ── Default fill values for columns that may be absent after group merges ─────

_CORE_DEFAULTS: dict[str, object] = {
    "hop": 0,
    "kg_score": 0.0,
    "magnitude": 0.0,
    "confidence": 1.0,
    "news_volume": 0.0,
    "decay_factor": 0.6,
    "max_hop": 2,
    "industry": 255,
    "market": 0,
    "window_score": 50.0,
    "net_sentiment": 0.0,
}


def _fill_all_defaults(df: pd.DataFrame) -> pd.DataFrame:
    """Fill all FEATURE_COLS to their neutral defaults after group merges."""
    from trade_py.factors.definitions import GOLD_DEFAULTS, TECHNICAL_DEFAULTS

    for col, default in _CORE_DEFAULTS.items():
        if col in df.columns:
            df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(default)
    for col, default in GOLD_DEFAULTS.items():
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(default)
    for col, default in TECHNICAL_DEFAULTS.items():
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(default)
    # Ensure encoded categoricals are int
    for col in ("event_type_code", "breadth_code"):
        if col in df.columns:
            df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(0).astype(int)
    return df


def _collect_group_coverage(groups: list[FactorGroupResult]) -> dict[str, float]:
    return {g.group_name: g.coverage for g in groups}


# ── Public API ─────────────────────────────────────────────────────────────────

def build_training_feature_frame(
    data_root: str,
) -> tuple[pd.DataFrame, dict[str, dict[str, int]], dict[str, float]]:
    """Build feature matrix for training from event_propagations + signals + gold.

    Returns
    -------
    df : pd.DataFrame
        Feature matrix with FEATURE_COLS + label columns.
    maps : dict[str, dict[str, int]]
        Categorical encoding maps (event_type, breadth).
    trust_weights : dict[str, float]
        composite_trust per factor (from factor_registry).
    """
    db = TradeDB(data_root)

    # Build encoding maps from distinct values in event_propagations/market_events
    _raw_rows = db._conn.execute(
        "SELECT DISTINCT me.event_type, me.breadth FROM market_events me"
    ).fetchall()
    if _raw_rows:
        _raw_df = pd.DataFrame([dict(r) for r in _raw_rows])
        maps: dict[str, dict[str, int]] = {
            "event_type": stable_code_map(_raw_df["event_type"]),
            "breadth": stable_code_map(_raw_df["breadth"]),
        }
    else:
        maps = {"event_type": {}, "breadth": {}}

    # ── Group 1: Event/KG (with full join for labels) ─────────────────────────
    event_group, full_df = build_event_group_training(db._conn, maps)
    if full_df.empty:
        return pd.DataFrame(), maps, {}

    df = full_df.copy()

    # ── Group 2: Gold sentiment ────────────────────────────────────────────────
    sentiment_group = build_sentiment_group(data_root)
    if not sentiment_group.values.empty:
        df = df.merge(
            sentiment_group.values,
            left_on=["date", "symbol"],
            right_on=["date", "symbol"],
            how="left",
            suffixes=("", "_gold"),
        )

    # ── Group 3: Technical ────────────────────────────────────────────────────
    reference_dates = pd.to_datetime(df["date"], errors="coerce")
    technical_group = build_technical_group(data_root, reference_dates)
    if not technical_group.values.empty:
        df = df.merge(
            technical_group.values,
            left_on=["date", "symbol"],
            right_on=["date", "symbol"],
            how="left",
            suffixes=("", "_tech"),
        )

    # ── Group 4: Instrument (training: join without date filter) ─────────────
    inst_rows = db._conn.execute(
        """
        SELECT i.symbol,
               COALESCE(i.industry, 255) AS industry,
               COALESCE(i.market,     0) AS market
        FROM instruments i
        """
    ).fetchall()
    if inst_rows:
        inst_df = pd.DataFrame([dict(r) for r in inst_rows])
        df = df.merge(inst_df, on="symbol", how="left", suffixes=("", "_inst"))

    # window_score + net_sentiment from signals, matched by (event_date, symbol)
    sig_rows = db._conn.execute(
        """
        SELECT s.symbol, s.date, s.window_score, s.net_sentiment
        FROM signals s
        """
    ).fetchall()
    if sig_rows:
        sig_df = pd.DataFrame([dict(r) for r in sig_rows])
        df = df.merge(
            sig_df,
            left_on=["date", "symbol"],
            right_on=["date", "symbol"],
            how="left",
            suffixes=("", "_sig"),
        )

    df = encode_with_maps(df, maps)
    df = _fill_all_defaults(df)

    # Load composite trust weights
    try:
        reg = load_registry_from_db(db)
        trust_weights = composite_trust_weights(reg)
    except Exception:
        trust_weights = composite_trust_weights()

    groups = [event_group, sentiment_group, technical_group]
    logger.debug(
        "build_training_feature_frame: %d rows, group_coverage=%s",
        len(df),
        _collect_group_coverage(groups),
    )
    return df, maps, trust_weights


def materialize_inference_factors(
    data_root: str,
    date_str: str | None = None,
) -> tuple[str, int, list[str], FreshnessReport]:
    """Build and persist factor rows for inference on a given date.

    Returns
    -------
    target_date : str
        ISO date string for which factors were materialized.
    n_symbols : int
        Number of symbols processed.
    feature_cols : list[str]
        FEATURE_COLS (unchanged contract).
    freshness : FreshnessReport
        Provenance report for the trust layer.
    """
    db = TradeDB(data_root)
    today_str = db._conn.execute("SELECT MAX(date) FROM signals").fetchone()[0]
    target_date = date_str or today_str
    if not target_date:
        empty_report = build_freshness_report([], as_of_date="")
        return "", 0, [], empty_report

    # ── Group 1: Event/KG (inference variant) ─────────────────────────────────
    maps = load_feature_maps(data_root)
    event_group = build_event_group(db._conn, target_date, maps=maps)

    # ── Group 2: Instrument + window_score ────────────────────────────────────
    instrument_group = build_instrument_group(db._conn, target_date)

    # ── Group 3: Gold sentiment ────────────────────────────────────────────────
    sentiment_group = build_sentiment_group(
        data_root, start_date=target_date, end_date=target_date
    )

    # ── Merge all groups onto the signals base table ───────────────────────────
    if instrument_group.values.empty:
        empty_report = build_freshness_report([], as_of_date=target_date)
        return target_date, 0, [], empty_report

    df = instrument_group.values.copy()

    # Merge event features (left join — some symbols may have no events)
    if not event_group.values.empty:
        df = df.merge(
            event_group.values,
            on=["date", "symbol"],
            how="left",
            suffixes=("", "_ev"),
        )

    # Merge sentiment features
    if not sentiment_group.values.empty:
        df = df.merge(
            sentiment_group.values,
            on=["date", "symbol"],
            how="left",
            suffixes=("", "_sent"),
        )

    # ── Group 4: Technical ────────────────────────────────────────────────────
    ref_dates = pd.Series([target_date] * len(df))
    technical_group = build_technical_group(data_root, ref_dates)
    if not technical_group.values.empty:
        df = df.merge(
            technical_group.values,
            on=["date", "symbol"],
            how="left",
            suffixes=("", "_tech"),
        )

    df = encode_with_maps(df, maps)
    df = _fill_all_defaults(df)

    # ── Build FreshnessReport ─────────────────────────────────────────────────
    snapshots = []
    for ds_name, dataset_key in [
        ("kline",   "kline"),
        ("signals", "window_score"),
    ]:
        try:
            # sync_state is per-symbol — take MAX across all symbols
            row = db._conn.execute(
                "SELECT MAX(last_date) FROM sync_state WHERE dataset=?",
                (dataset_key,),
            ).fetchone()
            last = row[0] if row else None
        except Exception:
            last = None
        snapshots.append(snapshot_from_sync_state(ds_name, target_date, last))

    # factors table freshness: last INSERT date
    try:
        row = db._conn.execute("SELECT MAX(updated_at) FROM factors").fetchone()
        last_factors = row[0] if row else None
    except Exception:
        last_factors = None
    snapshots.append(snapshot_from_sync_state("factors", target_date, last_factors))

    # Sentiment gold freshness from file existence
    gold_path = Path(data_root) / "sentiment" / "gold"
    if not sentiment_group.values.empty and sentiment_group.source_date_range:
        latest_sent = sentiment_group.source_date_range[1]
        try:
            from datetime import date as _date
            lag_sent = (_date.fromisoformat(target_date) - _date.fromisoformat(latest_sent)).days
        except Exception:
            lag_sent = None
        from trade_py.data.contracts import DataSnapshot
        snapshots.append(DataSnapshot(
            dataset="sentiment_gold",
            symbol=None,
            as_of_date=target_date,
            latest_available_date=latest_sent,
            freshness_days=lag_sent,
            row_count=len(sentiment_group.values),
            quality_flags=["stale"] if (lag_sent or 0) > 3 else [],
        ))
    else:
        from trade_py.data.contracts import DataSnapshot
        snapshots.append(DataSnapshot(
            dataset="sentiment_gold", symbol=None, as_of_date=target_date,
            freshness_days=None, quality_flags=["no_data"],
        ))

    freshness = build_freshness_report(snapshots, as_of_date=target_date)

    # ── Persist to DB ──────────────────────────────────────────────────────────
    db.factor_registry_upsert_batch(factor_registry_rows())
    factor_rows: list[dict] = []
    for record in df.to_dict(orient="records"):
        date_val = str(record.get("date", target_date))
        symbol = str(record["symbol"])
        for col in FEATURE_COLS:
            factor_rows.append({
                "date": date_val,
                "symbol": symbol,
                "factor_name": col,
                "factor_type": FACTOR_TYPE_MAP.get(col, "model_feature"),
                "value": float(record.get(col, 0.0) or 0.0),
            })
    db.factor_upsert_batch(factor_rows)

    groups = [event_group, sentiment_group, technical_group, instrument_group]
    logger.info(
        "materialize_inference_factors: date=%s symbols=%d coverage=%s",
        target_date, len(df),
        {g.group_name: f"{g.coverage:.2f}" for g in groups},
    )

    return target_date, len(df), FEATURE_COLS, freshness
