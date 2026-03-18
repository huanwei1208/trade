"""Gold-layer EMA/Kalman smoothing for sentiment time series.

Provides denoising for the daily per-symbol/date Gold sentiment aggregation,
reducing noise from individual article-level fluctuations.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def ema_smooth(series: list[float], alpha: float = 0.3) -> list[float]:
    """Apply Exponential Moving Average smoothing to a time series.

    Args:
        series: list of float values in chronological order
        alpha:  EMA smoothing factor in (0, 1]; higher = more reactive

    Returns:
        List of smoothed values, same length as input.
    """
    if not series:
        return []
    result: list[float] = []
    ema = series[0]
    for val in series:
        ema = alpha * val + (1.0 - alpha) * ema
        result.append(round(ema, 6))
    return result


def smooth_gold_sentiment(
    asof_date: str | None = None,
    data_root: str | None = None,
    alpha: float = 0.3,
    lookback_days: int = 30,
) -> dict[str, Any]:
    """Read Gold parquet files for [asof_date - lookback, asof_date], apply EMA smoothing.

    Writes back the smoothed net_sentiment column to the Gold parquet files.
    No-op if Gold files don't exist yet.

    Args:
        asof_date:     target date (YYYY-MM-DD)
        data_root:     path to data root
        alpha:         EMA alpha parameter (default 0.3)
        lookback_days: how many days of history to smooth over

    Returns:
        dict with smoothed_symbols count and summary.
    """
    import pandas as pd
    from datetime import date, timedelta
    from trade_py.infra.settings import default_data_root

    _data_root = Path(data_root or str(default_data_root()))
    _asof = date.fromisoformat(asof_date) if asof_date else date.today()

    gold_root = _data_root / "sentiment" / "gold"
    if not gold_root.exists():
        return {"smoothed_symbols": 0, "summary": "Gold root not found"}

    # Collect all Gold parquet files in the lookback window
    dates = [
        (_asof - timedelta(days=i)).isoformat()
        for i in range(lookback_days)
    ]
    files_by_date: dict[str, Path] = {}
    for d in reversed(dates):  # chronological order
        year, month, _ = d.split("-")
        p = gold_root / year / month / f"{d}.parquet"
        if p.exists():
            files_by_date[d] = p

    if not files_by_date:
        return {"smoothed_symbols": 0, "summary": "No Gold files in window"}

    # Load all files, group by symbol, apply EMA to net_sentiment
    frames: list[pd.DataFrame] = []
    for d, p in files_by_date.items():
        try:
            df = pd.read_parquet(p)
            df["_date"] = d
            frames.append(df)
        except Exception:
            pass

    if not frames:
        return {"smoothed_symbols": 0, "summary": "Could not read Gold files"}

    all_df = pd.concat(frames, ignore_index=True)
    if "net_sentiment" not in all_df.columns or "symbol" not in all_df.columns:
        return {"smoothed_symbols": 0, "summary": "Missing net_sentiment or symbol column"}

    all_df = all_df.sort_values(["symbol", "_date"])
    all_df["net_sentiment_smooth"] = (
        all_df.groupby("symbol")["net_sentiment"]
        .transform(lambda s: pd.Series(ema_smooth(s.tolist(), alpha), index=s.index))
    )

    # Write back smoothed column to the most recent Gold file
    target_date = max(files_by_date.keys())
    target_path = files_by_date[target_date]
    today_rows = all_df[all_df["_date"] == target_date].drop(columns=["_date"])
    smoothed_symbols = int(today_rows["symbol"].nunique()) if "symbol" in today_rows.columns else 0

    try:
        today_rows.to_parquet(target_path, index=False)
    except Exception as exc:
        return {
            "smoothed_symbols": smoothed_symbols,
            "summary": f"EMA smoothed {smoothed_symbols} symbols but write failed: {exc}",
        }

    return {
        "smoothed_symbols": smoothed_symbols,
        "summary": f"EMA(α={alpha}) smoothed net_sentiment for {smoothed_symbols} symbols on {target_date}",
    }
