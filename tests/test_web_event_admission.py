from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from trade_py.bus import Event


@pytest.fixture
def web_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[tuple[TestClient, Any]]:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client, app.state.resources


def _assert_admission_failure(
    response: Any,
    *,
    outcome: str,
    channel: str,
) -> int:
    assert response.status_code == 503
    payload = response.json()
    assert payload["accepted"] is False
    assert payload["durable"] is True
    assert payload["dispatch_status"] == "deferred"
    assert payload["outcome"] == outcome
    assert payload["channel"] == channel
    assert payload["action"] == "replay_existing"
    assert isinstance(payload["message"], str) and payload["message"]
    assert "retry" not in payload["message"].lower()
    assert isinstance(payload["event_id"], int) and payload["event_id"] > 0
    assert response.headers.get("Retry-After") is None
    return payload["event_id"]


def _event_row(resources: Any, event_id: int) -> dict[str, Any]:
    rows = resources.db.event_log_recent(limit=200)
    return next(row for row in rows if int(row["id"]) == event_id)


@pytest.mark.parametrize("payload", [None, [], "text", 7, 2.5, True, False])
@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/trigger", {"topic": "ops.web.invalid"}),
        ("/api/dag/999999/run", {"mode": "self"}),
    ],
)
def test_event_routes_reject_supplied_non_object_payload_before_writes(
    web_client: tuple[TestClient, Any],
    path: str,
    body: dict[str, Any],
    payload: Any,
) -> None:
    client, resources = web_client
    before_events = resources.db.event_log_recent(limit=500)
    before_runs = resources.db.job_runs_recent(limit=500)

    response = client.post(path, json={**body, "payload": payload})

    assert response.status_code == 400
    assert response.json() == {"detail": "payload must be a JSON object"}
    assert resources.db.event_log_recent(limit=500) == before_events
    assert resources.db.job_runs_recent(limit=500) == before_runs


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        ("/api/trigger", '{"topic":"ops.web.nonfinite","payload":{"value":'),
        ("/api/dag/999999/run", '{"mode":"self","payload":{"value":'),
        ("/api/run", '{"target":"morning","payload":{"value":'),
    ],
)
def test_web_transport_rejects_non_finite_payload_before_writes(
    web_client: tuple[TestClient, Any],
    path: str,
    prefix: str,
    constant: str,
) -> None:
    client, resources = web_client
    before_events = resources.db.event_log_recent(limit=500)
    before_runs = resources.db.job_runs_recent(limit=500)

    response = client.post(
        path,
        content=f"{prefix}{constant}}}}}",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "payload must contain only finite JSON numbers"}
    assert resources.db.event_log_recent(limit=500) == before_events
    assert resources.db.job_runs_recent(limit=500) == before_runs


def test_trigger_accepted_response_remains_compatible(web_client: tuple[TestClient, Any]) -> None:
    client, resources = web_client

    response = client.post(
        "/api/trigger",
        json={"topic": "ops.web.accepted", "payload": {"value": 7}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "event_id": payload["event_id"],
        "topic": "ops.web.accepted",
    }
    assert _event_row(resources, payload["event_id"])["status"] == "ok"


def test_trigger_saturation_returns_durable_actionable_503_without_false_success(
    web_client: tuple[TestClient, Any],
) -> None:
    client, resources = web_client
    bus = resources.bus
    started = threading.Event()
    release = threading.Event()

    def block(_event: Event) -> None:
        started.set()
        assert release.wait(timeout=5)

    block.__qualname__ = "tests.web_event_admission.block_io"
    topic = "ops.web.saturated"
    bus.subscribe(topic, block)
    io_capacity = next(
        channel.capacity for channel in bus.capacity_snapshot().channels if channel.name == "io"
    )
    admitted = [bus.publish(topic)]
    assert started.wait(timeout=2)
    admitted.extend(bus.publish(topic) for _ in range(io_capacity - 1))

    response = client.post("/api/trigger", json={"topic": topic, "payload": {"value": 8}})

    event_id = _assert_admission_failure(
        response,
        outcome="saturated",
        channel="io",
    )
    assert event_id not in {event.id for event in admitted}
    assert _event_row(resources, event_id)["status"] == "error"
    release.set()
    assert bus.wait_for_idle(min_event_id=admitted[0].id, timeout_sec=3)


def test_trigger_submission_failure_is_not_generic_500_or_false_success(
    web_client: tuple[TestClient, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, resources = web_client
    bus = resources.bus
    topic = "ops.web.submission-failed"

    def no_op(_event: Event) -> None:
        return None

    no_op.__qualname__ = "tests.web_event_admission.no_op"
    bus.subscribe(topic, no_op)

    def fail_submit(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("executor unavailable")

    monkeypatch.setattr(bus._pools["io"], "submit", fail_submit)
    response = client.post("/api/trigger", json={"topic": topic})

    event_id = _assert_admission_failure(
        response,
        outcome="submission_failed",
        channel="io",
    )
    assert _event_row(resources, event_id)["status"] == "error"


def test_dag_run_rerun_and_symbol_repull_reject_stopping_runtime(
    web_client: tuple[TestClient, Any],
) -> None:
    client, resources = web_client
    db = resources.db
    with db._conn_lock:
        cursor = db._conn.execute(
            """
            INSERT INTO pipeline_dag
                (stage, source, job_name, emits, enabled, description, config_json)
            VALUES
                ('fetch', 'gate.web.fixture', 'web_fixture_job', NULL, 1, 'fixture', '{}')
            """
        )
        dag_id = int(cursor.lastrowid)
        db._conn.commit()
    root_event_id = db.event_log_insert("gate.web.fixture", '{"symbol":"000001.SZ"}')
    db.event_log_complete(root_event_id, "error", "<fixture>", "retry fixture")
    resources.bus.begin_shutdown()

    responses = [
        client.post(f"/api/dag/{dag_id}/run", json={"mode": "self"}),
        client.post(
            f"/api/workflows/{root_event_id}/rerun-node",
            json={"dag_id": dag_id, "mode": "self"},
        ),
        client.post(
            "/api/symbol-data-ops/repull",
            json={"symbol": "000001.SZ", "domains": ["kline"]},
        ),
    ]

    event_ids = {
        _assert_admission_failure(
            response,
            outcome="shutting_down",
            channel="ingest",
        )
        for response in responses
    }
    assert len(event_ids) == len(responses)
    for event_id in event_ids:
        assert _event_row(resources, event_id)["status"] == "error"
