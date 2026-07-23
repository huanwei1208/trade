from __future__ import annotations

import pandas as pd

from trade_py.db.trade_db import TradeDB
from trade_web.backend import readiness as readiness_module
from trade_web.backend.readiness import (
    _collect_recovery_actions,
    build_readiness_grid,
    create_recovery_action,
    execute_recovery_action,
    list_recovery_history,
)


def test_collect_recovery_actions_clips_long_ranges_to_requested_window(tmp_path) -> None:
    db = TradeDB(tmp_path)
    with db._conn_lock:
        db._conn.execute(
            """
            INSERT INTO readiness_recovery_actions (
                dataset, date_from, date_to, action_type, mode, status,
                requested_at, updated_at, job_names_json, affected_outputs_json,
                request_json, fingerprint_before, fingerprint_after, result_json, summary
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '[]', '[]', '{}', ?, ?, '{}', ?)
            """,
            (
                "kline",
                "2026-01-30",
                "2026-03-20",
                "backfill",
                "data_only",
                "ok",
                "fp-before",
                "fp-after",
                "range repair",
            ),
        )
        db._conn.commit()

    by_cell, by_dataset = _collect_recovery_actions(db, "2026-02-20", "2026-03-20")

    assert "kline" in by_dataset
    assert by_cell[("kline", "2026-03-20")][0]["summary"] == "range repair"


def test_execute_recovery_action_creates_workflow_and_job_run_trace(monkeypatch, tmp_path) -> None:
    db = TradeDB(tmp_path)

    def fake_run_node(job_name: str, data_root: str, **kwargs) -> str:
        return f"{job_name} ok for {kwargs.get('date_to')}"

    monkeypatch.setattr("trade_py.engine.run_node", fake_run_node)
    monkeypatch.setattr(readiness_module, "compute_readiness_fingerprint", lambda *args, **kwargs: "fp-after")

    action_id = create_recovery_action(
        db,
        dataset="recommendation",
        date_from="2026-03-20",
        date_to="2026-03-20",
        action_type="replay",
        mode="data_plus_downstream",
        job_names=["evaluate_daily"],
        affected_outputs=["today", "candidates", "symbol"],
        request_payload={"dataset": "recommendation"},
        fingerprint_before="fp-before",
    )

    execute_recovery_action(
        str(tmp_path),
        db,
        action_id=action_id,
        dataset="recommendation",
        date_from="2026-03-20",
        date_to="2026-03-20",
        mode="data_plus_downstream",
        action_type="replay",
    )

    history = list_recovery_history(db, dataset="recommendation", date="2026-03-20", limit=5)
    assert history[0]["status"] == "ok"
    workflow_event_id = history[0]["result"]["workflow_event_id"]
    assert isinstance(workflow_event_id, int)
    assert history[0]["result"]["steps"][0]["job_name"] == "evaluate_daily"

    workflow = db.event_workflow_detail(workflow_event_id)
    assert workflow is not None
    assert workflow["title"] == "Restore the latest recommendation from Recommendation"
    assert workflow["status"] == "ok"
    assert workflow["progress"]["completed"] == 1
    assert workflow["progress"]["total"] == 1
    assert workflow["nodes"][0]["job_name"] == "evaluate_daily"

    recent = db.event_workflow_recent(limit=5)
    assert recent[0]["root_event_id"] == workflow_event_id
    assert recent[0]["status"] == "ok"

    with db._conn_lock:
        child_events = db._conn.execute(
            "SELECT id, topic, status, handler FROM event_log WHERE parent_event_id = ? ORDER BY id",
            (workflow_event_id,),
        ).fetchall()
        job_rows = db._conn.execute(
            "SELECT job_name, status, trigger_event_id, result_summary FROM job_runs ORDER BY id DESC LIMIT 1"
        ).fetchall()

    assert len(child_events) == 1
    assert child_events[0]["topic"] == "ops.readiness.step"
    assert child_events[0]["status"] == "ok"
    assert child_events[0]["handler"] == "evaluate_daily"
    assert len(job_rows) == 1
    assert job_rows[0]["job_name"] == "evaluate_daily"
    assert job_rows[0]["status"] == "ok"
    assert job_rows[0]["trigger_event_id"] == child_events[0]["id"]
    assert "2026-03-20" in str(job_rows[0]["result_summary"] or "")


def test_readiness_grid_exposes_crypto_btc_ads_health(monkeypatch, tmp_path) -> None:
    db = TradeDB(tmp_path)
    health = {
        "data_readiness": "degraded",
        "blocking_gate": "D3",
        "blocking_reason_code": "SOURCE_DIVERGENCE",
        "cross_source_validation": {"status": "fail", "block_rows": 1},
        "observed": {"watermark": "2026-01-09", "row_count": 730},
    }

    def fake_read_crypto_validation_outputs(_data_root):
        return {
            "tables": {
                "ads_crypto_data_readiness_report": pd.DataFrame(
                    [
                        {
                            "run_id": "validation-run",
                            "generation_id": "generation-1",
                            "data_run_id": "data-run",
                            "data_readiness": "degraded",
                            "watermark": "2026-01-09",
                            "reason_codes": '["SOURCE_DIVERGENCE"]',
                            "evidence_ref": "/tmp/run/manifest.json",
                            "data_health_json": readiness_module.json.dumps(health),
                        }
                    ]
                )
            }
        }

    monkeypatch.setattr(
        "trade_py.data.warehouse.crypto.read_crypto_validation_outputs",
        fake_read_crypto_validation_outputs,
    )
    monkeypatch.setattr(readiness_module, "_collect_repair_runs", lambda *_args, **_kwargs: ({}, {}))
    monkeypatch.setattr(readiness_module, "_collect_gap_ranges", lambda *_args, **_kwargs: {})

    payload = build_readiness_grid(
        tmp_path,
        db,
        days=2,
        end_date="2026-01-09",
        datasets=["crypto_btc"],
        include_actions=False,
    )

    row = payload["rows"][0]
    assert row["dataset"] == "crypto_btc"
    latest = row["cells"][-1]
    previous = row["cells"][0]
    assert latest["status"] == "LATE_READY"
    assert latest["source_last_date"] == "2026-01-09"
    assert latest["reason_codes"] == ["SOURCE_DIVERGENCE"]
    assert latest["data_health"]["blocking_gate"] == "D3"
    assert latest["data_health"]["cross_source_validation"]["block_rows"] == 1
    assert latest["evidence_ref"] == "/tmp/run/manifest.json"
    assert previous["status"] == "LATE_READY"
    assert previous["fingerprint"] != latest["fingerprint"]
