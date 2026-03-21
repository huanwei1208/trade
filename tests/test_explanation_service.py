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


def test_build_kline_context_prefers_stored_signal_score_for_single_symbol(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.signal_upsert(
        "2026-03-20",
        "600150.SH",
        model_score=23.31,
        model_risk=0.0,
        model_version="model-v1",
    )

    class _FakeInference:
        def predict(self, symbols):
            return {
                "600150.SH": {
                    "model_score": 0.0,
                    "model_risk": 0.0,
                    "model_version": "batch-of-one",
                    "trust": {
                        "trust_score": 0.8882,
                        "trust_level": "HIGH",
                        "feature_coverage": 1.0,
                        "data_freshness_score": 0.9,
                        "warnings": [],
                    },
                }
            }

    state_svc = StateService(str(tmp_path), db=db)
    svc = ExplanationService(state_svc, DecisionService(), inference=_FakeInference())

    svc._read_ohlcv = lambda *args, **kwargs: ([], {}, {}, {})  # type: ignore[method-assign]
    svc._read_event_markers = lambda *args, **kwargs: []  # type: ignore[method-assign]
    svc._read_belief_overlay = lambda *args, **kwargs: []  # type: ignore[method-assign]
    svc._read_recommendation = lambda *args, **kwargs: {}  # type: ignore[method-assign]
    svc._generate_reason_groups = lambda **kwargs: {}  # type: ignore[method-assign]

    payload = svc.build_kline_context("600150.SH", as_of_date="2026-03-20", db=db, data_root=str(tmp_path))

    assert payload["prediction"]["model_score"] == 23.31
    assert payload["prediction"]["model_risk"] == 0.0
    assert payload["prediction"]["model_version"] == "model-v1"
    assert payload["prediction"]["trust"]["trust_score"] == 0.8882
