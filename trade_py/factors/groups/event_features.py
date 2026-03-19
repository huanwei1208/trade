"""Event/KG factor group builder.

Covers: hop, kg_score, magnitude, confidence, event_type_code, breadth_code,
        news_volume, decay_factor, max_hop
Source: event_propagations JOIN market_events JOIN event_templates
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from trade_py.factors.groups._base import FactorGroupResult

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

# Columns this group owns (pre-encoding raw names)
_RAW_COLS = ["hop", "kg_score", "magnitude", "confidence",
             "event_type", "breadth", "news_volume", "decay_factor", "max_hop"]

# Columns after encoding (what appears in FEATURE_COLS)
EVENT_FEATURE_COLS: list[str] = [
    "hop", "kg_score", "magnitude", "confidence",
    "event_type_code", "breadth_code",
    "news_volume", "decay_factor", "max_hop",
]

_DEFAULTS: dict[str, float] = {
    "hop": 0, "kg_score": 0.0, "magnitude": 0.0, "confidence": 1.0,
    "event_type_code": 0, "breadth_code": 0,
    "news_volume": 0.0, "decay_factor": 0.6, "max_hop": 2,
}


def build_event_group(
    conn: "sqlite3.Connection",
    date_str: str | None = None,
    *,
    maps: dict[str, dict[str, int]] | None = None,
) -> FactorGroupResult:
    """Load and return event/KG features for all (date, symbol) pairs.

    Parameters
    ----------
    conn:
        SQLite connection (already open).
    date_str:
        If provided, filter to this event_date.
    maps:
        Encoding maps {event_type: {str: int}, breadth: {str: int}}.
        If None, creates identity maps (all values → 0).
    """
    where = f"WHERE ep.event_date = '{date_str}'" if date_str else ""
    try:
        rows = conn.execute(
            f"""
            SELECT
                ep.event_date AS date,
                ep.symbol,
                COALESCE(ep.hop, 0)                  AS hop,
                COALESCE(ep.kg_score, 0.0)           AS kg_score,
                COALESCE(me.magnitude, 0.0)          AS magnitude,
                COALESCE(me.confidence, 1.0)         AS confidence,
                COALESCE(me.event_type, '')          AS event_type,
                COALESCE(me.breadth, '')             AS breadth,
                COALESCE(me.news_volume, 0.0)        AS news_volume,
                COALESCE(et.decay_factor, 0.6)       AS decay_factor,
                COALESCE(et.max_hop, 2)              AS max_hop
            FROM event_propagations ep
            JOIN market_events me ON me.event_id = ep.event_id
            LEFT JOIN event_templates et ON et.event_type = me.event_type
            {where}
            """
        ).fetchall()
    except Exception as exc:
        logger.warning("event_group load failed: %s", exc)
        return FactorGroupResult.empty("event", EVENT_FEATURE_COLS)

    if not rows:
        return FactorGroupResult.empty("event", EVENT_FEATURE_COLS)

    df = pd.DataFrame([dict(r) for r in rows])

    # Encode categorical columns
    et_map = (maps or {}).get("event_type", {})
    br_map = (maps or {}).get("breadth", {})
    df["event_type_code"] = df["event_type"].map(et_map).fillna(0).astype(int)
    df["breadth_code"] = df["breadth"].map(br_map).fillna(0).astype(int)
    df = df.drop(columns=["event_type", "breadth"], errors="ignore")

    # Track which columns used defaults (null before COALESCE)
    used_defaults: list[str] = []
    for col, default in _DEFAULTS.items():
        target = col
        if col == "event_type":
            target = "event_type_code"
        if col == "breadth":
            target = "breadth_code"
        if target in df.columns:
            n_default = (df[target] == default).sum()
            if n_default > 0:
                used_defaults.append(target)

    n_rows = len(df)
    source_dates = df["date"].dropna().astype(str)
    date_range = (source_dates.min(), source_dates.max()) if not source_dates.empty else None

    # coverage: fraction of rows with non-zero kg_score (proxy for real events)
    n_with_events = (df["kg_score"].abs() > 0).sum()
    coverage = round(float(n_with_events) / max(n_rows, 1), 4)

    return FactorGroupResult(
        group_name="event",
        values=df[["date", "symbol"] + EVENT_FEATURE_COLS],
        expected_cols=EVENT_FEATURE_COLS,
        missing=[],
        used_defaults=used_defaults,
        coverage=coverage,
        source_date_range=date_range,
    )


def build_event_group_training(
    conn: "sqlite3.Connection",
    maps: dict[str, dict[str, int]],
) -> tuple[FactorGroupResult, pd.DataFrame]:
    """Training variant — also returns extra join columns (event_id, etc.)

    Returns (FactorGroupResult, full_df_with_labels_cols).
    full_df_with_labels_cols includes actual_return_5d, actual_return_20d for
    the orchestrator to use as label targets.
    """
    try:
        rows = conn.execute(
            """
            SELECT
                ep.event_id, ep.symbol,
                ep.hop, ep.kg_score, ep.typical_days,
                ep.rel_path, ep.actual_return_5d, ep.actual_return_20d,
                me.event_type, me.magnitude, me.confidence, me.breadth,
                me.news_volume, me.event_date AS date,
                COALESCE(et.decay_factor, 0.6) AS decay_factor,
                COALESCE(et.max_hop, 2)        AS max_hop
            FROM event_propagations ep
            JOIN market_events me ON me.event_id = ep.event_id
            LEFT JOIN event_templates et ON et.event_type = me.event_type
            """
        ).fetchall()
    except Exception as exc:
        logger.warning("event_group_training load failed: %s", exc)
        empty = FactorGroupResult.empty("event", EVENT_FEATURE_COLS)
        return empty, pd.DataFrame()

    if not rows:
        empty = FactorGroupResult.empty("event", EVENT_FEATURE_COLS)
        return empty, pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    et_map = maps.get("event_type", {})
    br_map = maps.get("breadth", {})
    df["event_type_code"] = df["event_type"].map(et_map).fillna(0).astype(int)
    df["breadth_code"] = df["breadth"].map(br_map).fillna(0).astype(int)

    n_with_events = (df["kg_score"].abs() > 0).sum()
    coverage = round(float(n_with_events) / max(len(df), 1), 4)

    result_df = df[["date", "symbol"] + EVENT_FEATURE_COLS].copy()
    result = FactorGroupResult(
        group_name="event",
        values=result_df,
        expected_cols=EVENT_FEATURE_COLS,
        coverage=coverage,
    )
    return result, df
