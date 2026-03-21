from __future__ import annotations

from trade_py.db.trade_db import TradeDB


def test_get_active_symbols_filters_st_statuses(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.upsert_instrument("000001.SZ", "平安银行")
    db.upsert_instrument("002231.SZ", "*ST奥维")
    db.upsert_instrument("300344.SZ", "*ST立方")

    assert db.get_all_symbols() == ["000001.SZ", "002231.SZ", "300344.SZ"]
    assert db.get_active_symbols() == ["000001.SZ"]


def test_get_latest_market_asof_prefers_latest_open_trade_day(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.trading_calendar_upsert_batch([
        {"exchange": "SSE", "trade_date": "2026-03-20", "is_open": 1},
        {"exchange": "SSE", "trade_date": "2026-03-21", "is_open": 0, "pretrade_date": "2026-03-20"},
    ])
    db.signal_upsert("2026-03-19", "000001.SZ", window_score=55)

    assert db.get_latest_open_trade_date(on_or_before="2026-03-21") == "2026-03-20"
    assert db.get_latest_market_asof(on_or_before="2026-03-21") == "2026-03-20"
