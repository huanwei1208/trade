"""Technical factor group builder.

Covers: tech_rsi_14, tech_macd_hist, tech_macd_cross,
        tech_kdj_k, tech_kdj_d, tech_kdj_j, tech_kdj_cross,
        tech_ma_gap_5_20, tech_price_vs_ma20,
        tech_volatility_20d, tech_volume_ratio_5_20

Source: market/kline/**/*.parquet (read via DuckDB + pandas computation)

This module wraps `trade_py.factors.technical` and adapts it to the
FactorGroupResult contract — preserving all existing computation logic.
"""
from __future__ import annotations

import logging

import pandas as pd

from trade_py.factors.definitions import TECHNICAL_DEFAULTS
from trade_py.factors.groups._base import FactorGroupResult
from trade_py.factors.technical import compute_technical_factors, _load_kline_history

logger = logging.getLogger(__name__)

TECHNICAL_FEATURE_COLS: list[str] = list(TECHNICAL_DEFAULTS.keys())

# Minimum RSI periods needed for reliable values
_WARMUP_DAYS = 120


def build_technical_group(
    data_root: str,
    reference_dates: pd.Series,
) -> FactorGroupResult:
    """Compute technical factors from kline history.

    Parameters
    ----------
    data_root:
        Root data directory.
    reference_dates:
        pd.Series of dates (ISO strings) for which we need factors.
        The warmup window is automatically prepended for indicator stability.
    """
    if reference_dates.empty:
        return FactorGroupResult.empty("technical", TECHNICAL_FEATURE_COLS)

    dates_dt = pd.to_datetime(reference_dates, errors="coerce").dropna()
    if dates_dt.empty:
        return FactorGroupResult.empty("technical", TECHNICAL_FEATURE_COLS)

    warm_start = (dates_dt.min() - pd.Timedelta(days=_WARMUP_DAYS)).date().isoformat()
    end_iso = dates_dt.max().date().isoformat()

    kline_df = _load_kline_history(data_root, warm_start, end_iso)
    if kline_df.empty:
        logger.debug("technical_group: no kline data for %s–%s", warm_start, end_iso)
        # Return empty result; orchestrator will fill defaults
        result = FactorGroupResult.empty("technical", TECHNICAL_FEATURE_COLS)
        result.missing = list(TECHNICAL_FEATURE_COLS)
        return result

    tech_df = compute_technical_factors(kline_df)
    if tech_df.empty:
        return FactorGroupResult.empty("technical", TECHNICAL_FEATURE_COLS)

    # Filter to only the requested dates
    tech_df["date"] = tech_df["date"].astype(str).str.slice(0, 10)
    ref_date_set = set(reference_dates.astype(str).str.slice(0, 10).unique())
    tech_df = tech_df[tech_df["date"].isin(ref_date_set)].copy()

    # Detect columns still at defaults (indicator not yet computed due to warmup)
    used_defaults: list[str] = []
    for col, default in TECHNICAL_DEFAULTS.items():
        if col in tech_df.columns:
            frac = (tech_df[col] == default).mean()
            if frac > 0.50:
                used_defaults.append(col)

    source_dates = tech_df["date"].dropna().astype(str)
    date_range = (source_dates.min(), source_dates.max()) if not source_dates.empty else None

    # Coverage: rows where RSI is not exactly the default 50.0
    n_real = (tech_df["tech_rsi_14"] != 50.0).sum()
    coverage = round(float(n_real) / max(len(tech_df), 1), 4)

    return FactorGroupResult(
        group_name="technical",
        values=tech_df[["date", "symbol"] + TECHNICAL_FEATURE_COLS],
        expected_cols=TECHNICAL_FEATURE_COLS,
        missing=[],
        used_defaults=used_defaults,
        coverage=coverage,
        source_date_range=date_range,
    )
