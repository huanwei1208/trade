from __future__ import annotations

import pandas as pd

from trade_py.data.market.fundamental.tushare import compute_fundamental_features


def _fundamental_frame(roes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "report_date": pd.Timestamp("2024-03-31") + pd.DateOffset(months=3 * idx),
                "roe": roe,
                "net_profit": 100.0 + idx,
                "revenue": 1000.0 + idx,
                "op_cash_flow": 120.0 + idx,
                "bps": 5.0,
            }
            for idx, roe in enumerate(roes)
        ]
    )


def test_fundamental_features_clip_roe_outliers_for_ttm_average() -> None:
    frame = _fundamental_frame([0.1, 0.2, 806.0, -192.0])

    features = compute_fundamental_features(frame)

    assert features["quarters_available"] == 4
    assert features["roe_ttm"] == (0.1 + 0.2 + 1.5 - 1.5) / 4


def test_fundamental_features_clip_roe_outliers_for_momentum() -> None:
    frame = _fundamental_frame([806.0, 806.0, 806.0, 806.0, -192.0, -192.0, -192.0, -192.0])

    features = compute_fundamental_features(frame)

    assert features["quarters_available"] == 8
    assert features["roe_ttm"] == -1.5
    assert features["roe_momentum"] == -3.0
