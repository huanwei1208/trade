from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _read_local_kline(data_root: str | Path, symbol: str):
    import pandas as pd

    kline_root = Path(data_root) / "market" / "kline"
    symbol_file = f"{symbol.replace('.', '_')}.parquet"
    flat_path = kline_root / symbol_file
    if flat_path.exists():
        try:
            return pd.read_parquet(flat_path)
        except Exception as exc:
            logger.warning("kline sparkline flat read failed: %s (%s)", flat_path, exc)

    frames = []
    for monthly_path in sorted(kline_root.glob(f"20??-??/{symbol_file}")):
        try:
            frames.append(pd.read_parquet(monthly_path))
        except Exception as exc:
            logger.warning(
                "kline sparkline monthly read failed: %s (%s)",
                monthly_path,
                exc,
            )
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def read_symbol_sparkline(
    data_root: str | Path,
    symbol: str,
    *,
    days: int = 12,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    import pandas as pd

    frame = _read_local_kline(data_root, symbol)
    if frame.empty or "close" not in frame.columns:
        return []

    date_column = "date" if "date" in frame.columns else "trade_date"
    if date_column not in frame.columns:
        return []

    limit = max(1, int(days))
    resolved_end = end_date or date.today()
    resolved_start = resolved_end - timedelta(days=max(14, limit * 3))
    points = frame[[date_column, "close"]].copy()
    points["date"] = pd.to_datetime(points[date_column], errors="coerce")
    points["close"] = pd.to_numeric(points["close"], errors="coerce")
    points = points.dropna(subset=["date", "close"])
    points = points[
        (points["date"].dt.date >= resolved_start) & (points["date"].dt.date <= resolved_end)
    ]
    points = points.drop_duplicates(subset=["date"], keep="last")
    points = points.sort_values("date").tail(limit)
    date_values = [str(value) for value in points["date"].dt.strftime("%Y-%m-%d").tolist()]
    close_values = [float(str(value)) for value in points["close"].tolist()]
    return [
        {
            "date": point_date,
            "close": close,
        }
        for point_date, close in zip(date_values, close_values, strict=True)
    ]
