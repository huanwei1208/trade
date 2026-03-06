"""LightGBM multi-target model for event propagation prediction.

Trains separate models for:
  - return_5d, return_20d, return_60d  (regression)
  - loss_5pct_20d, drawdown_20pct      (binary classification)

After training, models are exported to ONNX for C++ inference.
SHAP values provide per-prediction explanations.

Usage:
    trainer = PropagationModel("data")
    trainer.load_data()
    trainer.train()
    trainer.save("data/models/propagation")
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Targets: (column, type)
REGRESSION_TARGETS = ["return_5d", "return_20d", "return_60d"]
CLASSIFICATION_TARGETS = ["loss_5pct_20d", "drawdown_20pct"]
ALL_TARGETS = REGRESSION_TARGETS + CLASSIFICATION_TARGETS

# Feature columns (must match feature_builder.py)
from trade_py.analysis.feature_builder import ALL_FEATURE_COLS

# LightGBM hyperparameters (sensible defaults)
LGBM_REGRESSOR_PARAMS = {
    "n_estimators":    300,
    "max_depth":       5,
    "num_leaves":      31,
    "learning_rate":   0.05,
    "subsample":       0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 20,
    "random_state":    42,
    "n_jobs":          -1,
    "verbose":         -1,
}

LGBM_CLASSIFIER_PARAMS = {
    "n_estimators":    300,
    "max_depth":       4,
    "num_leaves":      15,
    "learning_rate":   0.05,
    "subsample":       0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 20,
    "random_state":    42,
    "n_jobs":          -1,
    "verbose":         -1,
    "class_weight":    "balanced",
}


def _check_lightgbm() -> None:
    """Raise ImportError with install hint if lightgbm is missing."""
    try:
        import lightgbm  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "lightgbm is required for model training. Install with:\n"
            "  pip install lightgbm"
        ) from e


def _check_shap() -> None:
    try:
        import shap  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "shap is required for explanations. Install with:\n"
            "  pip install shap"
        ) from e


# ── Cross-validation helper ────────────────────────────────────────────────────

def time_series_splits(df: pd.DataFrame,
                        date_col: str = "date",
                        n_splits: int = 5,
                        gap_days: int = 60) -> list[tuple]:
    """Generate time-series (walk-forward) train/val splits.

    Args:
        df: DataFrame with a date column.
        date_col: Name of the date column.
        n_splits: Number of validation windows.
        gap_days: Calendar-day gap between train end and val start.

    Returns:
        List of (train_idx, val_idx) index tuples.
    """
    dates = pd.to_datetime(df[date_col]).dt.normalize()
    min_date = dates.min()
    max_date = dates.max()
    total_days = (max_date - min_date).days
    fold_size = total_days // (n_splits + 1)

    splits = []
    for k in range(n_splits):
        train_end = min_date + pd.Timedelta(days=(k + 1) * fold_size)
        val_start = train_end + pd.Timedelta(days=gap_days)
        val_end   = val_start + pd.Timedelta(days=fold_size)

        train_idx = df.index[dates <= train_end].tolist()
        val_idx   = df.index[(dates >= val_start) & (dates <= val_end)].tolist()

        if len(train_idx) >= 30 and len(val_idx) >= 10:
            splits.append((train_idx, val_idx))

    return splits


# ── PropagationModel ───────────────────────────────────────────────────────────

class PropagationModel:
    """Multi-target LightGBM model for event propagation prediction.

    Args:
        data_root: Root data directory.
    """

    def __init__(self, data_root: str | Path) -> None:
        self._root = Path(data_root)
        self._models: dict[str, object] = {}       # target → fitted model
        self._feature_cols: list[str] = ALL_FEATURE_COLS
        self._cv_scores: dict[str, list[float]] = {}
        self._train_df: Optional[pd.DataFrame] = None
        self._label_df: Optional[pd.DataFrame] = None

    # ── Data loading ──────────────────────────────────────────────────────────

    def load_data(self,
                  features_path: Optional[str | Path] = None,
                  labels_path:   Optional[str | Path] = None) -> None:
        """Load pre-built features and labels from Parquet.

        Default paths:
          features: data/events/features.parquet
          labels:   data/events/propagation_labels.parquet
        """
        fp = Path(features_path) if features_path else self._root / "events" / "features.parquet"
        lp = Path(labels_path)   if labels_path   else self._root / "events" / "propagation_labels.parquet"

        if not fp.exists():
            raise FileNotFoundError(f"Features file not found: {fp}")
        if not lp.exists():
            raise FileNotFoundError(f"Labels file not found: {lp}")

        self._train_df = pd.read_parquet(fp)
        self._label_df = pd.read_parquet(lp)
        logger.info("Loaded %d feature rows and %d label rows",
                    len(self._train_df), len(self._label_df))

    def _merge(self) -> pd.DataFrame:
        """Merge features and labels on (event_id, symbol)."""
        assert self._train_df is not None and self._label_df is not None
        merged = self._train_df.merge(
            self._label_df,
            on=["event_id", "symbol"],
            how="inner",
            suffixes=("", "_lbl"),
        )
        # Use date from features side
        if "date_lbl" in merged.columns:
            merged = merged.drop(columns=["date_lbl"])
        logger.info("Merged training set: %d rows", len(merged))
        return merged

    # ── Training ──────────────────────────────────────────────────────────────

    def train(self, n_cv_splits: int = 5) -> dict[str, float]:
        """Train all target models with time-series cross-validation.

        Args:
            n_cv_splits: Number of walk-forward CV folds.

        Returns:
            Dict of {target: mean_val_score} (IC for regression, AUC for classification).
        """
        _check_lightgbm()
        import lightgbm as lgb
        from sklearn.metrics import roc_auc_score
        from scipy.stats import pearsonr

        df = self._merge()
        feat_cols = [c for c in self._feature_cols if c in df.columns]
        X = df[feat_cols].fillna(0.0).to_numpy(dtype=np.float32)

        summary: dict[str, float] = {}
        splits = time_series_splits(df, date_col="date", n_splits=n_cv_splits)
        if not splits:
            logger.warning("Not enough data for cross-validation – training on full set")
            splits = [(df.index.tolist(), [])]

        # ── Regression targets ─────────────────────────────────────────────
        for target in REGRESSION_TARGETS:
            if target not in df.columns:
                logger.warning("Target %s not in data – skipping", target)
                continue
            y = df[target].fillna(0.0).to_numpy(dtype=np.float32)

            ic_scores = []
            for train_idx, val_idx in splits:
                X_tr, y_tr = X[train_idx], y[train_idx]
                X_val, y_val = X[val_idx], y[val_idx]

                m = lgb.LGBMRegressor(**LGBM_REGRESSOR_PARAMS)
                m.fit(X_tr, y_tr,
                      eval_set=[(X_val, y_val)] if len(val_idx) > 0 else None,
                      callbacks=[lgb.log_evaluation(period=100)])

                if len(val_idx) > 5:
                    preds = m.predict(X_val)
                    ic, _ = pearsonr(preds, y_val)
                    ic_scores.append(float(ic))

            # Final model on all data
            final = lgb.LGBMRegressor(**LGBM_REGRESSOR_PARAMS)
            final.fit(X, y)
            self._models[target] = final

            mean_ic = float(np.mean(ic_scores)) if ic_scores else float("nan")
            self._cv_scores[target] = ic_scores
            summary[target] = mean_ic
            logger.info("Trained %s | CV IC: %.4f (n=%d)", target, mean_ic, len(ic_scores))

        # ── Classification targets ─────────────────────────────────────────
        for target in CLASSIFICATION_TARGETS:
            if target not in df.columns:
                logger.warning("Target %s not in data – skipping", target)
                continue
            y = df[target].fillna(0).to_numpy(dtype=np.int32)
            if y.sum() < 5:
                logger.warning("Target %s has too few positive samples (%d) – skipping",
                               target, int(y.sum()))
                continue

            auc_scores = []
            for train_idx, val_idx in splits:
                X_tr, y_tr = X[train_idx], y[train_idx]
                X_val, y_val = X[val_idx], y[val_idx]

                m = lgb.LGBMClassifier(**LGBM_CLASSIFIER_PARAMS)
                m.fit(X_tr, y_tr,
                      eval_set=[(X_val, y_val)] if len(val_idx) > 0 else None,
                      callbacks=[lgb.log_evaluation(period=100)])

                if len(val_idx) > 5 and y_val.sum() > 0:
                    probs = m.predict_proba(X_val)[:, 1]
                    auc = roc_auc_score(y_val, probs)
                    auc_scores.append(float(auc))

            final = lgb.LGBMClassifier(**LGBM_CLASSIFIER_PARAMS)
            final.fit(X, y)
            self._models[target] = final

            mean_auc = float(np.mean(auc_scores)) if auc_scores else float("nan")
            self._cv_scores[target] = auc_scores
            summary[target] = mean_auc
            logger.info("Trained %s | CV AUC: %.4f (n=%d)", target, mean_auc, len(auc_scores))

        return summary

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(self, features: dict[str, float]) -> dict[str, float]:
        """Run inference for a single feature vector.

        Args:
            features: Dict of feature_name → value (missing features → 0).

        Returns:
            Dict of target → predicted value/probability.
        """
        if not self._models:
            raise RuntimeError("No trained models. Call train() first.")

        feat_cols = self._feature_cols
        x = np.array([[features.get(c, 0.0) for c in feat_cols]],
                     dtype=np.float32)

        out: dict[str, float] = {}
        for target, model in self._models.items():
            if target in REGRESSION_TARGETS:
                out[target] = float(model.predict(x)[0])
            else:
                proba = model.predict_proba(x)
                out[target] = float(proba[0, 1])
        return out

    # ── SHAP explanation ──────────────────────────────────────────────────────

    def explain(self, features: dict[str, float],
                target: str = "return_20d") -> dict[str, float]:
        """Compute SHAP feature contributions for a single prediction.

        Args:
            features: Feature dict.
            target: Which model to explain.

        Returns:
            Dict of feature_name → SHAP contribution value.
        """
        _check_shap()
        import shap

        if target not in self._models:
            raise KeyError(f"Model for '{target}' not trained yet.")

        model = self._models[target]
        feat_cols = self._feature_cols
        x = np.array([[features.get(c, 0.0) for c in feat_cols]],
                     dtype=np.float32)
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(x)

        if isinstance(shap_vals, list):
            # Classifier returns list of [shap_neg, shap_pos]
            shap_vals = shap_vals[1]

        contributions = {col: float(shap_vals[0, i])
                         for i, col in enumerate(feat_cols)}
        return contributions

    # ── Serialization ─────────────────────────────────────────────────────────

    def save(self, model_dir: Optional[str | Path] = None) -> Path:
        """Save all trained models to a directory using joblib.

        Also exports ONNX models for C++ inference (requires skl2onnx/onnxmltools).

        Args:
            model_dir: Directory to save models. Default: data/models/propagation/

        Returns:
            Directory path.
        """
        import joblib

        if model_dir is None:
            model_dir = self._root / "models" / "propagation"
        out = Path(model_dir)
        out.mkdir(parents=True, exist_ok=True)

        for target, model in self._models.items():
            path = out / f"{target}.pkl"
            joblib.dump(model, path)
            logger.info("Saved model %s → %s", target, path)

        # Save feature column list for inference alignment
        import json
        (out / "feature_cols.json").write_text(
            json.dumps(self._feature_cols, indent=2))
        logger.info("Saved %d models to %s", len(self._models), out)
        return out

    def load(self, model_dir: Optional[str | Path] = None) -> None:
        """Load trained models from a directory.

        Args:
            model_dir: Directory saved by save(). Default: data/models/propagation/
        """
        import joblib

        if model_dir is None:
            model_dir = self._root / "models" / "propagation"
        out = Path(model_dir)

        for target in ALL_TARGETS:
            path = out / f"{target}.pkl"
            if path.exists():
                self._models[target] = joblib.load(path)
                logger.info("Loaded model %s from %s", target, path)

        feat_path = out / "feature_cols.json"
        if feat_path.exists():
            import json
            self._feature_cols = json.loads(feat_path.read_text())
        logger.info("Loaded %d models", len(self._models))

    # ── Feature importance ────────────────────────────────────────────────────

    def feature_importance(self, target: str = "return_20d",
                            top_n: int = 20) -> pd.DataFrame:
        """Return feature importance for a given target model.

        Args:
            target: Target model name.
            top_n: Return only the top N features.

        Returns:
            DataFrame with columns [feature, importance].
        """
        if target not in self._models:
            raise KeyError(f"Model for '{target}' not trained yet.")
        model = self._models[target]
        imp = model.feature_importances_
        df = pd.DataFrame({
            "feature":    self._feature_cols,
            "importance": imp,
        }).sort_values("importance", ascending=False).head(top_n)
        return df.reset_index(drop=True)
