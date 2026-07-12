from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from trade_py.data.market.cross_asset.btc import (
    BTC_PROVIDER_REQUIRED_COLUMNS,
    BINANCE_KLINES_URL,
    OKX_HISTORY_CANDLES_URL,
    BtcProviderContractError,
    BtcProviderCredentialError,
    CoinGeckoBtcDailyShadowProvider,
    OkxBtcDailyProvider,
    normalize_coingecko_market_chart,
    normalize_okx_candles,
    okx_canonical_candidate,
)
from trade_py.data.market.cross_asset.providers import normalize_binance_klines


def _timestamp_ms(day: str) -> str:
    return str(int(pd.Timestamp(day, tz="UTC").timestamp() * 1000))


@dataclass
class _FakeResponse:
    payload: Any

    @property
    def content(self) -> bytes:
        return json.dumps(self.payload, separators=(",", ":")).encode("utf-8")

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


def test_normalize_okx_retains_partial_lineage_but_candidate_is_final_only():
    payload = {
        "code": "0",
        "msg": "",
        "data": [
            [_timestamp_ms("2026-07-09"), "61000", "62000", "60000", "61500", "12", "0", "0", "0"],
            [_timestamp_ms("2026-07-08"), "60000", "61500", "59500", "61000", "10", "0", "0", "1"],
        ],
    }

    frame = normalize_okx_candles(
        payload,
        fetched_at="2026-07-09T12:00:00Z",
        run_id="run-okx",
    )

    assert set(BTC_PROVIDER_REQUIRED_COLUMNS).issubset(frame.columns)
    assert frame["provider"].tolist() == ["okx", "okx"]
    assert frame["venue"].tolist() == ["okx", "okx"]
    assert frame["instrument"].tolist() == ["BTC-USDT", "BTC-USDT"]
    assert frame["quote_asset"].tolist() == ["USDT", "USDT"]
    assert frame["interval"].tolist() == ["1Dutc", "1Dutc"]
    assert frame["provider_status"].tolist() == ["1", "0"]
    assert frame["is_final"].tolist() == [True, False]
    assert frame["bar_open_at"].dt.tz is not None
    assert (frame["bar_close_at"] - frame["bar_open_at"]).eq(pd.Timedelta(days=1)).all()
    assert frame["available_at"].tolist() == [
        pd.Timestamp("2026-07-09T00:00:00Z"),
        pd.Timestamp("2026-07-10T00:00:00Z"),
    ]
    assert frame["payload_hash"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert frame["payload_hash"].nunique() == 2

    candidate = okx_canonical_candidate(frame)
    assert candidate["bar_open_at"].tolist() == [pd.Timestamp("2026-07-08T00:00:00Z")]


def test_okx_adapter_requests_utc_daily_and_preserves_raw_payload():
    calls: list[dict[str, Any]] = []
    payload = {
        "code": "0",
        "msg": "",
        "data": [
            [_timestamp_ms("2026-07-09"), "61000", "62000", "60000", "61500", "12", "0", "0", "0"],
            [_timestamp_ms("2026-07-08"), "60000", "61500", "59500", "61000", "10", "0", "0", "1"],
        ],
    }

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        calls.append({"url": url, **kwargs})
        return _FakeResponse(payload)

    capture = OkxBtcDailyProvider(fake_get).capture(
        days=10,
        fetched_at="2026-07-09T12:00:00Z",
        run_id="run-okx",
    )

    assert calls[0]["url"] == OKX_HISTORY_CANDLES_URL
    assert calls[0]["params"]["instId"] == "BTC-USDT"
    assert calls[0]["params"]["bar"] == "1Dutc"
    assert calls[0]["params"]["limit"] == 100
    assert len(capture.frame) == 2
    assert len(capture.final_rows) == 1
    assert capture.raw_payloads == (_FakeResponse(payload).content,)
    assert capture.raw_payload_hashes[0] != capture.frame.iloc[0]["payload_hash"]


def test_okx_normalizer_rejects_non_utc_daily_timestamp():
    payload = {
        "code": "0",
        "data": [
            [
                str(int(pd.Timestamp("2026-07-08T08:00:00Z").timestamp() * 1000)),
                "60000",
                "61000",
                "59000",
                "60500",
                "10",
                "0",
                "0",
                "1",
            ]
        ],
    }

    with pytest.raises(BtcProviderContractError, match="non-UTC-daily"):
        normalize_okx_candles(
            payload,
            fetched_at="2026-07-09T00:40:00Z",
            run_id="run-okx",
        )


def test_binance_shadow_provider_returns_full_ohlcv():
    """Shadow provider (formerly CoinGecko, now Binance) returns full OHLCV without API key."""
    calls: list[dict[str, Any]] = []
    ts_08 = int(_timestamp_ms("2026-07-08"))
    ts_09 = int(_timestamp_ms("2026-07-09"))
    ts_10 = int(_timestamp_ms("2026-07-10"))
    # Binance kline format: [open_time, open, high, low, close, volume, close_time, ...]
    payload = [
        [ts_08, "60500", "61000", "60000", "60750", "100.5", ts_08 + 86399999, "6100000", 1000, "50.0", "3050000", "0"],
        [ts_09, "60750", "62000", "60500", "61600", "120.0", ts_09 + 86399999, "7400000", 1100, "60.0", "3700000", "0"],
        [ts_10, "61600", "62500", "61400", "61700", "90.0",  ts_10 + 86399999, "5500000",  900, "45.0", "2780000", "0"],
    ]

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        calls.append({"url": url, **kwargs})
        return _FakeResponse(payload)

    capture = CoinGeckoBtcDailyShadowProvider(fake_get).capture(
        days=3,
        fetched_at="2026-07-10T00:40:00Z",
        run_id="run-shadow",
    )

    assert len(calls) == 1
    assert calls[0]["url"] == BINANCE_KLINES_URL
    assert calls[0]["params"]["symbol"] == "BTCUSDT"
    assert calls[0]["params"]["interval"] == "1d"
    # No API key headers for free endpoints
    assert "x-cg-demo-api-key" not in calls[0].get("headers", {})
    assert capture.frame["provider"].eq("binance").all()
    assert capture.frame["instrument"].eq("BTCUSDT").all()
    assert capture.frame["quote_asset"].eq("USDT").all()
    assert capture.frame["interval"].eq("1d").all()
    # Binance returns full OHLCV
    assert not capture.frame[["open", "high", "low", "close"]].isna().any().any()
    assert capture.frame["close"].tolist() == [60750.0, 61600.0, 61700.0]
    # Binance returns closed candles; is_final is determined by bar close time < fetched_at
    assert len(capture.final_rows) >= 2


def test_binance_normalizer_rejects_non_sequence_payload():
    """Binance normalizer rejects malformed payloads."""
    with pytest.raises(BtcProviderContractError, match="sequence"):
        normalize_binance_klines(
            {"not_a_list": True},
            fetched_at="2026-07-10T00:40:00Z",
            run_id="run-shadow",
        )


def test_binance_normalizer_rejects_intraday_timestamps():
    """Binance normalizer rejects non-UTC-midnight timestamps."""
    intraday_ms = int(pd.Timestamp("2026-07-08T04:00:00Z").timestamp() * 1000)
    with pytest.raises(BtcProviderContractError, match="non-UTC-daily"):
        normalize_binance_klines(
            [[intraday_ms, "60000", "61000", "59000", "60500", "10.0", intraday_ms + 3599999, "600000", 100, "5.0", "300000", "0"]],
            fetched_at="2026-07-10T00:40:00Z",
            run_id="run-shadow",
        )


def test_coingecko_compat_alias_delegates_to_binance():
    """normalize_coingecko_market_chart is an alias that delegates to Binance normalizer."""
    ts_08 = int(_timestamp_ms("2026-07-08"))
    payload = [
        [ts_08, "60500", "61000", "60000", "60750", "100.5", ts_08 + 86399999, "6100000", 1000, "50.0", "3050000", "0"],
    ]
    frame = normalize_coingecko_market_chart(
        payload,
        fetched_at="2026-07-10T00:40:00Z",
        run_id="run-shadow",
    )
    assert len(frame) == 1
    assert frame.iloc[0]["close"] == 60750.0
