from __future__ import annotations

import numpy as np

from trade_py.db.trade_db import TradeDB
from trade_web.backend.inference import InferenceService


class _FakeModel:
    def predict(self, x):
        return np.array([0.42] * len(x), dtype=np.float32)


def test_inference_service_does_not_treat_neutral_feature_values_as_used_defaults(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.factor_upsert_batch([
        {"date": "2026-03-20", "symbol": "600096.SH", "factor_name": "window_score", "factor_type": "signal", "value": 69.0},
        {"date": "2026-03-20", "symbol": "600096.SH", "factor_name": "net_sentiment", "factor_type": "sentiment", "value": 0.0},
        {"date": "2026-03-20", "symbol": "600096.SH", "factor_name": "kg_score", "factor_type": "event", "value": 0.0},
        {"date": "2026-03-20", "symbol": "600096.SH", "factor_name": "tech_macd_cross", "factor_type": "technical", "value": 0.0},
    ])
    db.sync_state_set("tushare_kline", "daily", last_date="2026-03-20")

    svc = InferenceService(str(tmp_path))
    svc._models = {"kg_return_5d": _FakeModel()}
    svc._model_meta = {"kg_return_5d": {"model_name": "kg_return_5d", "framework": "lightgbm"}}
    svc._feature_cols_by_model = {"kg_return_5d": ["window_score", "net_sentiment", "kg_score", "tech_macd_cross"]}

    result = svc.predict(["600096.SH"])
    trust = result["600096.SH"]["trust"]

    assert trust["feature_coverage"] == 1.0
    assert trust["used_defaults"] == []
    assert not any("used_defaults:" in warning for warning in trust["warnings"])
