from __future__ import annotations

import types

import pandas as pd

from trade_py.data.market.kline.service import KlineSyncOptions, KlineSyncService
from trade_py.data.market.kline.tushare import _parse_raw
from trade_py.data.market.kline.providers import TencentKlineProvider


def test_missing_ranges_split_around_existing_downloads() -> None:
    start_d = KlineSyncService._parse_date("2026-01-01")
    end_d = KlineSyncService._parse_date("2026-01-31")
    covered = [
        (KlineSyncService._parse_date("2026-01-10"), KlineSyncService._parse_date("2026-01-20")),
    ]

    assert KlineSyncService._missing_ranges(start_d, end_d, covered) == [
        (KlineSyncService._parse_date("2026-01-01"), KlineSyncService._parse_date("2026-01-09")),
        (KlineSyncService._parse_date("2026-01-21"), KlineSyncService._parse_date("2026-01-31")),
    ]


def test_target_ranges_skip_fully_covered_range(tmp_path) -> None:
    service = KlineSyncService(tmp_path)
    service._db.upsert_instrument("000001.SZ", "Ping An")
    service._db.record_download(
        "000001.SZ",
        KlineSyncService._parse_date("2026-01-01"),
        KlineSyncService._parse_date("2026-03-31"),
        10,
    )

    opts = KlineSyncOptions(mode="range", symbols=["000001.SZ"], start="2026-02-01", end="2026-02-28")

    assert service._target_ranges("000001.SZ", opts) == []


def test_target_ranges_only_request_uncovered_gaps(tmp_path) -> None:
    service = KlineSyncService(tmp_path)
    service._db.upsert_instrument("000001.SZ", "Ping An")
    service._db.set("kline.start", "2026-01-01")
    service._db.record_download(
        "000001.SZ",
        KlineSyncService._parse_date("2026-01-10"),
        KlineSyncService._parse_date("2026-01-20"),
        5,
    )

    opts = KlineSyncOptions(mode="range", symbols=["000001.SZ"], start="2026-01-01", end="2026-01-31")

    assert service._target_ranges("000001.SZ", opts) == [
        (KlineSyncService._parse_date("2026-01-21"), KlineSyncService._parse_date("2026-01-31")),
    ]


def test_chunk_days_uses_larger_windows_for_tushare() -> None:
    assert KlineSyncService._chunk_days("tushare") == 3650
    assert KlineSyncService._chunk_days("tencent") == 3650
    assert KlineSyncService._chunk_days("akshare") == 31


def test_range_mode_keeps_trade_date_batch_for_sparse_gaps(tmp_path, monkeypatch) -> None:
    service = KlineSyncService(tmp_path)
    target_start = KlineSyncService._parse_date("2026-01-01")
    target_end = KlineSyncService._parse_date("2026-01-05")
    captured: dict[str, object] = {}

    def fake_target_ranges(symbol: str, opts: KlineSyncOptions):
        if symbol in {"000001.SZ", "000002.SZ"}:
            return [(target_start, target_end)]
        return []

    class FakeBatchProvider:
        def __init__(self, data_root: str) -> None:
            captured["data_root"] = data_root

        def fetch_batch_by_trade_date(self, symbols, trade_dates, adjust):
            captured["symbols"] = list(symbols)
            captured["trade_dates"] = list(trade_dates)
            captured["adjust"] = adjust
            return types.SimpleNamespace(frames={}, api_calls=len(trade_dates), trade_dates=len(trade_dates), days_with_hits=0)

    monkeypatch.setattr(service, "_target_ranges", fake_target_ranges)
    monkeypatch.setattr("trade_py.data.market.kline.service.TushareKlineProvider", FakeBatchProvider)

    summary = service._try_tushare_trade_date_batch(
        ["000001.SZ", "000002.SZ"],
        KlineSyncOptions(mode="range", start="2026-01-01", end="2026-01-05"),
    )

    assert summary is not None
    assert summary.sync_mode == "trade_date_batch"
    assert captured["symbols"] == ["000001.SZ", "000002.SZ"]
    assert captured["trade_dates"] == ["2026-01-01", "2026-01-02", "2026-01-05"]


def test_full_mode_uses_chunked_trade_date_batch_and_persists_rows(tmp_path, monkeypatch) -> None:
    service = KlineSyncService(tmp_path)
    target_start = KlineSyncService._parse_date("2026-01-01")
    target_end = KlineSyncService._parse_date("2026-01-06")
    captured: dict[str, object] = {"chunks": [], "saved": []}

    def fake_target_ranges(symbol: str, opts: KlineSyncOptions):
        if symbol in {"000001.SZ", "000002.SZ"}:
            return [(target_start, target_end)]
        return []

    class FakeBatchProvider:
        def __init__(self, data_root: str) -> None:
            captured["data_root"] = data_root

        def fetch_batch_by_trade_date(self, symbols, trade_dates, adjust):
            captured["chunks"].append(list(trade_dates))
            frames = {}
            for symbol in symbols:
                frames[symbol] = pd.DataFrame(
                    [
                        {
                            "symbol": symbol,
                            "date": trade_date,
                            "open": 1.0,
                            "high": 1.0,
                            "low": 1.0,
                            "close": 1.0,
                            "volume": 1.0,
                            "amount": 100.0,
                            "turnover_rate": 2.0,
                            "prev_close": 1.0,
                            "vwap": 1.0,
                        }
                        for trade_date in trade_dates
                    ]
                )
            return types.SimpleNamespace(
                frames=frames,
                api_calls=len(trade_dates),
                trade_dates=len(trade_dates),
                days_with_hits=len(trade_dates),
            )

    monkeypatch.setattr(service, "_target_ranges", fake_target_ranges)
    monkeypatch.setattr("trade_py.data.market.kline.service.TushareKlineProvider", FakeBatchProvider)
    monkeypatch.setattr("trade_py.data.market.kline.service._TUSHARE_BATCH_TRADE_DATES_PER_PASS", 2)

    def fake_save_parquet(symbol: str, frame: pd.DataFrame) -> None:
        captured["saved"].append((symbol, frame["date"].tolist()))

    monkeypatch.setattr(service._fetcher, "save_parquet", fake_save_parquet)

    summary = service._try_tushare_trade_date_batch(
        ["000001.SZ", "000002.SZ"],
        KlineSyncOptions(mode="full", start="2026-01-01", end="2026-01-06"),
    )

    assert summary is not None
    assert summary.sync_mode == "trade_date_batch"
    assert captured["chunks"] == [
        ["2026-01-01", "2026-01-02"],
        ["2026-01-05", "2026-01-06"],
    ]
    assert captured["saved"] == [
        ("000001.SZ", ["2026-01-01", "2026-01-02"]),
        ("000002.SZ", ["2026-01-01", "2026-01-02"]),
        ("000001.SZ", ["2026-01-05", "2026-01-06"]),
        ("000002.SZ", ["2026-01-05", "2026-01-06"]),
    ]
    assert summary.total_rows == 8
    assert summary.api_calls == 4


def test_tushare_parse_preserves_prev_close_and_turnover_rate() -> None:
    raw = pd.DataFrame(
        [
            {
                "ts_code": "603083.SH",
                "trade_date": "20260320",
                "open": 118.0,
                "high": 122.8,
                "low": 114.46,
                "close": 115.33,
                "pre_close": 115.67,
                "pct_chg": -0.2939,
                "vol": 350718.73,
                "amount": 4182823.469,
            }
        ]
    )
    basics = pd.DataFrame(
        [
            {
                "ts_code": "603083.SH",
                "trade_date": "20260320",
                "turnover_rate": 12.7262,
            }
        ]
    )

    parsed = _parse_raw(raw, "603083.SH", basics=basics)

    assert len(parsed) == 1
    row = parsed.iloc[0].to_dict()
    assert row["prev_close"] == 115.67
    assert row["turnover_rate"] == 12.7262
    assert row["close"] == 115.33
    assert row["amount"] == 4182823469.0
    assert row["vwap"] > 0


def test_kline_sync_options_default_to_none_adjust() -> None:
    assert KlineSyncOptions().adjust == "none"


def test_tencent_provider_parses_public_kline_payload(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self):
            return {
                "code": 0,
                "data": {
                    "sh600000": {
                        "qfqday": [
                            ["2026-03-24", "9.950", "10.040", "10.120", "9.890", "609859.000", "612298436.0"],
                            ["2026-03-25", "10.060", "10.100", "10.120", "9.940", "456784.000"],
                        ]
                    }
                },
            }

    def fake_get(url, params, timeout):
        assert params["param"].startswith("sh600000,day,2026-03-24,2026-03-25")
        assert timeout == 15
        return FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)

    df = TencentKlineProvider().fetch("600000.SH", "2026-03-24", "2026-03-25", adjust="qfq")

    assert df["symbol"].tolist() == ["600000.SH", "600000.SH"]
    assert df["date"].tolist() == ["2026-03-24", "2026-03-25"]
    assert df["close"].tolist() == [10.04, 10.1]
    assert round(float(df["vwap"].iloc[0]), 4) == round(612298436.0 / (609859.0 * 100.0), 4)
    assert df["vwap"].iloc[1] == 10.1
