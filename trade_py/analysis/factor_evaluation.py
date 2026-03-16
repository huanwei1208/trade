from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trade_py.analysis.propagation_runtime import FEATURE_COLS
from trade_py.db.trade_db import TradeDB


def _feature_path(data_root: str | Path) -> Path:
    return Path(data_root) / "events" / "features.parquet"


def _load_feature_frame(
    data_root: str | Path,
    *,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    path = _feature_path(data_root)
    if not path.exists():
        raise FileNotFoundError(f"features.parquet not found: {path}")
    df = pd.read_parquet(path)
    if "event_date" in df.columns:
        df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if start and "event_date" in df.columns:
        df = df[df["event_date"] >= start]
    if end and "event_date" in df.columns:
        df = df[df["event_date"] <= end]
    return df.reset_index(drop=True)


def _resolve_target(frame: pd.DataFrame, target: str) -> tuple[pd.DataFrame, str]:
    if target == "risk_5pct":
        if "actual_return_5d" not in frame.columns:
            raise ValueError("features.parquet missing actual_return_5d; cannot derive risk_5pct")
        work = frame.copy()
        ret_5d = pd.to_numeric(work["actual_return_5d"], errors="coerce")
        work["_factor_target"] = np.where(ret_5d.notna(), (ret_5d < -0.05).astype(float), np.nan)
        return work, "_factor_target"
    if target not in frame.columns:
        raise ValueError(f"features.parquet missing target column: {target}")
    return frame, target


def _rank_ic_by_group(
    frame: pd.DataFrame,
    score_col: str,
    target_col: str,
    *,
    group_col: str = "event_date",
    min_rows: int = 8,
) -> tuple[float | None, int]:
    valid_scores: list[float] = []
    if group_col not in frame.columns:
        return None, 0
    for _, group in frame.groupby(group_col):
        work = group[[score_col, target_col]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(work) < min_rows:
            continue
        if work[score_col].nunique() < 2 or work[target_col].nunique() < 2:
            continue
        score_rank = work[score_col].rank(method="average")
        target_rank = work[target_col].rank(method="average")
        corr = float(score_rank.corr(target_rank))
        if np.isnan(corr):
            continue
        valid_scores.append(corr)
    if not valid_scores:
        return None, 0
    return round(float(np.mean(valid_scores)), 4), len(valid_scores)


def factor_status(data_root: str | Path) -> dict[str, Any]:
    db = TradeDB(data_root)
    conn = db._conn
    latest_date_row = conn.execute("SELECT MAX(date) AS latest_date FROM factors").fetchone()
    latest_date = latest_date_row["latest_date"] if latest_date_row else None

    totals = conn.execute(
        """
        SELECT COUNT(*) AS total_rows,
               COUNT(DISTINCT date) AS date_count,
               COUNT(DISTINCT symbol) AS symbol_count,
               COUNT(DISTINCT factor_name) AS factor_count
        FROM factors
        """
    ).fetchone()
    registry_rows = db.factor_registry_list()

    type_rows = conn.execute(
        """
        SELECT factor_type,
               COUNT(*) AS row_count,
               COUNT(DISTINCT factor_name) AS factor_count,
               COUNT(DISTINCT symbol) AS symbol_count
        FROM factors
        GROUP BY factor_type
        ORDER BY factor_type
        """
    ).fetchall()
    latest_rows = []
    if latest_date:
        latest_rows = conn.execute(
            """
            SELECT factor_type,
                   COUNT(*) AS row_count,
                   COUNT(DISTINCT factor_name) AS factor_count,
                   COUNT(DISTINCT symbol) AS symbol_count
            FROM factors
            WHERE date = ?
            GROUP BY factor_type
            ORDER BY factor_type
            """,
            (latest_date,),
        ).fetchall()
    registry_by_type = conn.execute(
        """
        SELECT factor_type, COUNT(*) AS registry_count
        FROM factor_registry
        GROUP BY factor_type
        ORDER BY factor_type
        """
    ).fetchall()

    return {
        "latest_date": latest_date,
        "total_rows": int(totals["total_rows"] or 0) if totals else 0,
        "date_count": int(totals["date_count"] or 0) if totals else 0,
        "symbol_count": int(totals["symbol_count"] or 0) if totals else 0,
        "factor_count": int(totals["factor_count"] or 0) if totals else 0,
        "registry_count": len(registry_rows),
        "rows_by_type": [dict(row) for row in type_rows],
        "latest_rows_by_type": [dict(row) for row in latest_rows],
        "registry_by_type": [dict(row) for row in registry_by_type],
    }


def factor_metrics(
    data_root: str | Path,
    *,
    target: str = "actual_return_5d",
    start: str | None = None,
    end: str | None = None,
    factor_type: str | None = None,
    factor_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    db = TradeDB(data_root)
    registry_rows = db.factor_registry_list(factor_type=factor_type)
    registry_map = {row["factor_name"]: row for row in registry_rows}
    candidate_names = factor_names or [row["factor_name"] for row in registry_rows]
    if not candidate_names:
        candidate_names = list(FEATURE_COLS)

    frame = _load_feature_frame(data_root, start=start, end=end)
    frame, target_col = _resolve_target(frame, target)

    rows: list[dict[str, Any]] = []
    for factor_name in candidate_names:
        if factor_name not in frame.columns:
            continue
        series = pd.to_numeric(frame[factor_name], errors="coerce")
        coverage = float(series.notna().mean()) if len(series) else 0.0
        non_null = int(series.notna().sum())
        if non_null == 0:
            continue
        work = frame[[target_col, "event_date"]].copy() if "event_date" in frame.columns else frame[[target_col]].copy()
        work[factor_name] = series
        clean = work.replace([np.inf, -np.inf], np.nan).dropna(subset=[factor_name, target_col])
        rank_ic, valid_days = _rank_ic_by_group(clean, factor_name, target_col)
        pearson = None
        if len(clean) >= 8 and clean[factor_name].nunique() >= 2 and clean[target_col].nunique() >= 2:
            corr = float(clean[factor_name].corr(clean[target_col]))
            pearson = None if np.isnan(corr) else round(corr, 4)
        spec = registry_map.get(factor_name, {})
        rows.append(
            {
                "factor_name": factor_name,
                "factor_type": spec.get("factor_type", "unknown"),
                "factor_layer": spec.get("factor_layer", "unknown"),
                "coverage": round(coverage, 4),
                "non_null_rows": non_null,
                "mean_abs": round(float(series.abs().mean(skipna=True)), 4),
                "std": round(float(series.std(skipna=True) or 0.0), 4),
                "rank_ic": rank_ic,
                "pearson": pearson,
                "valid_days": valid_days,
                "target": target,
            }
        )
    rows.sort(
        key=lambda item: (
            abs(float(item["rank_ic"])) if item["rank_ic"] is not None else -1.0,
            float(item["coverage"]),
            item["factor_name"],
        ),
        reverse=True,
    )
    return rows
