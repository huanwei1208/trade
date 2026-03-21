"""Unified propagation-model training for LightGBM and backprop-based tabular NN."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trade_py.analysis.model_trainer import time_series_splits
from trade_py.analysis.propagation_runtime import FEATURE_COLS
from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

TARGET_SPECS = {
    "kg_return_5d": {
        "label_col": "actual_return_5d",
        "task": "regression",
        "min_rows": 100,
    },
    "kg_return_20d": {
        "label_col": "actual_return_20d",
        "task": "regression",
        "min_rows": 100,
    },
    "kg_risk_5pct": {
        "label_col": "label_risk_5pct",
        "task": "classification",
        "min_rows": 100,
        "min_positive": 20,
    },
}
TABULAR_NN_MAX_ROWS = 200_000


def _feature_path(data_root: str | Path) -> Path:
    return Path(data_root) / "events" / "features.parquet"


def _model_dir(data_root: str | Path) -> Path:
    return Path(data_root) / "models" / "propagation"


def _catboost_train_dir(data_root: str | Path, target_name: str) -> str:
    path = Path(data_root) / "catboost_info" / "propagation" / target_name
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _load_training_frame(data_root: str) -> pd.DataFrame:
    path = _feature_path(data_root)
    if not path.exists():
        raise FileNotFoundError(f"features.parquet not found: {path}")
    df = pd.read_parquet(path)
    if "actual_return_5d" in df.columns:
        df["label_risk_5pct"] = (pd.to_numeric(df["actual_return_5d"], errors="coerce") < -0.05).astype(float)
    else:
        df["label_risk_5pct"] = np.nan
    return df


def _available_features(df: pd.DataFrame) -> list[str]:
    return [col for col in FEATURE_COLS if col in df.columns]


def _rank_ic(pred: np.ndarray, target: np.ndarray) -> float | None:
    if len(pred) < 3 or len(target) < 3:
        return None
    if np.allclose(pred, pred[0]) or np.allclose(target, target[0]):
        return None
    return float(np.corrcoef(pred, target)[0, 1])


def _ensure_estimators(backend: str) -> None:
    if backend == "lgbm":
        import lightgbm  # noqa: F401
        import joblib  # noqa: F401
    elif backend == "xgboost":
        import xgboost  # noqa: F401
        import joblib  # noqa: F401
    elif backend == "catboost":
        import catboost  # noqa: F401
        import joblib  # noqa: F401
    elif backend == "tabular_nn":
        from sklearn.neural_network import MLPClassifier, MLPRegressor  # noqa: F401
        import joblib  # noqa: F401
    else:
        raise ValueError(f"Unknown backend: {backend}")


def _downsample_for_tabular_nn(work: pd.DataFrame, max_rows: int = TABULAR_NN_MAX_ROWS) -> pd.DataFrame:
    if len(work) <= max_rows:
        return work
    ordered = work.sort_values("event_date").reset_index(drop=True)
    recent_keep = min(len(ordered), max_rows // 2)
    recent = ordered.tail(recent_keep)
    remaining = ordered.iloc[:-recent_keep]
    if remaining.empty:
        return recent.reset_index(drop=True)
    random_keep = max_rows - len(recent)
    sampled = remaining.sample(min(len(remaining), random_keep), random_state=42)
    return (
        pd.concat([sampled, recent], ignore_index=True)
        .sort_values("event_date")
        .reset_index(drop=True)
    )


def _fallback_temporal_split(df: pd.DataFrame, date_col: str = "event_date") -> list[tuple[list[int], list[int]]]:
    dates = pd.to_datetime(df[date_col]).dt.normalize()
    unique_dates = sorted(dates.dropna().unique())
    if len(unique_dates) < 3:
        return [(df.index.tolist(), [])]
    cut = max(1, int(len(unique_dates) * 0.8))
    cut = min(cut, len(unique_dates) - 1)
    train_dates = set(unique_dates[:cut])
    val_dates = set(unique_dates[cut:])
    train_idx = df.index[dates.isin(train_dates)].tolist()
    val_idx = df.index[dates.isin(val_dates)].tolist()
    if not train_idx or not val_idx:
        return [(df.index.tolist(), [])]
    return [(train_idx, val_idx)]


def _train_lgbm(
    work: pd.DataFrame,
    feature_cols: list[str],
    target_name: str,
    spec: dict[str, Any],
    cv_splits: int,
) -> tuple[object, dict[str, Any]]:
    import lightgbm as lgb
    from sklearn.metrics import mean_absolute_error, roc_auc_score

    X_all = work[feature_cols].fillna(0.0).to_numpy(dtype=np.float32)
    y_all = (
        work[spec["label_col"]].astype(int).to_numpy(dtype=np.int32)
        if spec["task"] == "classification"
        else work[spec["label_col"]].to_numpy(dtype=np.float32)
    )
    splits = time_series_splits(work, date_col="event_date", n_splits=cv_splits)
    if not splits:
        splits = _fallback_temporal_split(work)

    scores: list[float] = []
    maes: list[float] = []
    for train_idx, val_idx in splits:
        if not val_idx:
            continue
        X_tr = X_all[train_idx]
        y_tr = y_all[train_idx]
        X_val = X_all[val_idx]
        y_val = y_all[val_idx]

        if spec["task"] == "regression":
            model = lgb.LGBMRegressor(
                n_estimators=300,
                learning_rate=0.05,
                max_depth=5,
                num_leaves=31,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                verbose=-1,
            )
            model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], callbacks=[lgb.early_stopping(20, verbose=False)])
            pred = model.predict(X_val)
            metric = _rank_ic(pred, y_val)
            if metric is not None:
                scores.append(metric)
            maes.append(float(mean_absolute_error(y_val, pred)))
        else:
            model = lgb.LGBMClassifier(
                n_estimators=300,
                learning_rate=0.05,
                max_depth=4,
                num_leaves=15,
                subsample=0.8,
                colsample_bytree=0.8,
                class_weight="balanced",
                random_state=42,
                verbose=-1,
            )
            model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], callbacks=[lgb.early_stopping(20, verbose=False)])
            if len(np.unique(y_val)) >= 2:
                scores.append(float(roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])))

    if spec["task"] == "regression":
        final = lgb.LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=5,
            num_leaves=31,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1,
        )
    else:
        final = lgb.LGBMClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=4,
            num_leaves=15,
            subsample=0.8,
            colsample_bytree=0.8,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
        )
    final.fit(X_all, y_all)
    metrics = {
        "backend": "lgbm",
        "target_name": target_name,
        "cv_metric": round(float(np.mean(scores)), 4) if scores else None,
        "cv_metric_name": "rank_ic" if spec["task"] == "regression" else "auc",
        "cv_mae": round(float(np.mean(maes)), 4) if maes else None,
        "train_rows": int(len(work)),
        "feature_cols": feature_cols,
    }
    return final, metrics


def _train_tabular_nn(
    work: pd.DataFrame,
    feature_cols: list[str],
    target_name: str,
    spec: dict[str, Any],
    cv_splits: int,
) -> tuple[object, dict[str, Any]]:
    from sklearn.metrics import mean_absolute_error, roc_auc_score
    from sklearn.neural_network import MLPClassifier, MLPRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    X_all = work[feature_cols].fillna(0.0).to_numpy(dtype=np.float32)
    y_all = (
        work[spec["label_col"]].astype(int).to_numpy(dtype=np.int32)
        if spec["task"] == "classification"
        else work[spec["label_col"]].to_numpy(dtype=np.float32)
    )
    splits = time_series_splits(work, date_col="event_date", n_splits=cv_splits)
    if not splits:
        splits = _fallback_temporal_split(work)

    scores: list[float] = []
    maes: list[float] = []
    for train_idx, val_idx in splits:
        if not val_idx:
            continue
        X_tr = X_all[train_idx]
        y_tr = y_all[train_idx]
        X_val = X_all[val_idx]
        y_val = y_all[val_idx]

        if spec["task"] == "regression":
            pipeline = Pipeline(
                [
                    ("scaler", StandardScaler()),
                    (
                        "model",
                        MLPRegressor(
                            hidden_layer_sizes=(256, 128, 64),
                            activation="relu",
                            solver="adam",
                            learning_rate_init=1e-3,
                            alpha=1e-4,
                            batch_size=min(256, max(32, len(train_idx))),
                            early_stopping=True,
                            n_iter_no_change=15,
                            max_iter=300,
                            random_state=42,
                        ),
                    ),
                ]
            )
            pipeline.fit(X_tr, y_tr)
            pred = pipeline.predict(X_val)
            metric = _rank_ic(pred, y_val)
            if metric is not None:
                scores.append(metric)
            maes.append(float(mean_absolute_error(y_val, pred)))
        else:
            pipeline = Pipeline(
                [
                    ("scaler", StandardScaler()),
                    (
                        "model",
                        MLPClassifier(
                            hidden_layer_sizes=(256, 128, 64),
                            activation="relu",
                            solver="adam",
                            learning_rate_init=1e-3,
                            alpha=1e-4,
                            batch_size=min(256, max(32, len(train_idx))),
                            early_stopping=True,
                            n_iter_no_change=15,
                            max_iter=300,
                            random_state=42,
                        ),
                    ),
                ]
            )
            pipeline.fit(X_tr, y_tr)
            if len(np.unique(y_val)) >= 2:
                scores.append(float(roc_auc_score(y_val, pipeline.predict_proba(X_val)[:, 1])))

    if spec["task"] == "regression":
        final = Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "model",
                    MLPRegressor(
                        hidden_layer_sizes=(256, 128, 64),
                        activation="relu",
                        solver="adam",
                        learning_rate_init=1e-3,
                        alpha=1e-4,
                        batch_size=min(256, max(32, len(work))),
                        early_stopping=True,
                        n_iter_no_change=15,
                        max_iter=300,
                        random_state=42,
                    ),
                ),
            ]
        )
    else:
        final = Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "model",
                    MLPClassifier(
                        hidden_layer_sizes=(256, 128, 64),
                        activation="relu",
                        solver="adam",
                        learning_rate_init=1e-3,
                        alpha=1e-4,
                        batch_size=min(256, max(32, len(work))),
                        early_stopping=True,
                        n_iter_no_change=15,
                        max_iter=300,
                        random_state=42,
                    ),
                ),
            ]
        )
    final.fit(X_all, y_all)
    metrics = {
        "backend": "tabular_nn",
        "target_name": target_name,
        "cv_metric": round(float(np.mean(scores)), 4) if scores else None,
        "cv_metric_name": "rank_ic" if spec["task"] == "regression" else "auc",
        "cv_mae": round(float(np.mean(maes)), 4) if maes else None,
        "train_rows": int(len(work)),
        "feature_cols": feature_cols,
    }
    return final, metrics


def _train_xgboost(
    work: pd.DataFrame,
    feature_cols: list[str],
    target_name: str,
    spec: dict[str, Any],
    cv_splits: int,
) -> tuple[object, dict[str, Any]]:
    from sklearn.metrics import mean_absolute_error, roc_auc_score
    import xgboost as xgb

    X_all = work[feature_cols].fillna(0.0).to_numpy(dtype=np.float32)
    y_all = (
        work[spec["label_col"]].astype(int).to_numpy(dtype=np.int32)
        if spec["task"] == "classification"
        else work[spec["label_col"]].to_numpy(dtype=np.float32)
    )
    splits = time_series_splits(work, date_col="event_date", n_splits=cv_splits)
    if not splits:
        splits = _fallback_temporal_split(work)

    scores: list[float] = []
    maes: list[float] = []
    for train_idx, val_idx in splits:
        if not val_idx:
            continue
        X_tr = X_all[train_idx]
        y_tr = y_all[train_idx]
        X_val = X_all[val_idx]
        y_val = y_all[val_idx]

        if spec["task"] == "regression":
            model = xgb.XGBRegressor(
                n_estimators=220,
                learning_rate=0.05,
                max_depth=5,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_lambda=1.0,
                random_state=42,
                tree_method="hist",
                n_jobs=min(8, max(1, (os.cpu_count() or 4))),
                objective="reg:squarederror",
                eval_metric="mae",
                verbosity=0,
            )
            model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
            pred = model.predict(X_val)
            metric = _rank_ic(pred, y_val)
            if metric is not None:
                scores.append(metric)
            maes.append(float(mean_absolute_error(y_val, pred)))
        else:
            model = xgb.XGBClassifier(
                n_estimators=180,
                learning_rate=0.05,
                max_depth=4,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_lambda=1.0,
                random_state=42,
                tree_method="hist",
                n_jobs=min(8, max(1, (os.cpu_count() or 4))),
                eval_metric="auc",
                verbosity=0,
            )
            model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
            if len(np.unique(y_val)) >= 2:
                scores.append(float(roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])))

    if spec["task"] == "regression":
        final = xgb.XGBRegressor(
            n_estimators=220,
            learning_rate=0.05,
            max_depth=5,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=42,
            tree_method="hist",
            n_jobs=min(8, max(1, (os.cpu_count() or 4))),
            objective="reg:squarederror",
            eval_metric="mae",
            verbosity=0,
        )
    else:
        final = xgb.XGBClassifier(
            n_estimators=180,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=42,
            tree_method="hist",
            n_jobs=min(8, max(1, (os.cpu_count() or 4))),
            eval_metric="auc",
            verbosity=0,
        )
    final.fit(X_all, y_all, verbose=False)
    metrics = {
        "backend": "xgboost",
        "target_name": target_name,
        "cv_metric": round(float(np.mean(scores)), 4) if scores else None,
        "cv_metric_name": "rank_ic" if spec["task"] == "regression" else "auc",
        "cv_mae": round(float(np.mean(maes)), 4) if maes else None,
        "train_rows": int(len(work)),
        "feature_cols": feature_cols,
    }
    return final, metrics


def _train_catboost(
    work: pd.DataFrame,
    feature_cols: list[str],
    target_name: str,
    spec: dict[str, Any],
    cv_splits: int,
    *,
    data_root: str,
) -> tuple[object, dict[str, Any]]:
    from sklearn.metrics import mean_absolute_error, roc_auc_score
    from catboost import CatBoostClassifier, CatBoostRegressor

    X_all = work[feature_cols].fillna(0.0).to_numpy(dtype=np.float32)
    y_all = (
        work[spec["label_col"]].astype(int).to_numpy(dtype=np.int32)
        if spec["task"] == "classification"
        else work[spec["label_col"]].to_numpy(dtype=np.float32)
    )
    splits = time_series_splits(work, date_col="event_date", n_splits=cv_splits)
    if not splits:
        splits = _fallback_temporal_split(work)

    scores: list[float] = []
    maes: list[float] = []
    for train_idx, val_idx in splits:
        if not val_idx:
            continue
        X_tr = X_all[train_idx]
        y_tr = y_all[train_idx]
        X_val = X_all[val_idx]
        y_val = y_all[val_idx]

        if spec["task"] == "regression":
            model = CatBoostRegressor(
                iterations=400,
                learning_rate=0.05,
                depth=6,
                loss_function="RMSE",
                eval_metric="MAE",
                random_seed=42,
                train_dir=_catboost_train_dir(data_root, target_name),
                verbose=False,
            )
            model.fit(X_tr, y_tr, eval_set=(X_val, y_val), use_best_model=True, verbose=False)
            pred = model.predict(X_val)
            metric = _rank_ic(pred, y_val)
            if metric is not None:
                scores.append(metric)
            maes.append(float(mean_absolute_error(y_val, pred)))
        else:
            model = CatBoostClassifier(
                iterations=400,
                learning_rate=0.05,
                depth=6,
                loss_function="Logloss",
                eval_metric="AUC",
                auto_class_weights="Balanced",
                random_seed=42,
                train_dir=_catboost_train_dir(data_root, target_name),
                verbose=False,
            )
            model.fit(X_tr, y_tr, eval_set=(X_val, y_val), use_best_model=True, verbose=False)
            if len(np.unique(y_val)) >= 2:
                scores.append(float(roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])))

    if spec["task"] == "regression":
        final = CatBoostRegressor(
            iterations=400,
            learning_rate=0.05,
            depth=6,
            loss_function="RMSE",
            eval_metric="MAE",
            random_seed=42,
            train_dir=_catboost_train_dir(data_root, target_name),
            verbose=False,
        )
    else:
        final = CatBoostClassifier(
            iterations=400,
            learning_rate=0.05,
            depth=6,
            loss_function="Logloss",
            eval_metric="AUC",
            auto_class_weights="Balanced",
            random_seed=42,
            train_dir=_catboost_train_dir(data_root, target_name),
            verbose=False,
        )
    final.fit(X_all, y_all, verbose=False)
    metrics = {
        "backend": "catboost",
        "target_name": target_name,
        "cv_metric": round(float(np.mean(scores)), 4) if scores else None,
        "cv_metric_name": "rank_ic" if spec["task"] == "regression" else "auc",
        "cv_mae": round(float(np.mean(maes)), 4) if maes else None,
        "train_rows": int(len(work)),
        "feature_cols": feature_cols,
    }
    return final, metrics


def _predict_values(model: object, X: np.ndarray, *, task: str) -> np.ndarray:
    if task == "classification" and hasattr(model, "predict_proba"):
        return np.asarray(model.predict_proba(X)[:, 1], dtype=np.float32)
    return np.asarray(model.predict(X), dtype=np.float32)


def _feature_cols_from_registry(row: dict | None, fallback: list[str]) -> list[str]:
    if not row:
        return list(fallback)
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    cols = metrics.get("feature_cols") if isinstance(metrics, dict) else None
    if isinstance(cols, list) and cols:
        return [str(col) for col in cols]
    return list(fallback)


def _matured_eval_window(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "event_date" not in frame.columns:
        return frame.iloc[0:0].copy()
    dates = pd.to_datetime(frame["event_date"], errors="coerce")
    cutoff_end = dates.max() - pd.Timedelta(days=28)
    cutoff_start = cutoff_end - pd.Timedelta(days=119)
    return frame[(dates >= cutoff_start) & (dates <= cutoff_end)].copy().reset_index(drop=True)


def _promotion_check(
    db: TradeDB,
    model: object,
    eval_frame: pd.DataFrame,
    feature_cols: list[str],
    target_name: str,
    spec: dict[str, Any],
    backend_name: str,
) -> dict[str, Any]:
    eval_frame = _matured_eval_window(eval_frame)
    label_col = spec["label_col"]
    work = eval_frame.dropna(subset=[label_col]).copy().reset_index(drop=True)
    if work.empty:
        return {
            "window_start": None,
            "window_end": None,
            "sample_count": 0,
            "candidate_metric": None,
            "active_metric": None,
            "metric_name": "rank_ic" if spec["task"] == "regression" else "auc",
            "baseline_delta": None,
            "pass_current": False,
            "consecutive_passes": 0,
            "eligible": False,
            "reason": "no matured labeled rows",
        }

    X = work[feature_cols].fillna(0.0).to_numpy(dtype=np.float32)
    y = (
        work[label_col].astype(int).to_numpy(dtype=np.int32)
        if spec["task"] == "classification"
        else work[label_col].to_numpy(dtype=np.float32)
    )
    pred = _predict_values(model, X, task=spec["task"])
    if spec["task"] == "classification":
        from sklearn.metrics import roc_auc_score

        candidate_metric = float(roc_auc_score(y, pred)) if len(np.unique(y)) >= 2 else None
        active_metric = None
        metric_name = "auc"
        baseline_delta = None
        active_row = db.model_registry_get_active(target_name)
        if active_row and Path(str(active_row["file_path"])).exists():
            import joblib

            active_model = joblib.load(active_row["file_path"])
            active_cols = [col for col in _feature_cols_from_registry(active_row, feature_cols) if col in work.columns]
            X_active = work[active_cols].fillna(0.0).to_numpy(dtype=np.float32)
            active_metric = float(roc_auc_score(y, _predict_values(active_model, X_active, task=spec["task"]))) if len(np.unique(y)) >= 2 else None
        pass_current = candidate_metric is not None and (active_metric is None or candidate_metric >= active_metric)
    else:
        candidate_metric = _rank_ic(pred, y)
        active_metric = None
        metric_name = "rank_ic"
        baseline = np.sign(pd.to_numeric(work.get("net_sentiment"), errors="coerce").fillna(0.0).to_numpy(dtype=np.float32))
        kg_dir = np.sign(pd.to_numeric(work.get("kg_score"), errors="coerce").fillna(0.0).to_numpy(dtype=np.float32))
        baseline = np.where(baseline == 0, kg_dir, baseline)
        baseline = np.where(baseline == 0, 1.0, baseline)
        base_pred = pd.to_numeric(work.get("magnitude"), errors="coerce").fillna(0.0).to_numpy(dtype=np.float32) * baseline
        static_pred = pd.to_numeric(work.get("kg_score"), errors="coerce").fillna(0.0).to_numpy(dtype=np.float32)
        baseline_candidates = [v for v in (_rank_ic(base_pred, y), _rank_ic(static_pred, y)) if v is not None]
        best_baseline = max(baseline_candidates) if baseline_candidates else None
        baseline_delta = (candidate_metric - best_baseline) if candidate_metric is not None and best_baseline is not None else None
        active_row = db.model_registry_get_active(target_name)
        if active_row and Path(str(active_row["file_path"])).exists():
            import joblib

            active_model = joblib.load(active_row["file_path"])
            active_cols = [col for col in _feature_cols_from_registry(active_row, feature_cols) if col in work.columns]
            X_active = work[active_cols].fillna(0.0).to_numpy(dtype=np.float32)
            active_metric = _rank_ic(_predict_values(active_model, X_active, task=spec["task"]), y)
        pass_current = (
            candidate_metric is not None
            and (active_metric is None or candidate_metric >= active_metric)
            and (baseline_delta is None or baseline_delta >= 0)
        )

    prior_candidates = [
        row for row in db.model_registry_list()
        if str(row.get("target_name") or row.get("model_name")) == target_name
        and str(row.get("backend") or "") == backend_name
        and str(row.get("promotion_state") or "") == "candidate"
    ]
    previous = prior_candidates[0] if prior_candidates else None
    prev_check = (previous or {}).get("metrics", {}).get("promotion_check", {}) if previous else {}
    prev_passes = int(prev_check.get("consecutive_passes", 0) or 0) if bool(prev_check.get("pass_current")) else 0
    consecutive_passes = prev_passes + 1 if pass_current else 0
    return {
        "window_start": str(work["event_date"].min())[:10],
        "window_end": str(work["event_date"].max())[:10],
        "sample_count": int(len(work)),
        "candidate_metric": round(float(candidate_metric), 4) if candidate_metric is not None else None,
        "active_metric": round(float(active_metric), 4) if active_metric is not None else None,
        "metric_name": metric_name,
        "baseline_delta": round(float(baseline_delta), 4) if baseline_delta is not None else None,
        "pass_current": bool(pass_current),
        "consecutive_passes": consecutive_passes,
        "eligible": bool(pass_current and consecutive_passes >= 2),
    }


def train_models(
    data_root: str,
    *,
    backend: str = "all",
    cv_splits: int = 5,
    activate_backend: str | None = None,
) -> list[dict[str, Any]]:
    import joblib

    backends = ["lgbm", "xgboost", "catboost", "tabular_nn"] if backend == "all" else [backend.replace("-", "_")]
    df = _load_training_frame(data_root)
    if df.empty:
        raise ValueError("features.parquet is empty")
    feature_cols = _available_features(df)
    if not feature_cols:
        raise ValueError("No usable feature columns found in features.parquet")

    model_dir = _model_dir(data_root)
    model_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    db = TradeDB(data_root)
    results: list[dict[str, Any]] = []

    for backend_name in backends:
        try:
            _ensure_estimators(backend_name)
        except Exception as exc:
            if backend == "all":
                logger.warning("skip backend %s: %s", backend_name, exc)
                continue
            raise
        trainer = {
            "lgbm": _train_lgbm,
            "xgboost": _train_xgboost,
            "catboost": _train_catboost,
            "tabular_nn": _train_tabular_nn,
        }[backend_name]
        for target_name, spec in TARGET_SPECS.items():
            label_col = spec["label_col"]
            if label_col not in df.columns:
                logger.warning("target %s missing label %s", target_name, label_col)
                continue
            eval_frame = df.dropna(subset=[label_col]).copy().reset_index(drop=True)
            work = eval_frame
            if len(work) < int(spec.get("min_rows", 0)):
                logger.info("skip %s/%s: labeled rows %d < %d", backend_name, target_name, len(work), spec["min_rows"])
                continue
            if spec["task"] == "classification":
                positive_count = int((work[label_col] > 0).sum())
                if positive_count < int(spec.get("min_positive", 0)):
                    logger.info("skip %s/%s: positives %d < %d", backend_name, target_name, positive_count, spec["min_positive"])
                    continue
            if backend_name == "tabular_nn":
                work = _downsample_for_tabular_nn(work)

            if backend_name == "catboost":
                model, metrics = trainer(work, feature_cols, target_name, spec, cv_splits, data_root=data_root)
            else:
                model, metrics = trainer(work, feature_cols, target_name, spec, cv_splits)
            metrics["promotion_check"] = _promotion_check(
                db,
                model,
                eval_frame,
                feature_cols,
                target_name,
                spec,
                backend_name,
            )
            suffix = "pkl"
            model_name = f"{target_name}__{backend_name}__{timestamp}"
            file_path = model_dir / f"{model_name}.{suffix}"
            joblib.dump(model, file_path)
            should_activate = activate_backend == backend_name
            if activate_backend is None and backend_name == "lgbm" and db.model_registry_get_active(target_name) is None:
                should_activate = True
            model_id = db.model_registry_insert(
                model_name,
                f"{backend_name}_{spec['task']}",
                str(file_path),
                metrics,
                target_name=target_name,
                backend=backend_name,
                artifact_format="joblib",
                feature_set="propagation_v2",
                promotion_state="active" if should_activate else "candidate",
                activate=should_activate,
            )
            results.append(
                {
                    "id": model_id,
                    "target_name": target_name,
                    "backend": backend_name,
                    "file_path": str(file_path),
                    "metrics": metrics,
                    "promotion_state": "active" if should_activate else "candidate",
                }
            )

    (model_dir / "feature_cols.json").write_text(json.dumps(feature_cols, ensure_ascii=False, indent=2))
    return results
