"""Feature materialization: assemble factor DataFrame, persist to DB."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from trade_py.db.trade_db import TradeDB
from trade_py.factors.definitions import (
    FEATURE_COLS,
    FACTOR_TYPE_MAP,
    GOLD_DEFAULTS,
    TECHNICAL_DEFAULTS,
    factor_registry_rows,
)
from trade_py.factors.technical import merge_technical_factors
from trade_py.factors.encoder import encode_with_maps, load_feature_maps, stable_code_map

logger = logging.getLogger(__name__)


def _load_gold_factors(data_root: str,
                       start_date: str | None = None,
                       end_date: str | None = None) -> pd.DataFrame:
    gold_glob = str(Path(data_root) / "sentiment" / "gold" / "**" / "*.parquet")
    try:
        import duckdb

        con = duckdb.connect()
        clauses = []
        if start_date:
            clauses.append(f"date >= '{start_date}'")
        if end_date:
            clauses.append(f"date <= '{end_date}'")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        df = con.execute(
            f"""
            SELECT
                date, symbol,
                COALESCE(bf_net_sentiment, 0.0) AS bf_net_sentiment,
                COALESCE(bf_event_strength, 0.0) AS bf_event_strength,
                COALESCE(bf_policy_intensity, 0.0) AS bf_policy_intensity,
                COALESCE(bf_entity_density, 0.0) AS bf_entity_density,
                COALESCE(bf_novelty, 1.0) AS bf_novelty,
                COALESCE(bf_volume_burst, 0.0) AS bf_volume_burst,
                COALESCE(bf_cross_source_confirmation, 0.0) AS bf_cross_source_confirmation,
                COALESCE(bf_noise_penalty, 1.0) AS bf_noise_penalty
            FROM read_parquet('{gold_glob}', union_by_name=true)
            {where_sql}
            """
        ).df()
        con.close()
        return df
    except Exception as exc:
        logger.debug("failed to load gold factors: %s", exc)
        return pd.DataFrame()


def _fill_factor_defaults(df: pd.DataFrame) -> pd.DataFrame:
    df["hop"] = df["hop"].fillna(0).astype(int)
    df["kg_score"] = pd.to_numeric(df.get("kg_score"), errors="coerce").fillna(0.0)
    df["magnitude"] = pd.to_numeric(df.get("magnitude"), errors="coerce").fillna(0.0)
    df["confidence"] = pd.to_numeric(df.get("confidence"), errors="coerce").fillna(1.0)
    df["news_volume"] = pd.to_numeric(df.get("news_volume"), errors="coerce").fillna(0.0)
    df["decay_factor"] = pd.to_numeric(df.get("decay_factor"), errors="coerce").fillna(0.6)
    df["max_hop"] = pd.to_numeric(df.get("max_hop"), errors="coerce").fillna(2).astype(int)
    df["industry"] = pd.to_numeric(df.get("industry"), errors="coerce").fillna(255).astype(int)
    df["market"] = pd.to_numeric(df.get("market"), errors="coerce").fillna(0).astype(int)
    df["window_score"] = pd.to_numeric(df.get("window_score"), errors="coerce").fillna(50.0)
    df["net_sentiment"] = pd.to_numeric(df.get("net_sentiment"), errors="coerce").fillna(0.0)
    for col, default in GOLD_DEFAULTS.items():
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(default)
    for col, default in TECHNICAL_DEFAULTS.items():
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(default)
    return df


def build_training_feature_frame(data_root: str) -> tuple[pd.DataFrame, dict[str, dict[str, int]]]:
    """Build feature matrix for training from event_propagations + signals + gold."""
    db = TradeDB(data_root)
    rows = db._conn.execute(
        """
        SELECT
            ep.event_id, ep.symbol, ep.hop, ep.kg_score, ep.typical_days,
            ep.rel_path, ep.actual_return_5d, ep.actual_return_20d,
            me.event_type, me.magnitude, me.confidence, me.breadth,
            me.news_volume, me.event_date,
            COALESCE(et.decay_factor, 0.6) AS decay_factor,
            COALESCE(et.max_hop, 2) AS max_hop,
            i.industry, i.market,
            s.window_score, s.net_sentiment
        FROM event_propagations ep
        JOIN market_events me ON me.event_id = ep.event_id
        JOIN instruments i ON i.symbol = ep.symbol
        LEFT JOIN event_templates et ON et.event_type = me.event_type
        LEFT JOIN signals s ON s.symbol = ep.symbol AND s.date = me.event_date
        """
    ).fetchall()
    if not rows:
        return pd.DataFrame(), {"event_type": {}, "breadth": {}}

    df = pd.DataFrame([dict(r) for r in rows])
    gold_df = _load_gold_factors(data_root)
    if not gold_df.empty:
        df = df.merge(
            gold_df,
            left_on=["event_date", "symbol"],
            right_on=["date", "symbol"],
            how="left",
            suffixes=("", "_gold"),
        ).drop(columns=["date"], errors="ignore")
    df = merge_technical_factors(data_root, df, "event_date")
    maps = {
        "event_type": stable_code_map(df["event_type"]),
        "breadth": stable_code_map(df["breadth"]),
    }
    df = encode_with_maps(df, maps)
    df = _fill_factor_defaults(df)
    return df, maps


def materialize_inference_factors(data_root: str,
                                  date_str: str | None = None) -> tuple[str, int, list[str]]:
    """Build and persist factor rows for inference on a given date."""
    db = TradeDB(data_root)
    target_date = date_str or db._conn.execute("SELECT MAX(date) FROM signals").fetchone()[0]
    if not target_date:
        return "", 0, []

    rows = db._conn.execute(
        """
        WITH ranked_events AS (
            SELECT
                ep.event_date, ep.symbol, ep.hop, ep.kg_score,
                me.event_type, me.magnitude, me.confidence, me.breadth, me.news_volume,
                COALESCE(et.decay_factor, 0.6) AS decay_factor,
                COALESCE(et.max_hop, 2) AS max_hop,
                ROW_NUMBER() OVER (
                    PARTITION BY ep.event_date, ep.symbol
                    ORDER BY ABS(ep.kg_score) DESC, ep.hop ASC, ep.event_id
                ) AS rn
            FROM event_propagations ep
            JOIN market_events me ON me.event_id = ep.event_id
            LEFT JOIN event_templates et ON et.event_type = me.event_type
            WHERE ep.event_date = ?
        )
        SELECT
            s.date, s.symbol,
            COALESCE(re.hop, 0) AS hop,
            COALESCE(re.kg_score, s.event_kg_score, 0.0) AS kg_score,
            COALESCE(re.magnitude, 0.0) AS magnitude,
            COALESCE(re.confidence, 1.0) AS confidence,
            COALESCE(re.event_type, s.event_type, '') AS event_type,
            COALESCE(re.breadth, '') AS breadth,
            COALESCE(re.news_volume, 0.0) AS news_volume,
            COALESCE(re.decay_factor, 0.6) AS decay_factor,
            COALESCE(re.max_hop, 2) AS max_hop,
            COALESCE(i.industry, 255) AS industry,
            COALESCE(i.market, 0) AS market,
            COALESCE(s.window_score, 50.0) AS window_score,
            COALESCE(s.net_sentiment, 0.0) AS net_sentiment
        FROM signals s
        LEFT JOIN ranked_events re
            ON re.event_date = s.date AND re.symbol = s.symbol AND re.rn = 1
        LEFT JOIN instruments i ON i.symbol = s.symbol
        WHERE s.date = ?
        """,
        (target_date, target_date),
    ).fetchall()
    if not rows:
        return target_date, 0, []

    df = pd.DataFrame([dict(r) for r in rows])
    gold_df = _load_gold_factors(data_root, start_date=target_date, end_date=target_date)
    if not gold_df.empty:
        df = df.merge(gold_df, left_on=["date", "symbol"], right_on=["date", "symbol"], how="left")
    df = merge_technical_factors(data_root, df, "date")
    maps = load_feature_maps(data_root)
    df = encode_with_maps(df, maps)
    df = _fill_factor_defaults(df)

    db.factor_registry_upsert_batch(factor_registry_rows())
    factor_rows: list[dict] = []
    for record in df.to_dict(orient="records"):
        date_val = str(record["date"])
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
    return target_date, len(df), FEATURE_COLS
