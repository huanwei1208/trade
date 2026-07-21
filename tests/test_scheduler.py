from __future__ import annotations

import json
import threading
import time
from datetime import datetime

import pytest
import schedule

from trade_py.bus import Event, EventBus, Topic, _make_agenda_handler
from trade_py.bus.scheduler import (
    _publish_scheduled_topic,
    _recover_pending_events,
    describe_schedule,
    drain_due_agenda,
    register_schedule,
)
from trade_py.db.trade_db import TradeDB

_CHANNEL_CAPACITIES = {
    "ingest": 1,
    "nlp": 1,
    "signal": 1,
    "decision": 1,
    "io": 1,
}


def _bus(db: TradeDB) -> EventBus:
    return EventBus(
        db,
        ingest_workers=1,
        nlp_workers=1,
        signal_workers=1,
        decision_workers=1,
        io_workers=1,
        channel_capacities=_CHANNEL_CAPACITIES,
    )


def _seed_due_agenda(db: TradeDB, count: int) -> list[int]:
    planned_events = [
        {
            "planned_event_id": f"scheduler-test-{index}",
            "event_date": "2026-07-21",
            "scheduled_at": "2026-07-21 00:00:00",
            "title": f"Scheduler test {index}",
        }
        for index in range(count)
    ]
    db.planned_events_upsert_batch(planned_events)
    db.agenda_queue_upsert_batch(
        [
            {
                "planned_event_id": row["planned_event_id"],
                "phase": "post",
                "run_at": "2026-07-21 00:00:00",
                "job_name": "scheduler_test",
                "priority": index + 1,
            }
            for index, row in enumerate(planned_events)
        ]
    )
    rows = db.agenda_queue_recent(limit=count)
    return sorted(int(row["agenda_id"]) for row in rows)


def _agenda_rows(db: TradeDB) -> dict[int, dict]:
    return {
        int(row["agenda_id"]): row
        for row in db.agenda_queue_recent(limit=100)
        if str(row["planned_event_id"]).startswith("scheduler-test-")
    }


def _seed_trigger_agenda(db: TradeDB, *, trigger_topic: str) -> int:
    db.planned_events_upsert_batch(
        [
            {
                "planned_event_id": "scheduler-test-trigger",
                "event_date": "2026-07-21",
                "scheduled_at": "2026-07-21 00:00:00",
                "title": "Scheduler trigger test",
            }
        ]
    )
    db.agenda_queue_upsert_batch(
        [
            {
                "planned_event_id": "scheduler-test-trigger",
                "phase": "post",
                "run_at": "2026-07-21 00:00:00",
                "trigger_topic": trigger_topic,
                "payload_json": '{"nested":{"value":7}}',
                "priority": 1,
            }
        ]
    )
    row = next(
        row
        for row in db.agenda_queue_recent(limit=100)
        if row["planned_event_id"] == "scheduler-test-trigger"
    )
    return int(row["agenda_id"])


def test_describe_schedule_exposes_morning_evening_and_agenda_jobs(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.trading_calendar_upsert_batch(
        [
            {"exchange": "SSE", "trade_date": "2026-03-20", "is_open": 1},
            {
                "exchange": "SSE",
                "trade_date": "2026-03-22",
                "is_open": 0,
                "pretrade_date": "2026-03-20",
            },
        ]
    )

    items = describe_schedule(db, now=datetime.fromisoformat("2026-03-22T10:00:00"))
    by_topic = {str(item.get("topic") or ""): item for item in items}

    assert "gate.morning" in by_topic
    assert "gate.evening" in by_topic
    assert "gate.crypto_daily" in by_topic
    assert "agenda.due" in by_topic
    assert by_topic["gate.morning"]["trading_day_only"] is True
    assert by_topic["gate.morning"]["state_hint"] == "waiting_trading_day"
    assert by_topic["agenda.due"]["currently_eligible"] is True
    assert by_topic["gate.crypto_daily"]["time"] == "09:00"
    assert by_topic["gate.crypto_daily"]["timezone"] == "Asia/Shanghai"
    assert by_topic["gate.crypto_daily"]["trading_day_only"] is False
    legacy_enabled = db._conn.execute(
        "SELECT enabled FROM pipeline_dag WHERE job_name='cross_asset_fetch'"
    ).fetchone()
    assert legacy_enabled[0] == 0
    crypto_source = db._conn.execute(
        "SELECT source FROM pipeline_dag WHERE job_name='crypto_btc_fetch' AND enabled=1"
    ).fetchone()
    assert crypto_source[0] == "gate.crypto_daily"
    validation_dag = db._conn.execute(
        "SELECT source FROM pipeline_dag WHERE job_name='crypto_research_validation' AND enabled=1"
    ).fetchone()
    assert validation_dag[0] == "data.crypto.synced"


def test_drain_due_agenda_defers_partial_batch_and_daemon_can_continue(tmp_path) -> None:
    db = TradeDB(tmp_path)
    agenda_ids = _seed_due_agenda(db, 3)
    bus = _bus(db)
    first_started = threading.Event()
    release_first = threading.Event()
    handled: list[int] = []

    def handle_agenda(event: Event) -> None:
        agenda_id = int(event.payload["agenda_id"])
        db.agenda_queue_update_status(agenda_id, "running")
        handled.append(agenda_id)
        if agenda_id == agenda_ids[0]:
            first_started.set()
            assert release_first.wait(timeout=3)
        db.agenda_queue_update_status(agenda_id, "done")

    handle_agenda.__qualname__ = "tests.scheduler_agenda"
    bus.subscribe(Topic.AGENDA_DUE, handle_agenda)

    try:
        assert drain_due_agenda(bus, db, limit=3) == 1
        assert first_started.wait(timeout=2)

        rows = _agenda_rows(db)
        assert rows[agenda_ids[0]]["status"] == "running"
        assert rows[agenda_ids[1]]["status"] == "error"
        assert "outcome=saturated" in str(rows[agenda_ids[1]]["result_summary"])
        assert "action=replay_event_bus_event" in str(rows[agenda_ids[1]]["result_summary"])
        assert rows[agenda_ids[2]]["status"] == "pending"
        assert "action=retry_next_scheduler_scan" in str(rows[agenda_ids[2]]["result_summary"])

        release_first.set()
        assert bus.wait_for_idle(timeout_sec=2)
        bus.replay_pending()
        assert bus.wait_for_idle(timeout_sec=2)
        assert drain_due_agenda(bus, db, limit=3) == 1
        assert bus.wait_for_idle(timeout_sec=2)

        rows = _agenda_rows(db)
        assert [rows[agenda_id]["status"] for agenda_id in agenda_ids] == [
            "done",
            "done",
            "done",
        ]
        assert handled == agenda_ids
    finally:
        release_first.set()
        bus.shutdown()
        db.close()


def test_drain_due_agenda_shutdown_defers_without_escaping(tmp_path) -> None:
    db = TradeDB(tmp_path)
    agenda_ids = _seed_due_agenda(db, 2)
    bus = _bus(db)
    bus.subscribe(Topic.AGENDA_DUE, lambda _event: None)
    bus.shutdown()

    assert drain_due_agenda(bus, db, limit=2) == 0

    rows = _agenda_rows(db)
    assert rows[agenda_ids[0]]["status"] == "error"
    assert "outcome=shutting_down" in str(rows[agenda_ids[0]]["result_summary"])
    assert rows[agenda_ids[1]]["status"] == "pending"
    assert "prior_outcome=shutting_down" in str(rows[agenda_ids[1]]["result_summary"])
    db.close()


def test_drain_due_agenda_submission_failure_records_actionable_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    agenda_ids = _seed_due_agenda(db, 2)
    bus = _bus(db)
    bus.subscribe(Topic.AGENDA_DUE, lambda _event: None)

    def fail_submit(*_args, **_kwargs) -> None:
        raise RuntimeError("executor unavailable")

    monkeypatch.setattr(bus._pools["ingest"], "submit", fail_submit)

    try:
        assert drain_due_agenda(bus, db, limit=2) == 0

        rows = _agenda_rows(db)
        current_summary = str(rows[agenda_ids[0]]["result_summary"])
        assert rows[agenda_ids[0]]["status"] == "error"
        assert "outcome=submission_failed" in current_summary
        assert "executor unavailable" in current_summary
        assert "action=replay_event_bus_event" in current_summary
        assert rows[agenda_ids[1]]["status"] == "pending"
        assert "prior_outcome=submission_failed" in str(rows[agenda_ids[1]]["result_summary"])
    finally:
        bus.shutdown()
        db.close()


def test_drain_due_agenda_publish_exception_restores_current_and_unattempted(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = TradeDB(tmp_path)
    agenda_ids = _seed_due_agenda(db, 3)
    bus = _bus(db)
    original_publish = bus.publish_once
    publish_calls = 0

    def fail_second_publish(*args, **kwargs):
        nonlocal publish_calls
        publish_calls += 1
        if publish_calls >= 2:
            raise RuntimeError("database unavailable")
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(bus, "publish_once", fail_second_publish)

    try:
        with caplog.at_level("ERROR"):
            assert drain_due_agenda(bus, db, limit=3) == 1

        rows = _agenda_rows(db)
        assert rows[agenda_ids[0]]["status"] == "queued"
        for agenda_id in agenda_ids[1:]:
            assert rows[agenda_id]["status"] == "pending"
            summary = str(rows[agenda_id]["result_summary"])
            assert "failed before typed outcome" in summary
            assert "action=retry_next_scheduler_scan" in summary
        assert "agenda_id=" in caplog.text
        assert "job_name=scheduler_test" in caplog.text
        assert "accepted=1" in caplog.text
    finally:
        bus.shutdown()
        db.close()


def test_drain_due_agenda_post_commit_exception_reuses_durable_event(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    agenda_id = _seed_due_agenda(db, 1)[0]
    bus = _bus(db)
    handled = threading.Event()
    bus.subscribe(Topic.AGENDA_DUE, lambda _event: handled.set())
    original_publish = bus.publish_once
    calls = 0

    def raise_after_commit(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original_publish(*args, **kwargs)
        if calls == 1:
            raise RuntimeError("connection lost after commit")
        return result

    monkeypatch.setattr(bus, "publish_once", raise_after_commit)

    assert drain_due_agenda(bus, db, limit=1) == 1
    assert handled.wait(timeout=2)
    assert bus.wait_for_idle(timeout_sec=2)

    events = db.event_log_recent(limit=10, topic=Topic.AGENDA_DUE)
    assert len(events) == 1
    assert json.loads(str(events[0]["payload"]))["agenda_id"] == agenda_id
    assert calls == 2
    bus.shutdown()
    db.close()


def test_nested_agenda_trigger_records_durable_child_deferred_outcome(tmp_path) -> None:
    db = TradeDB(tmp_path)
    agenda_id = _seed_trigger_agenda(db, trigger_topic="ops.agenda_child")
    bus = _bus(db)
    blocker_started = threading.Event()
    blocker_release = threading.Event()
    child_calls: list[int] = []

    def block(_event: Event) -> None:
        blocker_started.set()
        assert blocker_release.wait(timeout=3)

    bus.subscribe("ops.blocker", block)
    bus.subscribe("ops.agenda_child", lambda event: child_calls.append(event.id))
    bus.subscribe(Topic.AGENDA_DUE, _make_agenda_handler(db, str(tmp_path)))
    bus.publish("ops.blocker")
    assert blocker_started.wait(timeout=2)

    assert drain_due_agenda(bus, db, limit=1) == 1
    deadline = time.monotonic() + 2
    while (
        _agenda_rows(db)[agenda_id]["status"] in {"queued", "running"}
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)

    row = _agenda_rows(db)[agenda_id]
    assert row["status"] == "error"
    assert "agenda child deferred" in str(row["result_summary"])
    assert "outcome=saturated" in str(row["result_summary"])
    children = db.event_log_recent(limit=10, topic="ops.agenda_child")
    assert len(children) == 1
    child_id = int(children[0]["id"])
    assert f"child_event_id={child_id}" in str(row["result_summary"])

    blocker_release.set()
    assert bus.wait_for_idle(timeout_sec=2)
    bus.replay_pending()
    assert bus.wait_for_idle(min_event_id=child_id, timeout_sec=2)
    assert child_calls == [child_id]
    bus.shutdown()
    db.close()


def test_nested_agenda_trigger_reuses_child_after_post_commit_exception(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    agenda_id = _seed_trigger_agenda(db, trigger_topic="ops.agenda_child_once")
    bus = _bus(db)
    child_calls: list[int] = []
    bus.subscribe(
        "ops.agenda_child_once",
        lambda event: child_calls.append(event.id),
    )
    bus.subscribe(Topic.AGENDA_DUE, _make_agenda_handler(db, str(tmp_path)))
    original_publish_child = bus.publish_child_once
    calls = 0

    def raise_after_commit(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original_publish_child(*args, **kwargs)
        if calls == 1:
            raise RuntimeError("connection lost after child commit")
        return result

    monkeypatch.setattr(bus, "publish_child_once", raise_after_commit)

    assert drain_due_agenda(bus, db, limit=1) == 1
    assert bus.wait_for_idle(timeout_sec=2)

    children = db.event_log_recent(limit=10, topic="ops.agenda_child_once")
    assert len(children) == 1
    assert child_calls == [int(children[0]["id"])]
    row = _agenda_rows(db)[agenda_id]
    assert row["status"] == "done"
    assert calls == 2
    bus.shutdown()
    db.close()


def test_scheduled_gate_saturation_is_durable_and_does_not_escape(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def block(event: Event) -> None:
        calls.append(event.id)
        started.set()
        assert release.wait(timeout=3)

    block.__qualname__ = "tests.scheduler_gate"
    bus.subscribe(Topic.GATE_MORNING, block)
    first = bus.publish(Topic.GATE_MORNING)
    assert started.wait(timeout=2)

    assert _publish_scheduled_topic(bus, Topic.GATE_MORNING) is False
    rows = db.event_log_recent(limit=2, topic=Topic.GATE_MORNING)
    deferred_id = max(int(row["id"]) for row in rows)
    deferred = next(row for row in rows if int(row["id"]) == deferred_id)
    assert deferred["status"] == "error"
    assert "runtime_admission:saturated" in str(deferred["error"])

    release.set()
    assert bus.wait_for_idle(min_event_id=first.id, timeout_sec=2)
    _recover_pending_events(bus)
    assert bus.wait_for_idle(min_event_id=deferred_id, timeout_sec=2)
    assert calls == [first.id, deferred_id]
    bus.shutdown()
    db.close()


def test_scheduled_gate_persistence_failure_does_not_escape(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)

    def fail_publish(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(bus, "publish_with_outcome", fail_publish)

    assert _publish_scheduled_topic(bus, Topic.GATE_EVENING) is False
    bus.shutdown()
    db.close()


def test_periodic_recovery_reclaims_expired_durable_handler(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    handled = threading.Event()

    def handle(_event: Event) -> None:
        handled.set()

    handler_name = "tests.expired_claim"
    handle.__qualname__ = handler_name
    bus.subscribe("ops.expired_claim", handle)
    event_id = db.event_log_insert("ops.expired_claim", "{}")
    db.prepare_handler_runs(event_id, [handler_name])
    assert db.claim_handler_run(event_id, handler_name, "dead-runtime")
    db._conn.execute(
        """
        UPDATE event_handler_runs
        SET started_at=datetime('now', 'localtime', '-10 minutes')
        WHERE event_id=? AND handler_name=?
        """,
        (event_id, handler_name),
    )
    db._conn.commit()

    _recover_pending_events(bus)

    assert handled.wait(timeout=2)
    assert bus.wait_for_idle(min_event_id=event_id, timeout_sec=2)
    assert db.event_log_recent(limit=1)[0]["status"] == "ok"
    bus.shutdown()
    db.close()


def test_register_schedule_adds_bounded_periodic_recovery(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    schedule.clear()
    try:
        register_schedule(bus, db)

        recovery_jobs = [
            job
            for job in schedule.jobs
            if getattr(job.job_func, "func", None) is _recover_pending_events
        ]
        assert len(recovery_jobs) == 1
        assert recovery_jobs[0].interval == 1
        assert recovery_jobs[0].unit == "minutes"
    finally:
        schedule.clear()
        bus.shutdown()
        db.close()
