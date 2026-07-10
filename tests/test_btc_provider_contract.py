from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from trade_py.data.market.cross_asset.btc import (
    BTC_PROVIDER_REQUIRED_COLUMNS,
    COINGECKO_MARKET_CHART_URL,
    OKX_HISTORY_CANDLES_URL,
    BtcProviderContractError,
    BtcProviderCredentialError,
    CoinGeckoBtcDailyShadowProvider,
    OkxBtcDailyProvider,
    normalize_coingecko_market_chart,
    normalize_okx_candles,
    okx_canonical_candidate,
)


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

    assert calls == [
        {
            "url": OKX_HISTORY_CANDLES_URL,
            "params": {"instId": "BTC-USDT", "bar": "1Dutc", "limit": 100},
            "headers": {"Accept": "application/json"},
            "timeout": 15.0,
        }
    ]
    assert len(capture.frame) == 2
    assert len(capture.final_rows) == 1
    assert capture.raw_payloads == (_FakeResponse(payload).content,)
    assert capture.raw_payload_hashes[0] != capture.frame.iloc[0]["payload_hash"]
    assert capture.request_params == (
        {"instId": "BTC-USDT", "bar": "1Dutc", "limit": 100},
    )


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


def test_coingecko_adapter_uses_market_chart_daily_close_only():
    calls: list[dict[str, Any]] = []
    ts_08 = int(_timestamp_ms("2026-07-08"))
    ts_09 = int(_timestamp_ms("2026-07-09"))
    ts_10 = int(_timestamp_ms("2026-07-10"))
    payload = {
        "prices": [[ts_08, 60750.0], [ts_09, 61600.0], [ts_10, 61700.0]],
        "market_caps": [],
        "total_volumes": [[ts_08, 1_000.0], [ts_09, 1_100.0], [ts_10, 900.0]],
    }

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        calls.append({"url": url, **kwargs})
        return _FakeResponse(payload)

    capture = CoinGeckoBtcDailyShadowProvider(
        fake_get,
        api_key="demo-secret",
    ).capture(
        days=365,
        fetched_at="2026-07-10T00:40:00Z",
        run_id="run-shadow",
    )

    assert len(calls) == 1
    assert calls[0]["url"] == COINGECKO_MARKET_CHART_URL
    assert "/ohlc" not in calls[0]["url"]
    assert calls[0]["params"] == {
        "vs_currency": "usd",
        "days": "365",
        "interval": "daily",
        "precision": "full",
    }
    assert calls[0]["headers"]["x-cg-demo-api-key"] == "demo-secret"
    assert capture.request_params == (
        {
            "vs_currency": "usd",
            "days": "365",
            "interval": "daily",
            "precision": "full",
        },
    )
    assert capture.frame["provider"].eq("coingecko").all()
    assert capture.frame["instrument"].eq("BTC-USD").all()
    assert capture.frame["quote_asset"].eq("USD").all()
    assert capture.frame["interval"].eq("daily").all()
    assert capture.frame[["open", "high", "low"]].isna().all().all()
    assert capture.frame["close"].tolist() == [60750.0, 61600.0, 61700.0]
    assert capture.frame["is_final"].tolist() == [True, True, False]
    assert len(capture.final_rows) == 2

    with pytest.raises(BtcProviderContractError, match="cannot be used"):
        okx_canonical_candidate(capture)


def test_coingecko_requires_credentials_and_rejects_ohlc_payload_shape():
    provider = CoinGeckoBtcDailyShadowProvider(lambda *_args, **_kwargs: None)
    with pytest.raises(BtcProviderCredentialError, match="API key"):
        provider.capture(
            days=365,
            fetched_at="2026-07-10T00:40:00Z",
            run_id="run-shadow",
        )

    with pytest.raises(BtcProviderContractError, match="not OHLC rows"):
        normalize_coingecko_market_chart(  # type: ignore[arg-type]
            [[_timestamp_ms("2026-07-08"), 1.0, 2.0, 0.5, 1.5]],
            fetched_at="2026-07-10T00:40:00Z",
            run_id="run-shadow",
        )


def test_coingecko_rejects_intraday_market_chart_points():
    intraday_ms = int(pd.Timestamp("2026-07-08T04:00:00Z").timestamp() * 1000)
    with pytest.raises(BtcProviderContractError, match="non-UTC-daily"):
        normalize_coingecko_market_chart(
            {"prices": [[intraday_ms, 60_000.0]], "total_volumes": []},
            fetched_at="2026-07-10T00:40:00Z",
            run_id="run-shadow",
        )
