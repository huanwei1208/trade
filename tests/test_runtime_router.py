from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.routing import APIRoute


def _runtime_routes(app) -> dict[str, APIRoute]:
    wanted = {
        "/api/status",
        "/api/runtime/capacity",
        "/api/events/stream",
        "/api/runtime/stream",
        "/api/calendar",
        "/api/agenda",
        "/api/backups",
    }
    return {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path in wanted
    }


def test_runtime_route_inventory_and_parameter_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    app = create_app()
    routes = _runtime_routes(app)

    assert set(routes) == {
        "/api/status",
        "/api/runtime/capacity",
        "/api/events/stream",
        "/api/runtime/stream",
        "/api/calendar",
        "/api/agenda",
        "/api/backups",
    }
    assert all(route.methods == {"GET"} for route in routes.values())
    assert [param.name for param in routes["/api/events/stream"].dependant.query_params] == [
        "after_id",
        "limit",
        "poll_seconds",
    ]
    assert [param.default for param in routes["/api/events/stream"].dependant.query_params] == [
        0,
        50,
        2.0,
    ]
    assert [param.name for param in routes["/api/runtime/stream"].dependant.query_params] == [
        "scope",
        "poll_seconds",
    ]
    assert [param.default for param in routes["/api/runtime/stream"].dependant.query_params] == [
        "report",
        2.0,
    ]
    assert [param.default for param in routes["/api/calendar"].dependant.query_params] == [None, 5]
    assert [param.default for param in routes["/api/agenda"].dependant.query_params] == [
        50,
        None,
    ]
    assert [param.default for param in routes["/api/backups"].dependant.query_params] == [
        20,
        None,
    ]
    assert routes["/api/runtime/capacity"].dependant.query_params == []


def test_runtime_read_routes_use_owned_database(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from trade_py.db.trade_db import TradeDB

    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    if not hasattr(TradeDB, "trading_calendar_range"):
        monkeypatch.setattr(
            TradeDB,
            "trading_calendar_range",
            lambda db, start_date, end_date, exchange="SSE": [
                row
                for offset in range(
                    (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1
                )
                if (
                    row := db.trading_calendar_get(
                        date.fromisoformat(start_date) + timedelta(days=offset),
                        exchange=exchange,
                    )
                )
            ],
            raising=False,
        )
    from trade_web import create_app

    app = create_app()
    with TestClient(app) as client:
        owned_db = app.state.resources.db
        owned_db.trading_calendar_upsert_batch(
            [{"exchange": "SSE", "trade_date": "2026-07-21", "is_open": 1}]
        )
        calendar = client.get(
            "/api/calendar",
            params={"date_str": "2026-07-21", "days": 0},
        )
        agenda = client.get("/api/agenda")
        backups = client.get("/api/backups")
        capacity = client.get("/api/runtime/capacity")

        assert app.state.resources.db is owned_db

    assert calendar.status_code == 200
    assert calendar.json()["calendar"][0]["trade_date"] == "2026-07-21"
    assert agenda.status_code == 200
    assert agenda.json() == []
    assert backups.status_code == 200
    assert backups.json() == []
    assert capacity.status_code == 200
    capacity_payload = capacity.json()
    assert capacity_payload["status"] == "ready"
    assert capacity_payload["lifecycle"] == "ready"
    assert capacity_payload["generation"]
    assert capacity_payload["started_at"].endswith("+00:00")
    assert set(capacity_payload["channels"]) == {
        "ingest",
        "nlp",
        "signal",
        "decision",
        "io",
    }
    assert capacity_payload["channels"]["io"] == {
        "lifecycle": "ready",
        "workers": 2,
        "capacity": 4,
        "admitted": 0,
        "active": 0,
        "available": 4,
        "outcomes": {
            "accepted": 0,
            "saturated": 0,
            "shutting_down": 0,
            "submission_failed": 0,
        },
        "last_saturation_at": None,
    }


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/calendar", {"days": 367}),
        ("/api/calendar", {"days": -1}),
        ("/api/agenda", {"limit": 501}),
        ("/api/backups", {"limit": 0}),
        ("/api/events/stream", {"limit": 501}),
        ("/api/events/stream", {"poll_seconds": 0.1}),
        ("/api/runtime/stream", {"poll_seconds": 61}),
    ],
)
def test_runtime_query_cost_bounds_reject_invalid_values(
    monkeypatch,
    tmp_path,
    path: str,
    params: dict[str, int | float],
) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.get(path, params=params)

    assert response.status_code == 422


def test_calendar_uses_one_bounded_range_query() -> None:
    from trade_web.backend.runtime.resources import WebResourceContainer
    from trade_web.backend.runtime.service import RuntimeService

    class PublicDatabase:
        def __init__(self) -> None:
            self.range_calls: list[tuple[str, str, str]] = []
            self.planned_calls: list[tuple[str, str, int]] = []

        def trading_calendar_range(
            self,
            start_date: str,
            end_date: str,
            exchange: str = "SSE",
        ) -> list[dict[str, Any]]:
            self.range_calls.append((start_date, end_date, exchange))
            return [{"trade_date": start_date}, {"trade_date": end_date}]

        def planned_events_list(
            self,
            *,
            start_date: str,
            end_date: str,
            limit: int,
        ) -> list[dict[str, Any]]:
            self.planned_calls.append((start_date, end_date, limit))
            return []

    database = PublicDatabase()
    resources = cast(
        "WebResourceContainer",
        SimpleNamespace(db=database, data_root="unused"),
    )
    service = RuntimeService(resources, asyncio.Event())

    payload = asyncio.run(service.calendar(date_str="2026-07-21", days=366))

    assert database.range_calls == [("2026-07-21", "2027-07-22", "SSE")]
    assert database.planned_calls == [("2026-07-21", "2027-07-22", 100)]
    assert payload["calendar"] == [
        {"trade_date": "2026-07-21"},
        {"trade_date": "2027-07-22"},
    ]


def test_runtime_database_reads_are_offloaded_from_event_loop() -> None:
    from trade_web.backend.runtime.resources import WebResourceContainer
    from trade_web.backend.runtime.service import RuntimeService

    class BlockingDatabase:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self._lock = threading.Lock()
            self.worker_threads: list[int] = []

        def _block(self) -> None:
            with self._lock:
                self.worker_threads.append(threading.get_ident())
                if len(self.worker_threads) == 3:
                    self.started.set()
            assert self.release.wait(timeout=2)

        def trading_calendar_range(
            self,
            _start_date: str,
            _end_date: str,
            exchange: str = "SSE",
        ) -> list[dict[str, Any]]:
            del exchange
            self._block()
            return []

        def planned_events_list(
            self,
            *,
            start_date: str,
            end_date: str,
            limit: int,
        ) -> list[dict[str, Any]]:
            del start_date, end_date, limit
            return []

        def agenda_queue_recent(
            self,
            *,
            limit: int,
            status: str | None,
        ) -> list[dict[str, Any]]:
            del limit, status
            self._block()
            return []

        def backup_snapshots_recent(
            self,
            *,
            limit: int,
            status: str | None,
        ) -> list[dict[str, Any]]:
            del limit, status
            self._block()
            return []

    database = BlockingDatabase()
    resources = cast(
        "WebResourceContainer",
        SimpleNamespace(db=database, data_root="unused"),
    )

    async def exercise() -> int:
        service = RuntimeService(resources, asyncio.Event())
        main_thread = threading.get_ident()
        tasks = [
            asyncio.create_task(service.calendar(date_str="2026-07-21", days=5)),
            asyncio.create_task(service.agenda()),
            asyncio.create_task(service.backups()),
        ]
        try:
            for _ in range(200):
                if database.started.is_set():
                    break
                await asyncio.sleep(0.005)
            else:
                raise AssertionError("runtime reads did not enter worker threads concurrently")
        finally:
            database.release.set()
        await asyncio.gather(*tasks)
        return main_thread

    main_thread = asyncio.run(exercise())

    assert len(database.worker_threads) == 3
    assert all(worker_thread != main_thread for worker_thread in database.worker_threads)


def test_status_snapshot_offloads_and_coalesces_concurrent_builds() -> None:
    from trade_web.backend.runtime.resources import WebResourceContainer
    from trade_web.backend.runtime.service import RuntimeService

    resources = cast(
        "WebResourceContainer",
        SimpleNamespace(data_root="unused"),
    )

    async def exercise() -> tuple[int, list[int], list[dict[str, Any]]]:
        service = RuntimeService(resources, asyncio.Event())
        main_thread = threading.get_ident()
        calls = 0
        worker_threads: list[int] = []

        def build() -> dict[str, Any]:
            nonlocal calls
            calls += 1
            worker_threads.append(threading.get_ident())
            time.sleep(0.05)
            return {"status": "ok", "health": {"status": "ok", "reason_codes": []}}

        service._build_status_snapshot = build
        snapshots = await asyncio.gather(*(service.status_snapshot() for _ in range(8)))
        return main_thread, worker_threads, snapshots

    main_thread, worker_threads, snapshots = asyncio.run(exercise())

    assert len(worker_threads) == 1
    assert worker_threads[0] != main_thread
    assert all(snapshot == snapshots[0] for snapshot in snapshots)


def test_status_failure_is_explicit_and_sanitized(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))

    def fail_data_status(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise OSError("/private/data/vendor-secret.csv")

    def fail_backup(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("sqlite3.OperationalError: /private/backup.db is locked")

    monkeypatch.setattr("trade_py.utils.data_inspector.get_data_status", fail_data_status)
    monkeypatch.setattr("scripts.backup.backup_doctor", fail_backup)
    from trade_web import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["degraded"] is True
    assert payload["health"] == {
        "status": "degraded",
        "reason_codes": ["DATA_STATUS_UNAVAILABLE", "BACKUP_HEALTH_UNAVAILABLE"],
    }
    assert payload["data_quality_gate"]["reason_codes"] == ["DATA_STATUS_UNAVAILABLE"]
    assert "/private/" not in response.text
    assert "sqlite" not in response.text.lower()


def test_runtime_capacity_is_explicitly_unavailable_outside_lifespan(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    app = create_app()

    before_start = app.state.runtime_service.capacity_snapshot()
    assert before_start == {
        "status": "unavailable",
        "lifecycle": "new",
        "generation": None,
        "started_at": None,
        "channels": None,
    }

    app.state.resources.start()
    app.state.resources.stop(wait=True)
    after_stop = app.state.runtime_service.capacity_snapshot()
    assert after_stop == {
        "status": "unavailable",
        "lifecycle": "stopped",
        "generation": None,
        "started_at": None,
        "channels": None,
    }


def test_runtime_capacity_route_performs_no_database_query(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    app = create_app()
    with TestClient(app) as client:
        statements: list[str] = []
        db = app.state.resources.db
        db._conn.set_trace_callback(statements.append)
        try:
            response = client.get("/api/runtime/capacity")
        finally:
            db._conn.set_trace_callback(None)

    assert response.status_code == 200
    assert statements == []


def test_runtime_capacity_exposes_stopping_until_handlers_finish(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    app = create_app()
    resources = app.state.resources
    resources.start()
    started = threading.Event()
    release = threading.Event()

    def block(_event) -> None:
        started.set()
        assert release.wait(timeout=3)

    block.__qualname__ = "tests.runtime_capacity_stopping"
    resources.bus.subscribe("ops.stopping", block)
    resources.bus.publish("ops.stopping")
    assert started.wait(timeout=2)
    stopper = threading.Thread(
        target=resources.stop,
        kwargs={"wait": True},
        name="test-runtime-stop",
    )
    stopper.start()
    try:
        for _ in range(100):
            payload = app.state.runtime_service.capacity_snapshot()
            if payload["status"] == "stopping":
                break
            threading.Event().wait(0.01)
        else:
            raise AssertionError("runtime never exposed stopping capacity")

        assert payload["lifecycle"] == "stopping"
        assert payload["channels"]["io"]["lifecycle"] == "stopping"
        assert payload["channels"]["io"]["active"] == 1
    finally:
        release.set()
        stopper.join(timeout=3)

    assert not stopper.is_alive()
    assert app.state.runtime_service.capacity_snapshot() == {
        "status": "unavailable",
        "lifecycle": "stopped",
        "generation": None,
        "started_at": None,
        "channels": None,
    }


async def _first(iterator: AsyncIterator[str]) -> str:
    return await anext(iterator)


def test_runtime_signature_uses_public_persistence_facade() -> None:
    from trade_web.backend.runtime.resources import WebResourceContainer
    from trade_web.backend.runtime.service import RuntimeService

    class PublicDatabase:
        def runtime_payload_signature_inputs(self) -> tuple[object, ...]:
            return ("quality-v1", 7, 11)

        def get_latest_market_asof(self) -> str:
            return "2026-07-21"

    resources = cast(
        "WebResourceContainer",
        SimpleNamespace(db=PublicDatabase(), data_root="unused"),
    )
    service = RuntimeService(resources, asyncio.Event())

    signature = service.payload_signature("events-page")

    assert signature.startswith("events-page:2026-03-21-recommendation-recovery-v2:2026-07-21:")
    assert signature.endswith("quality-v1|7|11")


def test_runtime_streams_preserve_payload_shapes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    app = create_app()
    resources = app.state.resources
    resources.start()
    try:
        resources.db.event_log_insert("test.runtime", "{}", None)
        service = app.state.runtime_service

        async def connected() -> bool:
            return False

        event_frame = asyncio.run(
            _first(
                service.event_stream(
                    is_disconnected=connected,
                    after_id=0,
                    limit=10,
                    poll_seconds=0.25,
                )
            )
        )
        runtime_frame = asyncio.run(
            _first(
                service.runtime_stream(
                    is_disconnected=connected,
                    scope="events",
                    poll_seconds=0.25,
                )
            )
        )
    finally:
        resources.stop(wait=True)

    event_payload = json.loads(event_frame.removeprefix("data: ").strip())
    runtime_payload = json.loads(runtime_frame.removeprefix("data: ").strip())
    assert event_payload["topic"] == "test.runtime"
    assert runtime_payload["scope"] == "events-page"
    assert runtime_payload["signature"].startswith("events-page:")
    assert set(runtime_payload) == {"scope", "signature", "ts"}
