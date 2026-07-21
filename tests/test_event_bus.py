from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import pytest

from trade_py.bus import (
    Event,
    EventAdmissionError,
    EventBus,
    _make_dag_handler,
    bootstrap_from_dag,
    dispatch_dag_row,
)
from trade_py.bus.models import AdmissionOutcome, BusLifecycle, RuntimeCapacityStatus
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


def _named_handler(
    name: str,
    callback: Callable[[Event], None],
) -> Callable[[Event], None]:
    callback.__name__ = name
    callback.__qualname__ = name
    return callback


def _event_row(db: TradeDB, event_id: int) -> dict:
    row = db._conn.execute(
        "SELECT * FROM event_log WHERE id=?",
        (event_id,),
    ).fetchone()
    assert row is not None
    return dict(row)


def test_event_bus_validates_channel_configuration_before_start(tmp_path) -> None:
    db = TradeDB(tmp_path)

    with pytest.raises(ValueError, match="ingest workers must be positive"):
        EventBus(db, ingest_workers=0)
    with pytest.raises(ValueError, match="unknown EventBus channels: other"):
        EventBus(db, channel_capacities={"other": 1})

    bus = EventBus(db)
    snapshots = {name: admission.snapshot() for name, admission in bus._admission.items()}
    assert snapshots["ingest"].workers == 4
    assert snapshots["ingest"].capacity == 8
    assert snapshots["decision"].workers == 2
    assert snapshots["decision"].capacity == 4
    bus.shutdown()
    db.close()


def test_event_bus_reports_exact_database_binding(tmp_path) -> None:
    first_db = TradeDB(tmp_path)
    second_db = TradeDB(tmp_path)
    bus = _bus(first_db)

    assert bus.is_bound_to(first_db) is True
    assert bus.is_bound_to(second_db) is False

    bus.shutdown()
    first_db.close()
    second_db.close()


def test_capacity_snapshot_is_process_local_bounded_and_resets(tmp_path) -> None:
    db = TradeDB(tmp_path)
    first_bus = _bus(db)

    first = first_bus.capacity_snapshot()

    assert first.status is RuntimeCapacityStatus.READY
    assert first.lifecycle is BusLifecycle.READY
    assert len(first.channels) == 5
    assert {channel.name for channel in first.channels} == set(_CHANNEL_CAPACITIES)
    assert all(channel.admitted == 0 for channel in first.channels)
    assert all(channel.active == 0 for channel in first.channels)
    assert all(channel.available == channel.capacity for channel in first.channels)
    assert all(channel.last_saturation_at is None for channel in first.channels)

    first_bus.shutdown()
    stopped = first_bus.capacity_snapshot()
    assert stopped.generation == first.generation
    assert stopped.status is RuntimeCapacityStatus.STOPPED
    assert stopped.lifecycle is BusLifecycle.STOPPED

    second_bus = _bus(db)
    second = second_bus.capacity_snapshot()
    assert second.generation != first.generation
    assert second.status is RuntimeCapacityStatus.READY
    assert all(channel.accepted_count == 0 for channel in second.channels)
    assert all(channel.saturated_count == 0 for channel in second.channels)
    second_bus.shutdown()
    db.close()


def test_publish_preserves_event_return_for_accepted_work(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    handled = threading.Event()
    handler = _named_handler("tests.accepted", lambda _event: handled.set())
    bus.subscribe("ops.accepted", handler)

    event = bus.publish("ops.accepted", {"value": 7})

    assert isinstance(event, Event)
    assert event.payload == {"value": 7}
    assert handled.wait(timeout=2)
    assert bus.wait_for_idle(min_event_id=event.id, timeout_sec=2)
    assert _event_row(db, event.id)["status"] == "ok"
    bus.shutdown()
    db.close()


@pytest.mark.parametrize(
    "payload",
    [None, [], "", 0, False, {"score": float("nan")}, {"score": float("inf")}],
)
def test_publish_rejects_non_dict_payload_before_persistence(
    tmp_path,
    payload: object,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)

    error = TypeError if not isinstance(payload, dict) else ValueError
    with pytest.raises(error):
        bus.publish("ops.invalid_publish", cast(dict, payload))
    with pytest.raises(error):
        bus.publish_with_outcome("ops.invalid_publish", cast(dict, payload))

    count = db._conn.execute(
        "SELECT COUNT(*) FROM event_log WHERE topic='ops.invalid_publish'"
    ).fetchone()[0]
    assert count == 0
    bus.shutdown()
    db.close()


def test_omitted_payload_is_empty_immutable_snapshot(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    received: list[Event] = []
    bus.subscribe(
        "ops.omitted_payload",
        _named_handler("tests.omitted_payload", lambda event: received.append(event)),
    )

    event = bus.publish("ops.omitted_payload")

    assert bus.wait_for_idle(min_event_id=event.id, timeout_sec=2)
    assert event.payload == {}
    assert received == [event]
    with pytest.raises(TypeError):
        cast(dict, event.payload)["late"] = True
    assert _event_row(db, event.id)["payload"] == "{}"
    bus.shutdown()
    db.close()


def test_publish_dispatches_canonical_snapshot_before_caller_mutation(tmp_path) -> None:
    db = TradeDB(tmp_path)
    capacities = dict(_CHANNEL_CAPACITIES)
    capacities["io"] = 2
    bus = EventBus(
        db,
        ingest_workers=1,
        nlp_workers=1,
        signal_workers=1,
        decision_workers=1,
        io_workers=1,
        channel_capacities=capacities,
    )
    blocker_started = threading.Event()
    release_blocker = threading.Event()
    received: list[Event] = []

    def block(_event: Event) -> None:
        blocker_started.set()
        assert release_blocker.wait(timeout=3)

    bus.subscribe("ops.snapshot_blocker", _named_handler("tests.snapshot_blocker", block))
    bus.subscribe(
        "ops.snapshot",
        _named_handler("tests.snapshot", lambda event: received.append(event)),
    )
    bus.publish("ops.snapshot_blocker")
    assert blocker_started.wait(timeout=2)
    payload: dict[str, object] = {"nested": {"items": [1, 2]}}
    event = bus.publish("ops.snapshot", payload)

    nested = cast(dict[str, object], payload["nested"])
    cast(list[int], nested["items"]).append(3)
    nested["other"] = "late"
    release_blocker.set()

    assert bus.wait_for_idle(min_event_id=event.id, timeout_sec=2)
    assert len(received) == 1
    snapshot = received[0].payload
    assert snapshot["nested"]["items"] == (1, 2)
    assert "other" not in snapshot["nested"]
    persisted = json.loads(str(_event_row(db, event.id)["payload"]))
    assert persisted == {"nested": {"items": [1, 2]}}
    bus.shutdown()
    db.close()


def test_saturation_is_prompt_durable_and_replayable(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def block(event: Event) -> None:
        calls.append(event.id)
        started.set()
        assert release.wait(timeout=3)

    handler = _named_handler("tests.block_io", block)
    bus.subscribe("ops.blocked", handler)
    first = bus.publish("ops.blocked")
    assert started.wait(timeout=2)

    started_at = time.monotonic()
    second = bus.publish_with_outcome("ops.blocked")
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.5
    assert second.outcome is AdmissionOutcome.SATURATED
    assert second.handlers[0].outcome is AdmissionOutcome.SATURATED
    handler_row = db.get_handler_run(second.event.id, "tests.block_io")
    assert handler_row is not None
    assert str(handler_row["error_message"]).startswith("runtime_admission:saturated:")
    assert _event_row(db, second.event.id)["status"] == "error"

    release.set()
    assert bus.wait_for_idle(min_event_id=first.id, timeout_sec=2)
    bus.replay_pending()
    assert bus.wait_for_idle(min_event_id=second.event.id, timeout_sec=2)

    assert calls == [first.id, second.event.id]
    assert _event_row(db, second.event.id)["status"] == "ok"
    assert bus._admission["io"].snapshot().admitted == 0
    bus.shutdown()
    db.close()


def test_real_executor_never_admits_above_configured_capacity(tmp_path) -> None:
    db = TradeDB(tmp_path)
    capacities = dict(_CHANNEL_CAPACITIES)
    capacities["io"] = 2
    bus = EventBus(
        db,
        ingest_workers=1,
        nlp_workers=1,
        signal_workers=1,
        decision_workers=1,
        io_workers=1,
        channel_capacities=capacities,
    )
    first_started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    completed = 0
    completed_lock = threading.Lock()

    def block(_event: Event) -> None:
        nonlocal completed
        first_started.set()
        assert release.wait(timeout=3)
        with completed_lock:
            completed += 1
            if completed == 2:
                finished.set()

    bus.subscribe("ops.capacity", _named_handler("tests.capacity", block))
    first = bus.publish_with_outcome("ops.capacity")
    assert first_started.wait(timeout=2)
    second = bus.publish_with_outcome("ops.capacity")
    third = bus.publish_with_outcome("ops.capacity")

    snapshot = bus._admission["io"].snapshot()
    assert first.outcome is AdmissionOutcome.ACCEPTED
    assert second.outcome is AdmissionOutcome.ACCEPTED
    assert third.outcome is AdmissionOutcome.SATURATED
    assert snapshot.capacity == 2
    assert snapshot.admitted == 2
    assert snapshot.active == 1
    assert snapshot.available == 0
    runtime_snapshot = bus.capacity_snapshot()
    assert runtime_snapshot.status is RuntimeCapacityStatus.SATURATED

    release.set()
    assert finished.wait(timeout=2)
    assert bus.wait_for_idle(min_event_id=first.event.id, timeout_sec=2)
    snapshot = bus._admission["io"].snapshot()
    assert snapshot.admitted == 0
    assert snapshot.active == 0
    assert snapshot.available == 2
    bus.shutdown()
    db.close()


def test_saturation_logs_are_structured_rate_limited_and_payload_safe(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    started = threading.Event()
    release = threading.Event()

    def block(_event: Event) -> None:
        started.set()
        assert release.wait(timeout=3)

    bus.subscribe("ops.logs", _named_handler("tests.logs", block))
    bus.publish("ops.logs", {"secret": "do-not-log"})
    assert started.wait(timeout=2)

    with caplog.at_level(logging.WARNING, logger="trade_py.bus"):
        first = bus.publish_with_outcome("ops.logs", {"secret": "do-not-log"})
        second = bus.publish_with_outcome("ops.logs", {"secret": "do-not-log"})

    assert first.outcome is AdmissionOutcome.SATURATED
    assert second.outcome is AdmissionOutcome.SATURATED
    records = [
        record
        for record in caplog.records
        if getattr(record, "admission_outcome", None) == "saturated"
    ]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "event_id", None) == first.event.id
    assert getattr(record, "handler_name", None) == "tests.logs"
    assert getattr(record, "event_topic", None) == "ops.logs"
    assert getattr(record, "event_channel", None) == "io"
    assert getattr(record, "channel_capacity", None) == 1
    assert "do-not-log" not in record.getMessage()

    release.set()
    bus.shutdown()
    db.close()


def test_legacy_publish_raises_typed_error_when_saturated(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    started = threading.Event()
    release = threading.Event()

    def block(_event: Event) -> None:
        started.set()
        assert release.wait(timeout=3)

    bus.subscribe("ops.raise", _named_handler("tests.raise", block))
    bus.publish("ops.raise")
    assert started.wait(timeout=2)

    with pytest.raises(EventAdmissionError) as raised:
        bus.publish("ops.raise")

    assert raised.value.result.outcome is AdmissionOutcome.SATURATED
    release.set()
    bus.shutdown()
    db.close()


def test_partial_multi_handler_event_never_finalizes_early(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    release = threading.Event()
    calls: list[str] = []

    def first(_event: Event) -> None:
        calls.append("first")
        assert release.wait(timeout=3)

    def second(_event: Event) -> None:
        calls.append("second")

    bus.subscribe("ops.partial", _named_handler("tests.partial.first", first))
    bus.subscribe("ops.partial", _named_handler("tests.partial.second", second))

    result = bus.publish_with_outcome("ops.partial")

    assert result.outcome is AdmissionOutcome.SATURATED
    assert [item.outcome for item in result.handlers] == [
        AdmissionOutcome.ACCEPTED,
        AdmissionOutcome.SATURATED,
    ]
    runs = {
        row["handler_name"]: row["status"]
        for row in db._conn.execute(
            "SELECT handler_name, status FROM event_handler_runs WHERE event_id=?",
            (result.event.id,),
        ).fetchall()
    }
    assert runs == {
        "tests.partial.first": "running",
        "tests.partial.second": "error",
    }
    assert _event_row(db, result.event.id)["status"] == "error"

    release.set()
    assert bus.wait_for_idle(min_event_id=result.event.id, timeout_sec=2)
    assert _event_row(db, result.event.id)["status"] == "error"
    bus.replay_pending()
    assert bus.wait_for_idle(min_event_id=result.event.id, timeout_sec=2)

    assert calls == ["first", "second"]
    assert _event_row(db, result.event.id)["status"] == "ok"
    bus.shutdown()
    db.close()


def test_channel_capacity_is_isolated(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    nlp_started = threading.Event()
    release = threading.Event()
    decision_done = threading.Event()

    def block_nlp(_event: Event) -> None:
        nlp_started.set()
        assert release.wait(timeout=3)

    bus.subscribe("news.blocked", _named_handler("tests.nlp", block_nlp))
    bus.subscribe(
        "belief.ready",
        _named_handler("tests.decision", lambda _event: decision_done.set()),
    )
    bus.publish("news.blocked")
    assert nlp_started.wait(timeout=2)

    nlp_result = bus.publish_with_outcome("news.blocked")
    decision_result = bus.publish_with_outcome("belief.ready")

    assert nlp_result.outcome is AdmissionOutcome.SATURATED
    assert decision_result.outcome is AdmissionOutcome.ACCEPTED
    assert decision_done.wait(timeout=2)
    release.set()
    bus.shutdown()
    db.close()


def test_submission_failure_releases_permit_and_preserves_root_cause(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    bus.subscribe("ops.submit", _named_handler("tests.submit", lambda _event: None))
    pool = bus._pools["io"]

    def fail_submit(*_args, **_kwargs):
        raise RuntimeError("executor unavailable")

    with caplog.at_level(logging.ERROR, logger="trade_py.bus"):
        with monkeypatch.context() as patch:
            patch.setattr(pool, "submit", fail_submit)
            result = bus.publish_with_outcome("ops.submit", {"secret": "do-not-log"})

    assert result.outcome is AdmissionOutcome.SUBMISSION_FAILED
    assert isinstance(result.handlers[0].cause, RuntimeError)
    assert "executor unavailable" in str(result.handlers[0].cause)
    assert bus._admission["io"].snapshot().admitted == 0
    assert bus._admission["io"].snapshot().submission_failed_count == 1
    handler_row = db.get_handler_run(result.event.id, "tests.submit")
    assert handler_row is not None
    assert handler_row["status"] == "error"
    assert str(handler_row["error_message"]).startswith("runtime_admission:submission_failed:")
    records = [
        record
        for record in caplog.records
        if getattr(record, "admission_outcome", None) == "submission_failed"
    ]
    assert len(records) == 1
    assert getattr(records[0], "event_id", None) == result.event.id
    assert getattr(records[0], "event_channel", None) == "io"
    assert "do-not-log" not in records[0].getMessage()

    bus.replay_pending()
    assert bus.wait_for_idle(min_event_id=result.event.id, timeout_sec=2)
    assert _event_row(db, result.event.id)["status"] == "ok"
    bus.shutdown()
    db.close()


def test_claim_heartbeat_start_failure_is_replayable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    calls: list[int] = []
    bus.subscribe(
        "ops.heartbeat_start",
        _named_handler(
            "tests.heartbeat_start",
            lambda event: calls.append(event.id),
        ),
    )

    with monkeypatch.context() as patch:
        patch.setattr(
            threading.Thread,
            "start",
            lambda _thread: (_ for _ in ()).throw(RuntimeError("thread unavailable")),
        )
        result = bus.publish_with_outcome("ops.heartbeat_start")

    assert result.outcome is AdmissionOutcome.SUBMISSION_FAILED
    assert isinstance(result.handlers[0].cause, RuntimeError)
    assert bus._admission["io"].snapshot().admitted == 0
    handler_row = db.get_handler_run(result.event.id, "tests.heartbeat_start")
    assert handler_row is not None
    assert handler_row["status"] == "error"
    assert str(handler_row["error_message"]).startswith("runtime_admission:submission_failed:")
    assert "claim heartbeat" in str(handler_row["error_message"])
    assert _event_row(db, result.event.id)["status"] == "error"

    bus.replay_pending()
    assert bus.wait_for_idle(min_event_id=result.event.id, timeout_sec=2)
    assert calls == [result.event.id]
    assert _event_row(db, result.event.id)["status"] == "ok"
    bus.shutdown()
    db.close()


def test_shutdown_rejects_new_work_without_executor_submission(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    bus.subscribe("ops.stopped", _named_handler("tests.stopped", lambda _event: None))
    bus.shutdown()

    result = bus.publish_with_outcome("ops.stopped")

    assert result.outcome is AdmissionOutcome.SHUTTING_DOWN
    assert _event_row(db, result.event.id)["status"] == "error"
    assert bus._admission["io"].snapshot().admitted == 0
    bus.shutdown()
    db.close()


def test_shutdown_rejects_topic_without_handlers(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    bus.shutdown()

    result = bus.publish_with_outcome("ops.no_handler")

    assert result.outcome is AdmissionOutcome.SHUTTING_DOWN
    assert result.handlers[0].handler_name == "<no_handler>"
    row = _event_row(db, result.event.id)
    assert row["status"] == "pending"
    assert row["handler"] is None

    replayed: list[int] = []
    restarted = _bus(db)
    restarted.subscribe(
        "ops.no_handler",
        _named_handler("tests.no_handler_restart", lambda event: replayed.append(event.id)),
    )
    restarted.replay_pending()
    assert restarted.wait_for_idle(min_event_id=result.event.id, timeout_sec=2)
    assert replayed == [result.event.id]
    assert _event_row(db, result.event.id)["status"] == "ok"
    restarted.shutdown()
    db.close()


def test_replay_preserves_historical_error_when_handler_is_unavailable(tmp_path) -> None:
    db = TradeDB(tmp_path)
    event_id = db.event_log_insert("ops.missing", "{}")
    db.event_log_complete(
        event_id,
        "error",
        "tests.missing",
        "handler unavailable",
    )
    bus = _bus(db)

    bus.replay_pending()

    row = _event_row(db, event_id)
    assert row["status"] == "error"
    assert row["error"] == "handler unavailable"
    bus.shutdown()
    db.close()


def test_replay_preserves_pending_when_durable_handler_is_unavailable(tmp_path) -> None:
    db = TradeDB(tmp_path)
    event_id = db.event_log_insert("ops.missing_pending", "{}")
    db.prepare_handler_runs(event_id, ["tests.missing_pending"])
    bus = _bus(db)

    bus.replay_pending()

    row = _event_row(db, event_id)
    handler_row = db.get_handler_run(event_id, "tests.missing_pending")
    assert row["status"] == "pending"
    assert handler_row is not None
    assert handler_row["status"] == "pending"
    bus.shutdown()
    db.close()


def test_concurrent_replay_claims_each_handler_once(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def block(_event: Event) -> None:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=3)

    handler = _named_handler("tests.replay_once", block)
    bus.subscribe("ops.replay", handler)
    event_id = db.event_log_insert("ops.replay", "{}")
    db.prepare_handler_runs(event_id, ["tests.replay_once"])
    db.mark_handler_admission_failed(
        event_id,
        "tests.replay_once",
        "runtime_admission:saturated: fixture",
    )
    pool = ThreadPoolExecutor(max_workers=2)
    futures = [pool.submit(bus.replay_pending) for _ in range(2)]
    assert started.wait(timeout=2)
    for future in futures:
        future.result(timeout=2)

    release.set()
    assert bus.wait_for_idle(min_event_id=event_id, timeout_sec=2)
    assert calls == 1
    assert _event_row(db, event_id)["status"] == "ok"
    pool.shutdown()
    bus.shutdown()
    db.close()


def test_two_connections_concurrent_replay_claims_handler_once(tmp_path) -> None:
    first_db = TradeDB(tmp_path)
    second_db = TradeDB(tmp_path)
    first_bus = _bus(first_db)
    second_bus = _bus(second_db)
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def block(_event: Event) -> None:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=3)

    first_bus.subscribe("ops.shared_replay", _named_handler("tests.shared_replay", block))
    second_bus.subscribe("ops.shared_replay", _named_handler("tests.shared_replay", block))
    event_id = first_db.event_log_insert("ops.shared_replay", "{}")
    first_db.prepare_handler_runs(event_id, ["tests.shared_replay"])
    first_db.mark_handler_admission_failed(
        event_id,
        "tests.shared_replay",
        "runtime_admission:saturated: fixture",
    )

    pool = ThreadPoolExecutor(max_workers=2)
    futures = [
        pool.submit(first_bus.replay_pending),
        pool.submit(second_bus.replay_pending),
    ]
    assert started.wait(timeout=2)
    for future in futures:
        future.result(timeout=2)

    release.set()
    assert first_bus.wait_for_idle(min_event_id=event_id, timeout_sec=2)
    assert calls == 1
    assert _event_row(first_db, event_id)["status"] == "ok"
    pool.shutdown()
    first_bus.shutdown()
    second_bus.shutdown()
    first_db.close()
    second_db.close()


def test_replay_rotates_past_bounded_unavailable_rows(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    recovered: list[int] = []
    for _ in range(3):
        event_id = db.event_log_insert("ops.unavailable", "{}")
        db.prepare_handler_runs(event_id, ["tests.unavailable"])
    bus.subscribe(
        "belief.recoverable",
        _named_handler(
            "tests.recoverable",
            lambda event: recovered.append(event.id),
        ),
    )
    recoverable_id = db.event_log_insert("belief.recoverable", "{}")
    db.prepare_handler_runs(recoverable_id, ["tests.recoverable"])

    bus.replay_pending(max_events=2)
    assert recovered == []
    bus.replay_pending(max_events=2)
    assert bus.wait_for_idle(min_event_id=recoverable_id, timeout_sec=2)

    assert recovered == [recoverable_id]
    bus.shutdown()
    db.close()


def test_replay_saturated_channel_does_not_block_other_channels(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    blocker_started = threading.Event()
    blocker_release = threading.Event()
    recovered: list[int] = []

    def block(_event: Event) -> None:
        blocker_started.set()
        assert blocker_release.wait(timeout=3)

    bus.subscribe("ops.blocker", _named_handler("tests.replay_blocker", block))
    bus.subscribe("ops.saturated", _named_handler("tests.replay_saturated", lambda _event: None))
    bus.subscribe(
        "belief.recoverable",
        _named_handler(
            "tests.other_channel",
            lambda event: recovered.append(event.id),
        ),
    )
    bus.publish("ops.blocker")
    assert blocker_started.wait(timeout=2)
    for _ in range(3):
        event_id = db.event_log_insert("ops.saturated", "{}")
        db.prepare_handler_runs(event_id, ["tests.replay_saturated"])
    recoverable_id = db.event_log_insert("belief.recoverable", "{}")
    db.prepare_handler_runs(recoverable_id, ["tests.other_channel"])

    bus.replay_pending(max_events=2)
    assert recovered == []
    bus.replay_pending(max_events=2)
    assert bus.wait_for_idle(min_event_id=recoverable_id, timeout_sec=2)

    assert recovered == [recoverable_id]
    blocker_release.set()
    bus.shutdown()
    db.close()


def test_transient_claim_renewal_failure_does_not_allow_stale_reclaim(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_db = TradeDB(tmp_path)
    second_db = TradeDB(tmp_path)
    first_bus = _bus(first_db)
    second_bus = _bus(second_db)
    started = threading.Event()
    release = threading.Event()
    renewal_failed = threading.Event()
    renewal_recovered = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def block(_event: Event) -> None:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=4)

    handler = _named_handler("tests.renew_transient", block)
    first_bus.subscribe("ops.renew_transient", handler)
    second_bus.subscribe("ops.renew_transient", handler)
    original_renew = first_db.renew_handler_claim

    def renew_with_one_failure(
        event_id: int,
        handler_name: str,
        claim_token: str,
    ) -> bool:
        if not renewal_failed.is_set():
            renewal_failed.set()
            raise sqlite3.OperationalError("transient busy")
        renewed = original_renew(event_id, handler_name, claim_token)
        if renewed:
            renewal_recovered.set()
        return renewed

    monkeypatch.setattr("trade_py.bus._CLAIM_RENEW_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr("trade_py.bus._CLAIM_RENEW_INITIAL_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr("trade_py.bus._CLAIM_RENEW_MAX_BACKOFF_SECONDS", 0.05)
    monkeypatch.setattr(first_db, "renew_handler_claim", renew_with_one_failure)

    event = first_bus.publish("ops.renew_transient")
    assert started.wait(timeout=2)
    assert renewal_failed.wait(timeout=2)
    assert renewal_recovered.wait(timeout=2)
    time.sleep(1.1)

    original_event_log_replayable = second_db.event_log_replayable
    original_replayable_handler_names = second_db.replayable_handler_names
    original_claim_handler_run = second_db.claim_handler_run
    monkeypatch.setattr(
        second_db,
        "event_log_replayable",
        lambda **kwargs: original_event_log_replayable(
            after_id=kwargs.get("after_id", 0),
            limit=kwargs.get("limit", 100),
            stale_after_seconds=1,
        ),
    )
    monkeypatch.setattr(
        second_db,
        "replayable_handler_names",
        lambda event_id: original_replayable_handler_names(
            event_id,
            stale_after_seconds=1,
        ),
    )
    monkeypatch.setattr(
        second_db,
        "claim_handler_run",
        lambda event_id, handler_name, claim_token: original_claim_handler_run(
            event_id,
            handler_name,
            claim_token,
            stale_after_seconds=1,
        ),
    )

    second_bus.replay_pending()
    assert calls == 1

    release.set()
    assert first_bus.wait_for_idle(min_event_id=event.id, timeout_sec=2)
    assert _event_row(first_db, event.id)["status"] == "ok"
    first_bus.shutdown()
    second_bus.shutdown()
    first_db.close()
    second_db.close()


def test_prolonged_claim_renewal_outage_keeps_live_process_exclusive(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_db = TradeDB(tmp_path)
    second_db = TradeDB(tmp_path)
    first_bus = _bus(first_db)
    second_bus = _bus(second_db)
    started = threading.Event()
    release = threading.Event()
    renewal_failed = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def block(_event: Event) -> None:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=4)

    handler = _named_handler("tests.renew_prolonged", block)
    first_bus.subscribe("ops.renew_prolonged", handler)
    second_bus.subscribe("ops.renew_prolonged", handler)

    def fail_renewal(*_args, **_kwargs) -> bool:
        renewal_failed.set()
        raise sqlite3.OperationalError("prolonged busy")

    monkeypatch.setattr("trade_py.bus._CLAIM_RENEW_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr("trade_py.bus._CLAIM_RENEW_INITIAL_BACKOFF_SECONDS", 0.05)
    monkeypatch.setattr("trade_py.bus._CLAIM_RENEW_MAX_BACKOFF_SECONDS", 0.1)
    monkeypatch.setattr(first_db, "renew_handler_claim", fail_renewal)

    event = first_bus.publish("ops.renew_prolonged")
    assert started.wait(timeout=2)
    assert renewal_failed.wait(timeout=2)
    handler_row = first_db.get_handler_run(event.id, "tests.renew_prolonged")
    assert handler_row is not None
    claim_marker = str(handler_row["error_message"])
    assert claim_marker.startswith(f"claim:process:{os.getpid()}:")
    assert len(claim_marker.split(":")) == 5
    time.sleep(1.1)

    original_event_log_replayable = second_db.event_log_replayable
    original_replayable_handler_names = second_db.replayable_handler_names
    original_claim_handler_run = second_db.claim_handler_run
    monkeypatch.setattr(
        second_db,
        "event_log_replayable",
        lambda **kwargs: original_event_log_replayable(
            after_id=kwargs.get("after_id", 0),
            limit=kwargs.get("limit", 100),
            stale_after_seconds=1,
        ),
    )
    monkeypatch.setattr(
        second_db,
        "replayable_handler_names",
        lambda event_id: original_replayable_handler_names(
            event_id,
            stale_after_seconds=1,
        ),
    )
    monkeypatch.setattr(
        second_db,
        "claim_handler_run",
        lambda event_id, handler_name, claim_token: original_claim_handler_run(
            event_id,
            handler_name,
            claim_token,
            stale_after_seconds=1,
        ),
    )

    second_bus.replay_pending()
    assert calls == 1

    release.set()
    assert first_bus.wait_for_idle(min_event_id=event.id, timeout_sec=2)
    first_bus.shutdown()
    second_bus.shutdown()
    first_db.close()
    second_db.close()


def test_definitive_claim_loss_never_commits_handler_success(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    started = threading.Event()
    release = threading.Event()
    ownership_lost = threading.Event()

    def block(_event: Event) -> None:
        started.set()
        assert release.wait(timeout=3)

    def lose_ownership(event_id: int, handler_name: str, _claim_token: str) -> bool:
        with db._conn_lock:
            db._conn.execute(
                """
                UPDATE event_handler_runs
                SET error_message='claim:replacement-owner'
                WHERE event_id=? AND handler_name=?
                """,
                (event_id, handler_name),
            )
            db._conn.commit()
        ownership_lost.set()
        return False

    monkeypatch.setattr("trade_py.bus._CLAIM_RENEW_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(db, "renew_handler_claim", lose_ownership)
    bus.subscribe("ops.claim_lost", _named_handler("tests.claim_lost", block))

    event = bus.publish("ops.claim_lost")
    assert started.wait(timeout=2)
    assert ownership_lost.wait(timeout=2)
    release.set()
    assert bus.wait_for_idle(min_event_id=event.id, timeout_sec=2) is False

    handler_row = db.get_handler_run(event.id, "tests.claim_lost")
    assert handler_row is not None
    assert handler_row["status"] == "running"
    assert handler_row["error_message"] == "claim:replacement-owner"
    assert _event_row(db, event.id)["status"] != "ok"
    bus.shutdown()
    db.close()


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        "null",
        '"scalar"',
        '{"score":NaN}',
        '{"score":Infinity}',
        '{"score":-Infinity}',
    ],
)
def test_replay_quarantines_invalid_payload_without_running_handler(
    tmp_path,
    payload: str,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    calls: list[int] = []
    bus.subscribe(
        "ops.invalid_payload",
        _named_handler("tests.invalid_payload", lambda event: calls.append(event.id)),
    )
    event_id = db.event_log_insert("ops.invalid_payload", payload)
    db.prepare_handler_runs(event_id, ["tests.invalid_payload"])

    bus.replay_pending()

    row = _event_row(db, event_id)
    handler_row = db.get_handler_run(event_id, "tests.invalid_payload")
    assert calls == []
    assert row["status"] == "error"
    assert row["handler"] == "<payload_decode>"
    assert "payload_decode_failed" in str(row["error"])
    assert handler_row is not None
    assert handler_row["status"] == "error"
    bus.replay_pending()
    assert calls == []
    bus.shutdown()
    db.close()


def test_replay_skips_permanent_handler_error(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    calls: list[int] = []
    bus.subscribe(
        "ops.permanent_error",
        _named_handler("tests.permanent_error", lambda event: calls.append(event.id)),
    )
    event_id = db.event_log_insert("ops.permanent_error", "{}")
    db.prepare_handler_runs(event_id, ["tests.permanent_error"])
    db.mark_handler_error(
        event_id,
        "tests.permanent_error",
        "provider rejected request",
        7,
    )

    bus.replay_pending()

    row = _event_row(db, event_id)
    assert calls == []
    assert row["status"] == "error"
    assert row["handler"] == "tests.permanent_error"
    assert row["error"] == "provider rejected request"
    bus.shutdown()
    db.close()


def test_replay_retries_only_transient_handler_and_clears_event_error(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    calls: list[str] = []

    bus.subscribe(
        "ops.transient_replay",
        _named_handler("tests.already_ok", lambda _event: calls.append("already_ok")),
    )
    bus.subscribe(
        "ops.transient_replay",
        _named_handler("tests.retry", lambda _event: calls.append("retry")),
    )
    event_id = db.event_log_insert("ops.transient_replay", "{}")
    db.prepare_handler_runs(event_id, ["tests.already_ok", "tests.retry"])
    db.mark_handler_ok(event_id, "tests.already_ok", 1)
    db.mark_handler_admission_failed(
        event_id,
        "tests.retry",
        "runtime_admission:submission_failed: fixture",
    )

    bus.replay_pending()
    assert bus.wait_for_idle(min_event_id=event_id, timeout_sec=2)

    row = _event_row(db, event_id)
    assert calls == ["retry"]
    assert row["status"] == "ok"
    assert row["error"] is None
    assert row["handler"] == "<multiple>"
    bus.shutdown()
    db.close()


@pytest.mark.parametrize("payload", [None, [], "scalar", 7])
def test_publish_child_rejects_non_object_before_insertion(
    tmp_path,
    payload: object,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)

    with pytest.raises(TypeError, match="event payload must be a dict"):
        bus.publish_child_once(
            "ops.invalid_child",
            cast(dict, payload),
            parent_event_id=19,
            handoff_key="invalid",
        )

    count = db._conn.execute(
        "SELECT COUNT(*) FROM event_log WHERE topic='ops.invalid_child'"
    ).fetchone()[0]
    assert count == 0
    bus.shutdown()
    db.close()


def test_publish_child_quarantines_historical_malformed_row(tmp_path) -> None:
    db = TradeDB(tmp_path)
    row, created = db.event_log_get_or_insert_child(
        "ops.invalid_child_history",
        "[]",
        23,
        "historical-invalid",
    )
    assert created is True
    bus = _bus(db)

    with pytest.raises(TypeError, match="child event payload must be an object"):
        bus.publish_child_once(
            "ops.invalid_child_history",
            {"valid": True},
            parent_event_id=23,
            handoff_key="historical-invalid",
        )

    quarantined = _event_row(db, int(row["id"]))
    assert quarantined["status"] == "error"
    assert quarantined["handler"] == "<payload_decode>"
    bus.shutdown()
    db.close()


@pytest.mark.parametrize(
    "error_message",
    [
        "submission_failed: provider rejected payload",
        "admission_saturated: business rule",
        "admission_shutting_down: upstream maintenance",
    ],
)
def test_handler_error_text_never_becomes_runtime_replayable(
    tmp_path,
    error_message: str,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    calls = 0
    failed = threading.Event()

    def fail(_event: Event) -> None:
        nonlocal calls
        calls += 1
        failed.set()
        raise RuntimeError(error_message)

    bus.subscribe("ops.business_error", _named_handler("tests.business_error", fail))
    event = bus.publish("ops.business_error")
    assert failed.wait(timeout=2)
    deadline = time.monotonic() + 2
    while bus._has_active_handlers(min_event_id=event.id) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert bus._has_active_handlers(min_event_id=event.id) is False

    bus.replay_pending()

    assert calls == 1
    row = db.get_handler_run(event.id, "tests.business_error")
    assert row is not None
    assert row["error_message"] == error_message
    bus.shutdown()
    db.close()


def test_shutdown_cancels_queued_work_and_restart_replays_same_event(tmp_path) -> None:
    db = TradeDB(tmp_path)
    capacities = dict(_CHANNEL_CAPACITIES)
    capacities["io"] = 2
    bus = EventBus(
        db,
        ingest_workers=1,
        nlp_workers=1,
        signal_workers=1,
        decision_workers=1,
        io_workers=1,
        channel_capacities=capacities,
    )
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def block(event: Event) -> None:
        calls.append(event.id)
        started.set()
        assert release.wait(timeout=3)

    handler = _named_handler("tests.shutdown_queue", block)
    bus.subscribe("ops.shutdown_queue", handler)
    first = bus.publish("ops.shutdown_queue")
    assert started.wait(timeout=2)
    queued = bus.publish("ops.shutdown_queue")

    with pytest.raises(RuntimeError, match="EventBus shutdown incomplete"):
        bus.shutdown(timeout_sec=0.05)

    assert bus.capacity_snapshot().lifecycle is BusLifecycle.STOPPING
    queued_run = db.get_handler_run(queued.id, "tests.shutdown_queue")
    assert queued_run is not None
    assert str(queued_run["error_message"]).startswith("runtime_admission:shutdown_cancelled:")
    release.set()
    bus.shutdown(timeout_sec=2)
    assert calls == [first.id]

    restarted = _bus(db)
    restarted.subscribe("ops.shutdown_queue", handler)
    restarted.replay_pending()
    assert restarted.wait_for_idle(min_event_id=queued.id, timeout_sec=2)
    assert calls == [first.id, queued.id]
    restarted.shutdown()
    db.close()


def test_shutdown_retries_after_blocked_heartbeat_exits(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    handler_release = threading.Event()
    heartbeat_started = threading.Event()
    heartbeat_release = threading.Event()
    original_renew = db.renew_handler_claim

    def block_renewal(event_id: int, handler_name: str, claim_token: str) -> bool:
        heartbeat_started.set()
        assert heartbeat_release.wait(timeout=3)
        return original_renew(event_id, handler_name, claim_token)

    def handle(_event: Event) -> None:
        assert handler_release.wait(timeout=3)

    monkeypatch.setattr("trade_py.bus._CLAIM_RENEW_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(db, "renew_handler_claim", block_renewal)
    bus.subscribe("ops.blocked_heartbeat", _named_handler("tests.blocked_heartbeat", handle))
    event = bus.publish("ops.blocked_heartbeat")
    assert heartbeat_started.wait(timeout=2)
    handler_release.set()

    with pytest.raises(RuntimeError, match="heartbeats=1"):
        bus.shutdown(timeout_sec=0.05)

    assert bus.capacity_snapshot().lifecycle is BusLifecycle.STOPPING
    assert db.get_handler_run(event.id, "tests.blocked_heartbeat") is not None
    heartbeat_release.set()
    bus.shutdown(timeout_sec=2)
    assert bus.capacity_snapshot().lifecycle is BusLifecycle.STOPPED
    db.close()


def test_dag_child_handoff_is_idempotent_after_saturation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    blocker_started = threading.Event()
    blocker_release = threading.Event()
    child_calls: list[int] = []
    job_calls = 0

    def block(_event: Event) -> None:
        blocker_started.set()
        assert blocker_release.wait(timeout=3)

    def run_job(*_args, **_kwargs) -> str:
        nonlocal job_calls
        job_calls += 1
        return "fixture complete"

    bus.subscribe("ops.child_blocker", _named_handler("tests.child_blocker", block))
    bus.subscribe(
        "ops.child",
        _named_handler("tests.child", lambda event: child_calls.append(event.id)),
    )
    bus.publish("ops.child_blocker")
    assert blocker_started.wait(timeout=2)
    monkeypatch.setattr("trade_py.jobs.run_job", run_job)
    row = {
        "id": 77,
        "enabled": 1,
        "source": "gate.manual",
        "job_name": "fixture_job",
        "emits": "ops.child",
        "stage": "fetch",
        "config_json": "{}",
    }

    parent = dispatch_dag_row(db, bus, str(tmp_path), row)
    assert bus.wait_for_idle(min_event_id=parent.id, timeout_sec=2)
    children = db._conn.execute(
        "SELECT id, status FROM event_log WHERE parent_event_id=? AND topic='ops.child'",
        (parent.id,),
    ).fetchall()
    assert len(children) == 1
    child_id = int(children[0]["id"])
    assert children[0]["status"] == "error"
    assert _event_row(db, parent.id)["status"] == "ok"
    assert job_calls == 1

    blocker_release.set()
    assert bus.wait_for_idle(timeout_sec=2)
    bus.replay_pending()
    assert bus.wait_for_idle(min_event_id=child_id, timeout_sec=2)

    children = db._conn.execute(
        "SELECT id, status FROM event_log WHERE parent_event_id=? AND topic='ops.child'",
        (parent.id,),
    ).fetchall()
    assert [(int(child["id"]), child["status"]) for child in children] == [(child_id, "ok")]
    assert child_calls == [child_id]
    assert job_calls == 1
    bus.shutdown()
    db.close()


def test_dag_child_handoff_exception_preserves_successful_job_for_replay(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    job_calls = 0
    child_calls: list[int] = []
    handoff_attempts = 0

    def run_job(*_args, **_kwargs) -> str:
        nonlocal job_calls
        job_calls += 1
        return "fixture complete"

    original_publish_child_once = bus.publish_child_once

    def fail_first_handoff(*args, **kwargs):
        nonlocal handoff_attempts
        handoff_attempts += 1
        if handoff_attempts == 1:
            raise RuntimeError("transient child persistence failure")
        return original_publish_child_once(*args, **kwargs)

    monkeypatch.setattr("trade_py.jobs.run_job", run_job)
    monkeypatch.setattr(bus, "publish_child_once", fail_first_handoff)
    bus.subscribe(
        "ops.child_exception",
        _named_handler(
            "tests.child_exception",
            lambda event: child_calls.append(event.id),
        ),
    )
    row = {
        "id": 78,
        "enabled": 1,
        "source": "gate.manual",
        "job_name": "fixture_job",
        "emits": "ops.child_exception",
        "stage": "fetch",
        "config_json": "{}",
    }

    parent = dispatch_dag_row(db, bus, str(tmp_path), row)
    assert bus.wait_for_idle(min_event_id=parent.id, timeout_sec=2)
    runs = db._conn.execute(
        """
        SELECT id, status, result_summary
        FROM job_runs
        WHERE trigger_event_id=? AND job_name='fixture_job'
        ORDER BY id
        """,
        (parent.id,),
    ).fetchall()
    assert [(run["status"], run["result_summary"]) for run in runs] == [("ok", "fixture complete")]
    assert _event_row(db, parent.id)["status"] == "error"
    assert str(_event_row(db, parent.id)["error"]).startswith("runtime_admission:child_handoff:")
    assert job_calls == 1

    bus.subscribe(
        "gate.manual",
        _make_dag_handler(
            db,
            dag_id=78,
            job_name="fixture_job",
            emits="ops.child_exception",
            stage="fetch",
            data_root=str(tmp_path),
            config={},
        ),
    )
    bus.replay_pending()
    assert bus.wait_for_idle(min_event_id=parent.id, timeout_sec=2)

    runs = db._conn.execute(
        """
        SELECT id, status, result_summary
        FROM job_runs
        WHERE trigger_event_id=? AND job_name='fixture_job'
        ORDER BY id
        """,
        (parent.id,),
    ).fetchall()
    children = db._conn.execute(
        """
        SELECT id, status
        FROM event_log
        WHERE parent_event_id=? AND topic='ops.child_exception'
        """,
        (parent.id,),
    ).fetchall()
    assert [(run["status"], run["result_summary"]) for run in runs] == [("ok", "fixture complete")]
    assert len(children) == 1
    assert children[0]["status"] == "ok"
    assert child_calls == [int(children[0]["id"])]
    assert handoff_attempts == 2
    assert job_calls == 1
    assert _event_row(db, parent.id)["status"] == "ok"
    bus.shutdown()
    db.close()


def test_same_job_name_dag_rows_keep_distinct_run_identity(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    capacities = dict(_CHANNEL_CAPACITIES)
    capacities["ingest"] = 2
    bus = EventBus(
        db,
        ingest_workers=1,
        nlp_workers=1,
        signal_workers=1,
        decision_workers=1,
        io_workers=1,
        channel_capacities=capacities,
    )
    configs: list[str] = []

    def run_job(*_args, **kwargs) -> str:
        marker = str(kwargs["config"]["marker"])
        configs.append(marker)
        return marker

    monkeypatch.setattr("trade_py.jobs.run_job", run_job)
    db._conn.executemany(
        """
        INSERT INTO pipeline_dag
            (stage, source, job_name, emits, enabled, description, config_json)
        VALUES ('fetch', 'gate.same_job_fixture', 'fixture_job', '', 1, ?, ?)
        """,
        [
            ("first fixture", '{"marker":"first"}'),
            ("second fixture", '{"marker":"second"}'),
        ],
    )
    db._conn.commit()
    bootstrap_from_dag(db, str(tmp_path), bus=bus)

    event = bus.publish("gate.same_job_fixture")
    assert bus.wait_for_idle(min_event_id=event.id, timeout_sec=2)

    runs = db._conn.execute(
        """
        SELECT status, message, result_summary
        FROM job_runs
        WHERE trigger_event_id=? AND job_name='fixture_job'
        ORDER BY id
        """,
        (event.id,),
    ).fetchall()
    assert configs == ["first", "second"]
    assert [run["status"] for run in runs] == ["ok", "ok"]
    assert [run["result_summary"] for run in runs] == ["first", "second"]
    assert len({run["message"] for run in runs}) == 2
    assert all(str(run["message"]).startswith("<run-key:dag:") for run in runs)
    bus.shutdown()
    db.close()


def test_direct_dag_dispatch_uses_same_bounded_admission(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    started = threading.Event()
    release = threading.Event()

    def block(_event: Event) -> None:
        started.set()
        assert release.wait(timeout=3)

    bus.subscribe("gate.blocked", _named_handler("tests.ingest_block", block))
    bus.publish("gate.blocked")
    assert started.wait(timeout=2)
    row = {
        "id": 42,
        "enabled": 1,
        "source": "gate.manual",
        "job_name": "fixture_job",
        "emits": None,
        "stage": "fetch",
        "config_json": "{}",
    }

    with pytest.raises(EventAdmissionError) as raised:
        dispatch_dag_row(db, bus, str(tmp_path), row)

    assert raised.value.result.outcome is AdmissionOutcome.SATURATED
    handler_name = "dag.fetch.fixture_job.row_42"
    handler_row = db.get_handler_run(raised.value.result.event.id, handler_name)
    assert handler_row is not None
    assert handler_row["status"] == "error"
    release.set()
    bus.shutdown()
    db.close()


def test_direct_dag_dispatch_preserves_accepted_event_contract(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = TradeDB(tmp_path)
    bus = _bus(db)
    monkeypatch.setattr(
        "trade_py.jobs.run_job",
        lambda *_args, **_kwargs: "fixture complete",
    )
    row = {
        "id": 43,
        "enabled": 1,
        "source": "gate.manual",
        "job_name": "fixture_job",
        "emits": None,
        "stage": "fetch",
        "config_json": "{}",
    }
    parent_event_id = db.event_log_insert("gate.parent", "{}")
    db.event_log_complete(parent_event_id, "ok", "<fixture>")

    event = dispatch_dag_row(
        db,
        bus,
        str(tmp_path),
        row,
        {"value": 11},
        parent_event_id=parent_event_id,
    )

    assert isinstance(event, Event)
    assert event.payload == {"value": 11}
    assert event.parent_event_id == parent_event_id
    assert bus.wait_for_idle(min_event_id=event.id, timeout_sec=2)
    assert _event_row(db, event.id)["status"] == "ok"
    handler_row = db.get_handler_run(
        event.id,
        "dag.fetch.fixture_job.row_43",
    )
    assert handler_row is not None
    assert handler_row["status"] == "ok"
    bus.shutdown()
    db.close()
