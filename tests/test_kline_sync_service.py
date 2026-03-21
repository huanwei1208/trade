from __future__ import annotations

import types

from trade_py.data.market.kline.service import KlineSyncOptions, KlineSyncService


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
