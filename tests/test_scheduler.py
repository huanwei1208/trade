from __future__ import annotations

from datetime import datetime

from trade_py.bus.scheduler import describe_schedule
from trade_py.db.trade_db import TradeDB


def test_describe_schedule_exposes_morning_evening_and_agenda_jobs(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.trading_calendar_upsert_batch([
        {"exchange": "SSE", "trade_date": "2026-03-20", "is_open": 1},
        {"exchange": "SSE", "trade_date": "2026-03-22", "is_open": 0, "pretrade_date": "2026-03-20"},
    ])

    items = describe_schedule(db, now=datetime.fromisoformat("2026-03-22T10:00:00"))
    by_topic = {str(item.get("topic") or ""): item for item in items}

    assert "gate.morning" in by_topic
    assert "gate.evening" in by_topic
    assert "agenda.due" in by_topic
    assert by_topic["gate.morning"]["trading_day_only"] is True
    assert by_topic["gate.morning"]["state_hint"] == "waiting_trading_day"
    assert by_topic["agenda.due"]["currently_eligible"] is True
