"""Gold sentiment factor group builder.

Covers: bf_net_sentiment, bf_event_strength, bf_policy_intensity,
        bf_entity_density, bf_novelty, bf_volume_burst,
        bf_cross_source_confirmation, bf_noise_penalty

Source: sentiment/gold/**/*.parquet (read via DuckDB)
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from trade_py.factors.definitions import GOLD_DEFAULTS
from trade_py.factors.groups._base import FactorGroupResult

logger = logging.getLogger(__name__)

SENTIMENT_FEATURE_COLS: list[str] = list(GOLD_DEFAULTS.keys())


def build_sentiment_group(
    data_root: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FactorGroupResult:
    """Load gold sentiment features from parquet files.

    Parameters
    ----------
    data_root:
        Root data directory containing sentiment/gold/**/*.parquet.
    start_date / end_date:
        Optional date range filter (ISO strings).
    """
    gold_glob = str(Path(data_root) / "sentiment" / "gold" / "**" / "*.parquet")
    try:
        import duckdb

        clauses: list[str] = []
        if start_date:
            clauses.append(f"date >= '{start_date}'")
        if end_date:
            clauses.append(f"date <= '{end_date}'")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        con = duckdb.connect()
        df = con.execute(
            f"""
            SELECT
                date, symbol,
                COALESCE(bf_net_sentiment,             0.0) AS bf_net_sentiment,
                COALESCE(bf_event_strength,            0.0) AS bf_event_strength,
                COALESCE(bf_policy_intensity,          0.0) AS bf_policy_intensity,
                COALESCE(bf_entity_density,            0.0) AS bf_entity_density,
                COALESCE(bf_novelty,                   1.0) AS bf_novelty,
                COALESCE(bf_volume_burst,              0.0) AS bf_volume_burst,
                COALESCE(bf_cross_source_confirmation, 0.0) AS bf_cross_source_confirmation,
                COALESCE(bf_noise_penalty,             1.0) AS bf_noise_penalty
            FROM read_parquet('{gold_glob}', union_by_name=true)
            {where_sql}
            """
        ).df()
        con.close()
    except Exception as exc:
        logger.debug("sentiment_group load failed: %s", exc)
        return FactorGroupResult.empty("sentiment_gold", SENTIMENT_FEATURE_COLS)

    if df.empty:
        return FactorGroupResult.empty("sentiment_gold", SENTIMENT_FEATURE_COLS)

    # Determine which columns used their default values (proxy: == default)
    used_defaults: list[str] = []
    for col, default in GOLD_DEFAULTS.items():
        if col in df.columns:
            frac_default = (df[col] == default).mean()
            if frac_default > 0.80:  # >80% of rows at default → likely missing
                used_defaults.append(col)

    source_dates = df["date"].dropna().astype(str)
    date_range = (source_dates.min(), source_dates.max()) if not source_dates.empty else None

    # Coverage: fraction of rows where at least one bf_* is non-zero
    non_neutral = (
        (df["bf_net_sentiment"].abs() > 0)
        | (df["bf_event_strength"].abs() > 0)
        | (df["bf_volume_burst"].abs() > 0)
    )
    coverage = round(float(non_neutral.mean()), 4)

    return FactorGroupResult(
        group_name="sentiment_gold",
        values=df[["date", "symbol"] + SENTIMENT_FEATURE_COLS],
        expected_cols=SENTIMENT_FEATURE_COLS,
        missing=[],
        used_defaults=used_defaults,
        coverage=coverage,
        source_date_range=date_range,
    )
