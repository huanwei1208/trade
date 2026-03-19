"""Online inference service for the TradeDB web backend.

predict() now returns a trust block alongside model scores:
  {
    "model_score": float,
    "model_risk": float | None,
    "model_version": str,
    "trust": {
        "trust_score": float,
        "trust_level": "LOW"|"MEDIUM"|"HIGH",
        "feature_coverage": float,
        "missing_features": list[str],
        "used_defaults": list[str],
        "data_freshness_score": float,
        "model_version": str,
        "feature_schema_version": str,
        "trace_id": str,
        "generation_method": str,
        "warnings": list[str],
    }
  }
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Neutral / default values used for missing features (sentinels for trust detection)
_DEFAULT_SENTINELS: dict[str, float] = {
    "hop": 0.0,
    "kg_score": 0.0,
    "magnitude": 0.0,
    "window_score": 50.0,
    "net_sentiment": 0.0,
    "tech_rsi_14": 50.0,
    "tech_macd_hist": 0.0,
    "tech_macd_cross": 0.0,
    "tech_kdj_k": 50.0,
    "tech_kdj_d": 50.0,
    "tech_kdj_j": 50.0,
    "tech_volatility_20d": 0.0,
    "tech_volume_ratio_5_20": 1.0,
    "bf_net_sentiment": 0.0,
    "bf_event_strength": 0.0,
    "bf_novelty": 1.0,
    "bf_noise_penalty": 1.0,
}


class InferenceService:
    """Wraps active registry models and serves prediction requests."""

    def __init__(self, data_root: str) -> None:
        self._data_root = data_root
        self._lock = threading.RLock()
        self._models: dict[str, Any] = {}
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
            str(row.get("target_name") or row.get("model_name")): row
            for row in registry_rows
            if int(row.get("is_active", 0) or 0) == 1
            or str(row.get("promotion_state", "")) == "active"
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

        model_dir = Path(self._data_root) / "models" / "propagation"
        feat_path = model_dir / "feature_cols.json"
        fallback_feature_cols: list[str] = []
        if feat_path.exists():
            try:
                fallback_feature_cols = json.loads(feat_path.read_text())
            except Exception:
                fallback_feature_cols = []
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
        logger.info("InferenceService: reloading models")
        self._load_models()

    def _data_lag_days(self) -> int | None:
        """Estimate data freshness lag from kline sync_state (max across symbols)."""
        try:
            from datetime import date
            from trade_py.db.trade_db import TradeDB

            db = TradeDB(self._data_root)
            row = db._conn.execute(
                "SELECT MAX(last_date) FROM sync_state WHERE dataset='kline'"
            ).fetchone()
            last_raw = row[0] if row else None
            if last_raw is None:
                return None
            today = date.today()
            last_date = last_raw if hasattr(last_raw, "year") else date.fromisoformat(str(last_raw)[:10])
            return max(0, (today - last_date).days)
        except Exception:
            return None

    def predict(self, symbols: list[str], date_str: str | None = None) -> dict[str, dict]:
        """Run inference for the given symbols, returning scores + trust."""
        import numpy as np
        import pandas as pd
        from trade_py.trust import TrustBreakdown, compute_prediction_trust

        del date_str  # reserved for future point-in-time inference

        with self._lock:
            model_5d = self._models.get("kg_return_5d")
            model_risk = self._models.get("kg_risk_5pct")
            meta_5d = self._model_meta.get("kg_return_5d", {})
            feature_cols_5d = list(self._feature_cols_by_model.get("kg_return_5d", []))
            feature_cols_risk = list(self._feature_cols_by_model.get("kg_risk_5pct", feature_cols_5d))

        if model_5d is None:
            return {
                symbol: {
                    "model_score": None,
                    "model_risk": None,
                    "model_version": None,
                    "trust": TrustBreakdown.unavailable("model_not_loaded").to_dict(),
                }
                for symbol in symbols
            }

        data_lag = self._data_lag_days()
        model_version = str(meta_5d.get("model_name", "kg_return_5d"))
        generation_method = str(meta_5d.get("framework", "lightgbm"))

        try:
            from trade_py.db.trade_db import TradeDB

            db = TradeDB(self._data_root)
            requested_cols = list(dict.fromkeys(feature_cols_5d + feature_cols_risk))
            raw_factor_values: dict[str, dict[str, Any]] = {}
            records = []
            for symbol in symbols:
                factors = db.factor_get_latest(symbol, requested_cols if requested_cols else None)
                raw_factor_values[symbol] = dict(factors)
                row = {col: factors.get(col, 0.0) for col in requested_cols}
                row["symbol"] = symbol
                records.append(row)

            if not records:
                return {}

            df = pd.DataFrame(records)
            available_5d = [col for col in feature_cols_5d if col in df.columns]
            if not available_5d:
                return {
                    symbol: {
                        "model_score": 50.0,
                        "model_risk": None,
                        "model_version": model_version,
                        "trust": TrustBreakdown.unavailable("no_feature_cols").to_dict(),
                    }
                    for symbol in symbols
                }

            x_5d = df[available_5d].fillna(0).to_numpy(dtype=np.float32)
            scores_5d = model_5d.predict(x_5d)
            ranks = np.argsort(np.argsort(scores_5d)) / max(len(scores_5d) - 1, 1) * 100

            risk_scores = None
            if model_risk is not None:
                try:
                    available_risk = [col for col in feature_cols_risk if col in df.columns]
                    x_risk = df[available_risk].fillna(0).to_numpy(dtype=np.float32)
                    risk_scores = model_risk.predict_proba(x_risk)[:, 1]
                except Exception as exc:
                    logger.warning("risk model failed: %s", exc)

            result = {}
            for idx, symbol in enumerate(df["symbol"].tolist()):
                # Compute per-symbol trust
                trust = compute_prediction_trust(
                    factor_values=raw_factor_values.get(symbol, {}),
                    expected_cols=feature_cols_5d,
                    model_version=model_version,
                    generation_method=generation_method,
                    data_lag_days=data_lag,
                    default_value_sentinels=_DEFAULT_SENTINELS,
                )
                result[symbol] = {
                    "model_score": round(float(ranks[idx]), 2),
                    "model_risk": round(float(risk_scores[idx]), 4) if risk_scores is not None else None,
                    "model_version": model_version,
                    "trust": trust.to_dict(),
                }
            return result
        except Exception as exc:
            logger.error("Inference failed: %s", exc, exc_info=True)
            return {
                symbol: {
                    "model_score": None,
                    "model_risk": None,
                    "model_version": None,
                    "trust": TrustBreakdown.unavailable(f"inference_error:{type(exc).__name__}").to_dict(),
                }
                for symbol in symbols
            }

    @property
    def loaded_at(self) -> str | None:
        return self._loaded_at

    @property
    def model_names(self) -> list[str]:
        with self._lock:
            return list(self._models.keys())


__all__ = ["InferenceService"]
