from __future__ import annotations

import types

import pandas as pd
import pytest

from trade_py.data.market.cross_asset import akshare as cross_asset


def test_fetch_gold_rejects_invalid_ohlc_before_writing(tmp_path, monkeypatch) -> None:
    def fake_spot_hist_sge(symbol: str) -> pd.DataFrame:
        assert symbol == "Au99.99"
        return pd.DataFrame(
            [
                {"date": "2026-03-20", "open": 280.4, "high": 281.25, "low": 279.5, "close": 281.83},
            ]
        )

    monkeypatch.setitem(
        __import__("sys").modules,
        "akshare",
        types.SimpleNamespace(spot_hist_sge=fake_spot_hist_sge),
    )

    with pytest.raises(ValueError, match="gold OHLC data failed validation"):
        cross_asset.fetch_gold(str(tmp_path))

    assert not (tmp_path / "market" / "cross_asset" / "gold.parquet").exists()


def test_fetch_fx_cnh_validates_and_writes_ohlc(tmp_path, monkeypatch) -> None:
    def fake_forex_hist_em(symbol: str) -> pd.DataFrame:
        assert symbol == "USDCNH"
        return pd.DataFrame(
            [
                {
                    "日期": "2026-03-20",
                    "今开": 7.21,
                    "最高": 7.24,
                    "最低": 7.20,
                    "最新价": 7.22,
                },
            ]
        )

    monkeypatch.setitem(
        __import__("sys").modules,
        "akshare",
        types.SimpleNamespace(forex_hist_em=fake_forex_hist_em),
    )

    frame = cross_asset.fetch_fx_cnh(str(tmp_path))

    assert frame["close"].tolist() == [7.22]
    assert (tmp_path / "market" / "cross_asset" / "fx_cnh.parquet").exists()
