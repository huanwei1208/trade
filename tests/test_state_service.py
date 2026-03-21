from __future__ import annotations

import json

from trade_py.db.trade_db import TradeDB
from trade_py.services.state_service import StateService


def test_state_service_defaults_to_latest_market_asof_and_reads_sync_state_sources(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.trading_calendar_upsert_batch([
        {"exchange": "SSE", "trade_date": "2026-03-20", "is_open": 1},
        {"exchange": "SSE", "trade_date": "2026-03-21", "is_open": 0, "pretrade_date": "2026-03-20"},
    ])
    db.signal_upsert("2026-03-20", "000001.SZ", window_score=68)
    db.sync_state_set("tushare_kline", "daily", last_date="2026-03-20")
    with db._conn_lock:
        db._conn.execute(
            """
            INSERT INTO dataset_snapshots (
                snapshot_name, eval_date, start_date, end_date,
                source_count, market_event_count, propagation_count,
                feature_rows, labeled_rows_5d, labeled_rows_20d,
                signal_dates, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                "daily",
                "2026-03-20",
                "2026-03-01",
                "2026-03-20",
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                json.dumps({"fund_flow_coverage": 0.95, "fundamental_coverage": 1.0}),
            ),
        )
        db._conn.commit()

    svc = StateService(str(tmp_path), db=db)
    ws = svc.build("000001.SZ")
    payload = ws.to_dict()

    assert ws.as_of_date == "2026-03-20"
    assert payload["market_regime"] == "SIDEWAYS"
    assert payload["data_quality_state"]["missing_datasets"] == []
    assert payload["data_quality_state"]["freshness_score"] == 1.0


def test_state_service_reads_symbol_events_from_event_propagations_and_signal_fallback(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.trading_calendar_upsert_batch([
        {"exchange": "SSE", "trade_date": "2026-03-19", "is_open": 1},
        {"exchange": "SSE", "trade_date": "2026-03-20", "is_open": 1, "pretrade_date": "2026-03-19"},
    ])
    db.upsert_instrument("000001.SZ", "平安银行")
    db.signal_upsert("2026-03-19", "000001.SZ", window_score=61, event_kg_score=0.72, event_type="policy_support")
    db.signal_upsert("2026-03-20", "000001.SZ", window_score=68)
    db.sync_state_set("tushare_kline", "daily", last_date="2026-03-20")
    with db._conn_lock:
        db._conn.execute(
            """
            INSERT INTO market_events (
                event_id, event_date, event_type, entity_id, magnitude,
                confidence, breadth, sentiment_score, news_volume, summary, source_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "evt-1",
                "2026-03-19",
                "policy_support",
                "SW_Bank",
                0.8,
                0.9,
                "sector",
                0.7,
                2,
                "政策支持银行板块",
                "hash-1",
            ),
        )
        db._conn.execute(
            """
            INSERT INTO event_propagations (
                event_id, symbol, kg_score, hop, typical_days
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("evt-1", "000001.SZ", 0.72, 1, 5),
        )
        db._conn.commit()

    svc = StateService(str(tmp_path), db=db)
    ws = svc.build("000001.SZ", as_of_date="2026-03-20")
    payload = ws.to_dict()

    assert payload["event_state"]["top_event_type"] == "policy_support"
    assert payload["event_state"]["event_count_recent"] >= 1
    assert payload["event_state"]["kg_score"] == 0.72
