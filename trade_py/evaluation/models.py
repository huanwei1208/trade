"""Model evaluation: IC, MAE, hit rate, and Brier score against feature store."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trade_py.analysis.propagation_runtime import FEATURE_COLS
from trade_py.db.trade_db import TradeDB
from trade_py.infra.settings import default_data_root
from trade_py.evaluation.utils import (
    EvalOutcome,
    _brier_score,
    _cached_model_outcome,
    _calibration_bins,
    _coverage_ratio,
    _instrument_total,
    _rank_ic_by_group,
    _safe_float,
    _safe_int,
    _sector_concentration,
    _topk_hit_rate,
    resolve_eval_date,
)

logger = logging.getLogger(__name__)


def _load_feature_frame(data_root: str, eval_date: str,
                        start_date: str | None = None,
                        end_date: str | None = None) -> pd.DataFrame:
    path = Path(data_root) / "events" / "features.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if "event_date" in df.columns:
        df["event_date"] = df["event_date"].astype(str).str.slice(0, 10)
        df = df[df["event_date"] <= eval_date].copy()
        if start_date:
            df = df[df["event_date"] >= start_date].copy()
        if end_date:
            df = df[df["event_date"] <= end_date].copy()
    return df


def _model_feature_matrix(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    available = [col for col in feature_cols if col in df.columns]
    return df[available].fillna(0.0).astype(np.float32)


def _model_version(row: dict[str, Any]) -> str:
    if row.get("trained_at"):
        return f"{row.get('id', 'model')}@{row['trained_at']}"
    return str(row.get("id", "model"))


def _latest_model_eval(db: TradeDB, eval_date: str, model_name: str) -> dict[str, Any] | None:
    rows = db.model_eval_list(eval_date=eval_date, model_name=model_name)
    return rows[0] if rows else None


def _dataset_snapshot(data_root: str, eval_date: str,
                      start_date: str | None = None,
                      metadata_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    db = TradeDB(data_root)
    features_path = Path(data_root) / "events" / "features.parquet"
    instrument_total = _instrument_total(data_root)
    feature_rows = labeled_rows_5d = labeled_rows_20d = 0
    if features_path.exists():
        df = pd.read_parquet(features_path)
        if "event_date" in df.columns:
            df["event_date"] = df["event_date"].astype(str).str.slice(0, 10)
            df = df[df["event_date"] <= eval_date]
            if start_date:
                df = df[df["event_date"] >= start_date]
        feature_rows = int(len(df))
        labeled_rows_5d = int(df["actual_return_5d"].notna().sum()) if "actual_return_5d" in df.columns else 0
        labeled_rows_20d = int(df["actual_return_20d"].notna().sum()) if "actual_return_20d" in df.columns else 0
    signal_dates = _safe_int(db._conn.execute("SELECT COUNT(DISTINCT date) FROM signals").fetchone()[0], 0)
    source_count = _safe_int(db._conn.execute(
        "SELECT COUNT(DISTINCT source_name) FROM source_eval_daily WHERE eval_date=?",
        (eval_date,),
    ).fetchone()[0], 0)
    event_row = db._conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT me.event_id) FROM event_propagations ep JOIN market_events me ON me.event_id = ep.event_id WHERE me.event_date <= ?",
        (eval_date,),
    ).fetchone()
    propagation_count = _safe_int(event_row[0], 0) if event_row else 0
    event_count = _safe_int(event_row[1], 0) if event_row else 0
    metadata: dict[str, Any] = {
        "instrument_total": instrument_total,
        "fund_flow_coverage": _coverage_ratio(Path(data_root) / "market" / "fund_flow", instrument_total),
        "fundamental_coverage": _coverage_ratio(Path(data_root) / "market" / "fundamental", instrument_total),
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    return {
        "snapshot_name": "daily",
        "eval_date": eval_date,
        "start_date": start_date,
        "end_date": eval_date,
        "source_count": source_count,
        "market_event_count": event_count,
        "propagation_count": propagation_count,
        "feature_rows": feature_rows,
        "labeled_rows_5d": labeled_rows_5d,
        "labeled_rows_20d": labeled_rows_20d,
        "signal_dates": signal_dates,
        "metadata_json": metadata,
    }


def evaluate_models(data_root: str = str(default_data_root()),
                    eval_date: str | None = None,
                    start_date: str | None = None,
                    end_date: str | None = None,
                    persist: bool = True,
                    use_cache: bool = True) -> EvalOutcome:
    target_date = resolve_eval_date(data_root, eval_date)
    db = TradeDB(data_root)
    persist = persist and not (start_date or end_date)
    if use_cache and not start_date and not end_date:
        cached = _cached_model_outcome(db, target_date)
        if cached is not None:
            return cached
    df = _load_feature_frame(data_root, target_date, start_date, end_date)
    if df.empty:
        return EvalOutcome(
            status="blocked_by_dependency",
            summary="model eval skipped: features.parquet missing or empty",
            payload={"eval_date": target_date, "rows": []},
        )

    metrics_rows: list[dict[str, Any]] = []
    model_rows = [
        row
        for row in db.model_registry_list()
        if int(row.get("is_active", 0) or 0) == 1 or str(row.get("promotion_state", "")) == "active"
    ]
    if not model_rows:
        return EvalOutcome(
            status="blocked_by_dependency",
            summary="model eval skipped: no active models",
            payload={"eval_date": target_date, "rows": []},
        )

    try:
        import joblib
    except Exception as exc:
        return EvalOutcome(
            status="error",
            summary=f"model eval failed: joblib unavailable ({exc})",
            payload={"eval_date": target_date, "rows": []},
            exit_code=1,
        )

    baseline_direction = np.sign(pd.to_numeric(df.get("net_sentiment"), errors="coerce").fillna(0.0))
    kg_direction = np.sign(pd.to_numeric(df.get("kg_score"), errors="coerce").fillna(0.0))
    baseline_direction = np.where(baseline_direction == 0, kg_direction, baseline_direction)
    baseline_direction = np.where(baseline_direction == 0, 1.0, baseline_direction)
    df["_baseline_event_only"] = pd.to_numeric(df.get("magnitude"), errors="coerce").fillna(0.0) * baseline_direction
    df["_baseline_static_kg"] = pd.to_numeric(df.get("kg_score"), errors="coerce").fillna(0.0)

    overall_status = "ok"
    for row in model_rows:
        model_name = str(row.get("target_name") or row["model_name"])
        file_path = Path(str(row["file_path"]))
        if not file_path.exists():
            metrics_rows.append({
                "eval_date": target_date,
                "model_name": model_name,
                "target_name": model_name,
                "model_version": _model_version(row),
                "status": "blocked_by_dependency",
                "sample_count": 0,
                "valid_days": 0,
                "rank_ic": None,
                "mae": None,
                "topk_hit_rate": None,
                "sector_concentration": None,
                "risk_brier_score": None,
                "baseline_json": {},
                "calibration_json": [],
                "details_json": {"reason": f"missing model file {file_path}"},
            })
            overall_status = "partial"
            continue

        model = joblib.load(file_path)
        feature_cols = FEATURE_COLS
        row_metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        if row_metrics and row_metrics.get("feature_cols"):
            feature_cols = list(row_metrics["feature_cols"])

        target_col = "actual_return_5d" if "5d" in model_name else "actual_return_20d" if "20d" in model_name else "actual_return_5d"
        work = df.dropna(subset=[target_col]).copy()
        if work.empty:
            metrics_rows.append({
                "eval_date": target_date,
                "model_name": model_name,
                "target_name": target_col,
                "model_version": _model_version(row),
                "status": "partial",
                "sample_count": 0,
                "valid_days": 0,
                "rank_ic": None,
                "mae": None,
                "topk_hit_rate": None,
                "sector_concentration": None,
                "risk_brier_score": None,
                "baseline_json": {},
                "calibration_json": [],
                "details_json": {"reason": f"no labeled rows for {target_col}"},
            })
            overall_status = "partial"
            continue

        X = _model_feature_matrix(work, feature_cols)
        if model_name == "kg_risk_5pct":
            if not hasattr(model, "predict_proba"):
                pred = pd.Series(model.predict(X), index=work.index, dtype=float)
            else:
                pred = pd.Series(model.predict_proba(X)[:, 1], index=work.index, dtype=float)
            actual = (work["actual_return_5d"] < -5.0).astype(float)
            brier = _brier_score(pred, actual)
            calibration = _calibration_bins(pred, actual)
            rank_ic, valid_days = _rank_ic_by_group(
                pd.DataFrame({"event_date": work["event_date"], "score": pred, "target": actual}),
                "score",
                "target",
            )
            model_row = {
                "eval_date": target_date,
                "model_name": model_name,
                "target_name": "risk_5pct",
                "model_version": _model_version(row),
                "status": "ok" if brier is not None else "partial",
                "sample_count": int(len(work)),
                "valid_days": valid_days,
                "rank_ic": round(rank_ic, 4) if rank_ic is not None else None,
                "mae": None,
                "topk_hit_rate": None,
                "sector_concentration": None,
                "risk_brier_score": round(brier, 4) if brier is not None else None,
                "baseline_json": {},
                "calibration_json": calibration,
                "details_json": {"positive_rate": round(float(actual.mean()), 4)},
            }
        else:
            pred = pd.Series(model.predict(X), index=work.index, dtype=float)
            work["_model_pred"] = pred
            rank_ic, valid_days = _rank_ic_by_group(work, "_model_pred", target_col)
            mae = float(np.mean(np.abs(work[target_col] - work["_model_pred"])))
            topk = _topk_hit_rate(work, "_model_pred", target_col)
            sector_conc = _sector_concentration(work, "_model_pred")
            event_only_ic, _ = _rank_ic_by_group(work.assign(_pred=work["_baseline_event_only"]), "_pred", target_col)
            static_kg_ic, _ = _rank_ic_by_group(work.assign(_pred=work["_baseline_static_kg"]), "_pred", target_col)
            best_baseline = max(v for v in [event_only_ic, static_kg_ic] if v is not None) if any(v is not None for v in [event_only_ic, static_kg_ic]) else None
            model_row = {
                "eval_date": target_date,
                "model_name": model_name,
                "target_name": target_col,
                "model_version": _model_version(row),
                "status": "ok" if rank_ic is not None else "partial",
                "sample_count": int(len(work)),
                "valid_days": valid_days,
                "rank_ic": round(rank_ic, 4) if rank_ic is not None else None,
                "mae": round(mae, 4),
                "topk_hit_rate": round(topk, 4) if topk is not None else None,
                "sector_concentration": round(sector_conc, 4) if sector_conc is not None else None,
                "risk_brier_score": None,
                "baseline_json": {
                    "event_only": {"rank_ic": round(event_only_ic, 4) if event_only_ic is not None else None},
                    "event_static_kg": {"rank_ic": round(static_kg_ic, 4) if static_kg_ic is not None else None},
                    "best_baseline_rank_ic": round(best_baseline, 4) if best_baseline is not None else None,
                    "baseline_delta": round((rank_ic - best_baseline), 4) if rank_ic is not None and best_baseline is not None else None,
                },
                "calibration_json": [],
                "details_json": {"feature_cols": feature_cols},
            }
        if model_row["status"] != "ok":
            overall_status = "partial"
        metrics_rows.append(model_row)

    if persist:
        for row in metrics_rows:
            db.model_eval_upsert(row)

    summary = (
        f"model eval {start_date or 'begin'}->{end_date or target_date}: "
        f"models={len(metrics_rows)}, status={overall_status}"
    )
    return EvalOutcome(status=overall_status, summary=summary, payload={"eval_date": target_date, "rows": metrics_rows})
