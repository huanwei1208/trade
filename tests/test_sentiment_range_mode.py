from __future__ import annotations

from datetime import date

from trade_py.cli._sentiment import (
    _bronze_path,
    _contiguous_windows,
    _gold_path,
    _range_fetch_and_process_dates,
    _silver_path,
)


def test_contiguous_windows_merges_adjacent_days() -> None:
    dates = [
        date(2026, 3, 1),
        date(2026, 3, 2),
        date(2026, 3, 4),
        date(2026, 3, 5),
    ]

    assert _contiguous_windows(dates) == [
        (date(2026, 3, 1), date(2026, 3, 2)),
        (date(2026, 3, 4), date(2026, 3, 5)),
    ]


def test_range_fetch_and_process_dates_use_recent_refetch_and_output_gaps(tmp_path) -> None:
    dates = [date(2026, 3, d) for d in range(1, 6)]

    _bronze_path(tmp_path, "rss", date(2026, 3, 1)).parent.mkdir(parents=True, exist_ok=True)
    _bronze_path(tmp_path, "rss", date(2026, 3, 1)).write_text("x", encoding="utf-8")
    _silver_path(tmp_path, date(2026, 3, 1)).parent.mkdir(parents=True, exist_ok=True)
    _silver_path(tmp_path, date(2026, 3, 1)).write_text("x", encoding="utf-8")
    _gold_path(tmp_path, date(2026, 3, 1)).parent.mkdir(parents=True, exist_ok=True)
    _gold_path(tmp_path, date(2026, 3, 1)).write_text("x", encoding="utf-8")

    fetch_dates, process_dates = _range_fetch_and_process_dates(
        str(tmp_path),
        "rss",
        dates,
        settle_window_days=2,
    )

    assert fetch_dates == [
        date(2026, 3, 2),
        date(2026, 3, 3),
        date(2026, 3, 4),
        date(2026, 3, 5),
    ]
    assert process_dates == [
        date(2026, 3, 2),
        date(2026, 3, 3),
        date(2026, 3, 4),
        date(2026, 3, 5),
    ]
