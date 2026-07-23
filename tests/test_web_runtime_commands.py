from __future__ import annotations

import json
import threading
from enum import Enum
from typing import Any

import pytest
from fastapi.testclient import TestClient

from trade_web.backend.runtime.commands import (
    CommandStartOutcome,
    CommandStartResult,
    RuntimeCommandRunner,
)


@pytest.fixture(autouse=True)
def _provide_coordinated_job_run_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    from trade_py.db.trade_db import TradeDB

    monkeypatch.setattr(
        TradeDB,
        "job_runs_finish_running_stage",
        lambda _db, _stage, *, status, result_summary: 0,
        raising=False,
    )


def test_api_run_admits_isolated_command_without_calling_in_process_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_py.cli import run as run_cli
    from trade_web import create_app

    captured: list[tuple[str, str | None, int]] = []

    async def start_async(
        _runner: RuntimeCommandRunner,
        target: str,
        *,
        payload_json: str | None = None,
        limit: int = 10,
    ) -> CommandStartResult:
        captured.append((target, payload_json, limit))
        return CommandStartResult(
            outcome=CommandStartOutcome.ACCEPTED,
            target=target,
            run_id=17,
            pid=4321,
        )

    monkeypatch.setattr(RuntimeCommandRunner, "start_async", start_async)
    monkeypatch.setattr(
        run_cli,
        "main",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("in-process CLI must not run")
        ),
    )
    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/run",
            json={
                "target": "agenda",
                "payload": {"symbol": "比特币"},
                "limit": 7,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "target": "agenda",
        "limit": 7,
        "pid": 4321,
        "run_id": 17,
        "status": "running",
    }
    assert captured == [
        (
            "agenda",
            json.dumps({"symbol": "比特币"}, ensure_ascii=False),
            7,
        )
    ]


@pytest.mark.parametrize(
    ("outcome", "retry_after", "message", "reason_code", "status"),
    [
        (
            CommandStartOutcome.SATURATED,
            "1",
            "workflow command capacity is exhausted",
            "COMMAND_CAPACITY_EXHAUSTED",
            "saturated",
        ),
        (
            CommandStartOutcome.STOPPING,
            "5",
            "workflow command runtime is stopping",
            "COMMAND_RUNTIME_STOPPING",
            "stopping",
        ),
        (
            CommandStartOutcome.SPAWN_FAILED,
            None,
            "workflow command could not be started",
            "COMMAND_START_FAILED",
            "error",
        ),
    ],
)
def test_api_run_surfaces_command_admission_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    outcome: CommandStartOutcome,
    retry_after: str | None,
    message: str,
    reason_code: str,
    status: str,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    async def start_async(
        _runner: RuntimeCommandRunner,
        target: str,
        **_kwargs,
    ) -> CommandStartResult:
        return CommandStartResult(
            outcome=outcome,
            target=target,
            run_id=29 if outcome is CommandStartOutcome.SPAWN_FAILED else None,
            detail=f"{outcome.value} fixture",
        )

    monkeypatch.setattr(RuntimeCommandRunner, "start_async", start_async)
    app = create_app()

    with TestClient(app) as client:
        response = client.post("/api/run", json={"target": "morning"})

    assert response.status_code == 503
    assert response.headers.get("Retry-After") == retry_after
    assert response.json() == {
        "accepted": False,
        "target": "morning",
        "limit": 10,
        "outcome": outcome.value,
        "message": message,
        "reason_code": reason_code,
        "run_id": 29 if outcome is CommandStartOutcome.SPAWN_FAILED else None,
        "status": status,
    }


@pytest.mark.parametrize("payload", [None, [], "text", 7, 2.5, True, False])
def test_api_run_validates_payload_before_command_admission_or_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    payload: Any,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    calls = 0

    async def start_async(*_args, **_kwargs) -> CommandStartResult:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid request must not reach command runner")

    monkeypatch.setattr(RuntimeCommandRunner, "start_async", start_async)
    app = create_app()

    with TestClient(app) as client:
        resources = app.state.resources
        before_events = resources.db.event_log_recent(limit=500)
        before_runs = resources.db.job_runs_recent(limit=500)
        response = client.post("/api/run", json={"target": "morning", "payload": payload})

        assert resources.db.event_log_recent(limit=500) == before_events
        assert resources.db.job_runs_recent(limit=500) == before_runs

    assert response.status_code == 400
    assert response.json() == {"detail": "payload must be a JSON object"}
    assert calls == 0


def test_api_run_requires_target_before_command_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    monkeypatch.setattr(
        RuntimeCommandRunner,
        "start",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid request must not reach command runner")
        ),
    )
    app = create_app()

    with TestClient(app) as client:
        response = client.post("/api/run", json={})

    assert response.status_code == 400


@pytest.mark.parametrize("limit", [-1, 0, 501, "not-an-integer"])
def test_api_run_rejects_invalid_limit_before_command_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    limit: Any,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    calls = 0

    async def start_async(*_args, **_kwargs) -> CommandStartResult:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid request must not reach command runner")

    monkeypatch.setattr(RuntimeCommandRunner, "start_async", start_async)
    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/run",
            json={"target": "morning", "limit": limit},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "limit must be between 1 and 500"}
    assert calls == 0


@pytest.mark.parametrize(
    "path",
    [
        "/api/dag/runtime",
        "/api/events",
        "/api/workflows",
        "/api/runs",
    ],
)
@pytest.mark.parametrize("limit", [0, 501])
def test_runtime_list_routes_reject_out_of_bounds_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    path: str,
    limit: int,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    app = create_app()

    with TestClient(app) as client:
        response = client.get(path, params={"limit": limit})

    assert response.status_code == 422


def test_api_run_maps_future_persistence_failure_without_leaking_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FutureOutcome(str, Enum):
        PERSISTENCE_FAILED = "persistence_failed"

    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    async def start_async(
        _runner: RuntimeCommandRunner,
        target: str,
        **_kwargs: Any,
    ) -> CommandStartResult:
        return CommandStartResult(
            outcome=FutureOutcome.PERSISTENCE_FAILED,  # type: ignore[arg-type]
            target=target,
            detail="sqlite3.OperationalError: /private/path/trade.db is locked",
        )

    monkeypatch.setattr(RuntimeCommandRunner, "start_async", start_async)
    app = create_app()

    with TestClient(app) as client:
        response = client.post("/api/run", json={"target": "morning"})

    assert response.status_code == 503
    assert response.headers.get("Retry-After") is None
    assert response.json() == {
        "accepted": False,
        "target": "morning",
        "limit": 10,
        "outcome": "persistence_failed",
        "message": "workflow command could not be recorded",
        "reason_code": "COMMAND_PERSISTENCE_FAILED",
        "run_id": None,
        "status": "error",
    }
    assert "sqlite" not in response.text.lower()
    assert "/private/path" not in response.text


def test_api_run_is_queryable_in_job_runs_without_persisting_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    async def start_async(
        runner: RuntimeCommandRunner,
        target: str,
        *,
        payload_json: str | None = None,
        limit: int = 10,
    ) -> CommandStartResult:
        del limit
        assert json.loads(payload_json or "{}") == {"secret": "do-not-persist"}
        run_id = runner._db.job_run_start(target, stage="web_command")
        return CommandStartResult(
            outcome=CommandStartOutcome.ACCEPTED,
            target=target,
            run_id=run_id,
            pid=5432,
        )

    monkeypatch.setattr(RuntimeCommandRunner, "start_async", start_async)
    app = create_app()

    with TestClient(app) as client:
        accepted = client.post(
            "/api/run",
            json={"target": "morning", "payload": {"secret": "do-not-persist"}},
        )
        runs = client.get("/api/runs", params={"stage": "web_command"})

    assert accepted.status_code == 200
    run_id = accepted.json()["run_id"]
    assert runs.status_code == 200
    row = next(item for item in runs.json() if item["id"] == run_id)
    assert row["job_name"] == "morning"
    assert row["stage"] == "web_command"
    assert row["status"] == "running"
    assert "do-not-persist" not in json.dumps(row)


def test_api_run_offloads_blocked_start_without_blocking_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    start_blocked = threading.Event()
    release_start = threading.Event()

    def start_reserved(
        _runner: RuntimeCommandRunner,
        _slot_id: int,
        target: str,
        *,
        payload_json: str | None,
        limit: int,
    ) -> CommandStartResult:
        del payload_json, limit
        start_blocked.set()
        assert release_start.wait(timeout=2)
        _runner._release_unrecorded_start(_slot_id)
        return CommandStartResult(
            outcome=CommandStartOutcome.PERSISTENCE_FAILED,
            target=target,
        )

    monkeypatch.setattr(RuntimeCommandRunner, "_start_reserved", start_reserved)
    app = create_app()
    response_holder: list[Any] = []

    with TestClient(app) as client:
        request_thread = threading.Thread(
            target=lambda: response_holder.append(
                client.post("/api/run", json={"target": "morning"})
            ),
            name="blocked-api-run",
        )
        request_thread.start()
        try:
            assert start_blocked.wait(timeout=1)
            health = client.get("/")
            assert health.status_code == 200
            assert request_thread.is_alive()
        finally:
            release_start.set()
            request_thread.join(timeout=2)

    assert not request_thread.is_alive()
    assert response_holder[0].status_code == 503
