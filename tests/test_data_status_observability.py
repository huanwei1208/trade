from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from trade_py.cli.data import _running_job_state
from trade_py.db.trade_db import TradeDB
from trade_py.utils.data_inspector import build_status_lines, kline_freshness_stats


def test_kline_freshness_reports_trading_day_lag(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.trading_calendar_upsert_batch(
        [
            {"exchange": "SSE", "trade_date": "2026-03-18", "is_open": 1},
            {"exchange": "SSE", "trade_date": "2026-03-19", "is_open": 1},
            {"exchange": "SSE", "trade_date": "2026-03-20", "is_open": 1},
            {"exchange": "SSE", "trade_date": "2026-03-21", "is_open": 0},
        ]
    )
    with db._conn_lock:
        db._conn.executemany(
            """
            INSERT INTO instruments(symbol, name, market, board, industry, status)
            VALUES (?, ?, 1, 1, 1, 0)
            """,
            [
                ("000001.SZ", "A"),
                ("000002.SZ", "B"),
            ],
        )
        db._conn.commit()
    db.record_download("000001.SZ", datetime.fromisoformat("2026-03-18").date(), datetime.fromisoformat("2026-03-18").date(), 1)
    db.record_download("000002.SZ", datetime.fromisoformat("2026-03-20").date(), datetime.fromisoformat("2026-03-20").date(), 1)

    status = kline_freshness_stats(tmp_path, sample_limit=5)
    lines = build_status_lines({"as_of": "2026-03-21", "kline_freshness": status})

    assert status["expected_trade_date"] == "2026-03-20"
    assert status["trading_day_stale_ge_1"] == 1
    assert status["max_trading_day_stale_days"] == 2
    assert any("交易日基准: 2026-03-20" in line for line in lines)


@pytest.mark.parametrize(
    ("job_name", "age_hours", "expected"),
    [
        ("realtime_compute", 0.3, "stale_running"),
        ("kline_update", 1.0, "running"),
        ("kline_update", 7.0, "stale_running"),
    ],
)
def test_running_job_state_classifies_stale_rows(job_name: str, age_hours: float, expected: str) -> None:
    now = datetime.fromisoformat("2026-03-20T12:00:00")
    row = {
        "job_name": job_name,
        "started_at": (now - timedelta(hours=age_hours)).isoformat(sep=" "),
    }

    state = _running_job_state(row, now=now)

    assert state["status"] == expected
    assert state["age_hours"] == pytest.approx(age_hours)
