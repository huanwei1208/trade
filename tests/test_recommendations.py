from __future__ import annotations

import json

from trade_py.db.trade_db import TradeDB
from trade_py.decision import produce_recommendations


def test_produce_recommendations_filters_non_active_symbols(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.upsert_instrument("000001.SZ", "平安银行")
    db.upsert_instrument("000908.SZ", "*ST景峰")

    db.belief_state_upsert(
        "2026-03-20",
        "000001.SZ",
        {"mu": 0.1, "sigma": 0.2, "mu_5d": 0.1, "sigma_5d": 0.2},
        "v1",
        confidence=0.6,
        uncertainty=0.2,
    )
    db.belief_state_upsert(
        "2026-03-20",
        "000908.SZ",
        {"mu": 0.2, "sigma": 0.2, "mu_5d": 0.2, "sigma_5d": 0.2},
        "v1",
        confidence=0.6,
        uncertainty=0.2,
    )
    db.signal_upsert("2026-03-20", "000001.SZ", window_score=60)
    db.signal_upsert("2026-03-20", "000908.SZ", window_score=90)
    db.recommendation_upsert(
        rec_id="legacy-st",
        as_of_date="2026-03-20",
        symbol="000908.SZ",
        action="watch",
        conviction="low",
        score=0.9,
        risk=0.1,
        horizon_days=5,
        reasons=[],
    )

    recs = produce_recommendations("2026-03-20", str(tmp_path), db)

    assert [row["symbol"] for row in recs] == ["000001.SZ"]
    assert [row["symbol"] for row in db.recommendation_list("2026-03-20")] == ["000001.SZ"]


def test_produce_recommendations_writes_freshness_from_real_latest_inputs(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.upsert_instrument("000001.SZ", "平安银行")
    db.belief_state_upsert(
        "2026-03-20",
        "000001.SZ",
        {"mu": 0.1, "sigma": 0.2, "mu_5d": 0.1, "sigma_5d": 0.2},
        "v1",
        confidence=0.6,
        uncertainty=0.2,
    )
    db.signal_upsert("2026-03-20", "000001.SZ", window_score=60)
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
        db._conn.commit()

    produce_recommendations("2026-03-20", str(tmp_path), db)
    freshness = {row["dataset"]: row for row in db.freshness_status_list("2026-03-20")}

    assert freshness["kline"]["status"] == "ok"
    assert freshness["fund_flow"]["status"] == "ok"
    assert freshness["factors"]["status"] == "ok"
    assert freshness["market_events"]["freshness_date"] == "2026-03-19"
