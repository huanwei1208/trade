"""Online inference service — loads models from model_registry and serves predictions.

Lifecycle:
  1. On startup: load active models from model_registry
  2. predict(symbols, date) → dict[symbol, scores]
  3. watch_for_new_models() → reload when model.trained event fires

This module is imported by web/app.py and runs inside the FastAPI process.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class InferenceService:
    """Wraps LightGBM models loaded from model_registry.

    Thread-safe: models are replaced atomically via a lock.
    """

    def __init__(self, data_root: str) -> None:
        self._data_root = data_root
        self._lock = threading.RLock()
        self._models: dict[str, Any] = {}         # model_name → lgbm model
        self._model_meta: dict[str, dict[str, Any]] = {}
        self._feature_cols_by_model: dict[str, list[str]] = {}
        self._loaded_at: str | None = None
        self._load_models()

    def _load_models(self) -> None:
        """Load all active models from model_registry."""
        try:
            import joblib
        except ImportError:
            logger.warning("joblib not installed; inference unavailable")
            return

        try:
            from trade_py.db.trade_db import TradeDB
            db = TradeDB(self._data_root)
            registry_rows = db.model_registry_list()
        except Exception as exc:
            logger.error("Failed to load model_registry: %s", exc)
            return

        active = {
            str(r.get("target_name") or r.get("model_name")): r
            for r in registry_rows
            if int(r.get("is_active", 0) or 0) == 1
            or str(r.get("promotion_state", "")) == "active"
        }
        if not active:
            logger.info("No active models in model_registry")
            return

        new_models: dict[str, Any] = {}
        new_meta: dict[str, dict[str, Any]] = {}
        feature_cols_by_model: dict[str, list[str]] = {}
        for model_name, row in active.items():
            path = Path(row["file_path"])
            if not path.exists():
                logger.warning("Model file missing: %s", path)
                continue
            try:
                new_models[model_name] = joblib.load(path)
                new_meta[model_name] = dict(row)
                logger.info("Loaded model %s from %s", model_name, path)
                metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
                if isinstance(metrics, dict) and metrics.get("feature_cols"):
                    feature_cols_by_model[model_name] = list(metrics["feature_cols"])
            except Exception as exc:
                logger.error("Failed to load %s: %s", model_name, exc)

        # Load fallback feature column list
        model_dir = Path(self._data_root) / "models" / "propagation"
        feat_path = model_dir / "feature_cols.json"
        fallback_feature_cols: list[str] = []
        if feat_path.exists():
            try:
                fallback_feature_cols = json.loads(feat_path.read_text())
            except Exception:
                pass
        for model_name in new_models:
            feature_cols_by_model.setdefault(model_name, list(fallback_feature_cols))

        with self._lock:
            self._models = new_models
            self._model_meta = new_meta
            self._feature_cols_by_model = feature_cols_by_model
            from datetime import datetime
            self._loaded_at = datetime.utcnow().isoformat()

        logger.info("InferenceService: loaded %d models", len(new_models))

    def reload(self) -> None:
        """Hot-reload models (called when model.trained event fires)."""
        logger.info("InferenceService: reloading models")
        self._load_models()

    def predict(
        self,
        symbols: list[str],
        date_str: str | None = None,
    ) -> dict[str, dict]:
        """Run inference for given symbols.

        Returns dict: symbol → {"model_score": float, "model_risk": float|None,
                                 "model_version": str}
        """
        import numpy as np
        import pandas as pd

        with self._lock:
            model_5d = self._models.get("kg_return_5d")
            model_risk = self._models.get("kg_risk_5pct")
            meta_5d = self._model_meta.get("kg_return_5d", {})
            feature_cols_5d = list(self._feature_cols_by_model.get("kg_return_5d", []))
            feature_cols_risk = list(self._feature_cols_by_model.get("kg_risk_5pct", feature_cols_5d))

        if model_5d is None:
            return {s: {"model_score": None, "model_risk": None,
                        "model_version": None} for s in symbols}

        try:
            from trade_py.db.trade_db import TradeDB
            db = TradeDB(self._data_root)

            # Build feature matrix from factors table
            requested_cols = list(dict.fromkeys(feature_cols_5d + feature_cols_risk))
            records = []
            for sym in symbols:
                factors = db.factor_get_latest(sym, requested_cols if requested_cols else None)
                row = {col: factors.get(col, 0.0) for col in requested_cols}
                row["symbol"] = sym
                records.append(row)

            if not records:
                return {}

            df = pd.DataFrame(records)
            available_5d = [c for c in feature_cols_5d if c in df.columns]
            if not available_5d:
                # Fallback: return neutral scores
                return {s: {"model_score": 50.0, "model_risk": None,
                            "model_version": str(meta_5d.get("model_name", "kg_return_5d"))} for s in symbols}

            X_5d = df[available_5d].fillna(0).to_numpy(dtype=np.float32)
            scores_5d = model_5d.predict(X_5d)
            # Convert to percentile rank 0-100
            ranks = np.argsort(np.argsort(scores_5d)) / max(len(scores_5d) - 1, 1) * 100

            risk_scores = None
            if model_risk is not None:
                try:
                    available_risk = [c for c in feature_cols_risk if c in df.columns]
                    X_risk = df[available_risk].fillna(0).to_numpy(dtype=np.float32)
                    risk_scores = model_risk.predict_proba(X_risk)[:, 1]
                except Exception as exc:
                    logger.warning("risk model failed: %s", exc)

            result = {}
            for i, sym in enumerate(df["symbol"].tolist()):
                result[sym] = {
                    "model_score": round(float(ranks[i]), 2),
                    "model_risk": round(float(risk_scores[i]), 4) if risk_scores is not None else None,
                    "model_version": str(meta_5d.get("model_name", "kg_return_5d")),
                }
            return result

        except Exception as exc:
            logger.error("Inference failed: %s", exc, exc_info=True)
            return {s: {"model_score": None, "model_risk": None,
                        "model_version": None} for s in symbols}

    @property
    def loaded_at(self) -> str | None:
        return self._loaded_at

    @property
    def model_names(self) -> list[str]:
        with self._lock:
            return list(self._models.keys())
