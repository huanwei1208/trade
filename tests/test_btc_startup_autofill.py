from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trade_py.bus import EventBus
from trade_py.db.trade_db import TradeDB
from trade_web.backend.runtime.startup_autofill import (
    BTC_AUTOFILL_JOB_NAME,
    BTC_AUTOFILL_TOPIC,
    BTC_STARTUP_CHECK_TOPIC,
    build_btc_startup_gap_decision,
    publish_btc_startup_gap_check,
    register_btc_startup_autofill_handlers,
)


def _bus(db: TradeDB) -> EventBus:
    return EventBus(
        db,
        ingest_workers=1,
        nlp_workers=1,
        signal_workers=1,
        decision_workers=1,
        io_workers=1,
        channel_capacities={
            "ingest": 2,
            "nlp": 1,
            "signal": 1,
            "decision": 1,
            "io": 1,
        },
    )


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    return json.loads(str(row["payload"]))


def _write_current_pointer(data_root: Path) -> None:
    crypto_root = data_root / "market" / "crypto"
    crypto_root.mkdir(parents=True)
    (crypto_root / "btc_current.json").write_text(
        json.dumps(
            {
                "run_id": "btc-run",
                "canonical_sha256": "0" * 64,
                "manifest_path": str(crypto_root / "runs" / "btc" / "btc-run" / "manifest.json"),
                "run_dir": str(crypto_root / "runs" / "btc" / "btc-run"),
            }
        ),
        encoding="utf-8",
    )


def test_btc_startup_gap_decision_does_not_autofill_empty_root(tmp_path: Path) -> None:
    decision = build_btc_startup_gap_decision(
        tmp_path,
        now=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )

    assert decision.should_autofill is False
    assert decision.payload["decision"] == "no_autofill"
    assert decision.payload["title"] == "BTC startup data check"
    assert decision.payload["phase"] == "not_bootstrapped"
    assert decision.payload["reason_code"] == "BTC_CURRENT_POINTER_MISSING"
    assert decision.payload["current_exists"] is False
    assert decision.payload["check_date"] == "2026-07-22"
    assert "events_api" in decision.payload["visibility"]


def test_btc_startup_gap_check_does_not_publish_for_empty_root(tmp_path: Path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    try:
        register_btc_startup_autofill_handlers(db, bus, str(tmp_path))

        decision = publish_btc_startup_gap_check(
            db,
            bus,
            str(tmp_path),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        check_rows = db.event_log_recent(limit=10, topic=BTC_STARTUP_CHECK_TOPIC)
        repair_rows = db.event_log_recent(limit=10, topic=BTC_AUTOFILL_TOPIC)
        runs = db.job_runs_recent(limit=10)
    finally:
        bus.shutdown()
        db.close()

    assert decision.should_autofill is False
    assert check_rows == []
    assert repair_rows == []
    assert runs == []


def test_btc_startup_gap_check_enqueues_visible_autofill_event_and_job(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _write_current_pointer(tmp_path)

    def inspect_btc_status(_data_root: str, *, as_of: Any | None = None) -> dict[str, Any]:
        del as_of
        return {
            "data_readiness": "degraded",
            "reason_code": "CANONICAL_STALE",
            "reason_codes": ["CANONICAL_STALE"],
            "operational_freshness": {
                "watermark": "2026-07-11",
                "expected_latest_open": "2026-07-21",
                "staleness_days": 10,
                "maximum_staleness_days": 1,
                "fresh": False,
            },
            "health": {
                "observed": {"watermark": "2026-07-11"},
                "blocking_reason_code": "CANONICAL_STALE",
            },
        }

    run_calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def run_job(name: str, data_root: str, config: dict[str, Any] | None = None) -> str:
        run_calls.append((name, data_root, config))
        return "BTC assurance sync completed"

    monkeypatch.setattr("trade_py.data.market.crypto.store.inspect_btc_status", inspect_btc_status)
    monkeypatch.setattr("trade_py.jobs.run_job", run_job)

    db = TradeDB(tmp_path)
    bus = _bus(db)
    try:
        register_btc_startup_autofill_handlers(db, bus, str(tmp_path))

        decision = publish_btc_startup_gap_check(
            db,
            bus,
            str(tmp_path),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        assert bus.wait_for_idle(timeout_sec=2)

        check_rows = db.event_log_recent(limit=10, topic=BTC_STARTUP_CHECK_TOPIC)
        repair_rows = db.event_log_recent(limit=10, topic=BTC_AUTOFILL_TOPIC)
        synced_rows = db.event_log_recent(limit=10, topic="data.crypto.synced")
        runs = db.job_runs_recent(limit=10, stage="fetch")
    finally:
        bus.shutdown()
        db.close()

    assert decision.should_autofill is True
    assert len(check_rows) == 1
    assert len(repair_rows) == 1
    assert len(synced_rows) == 1
    assert check_rows[0]["status"] == "ok"
    assert repair_rows[0]["status"] == "ok"
    assert int(repair_rows[0]["parent_event_id"]) == int(check_rows[0]["id"])

    check_payload = _payload(check_rows[0])
    assert check_payload["title"] == "BTC data auto-fill requested"
    assert check_payload["phase"] == "repair_requested"
    assert check_payload["status_text"] == (
        "BTC data is not ready; startup queued an assurance sync job."
    )
    assert check_payload["decision"] == "enqueue_autofill"
    assert check_payload["reason_code"] == "CANONICAL_STALE"
    assert check_payload["watermark"] == "2026-07-11"
    assert check_payload["expected_latest_open"] == "2026-07-21"

    repair_payload = _payload(repair_rows[0])
    assert repair_payload["title"] == "BTC data auto-fill job"
    assert repair_payload["phase"] == "repair_job"
    assert repair_payload["action"] == "btc_auto_fill"
    assert repair_payload["job_name"] == BTC_AUTOFILL_JOB_NAME
    assert repair_payload["job_mode"] == "assurance_sync"
    assert repair_payload["source_event_id"] == check_rows[0]["id"]
    assert repair_payload["visibility"]["runs_api"] == "/api/runs?stage=fetch"

    assert run_calls == [(BTC_AUTOFILL_JOB_NAME, str(tmp_path), {"trigger": "startup_autofill"})]
    assert len(runs) == 1
    assert runs[0]["job_name"] == BTC_AUTOFILL_JOB_NAME
    assert runs[0]["status"] == "ok"
    assert runs[0]["trigger_event_id"] == repair_rows[0]["id"]
    assert runs[0]["result_summary"] == "BTC assurance sync completed"


def test_btc_autofill_records_quality_warning_without_downstream_sync(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from trade_py.jobs import JobQualityWarning

    _write_current_pointer(tmp_path)

    def inspect_btc_status(_data_root: str, *, as_of: Any | None = None) -> dict[str, Any]:
        del as_of
        return {
            "data_readiness": "degraded",
            "reason_code": "CANONICAL_STALE",
            "reason_codes": ["CANONICAL_STALE"],
            "operational_freshness": {
                "watermark": "2026-07-18",
                "expected_latest_open": "2026-07-21",
                "staleness_days": 3,
                "maximum_staleness_days": 1,
                "fresh": False,
            },
        }

    def run_job(_name: str, _data_root: str, config: dict[str, Any] | None = None) -> str:
        del config
        raise JobQualityWarning(
            "BTC 候选已暂存，等待采集稳定性门禁: run_id=abc qualified_days=3/29"
        )

    monkeypatch.setattr("trade_py.data.market.crypto.store.inspect_btc_status", inspect_btc_status)
    monkeypatch.setattr("trade_py.jobs.run_job", run_job)

    db = TradeDB(tmp_path)
    bus = _bus(db)
    try:
        register_btc_startup_autofill_handlers(db, bus, str(tmp_path))

        publish_btc_startup_gap_check(
            db,
            bus,
            str(tmp_path),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        assert bus.wait_for_idle(timeout_sec=2)

        repair_rows = db.event_log_recent(limit=10, topic=BTC_AUTOFILL_TOPIC)
        synced_rows = db.event_log_recent(limit=10, topic="data.crypto.synced")
        runs = db.job_runs_recent(limit=10, stage="fetch")
    finally:
        bus.shutdown()
        db.close()

    assert len(repair_rows) == 1
    assert repair_rows[0]["status"] == "ok"
    assert synced_rows == []
    assert len(runs) == 1
    assert runs[0]["job_name"] == BTC_AUTOFILL_JOB_NAME
    assert runs[0]["status"] == "warn"
    assert "qualified_days=3/29" in runs[0]["result_summary"]


def test_btc_startup_gap_check_is_idempotent_per_watermark(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _write_current_pointer(tmp_path)

    def inspect_btc_status(_data_root: str, *, as_of: Any | None = None) -> dict[str, Any]:
        del as_of
        return {
            "data_readiness": "degraded",
            "reason_code": "CANONICAL_STALE",
            "reason_codes": ["CANONICAL_STALE"],
            "operational_freshness": {
                "watermark": "2026-07-11",
                "expected_latest_open": "2026-07-21",
                "staleness_days": 10,
                "maximum_staleness_days": 1,
                "fresh": False,
            },
        }

    calls = 0

    def run_job(_name: str, _data_root: str, config: dict[str, Any] | None = None) -> str:
        nonlocal calls
        del config
        calls += 1
        return "ok"

    monkeypatch.setattr("trade_py.data.market.crypto.store.inspect_btc_status", inspect_btc_status)
    monkeypatch.setattr("trade_py.jobs.run_job", run_job)

    db = TradeDB(tmp_path)
    bus = _bus(db)
    try:
        register_btc_startup_autofill_handlers(db, bus, str(tmp_path))
        when = datetime(2026, 7, 22, tzinfo=timezone.utc)

        publish_btc_startup_gap_check(db, bus, str(tmp_path), now=when)
        assert bus.wait_for_idle(timeout_sec=2)
        publish_btc_startup_gap_check(db, bus, str(tmp_path), now=when)
        assert bus.wait_for_idle(timeout_sec=2)

        check_rows = db.event_log_recent(limit=10, topic=BTC_STARTUP_CHECK_TOPIC)
        repair_rows = db.event_log_recent(limit=10, topic=BTC_AUTOFILL_TOPIC)
        runs = db.job_runs_recent(limit=10, stage="fetch")
    finally:
        bus.shutdown()
        db.close()

    assert len(check_rows) == 1
    assert len(repair_rows) == 1
    assert len(runs) == 1
    assert calls == 1
