from __future__ import annotations

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
    service._db.record_download(
        "000001.SZ",
        KlineSyncService._parse_date("2026-01-10"),
        KlineSyncService._parse_date("2026-01-20"),
        5,
    )

    opts = KlineSyncOptions(mode="range", symbols=["000001.SZ"], start="2026-01-01", end="2026-01-31")

    assert service._target_ranges("000001.SZ", opts) == [
        (KlineSyncService._parse_date("2026-01-01"), KlineSyncService._parse_date("2026-01-09")),
        (KlineSyncService._parse_date("2026-01-21"), KlineSyncService._parse_date("2026-01-31")),
    ]


def test_chunk_days_uses_larger_windows_for_tushare() -> None:
    assert KlineSyncService._chunk_days("tushare") == 3650
    assert KlineSyncService._chunk_days("akshare") == 31
