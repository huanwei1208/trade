"""Sentiment IC (Information Coefficient) calculator.

Measures whether Gold-layer net_sentiment has genuine predictive power
over forward stock returns using Spearman rank correlation.

Usage:
    from trade_py.analysis.sentiment_ic import compute_ic
    result = compute_ic(data_root="data", lookback=60, forward_days=5)
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from trade_py.utils.data_inspector import _resolve_kline_glob

logger = logging.getLogger(__name__)

# Minimum number of stocks required for a valid daily IC observation
_MIN_STOCKS_PER_DAY = 5
# Minimum trading days needed before we report conclusions
_MIN_VALID_DAYS = 15


def _load_gold(data_root: Path, start: date, end: date) -> pd.DataFrame:
    """Load Gold parquet rows in [start, end] date range."""
    gold_dir = data_root / "sentiment" / "gold"
    if not gold_dir.exists():
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    cur = start
    while cur <= end:
        p = (gold_dir / f"{cur.year:04d}" / f"{cur.month:02d}"
             / f"{cur.isoformat()}.parquet")
        if p.exists():
            try:
                df = pd.read_parquet(p)
                frames.append(df)
            except Exception as e:
                logger.warning("Cannot read gold %s: %s", p, e)
        cur += timedelta(days=1)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _load_kline_close(data_root: Path) -> pd.DataFrame:
    """Load all kline close prices as a (date × symbol) pivot table."""
    try:
        import duckdb
        kline_glob = _resolve_kline_glob(data_root)
        con = duckdb.connect()
        df = con.execute(f"""
            SELECT symbol, date, close
            FROM read_parquet('{kline_glob}', union_by_name=true)
            WHERE close IS NOT NULL AND close > 0
        """).df()
        con.close()
    except Exception as e:
        logger.warning("DuckDB kline load failed: %s", e)
        return pd.DataFrame()

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"]).dt.date
    pivot = df.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    return pivot


def _spearman_ic(sentiment: pd.Series, returns: pd.Series) -> Optional[float]:
    """Compute Spearman rank correlation between sentiment and returns.

    Returns None if there are fewer than _MIN_STOCKS_PER_DAY valid pairs.
    """
    aligned = pd.concat([sentiment, returns], axis=1).dropna()
    if len(aligned) < _MIN_STOCKS_PER_DAY:
        return None
    s_rank = aligned.iloc[:, 0].rank()
    r_rank = aligned.iloc[:, 1].rank()
    n = len(aligned)
    cov = ((s_rank - s_rank.mean()) * (r_rank - r_rank.mean())).sum()
    denom = math.sqrt(((s_rank - s_rank.mean()) ** 2).sum()
                      * ((r_rank - r_rank.mean()) ** 2).sum())
    if denom == 0:
        return None
    return float(cov / denom)


def compute_ic(
    data_root: str | Path = "data",
    lookback: int = 60,
    forward_days: int = 5,
    by_source: bool = False,
) -> dict:
    """Compute sentiment IC statistics.

    Args:
        data_root:    Root data directory.
        lookback:     Number of calendar days to look back for Gold data.
        forward_days: Number of trading days ahead for forward return.
        by_source:    If True, also compute per-source IC breakdown.

    Returns:
        Dict with keys: valid_days, skipped_days, mean_ic, ic_positive_rate,
        ir, t_stat, significant, rolling_10d, rolling_30d, rolling_60d,
        and optionally by_source dict.
    """
    data_root = Path(data_root)
    end = date.today()
    start = end - timedelta(days=lookback)

    gold_df = _load_gold(data_root, start, end)
    if gold_df.empty:
        return {"error": "No Gold data found", "valid_days": 0}

    # Exclude market-level rows
    gold_df = gold_df[gold_df["symbol"] != "_MARKET_"]
    if gold_df.empty:
        return {"error": "No symbol-level Gold data", "valid_days": 0}

    gold_df["date"] = pd.to_datetime(gold_df["date"]).dt.date

    kline_pivot = _load_kline_close(data_root)
    if kline_pivot.empty:
        return {"error": "No kline data found", "valid_days": 0}

    # Compute forward returns: return[d] = close[d+N]/close[d] - 1
    # NaN for the most recent forward_days rows (future not yet known)
    fwd_pivot = (kline_pivot.shift(-forward_days) / kline_pivot - 1.0)

    trading_dates = sorted(gold_df["date"].unique())
    ic_series: list[float] = []
    date_series: list[date] = []
    skipped = 0
    skip_reasons = {
        "missing_net_sentiment": 0,
        "missing_forward_window": 0,
        "too_few_pairs": 0,
    }

    for d in trading_dates:
        day_gold = gold_df[gold_df["date"] == d].set_index("symbol")
        if "net_sentiment" not in day_gold.columns:
            skipped += 1
            skip_reasons["missing_net_sentiment"] += 1
            continue
        sentiment_s = day_gold["net_sentiment"].dropna()

        # Filter out suspended stocks (no close on this date)
        if d not in fwd_pivot.index:
            skipped += 1
            skip_reasons["missing_forward_window"] += 1
            continue

        fwd_row = fwd_pivot.loc[d]
        # Exclude zero-volume / suspended: if close == 0 on that day
        if d in kline_pivot.index:
            close_row = kline_pivot.loc[d]
            active_syms = close_row[close_row > 0].index
            fwd_row = fwd_row[fwd_row.index.isin(active_syms)]

        ic = _spearman_ic(sentiment_s, fwd_row)
        if ic is None:
            skipped += 1
            if fwd_row.notna().sum() == 0:
                skip_reasons["missing_forward_window"] += 1
            else:
                skip_reasons["too_few_pairs"] += 1
            continue

        ic_series.append(ic)
        date_series.append(d)

    if len(ic_series) < _MIN_VALID_DAYS:
        latest_gold_date = max(trading_dates) if trading_dates else None
        fwd_ready_dates = [d for d in fwd_pivot.index if fwd_pivot.loc[d].notna().sum() > 0]
        latest_fwd_ready_date = max(fwd_ready_dates) if fwd_ready_dates else None
        return {
            "valid_days": len(ic_series),
            "skipped_days": skipped,
            "error": f"Insufficient data: need {_MIN_VALID_DAYS}+ valid days, got {len(ic_series)}",
            "diagnostics": {
                "gold_days": len(trading_dates),
                "latest_gold_date": latest_gold_date.isoformat() if latest_gold_date else None,
                "latest_fwd_ready_date": latest_fwd_ready_date.isoformat() if latest_fwd_ready_date else None,
                "skip_reasons": skip_reasons,
            },
        }

    ic_arr = np.array(ic_series)
    mean_ic = float(np.mean(ic_arr))
    std_ic = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else float("nan")
    ir = mean_ic / std_ic if std_ic > 0 else float("nan")
    t_stat = mean_ic * math.sqrt(len(ic_arr)) / std_ic if std_ic > 0 else float("nan")
    ic_pos_rate = float((ic_arr > 0).mean())

    # Rolling ICs
    def _tail_mean(n: int) -> Optional[float]:
        tail = ic_arr[-n:]
        return float(np.mean(tail)) if len(tail) > 0 else None

    result: dict = {
        "lookback_days": lookback,
        "forward_days": forward_days,
        "valid_days": len(ic_series),
        "skipped_days": skipped,
        "mean_ic": round(mean_ic, 4),
        "std_ic": round(std_ic, 4),
        "ic_positive_rate": round(ic_pos_rate, 3),
        "ir": round(ir, 3) if not math.isnan(ir) else None,
        "t_stat": round(t_stat, 3) if not math.isnan(t_stat) else None,
        "significant": bool(not math.isnan(t_stat) and abs(t_stat) > 1.96),
        "rolling_10d": round(_tail_mean(10), 4) if _tail_mean(10) is not None else None,
        "rolling_30d": round(_tail_mean(30), 4) if _tail_mean(30) is not None else None,
        "rolling_60d": round(_tail_mean(60), 4) if _tail_mean(60) is not None else None,
    }

    if by_source:
        result["by_source"] = _compute_by_source_ic(
            data_root, start, end, kline_pivot, fwd_pivot, forward_days
        )

    return result


def _compute_by_source_ic(
    data_root: Path,
    start: date,
    end: date,
    kline_pivot: pd.DataFrame,
    fwd_pivot: pd.DataFrame,
    forward_days: int,
) -> dict[str, Optional[float]]:
    """Compute IC broken down by Silver source (rss, cls, gdelt)."""
    silver_dir = data_root / "sentiment" / "silver"
    if not silver_dir.exists():
        return {}

    try:
        import duckdb
        silver_glob = str(silver_dir / "**" / "*.parquet")
        con = duckdb.connect()
        silver_df = con.execute(f"""
            SELECT symbol, date, source, sentiment_score, sentiment_label
            FROM read_parquet('{silver_glob}', union_by_name=true)
            WHERE date >= '{start.isoformat()}' AND date <= '{end.isoformat()}'
              AND symbol != '_MARKET_'
        """).df()
        con.close()
    except Exception as e:
        logger.warning("Cannot load silver for by-source IC: %s", e)
        return {}

    if silver_df.empty or "source" not in silver_df.columns:
        return {}

    silver_df["date"] = pd.to_datetime(silver_df["date"]).dt.date
    sources = silver_df["source"].dropna().unique().tolist()

    source_ic: dict[str, Optional[float]] = {}
    for src in sorted(sources):
        src_df = silver_df[silver_df["source"] == src]
        # Aggregate per (date, symbol): net_sentiment
        agg = (src_df.groupby(["date", "symbol"])["sentiment_label"]
               .apply(lambda labels: float(
                   ((labels == "positive").sum() - (labels == "negative").sum()) / max(len(labels), 1)
               )).reset_index(name="net_sentiment"))

        ic_vals: list[float] = []
        for d, grp in agg.groupby("date"):
            if d not in fwd_pivot.index:
                continue
            sentiment_s = grp.set_index("symbol")["net_sentiment"]
            fwd_row = fwd_pivot.loc[d]
            if d in kline_pivot.index:
                active = kline_pivot.loc[d]
                active_syms = active[active > 0].index
                fwd_row = fwd_row[fwd_row.index.isin(active_syms)]
            ic = _spearman_ic(sentiment_s, fwd_row)
            if ic is not None:
                ic_vals.append(ic)

        source_ic[src] = round(float(np.mean(ic_vals)), 4) if ic_vals else None

    return source_ic


def compute_ic_decay(
    data_root: str | Path = "data",
    factor_col: str = "net_sentiment",
    horizons: list[int] | None = None,
    lookback: int = 120,
) -> dict[int, dict]:
    """Compute IC at multiple forward horizons to analyse factor decay.

    Args:
        data_root:  Root data directory.
        factor_col: Column name in Gold layer to use as factor signal.
        horizons:   List of forward trading-day windows. Default: [1, 5, 10, 20, 60].
        lookback:   Calendar days of Gold data to look back.

    Returns:
        Dict[horizon → IC stats dict] with keys: mean_ic, ic_positive_rate, ir, t_stat, valid_days.
    """
    if horizons is None:
        horizons = [1, 5, 10, 20, 60]

    data_root = Path(data_root)
    end = date.today()
    start = end - timedelta(days=lookback)

    gold_df = _load_gold(data_root, start, end)
    if gold_df.empty:
        return {h: {"error": "No Gold data"} for h in horizons}

    gold_df = gold_df[gold_df["symbol"] != "_MARKET_"]
    if factor_col not in gold_df.columns:
        return {h: {"error": f"Column {factor_col!r} not in Gold data"} for h in horizons}

    gold_df["date"] = pd.to_datetime(gold_df["date"]).dt.date

    kline_pivot = _load_kline_close(data_root)
    if kline_pivot.empty:
        return {h: {"error": "No kline data"} for h in horizons}

    results: dict[int, dict] = {}
    for horizon in horizons:
        fwd_pivot = kline_pivot.shift(-horizon) / kline_pivot - 1.0
        trading_dates = sorted(gold_df["date"].unique())
        ic_series: list[float] = []

        for d in trading_dates:
            day_gold = gold_df[gold_df["date"] == d].set_index("symbol")
            factor_s = day_gold[factor_col].dropna()
            if d not in fwd_pivot.index:
                continue
            fwd_row = fwd_pivot.loc[d]
            if d in kline_pivot.index:
                active = kline_pivot.loc[d]
                fwd_row = fwd_row[fwd_row.index.isin(active[active > 0].index)]
            ic = _spearman_ic(factor_s, fwd_row)
            if ic is not None:
                ic_series.append(ic)

        if not ic_series:
            results[horizon] = {"valid_days": 0, "error": "Insufficient data"}
            continue

        ic_arr = np.array(ic_series)
        mean_ic = float(np.mean(ic_arr))
        std_ic = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else float("nan")
        ir = mean_ic / std_ic if std_ic > 0 else float("nan")
        t_stat = mean_ic * math.sqrt(len(ic_arr)) / std_ic if std_ic > 0 else float("nan")
        results[horizon] = {
            "horizon":          horizon,
            "valid_days":       len(ic_series),
            "mean_ic":          round(mean_ic, 4),
            "ic_positive_rate": round(float((ic_arr > 0).mean()), 3),
            "ir":               round(ir, 3) if not math.isnan(ir) else None,
            "t_stat":           round(t_stat, 3) if not math.isnan(t_stat) else None,
            "significant":      bool(not math.isnan(t_stat) and abs(t_stat) > 1.96),
        }

    return results


def format_ic_decay_report(decay: dict[int, dict], factor_col: str = "net_sentiment") -> str:
    """Format IC decay dict as a human-readable table."""
    lines = [
        f"\n因子衰减分析: {factor_col}",
        "─" * 52,
        f"{'窗口':>6} {'均值IC':>8} {'IC>0%':>7} {'IR':>7} {'t统计':>7} {'显著'}",
        "─" * 52,
    ]
    for horizon in sorted(decay):
        r = decay[horizon]
        if "error" in r:
            lines.append(f"{horizon:>5}d  {'[无数据]'}")
            continue
        sig = "✅" if r.get("significant") else "  "
        lines.append(
            f"{horizon:>5}d"
            f"  {r.get('mean_ic', 'N/A'):>8.4f}"
            f"  {r.get('ic_positive_rate', 0):>6.1%}"
            f"  {r.get('ir') or 0:>7.3f}"
            f"  {r.get('t_stat') or 0:>7.3f}"
            f"  {sig}"
        )
    lines.append("─" * 52)
    return "\n".join(lines)


def format_ic_report(result: dict) -> str:
    """Format IC result dict as a human-readable report string."""
    if "error" in result and result.get("valid_days", 0) == 0:
        lines = [f"IC Analysis: {result['error']}"]
        diag = result.get("diagnostics", {})
        if isinstance(diag, dict) and diag:
            lines.append(
                "  diagnostics: "
                f"gold_days={diag.get('gold_days', '?')}, "
                f"latest_gold_date={diag.get('latest_gold_date', '?')}, "
                f"latest_fwd_ready_date={diag.get('latest_fwd_ready_date', '?')}"
            )
            reasons = diag.get("skip_reasons", {})
            if isinstance(reasons, dict):
                lines.append(
                    "  skip_reasons: "
                    f"missing_forward_window={reasons.get('missing_forward_window', 0)}, "
                    f"too_few_pairs={reasons.get('too_few_pairs', 0)}, "
                    f"missing_net_sentiment={reasons.get('missing_net_sentiment', 0)}"
                )
        return "\n".join(lines)

    lines = [
        f"\n情绪IC分析 (lookback={result.get('lookback_days','?')}d, "
        f"forward={result.get('forward_days','?')}d)",
        "─" * 45,
        f"有效交易日   : {result['valid_days']} 天"
        f"（{result.get('skipped_days',0)}天样本不足被跳过）",
        "",
        "整体 IC 统计:",
        f"  均值 IC      : {result.get('mean_ic', 'N/A'):>8}",
        f"  IC>0 占比    : {result.get('ic_positive_rate', 'N/A'):>7.1%}"
        if isinstance(result.get('ic_positive_rate'), float) else
        f"  IC>0 占比    : N/A",
        f"  IR           : {result.get('ir', 'N/A'):>8}",
        f"  t统计量      : {result.get('t_stat', 'N/A'):>8}",
        f"  结论         : {'✅ 情绪信号有显著预测力' if result.get('significant') else '⚠️  信号尚不显著'}",
        "",
        "滚动IC:",
        f"  最近10天 IC  : {result.get('rolling_10d', 'N/A')}",
        f"  最近30天 IC  : {result.get('rolling_30d', 'N/A')}",
        f"  最近60天 IC  : {result.get('rolling_60d', 'N/A')}",
    ]

    if "by_source" in result and result["by_source"]:
        lines.append("")
        lines.append("分数据源 IC:")
        for src, ic in result["by_source"].items():
            ic_str = f"{ic:.4f}" if ic is not None else "N/A"
            lines.append(f"  {src:<15} IC = {ic_str}")

    return "\n".join(lines)
