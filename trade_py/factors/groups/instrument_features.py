"""Instrument/signal factor group builder.

Covers: industry, market, window_score, net_sentiment

Source:
  - instruments table (industry, market)
  - signals table (window_score, net_sentiment)

These are cross-cutting factors that tie a symbol to its market context
and current window/sentiment state from the online signal pipeline.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from trade_py.factors.groups._base import FactorGroupResult

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

INSTRUMENT_FEATURE_COLS: list[str] = [
    "industry",
    "market",
    "window_score",
    "net_sentiment",
]

_DEFAULTS: dict[str, float] = {
    "industry": 255.0,
    "market": 0.0,
    "window_score": 50.0,
    "net_sentiment": 0.0,
}


def build_instrument_group(
    conn: "sqlite3.Connection",
    date_str: str,
) -> FactorGroupResult:
    """Load instrument + signal factors for the given date.

    Parameters
    ----------
    conn:
        SQLite connection.
    date_str:
        Target date (ISO string).  Pulls signal row for this date.
    """
    try:
        rows = conn.execute(
            """
            SELECT
                s.date,
                s.symbol,
                COALESCE(i.industry,      255) AS industry,
                COALESCE(i.market,          0) AS market,
                COALESCE(s.window_score,  50.0) AS window_score,
                COALESCE(s.net_sentiment,  0.0) AS net_sentiment
            FROM signals s
            LEFT JOIN instruments i ON i.symbol = s.symbol
            WHERE s.date = ?
            """,
            (date_str,),
        ).fetchall()
    except Exception as exc:
        logger.warning("instrument_group load failed for %s: %s", date_str, exc)
        return FactorGroupResult.empty("instrument", INSTRUMENT_FEATURE_COLS)

    if not rows:
        logger.debug("instrument_group: no signals for date=%s", date_str)
        return FactorGroupResult.empty("instrument", INSTRUMENT_FEATURE_COLS)

    df = pd.DataFrame([dict(r) for r in rows])

    # Detect defaults
    used_defaults: list[str] = []
    for col, default in _DEFAULTS.items():
        if col in df.columns:
            frac = (df[col] == default).mean()
            if frac > 0.50:
                used_defaults.append(col)

    # Coverage: symbols where window_score is not neutral 50
    n_real_window = (df["window_score"] != 50.0).sum()
    coverage = round(float(n_real_window) / max(len(df), 1), 4)

    source_dates = df["date"].dropna().astype(str)
    date_range = (source_dates.min(), source_dates.max()) if not source_dates.empty else None

    return FactorGroupResult(
        group_name="instrument",
        values=df[["date", "symbol"] + INSTRUMENT_FEATURE_COLS],
        expected_cols=INSTRUMENT_FEATURE_COLS,
        missing=[],
        used_defaults=used_defaults,
        coverage=coverage,
        source_date_range=date_range,
    )


def build_instrument_group_training(
    conn: "sqlite3.Connection",
    symbols: pd.Series,
    dates: pd.Series,
) -> FactorGroupResult:
    """Training variant — join over multiple (date, symbol) pairs.

    Uses the signal row for each event_date, matching by (date, symbol).
    """
    try:
        rows = conn.execute(
            """
            SELECT
                s.date,
                s.symbol,
                COALESCE(i.industry,      255) AS industry,
                COALESCE(i.market,          0) AS market,
                COALESCE(s.window_score,  50.0) AS window_score,
                COALESCE(s.net_sentiment,  0.0) AS net_sentiment
            FROM instruments i
            LEFT JOIN signals s ON s.symbol = i.symbol
            """
        ).fetchall()
    except Exception as exc:
        logger.warning("instrument_group_training failed: %s", exc)
        return FactorGroupResult.empty("instrument", INSTRUMENT_FEATURE_COLS)

    if not rows:
        return FactorGroupResult.empty("instrument", INSTRUMENT_FEATURE_COLS)

    df = pd.DataFrame([dict(r) for r in rows])
    n_real_window = (df["window_score"] != 50.0).sum()
    coverage = round(float(n_real_window) / max(len(df), 1), 4)

    return FactorGroupResult(
        group_name="instrument",
        values=df[["date", "symbol"] + INSTRUMENT_FEATURE_COLS],
        expected_cols=INSTRUMENT_FEATURE_COLS,
        coverage=coverage,
    )
