from __future__ import annotations

from trade_py.db.trade_db import TradeDB
from trade_py.services.decision_service import DecisionService
from trade_py.services.explanation_service import ExplanationService
from trade_py.services.state_service import StateService


def test_explanation_service_reads_event_markers_via_event_propagations(tmp_path) -> None:
    db = TradeDB(tmp_path)
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

    state_svc = StateService(str(tmp_path), db=db)
    svc = ExplanationService(state_svc, DecisionService())

    markers = svc._read_event_markers(db, "000001.SZ", 60, "2026-03-20")

    assert len(markers) == 1
    assert markers[0]["event_type"] == "policy_support"
    assert markers[0]["kg_score"] == 0.72
