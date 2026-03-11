"""Factor quantile return analysis.

Splits stocks into N quantile buckets by factor signal on each date,
then computes average forward return per bucket to verify monotonicity.

Usage:
    from trade_py.analysis.factor_quantile import compute_quantile_returns, format_quantile_report
    result = compute_quantile_returns("data", factor_col="net_sentiment", n_quantiles=5, forward_days=5)
    print(format_quantile_report(result))
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_MIN_STOCKS_PER_DAY = 10  # minimum stocks required per day for a valid observation


def _load_gold_factor(
    data_root: Path,
    factor_col: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Load Gold parquet rows with the requested factor column."""
    gold_dir = data_root / "sentiment" / "gold"
    if not gold_dir.exists():
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    cur = start
    while cur <= end:
        p = gold_dir / f"{cur.year:04d}" / f"{cur.month:02d}" / f"{cur.isoformat()}.parquet"
        if p.exists():
            try:
                df = pd.read_parquet(p)
                if factor_col in df.columns:
                    frames.append(df[["date", "symbol", factor_col]])
            except Exception as exc:
                logger.debug("Cannot read gold %s: %s", p, exc)
        cur += timedelta(days=1)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _load_kline_pivot(data_root: Path) -> pd.DataFrame:
    """Load kline close prices as (date × symbol) pivot via DuckDB."""
    kline_dir = data_root / "kline"
    if not kline_dir.exists():
        return pd.DataFrame()
    try:
        import duckdb
        kline_glob = str(kline_dir / "**" / "*.parquet")
        con = duckdb.connect()
        df = con.execute(f"""
            SELECT symbol, date, close
            FROM read_parquet('{kline_glob}', union_by_name=true)
            WHERE close IS NOT NULL AND close > 0
        """).df()
        con.close()
    except Exception as exc:
        logger.warning("DuckDB kline load failed: %s", exc)
        return pd.DataFrame()

    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")


def compute_quantile_returns(
    data_root: str | Path = "data",
    factor_col: str = "net_sentiment",
    n_quantiles: int = 5,
    forward_days: int = 5,
    lookback: int = 120,
) -> dict:
    """Compute average forward returns per factor quantile bucket.

    Args:
        data_root:    Root data directory.
        factor_col:   Column name in Gold layer to use as factor signal.
        n_quantiles:  Number of quantile buckets (e.g. 5 = quintiles).
        forward_days: Forward trading days for return computation.
        lookback:     Calendar days of data to use.

    Returns:
        Dict with keys:
          factor_col, n_quantiles, forward_days, valid_days,
          quantile_returns: list of mean returns per quantile [Q1..Qn],
          spread: Q_top - Q_bottom return,
          monotone: bool (True if returns are monotonically increasing),
          ic: overall Spearman IC (factor vs return).
    """
    data_root = Path(data_root)
    end = date.today()
    start = end - timedelta(days=lookback)

    gold_df = _load_gold_factor(data_root, factor_col, start, end)
    if gold_df.empty:
        return {"error": f"No Gold data with column {factor_col!r}", "valid_days": 0}

    gold_df = gold_df[gold_df["symbol"] != "_MARKET_"]
    gold_df["date"] = pd.to_datetime(gold_df["date"]).dt.date
    gold_df[factor_col] = pd.to_numeric(gold_df[factor_col], errors="coerce")

    kline_pivot = _load_kline_pivot(data_root)
    if kline_pivot.empty:
        return {"error": "No kline data found", "valid_days": 0}

    fwd_pivot = kline_pivot.shift(-forward_days) / kline_pivot - 1.0

    trading_dates = sorted(gold_df["date"].unique())
    quantile_buckets: list[list[float]] = [[] for _ in range(n_quantiles)]
    ic_vals: list[float] = []
    valid_days = 0

    for d in trading_dates:
        day_gold = gold_df[gold_df["date"] == d].dropna(subset=[factor_col])
        if len(day_gold) < _MIN_STOCKS_PER_DAY:
            continue
        if d not in fwd_pivot.index:
            continue

        fwd_row = fwd_pivot.loc[d]
        if d in kline_pivot.index:
            active = kline_pivot.loc[d]
            fwd_row = fwd_row[fwd_row.index.isin(active[active > 0].index)]

        combined = (
            day_gold.set_index("symbol")[factor_col]
            .to_frame()
            .join(fwd_row.rename("fwd_return"), how="inner")
            .dropna()
        )
        if len(combined) < _MIN_STOCKS_PER_DAY:
            continue

        # Assign quantile labels (1 = lowest, n_quantiles = highest)
        try:
            combined["q"] = pd.qcut(
                combined[factor_col], q=n_quantiles, labels=False, duplicates="drop"
            )
        except ValueError:
            continue

        for q_idx in range(n_quantiles):
            bucket = combined[combined["q"] == q_idx]["fwd_return"]
            if not bucket.empty:
                quantile_buckets[q_idx].extend(bucket.tolist())

        # Overall IC for this day
        s_rank = combined[factor_col].rank()
        r_rank = combined["fwd_return"].rank()
        n = len(combined)
        cov = ((s_rank - s_rank.mean()) * (r_rank - r_rank.mean())).sum()
        denom = math.sqrt(
            ((s_rank - s_rank.mean()) ** 2).sum()
            * ((r_rank - r_rank.mean()) ** 2).sum()
        )
        if denom > 0:
            ic_vals.append(float(cov / denom))

        valid_days += 1

    if valid_days == 0:
        return {"error": "No valid days with enough data", "valid_days": 0}

    q_returns = [
        round(float(np.mean(b)) * 100, 4) if b else float("nan")
        for b in quantile_buckets
    ]

    # Check monotonicity
    valid_q = [r for r in q_returns if not math.isnan(r)]
    monotone = all(valid_q[i] <= valid_q[i + 1] for i in range(len(valid_q) - 1))

    spread = (
        round(q_returns[-1] - q_returns[0], 4)
        if not math.isnan(q_returns[-1]) and not math.isnan(q_returns[0])
        else float("nan")
    )

    mean_ic = round(float(np.mean(ic_vals)), 4) if ic_vals else float("nan")

    return {
        "factor_col":       factor_col,
        "n_quantiles":      n_quantiles,
        "forward_days":     forward_days,
        "lookback_days":    lookback,
        "valid_days":       valid_days,
        "quantile_returns": q_returns,   # pct, Q1 (lowest factor) ... Qn (highest)
        "spread":           spread,       # Qn - Q1, pct
        "monotone":         monotone,
        "ic":               mean_ic,
    }


def format_quantile_report(result: dict) -> str:
    """Format quantile return dict as a human-readable string."""
    if "error" in result:
        return f"分位数分析: {result['error']}"

    factor = result.get("factor_col", "?")
    fwd = result.get("forward_days", "?")
    n_q = result.get("n_quantiles", 5)
    lines = [
        f"\n因子分位数分析: {factor} (forward={fwd}d)",
        "─" * 40,
    ]
    q_returns = result.get("quantile_returns", [])
    for i, ret in enumerate(q_returns, 1):
        label = "Q1(最低)" if i == 1 else (f"Q{n_q}(最高)" if i == n_q else f"Q{i}")
        ret_str = f"{ret:+.4f}%" if not math.isnan(ret) else "N/A"
        lines.append(f"  {label:12} {ret_str}")

    spread = result.get("spread", float("nan"))
    spread_str = f"{spread:+.4f}%" if not math.isnan(spread) else "N/A"
    monotone = "✅ 单调" if result.get("monotone") else "⚠️  非单调"
    ic = result.get("ic", float("nan"))
    ic_str = f"{ic:.4f}" if not math.isnan(ic) else "N/A"

    lines += [
        "─" * 40,
        f"  多空价差:   {spread_str}",
        f"  单调性:     {monotone}",
        f"  均值IC:     {ic_str}",
        f"  有效天数:   {result.get('valid_days', 0)} 天",
    ]
    return "\n".join(lines)
