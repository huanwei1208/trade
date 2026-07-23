from __future__ import annotations

import time
from types import SimpleNamespace

from trade_py.db.trade_db import TradeDB
from trade_web.backend import ops_workspace
from trade_web.backend.ops_workspace import (
    build_ops_compute_layers,
    build_ops_replay_preview,
    execute_ops_replay,
)


class _FakeStateBuilder:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


class _FakeStateService:
    def __init__(self, payload):
        self._payload = payload

    def build(self, symbol, as_of_date=None):
        return _FakeStateBuilder(self._payload)


class _FakeExplainService:
    def __init__(self, state_payload, explain_payload, causal_payload):
        self._state_svc = _FakeStateService(state_payload)
        self._explain_payload = explain_payload
        self._causal_payload = causal_payload

    def explain(self, symbol, as_of_date=None):
        return SimpleNamespace(to_dict=lambda: self._explain_payload)

    def causal_chain(self, symbol, as_of_date=None, persist=False, include_validation=False):
        return self._causal_payload


def test_build_ops_compute_layers_groups_nodes_by_semantic_layer(monkeypatch, tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.signal_upsert("2026-03-19", "603083.SH", model_score=0.41, model_risk=0.12, model_version="model-v1")
    db.signal_upsert("2026-03-20", "603083.SH", model_score=0.53, model_risk=0.11, model_version="model-v2")

    monkeypatch.setattr(ops_workspace, "_pick_representative_symbol", lambda _db, _asof: "603083.SH")
    monkeypatch.setattr(
        ops_workspace,
        "build_readiness_grid",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "dataset": "kline",
                    "cells": [
                        {"date": "2026-03-20", "status": "READY", "row_count": 12, "expected_count": 12, "coverage_pct": 1.0, "lag_days": 0, "source_last_date": "2026-03-20", "last_backfill_at": None},
                        {"date": "2026-03-19", "status": "PARTIAL", "row_count": 10, "expected_count": 12, "coverage_pct": 0.83, "lag_days": 1, "source_last_date": "2026-03-19", "last_backfill_at": None},
                    ],
                },
                {
                    "dataset": "planned_events",
                    "cells": [{"date": "2026-03-20", "status": "READY", "row_count": 4, "expected_count": 4, "coverage_pct": 1.0, "lag_days": 0, "source_last_date": "2026-03-20", "last_backfill_at": None}],
                },
                {
                    "dataset": "belief_state",
                    "cells": [{"date": "2026-03-20", "status": "READY", "row_count": 1, "expected_count": 1, "coverage_pct": 1.0, "lag_days": 0, "source_last_date": "2026-03-20", "last_backfill_at": None}],
                },
                {
                    "dataset": "recommendation",
                    "cells": [{"date": "2026-03-20", "status": "READY", "row_count": 1, "expected_count": 1, "coverage_pct": 1.0, "lag_days": 0, "source_last_date": "2026-03-20", "last_backfill_at": None}],
                },
                {
                    "dataset": "models",
                    "cells": [{"date": "2026-03-20", "status": "READY", "row_count": 2, "expected_count": 2, "coverage_pct": 1.0, "lag_days": 0, "source_last_date": "2026-03-20", "last_backfill_at": None}],
                },
                {
                    "dataset": "crypto_btc",
                    "cells": [
                        {
                            "date": "2026-03-20",
                            "status": "LATE_READY",
                            "row_count": 730,
                            "expected_count": 1,
                            "coverage_pct": 1.0,
                            "lag_days": 0,
                            "source_last_date": "2026-03-20",
                            "last_backfill_at": None,
                            "data_health": {
                                "blocking_gate": "D3",
                                "blocking_reason_code": "SOURCE_DIVERGENCE",
                            },
                        }
                    ],
                },
            ]
        },
    )

    explain_svc = _FakeExplainService(
        {
            "market_regime": "TRENDING_UP",
            "technical_regime": "NEUTRAL",
            "sentiment_regime": "NEUTRAL",
            "blockers": [],
            "market_state": {"rationale": "trend improving"},
            "technical_state": {"rationale": "RSI stabilized", "rsi_14": 47.0, "macd_signal": 1.0},
            "liquidity_state": {"rationale": "volume normal", "vol_ratio": 1.1},
            "sentiment_state": {"rationale": "neutral flow", "net_sentiment": 0.0},
            "event_state": {"kg_score": 0.2},
        },
        {
            "action": "WATCH",
            "thesis": "trend improving",
            "world_state_summary": "trend improving",
            "invalidators": ["trend_break"],
            "next_triggers": ["probe_if_score_crosses_0.55"],
            "trust": {"trust_score": 0.88},
            "input_warnings": [],
        },
        {
            "conviction_vector": {
                "final_decision_confidence": 0.61,
                "labels": {
                    "final_decision_confidence": "MEDIUM",
                    "market_conviction": "MEDIUM",
                    "symbol_conviction": "MEDIUM",
                },
            },
            "causal_factors": [
                {"factor_type": "trend_factor", "direction": "positive", "strength": 0.6, "rationale": "price trend improving"},
                {"factor_type": "momentum_factor", "direction": "neutral", "strength": 0.1, "rationale": "RSI recovered"},
                {"factor_type": "data_quality_factor", "direction": "positive", "strength": 0.9, "rationale": "inputs healthy"},
            ],
        },
    )

    payload = build_ops_compute_layers(str(tmp_path), db, None, explain_svc, as_of_date="2026-03-20")

    assert payload["representative_symbol"] == "603083.SH"
    assert {layer["key"] for layer in payload["layers"]} == {"source", "feature", "factor", "model", "decision", "workflow"}
    by_id = {node["id"]: node for node in payload["nodes"]}
    assert by_id["source:planned_events"]["mapped_dataset"] == "planned_events"
    assert by_id["source:crypto_btc"]["mapped_dataset"] == "crypto_btc"
    assert by_id["source:crypto_btc"]["latest_status"] == "partial"
    assert by_id["source:crypto_btc"]["latest_output_summary"]["metric"] == 1.0
    assert by_id["source:crypto_btc"]["downstream_ids"] == [
        "factor:data_quality_factor",
        "model:trust",
        "workflow:crypto_research_validation",
    ]
    assert "source:crypto_btc" in by_id["factor:data_quality_factor"]["upstream_ids"]
    assert by_id["model:conviction"]["mapped_dataset"] == "belief_state"
    assert by_id["model:model_registry"]["mapped_dataset"] == "models"
    assert by_id["decision:recommendation"]["latest_output_summary"]["primary"] == "WATCH"


def test_build_ops_replay_preview_resolves_multi_select_scope(tmp_path) -> None:
    db = TradeDB(tmp_path)
    run_id = db.job_run_start("recommend", stage="decision")
    db.job_run_finish(run_id, "ok", result_summary="recommend ok", elapsed_ms=3200)

    preview = build_ops_replay_preview(
        db,
        selected_node_ids=["decision:recommendation"],
        selected_cells=[{"dataset": "kline", "date": "2026-03-20"}],
        date_from="2026-03-20",
        date_to="2026-03-20",
        mode="selected_plus_downstream",
        action="recompute",
    )

    job_names = [item["job_name"] for item in preview["nodes_to_run"]]
    assert "recommend" in job_names
    assert "evaluate_daily" in job_names
    assert preview["estimated_scope"]["selected_count"] == 2
    assert preview["estimated_scope"]["job_count"] >= 2
    assert any(item["id"] == "decision:recommendation" for item in preview["downstream_affected"])


def test_execute_ops_replay_creates_batch_workflow_trace(monkeypatch, tmp_path) -> None:
    db = TradeDB(tmp_path)

    def fake_run_node(job_name: str, data_root: str, **kwargs) -> str:
        return f"{job_name} ok for {kwargs.get('date_to')}"

    monkeypatch.setattr("trade_py.engine.run_node", fake_run_node)

    response = execute_ops_replay(
        str(tmp_path),
        db,
        selected_node_ids=["decision:recommendation"],
        selected_cells=[],
        date_from="2026-03-20",
        date_to="2026-03-20",
        mode="selected_only",
        action="recompute",
    )

    assert response["accepted"] is True
    workflow_event_id = response["workflow_event_id"]

    deadline = time.monotonic() + 2.0
    detail = None
    while time.monotonic() < deadline:
        detail = db.event_workflow_detail(workflow_event_id)
        if detail and detail.get("status") in {"ok", "error"}:
            break
        time.sleep(0.05)

    assert detail is not None
    assert detail["status"] == "ok"
    assert detail["title"] == "Recompute selected compute layers"
    assert detail["progress"]["completed"] == detail["progress"]["total"]
    assert {node["job_name"] for node in detail["nodes"]} >= {"recommend", "evaluate_daily"}
