from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from trade_py.bus import Event, EventBus
from trade_py.db.trade_db import TradeDB
from trade_web.backend.runtime import ResourceLifecycle, WebResourceContainer

if TYPE_CHECKING:
    from trade_py.services.decision_service import DecisionService
    from trade_py.services.explanation_service import ExplanationService
    from trade_py.services.state_service import StateService
    from trade_web.backend.inference import InferenceService
    from trade_web.backend.runtime.commands import RuntimeCommandRunner


@pytest.fixture(autouse=True)
def _provide_coordinated_job_run_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        TradeDB,
        "job_runs_finish_running_stage",
        lambda _db, _stage, *, status, result_summary: 0,
        raising=False,
    )


@dataclass
class _Resource:
    name: str
    events: list[str]

    def close(self) -> None:
        self.events.append(f"close:{self.name}")

    def job_runs_finish_running_stage(
        self,
        _stage: str,
        *,
        status: str,
        result_summary: str,
    ) -> int:
        del status, result_summary
        return 0


class _Bus(_Resource):
    def begin_shutdown(self) -> None:
        self.events.append(f"begin_shutdown:{self.name}")

    def shutdown(self, wait: bool = True) -> None:
        self.events.append(f"shutdown:{self.name}:{wait}")


class _Commands(_Resource):
    def begin_shutdown(self) -> None:
        self.events.append(f"begin_shutdown:{self.name}")

    def shutdown(self, *, wait: bool = True) -> None:
        self.events.append(f"shutdown:{self.name}:{wait}")


def _services(
    _root: str,
    _db: TradeDB,
    _inference: InferenceService,
) -> tuple[StateService, DecisionService, ExplanationService]:
    return (
        cast("StateService", object()),
        cast("DecisionService", object()),
        cast("ExplanationService", object()),
    )


def test_container_reuses_resources_and_closes_bus_before_db() -> None:
    import trade_py.bus as bus_module

    events: list[str] = []
    db = _Resource("db", events)
    bus = _Bus("bus", events)
    inference = object()
    container = WebResourceContainer(
        "tmp",
        db_factory=cast("Callable[[str], TradeDB]", lambda _root: db),
        bus_factory=cast("Callable[[TradeDB], EventBus]", lambda _db: bus),
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            lambda _root, _db: inference,
        ),
        service_factory=_services,
    )

    assert container.lifecycle is ResourceLifecycle.NEW
    assert container.start() is container
    assert container.start() is container
    assert container.db is db
    assert container.db is db
    assert container.bus is bus
    bus_module.bind_bus(cast("EventBus", bus))
    assert bus_module._BUS is bus

    container.stop()
    container.stop(wait=False)

    assert events == ["begin_shutdown:bus", "shutdown:bus:True", "close:db"]
    assert bus_module._BUS is None
    assert container.lifecycle is ResourceLifecycle.STOPPED
    with pytest.raises(RuntimeError, match="unavailable in stopped"):
        _ = container.db
    with pytest.raises(RuntimeError, match="cannot start Web resources from stopped"):
        container.start()


def test_container_stops_commands_before_bus_and_database() -> None:
    events: list[str] = []
    db = _Resource("db", events)
    bus = _Bus("bus", events)
    commands = _Commands("commands", events)
    container = WebResourceContainer(
        "tmp",
        db_factory=cast("Callable[[str], TradeDB]", lambda _root: db),
        bus_factory=cast("Callable[[TradeDB], EventBus]", lambda _db: bus),
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            lambda _root, _db: object(),
        ),
        command_factory=cast(
            "Callable[[str, TradeDB], RuntimeCommandRunner]",
            lambda _root, _db: commands,
        ),
        service_factory=_services,
    ).start()

    assert container.commands is commands
    container.stop(wait=False)

    assert events == [
        "begin_shutdown:commands",
        "begin_shutdown:bus",
        "shutdown:commands:True",
        "shutdown:bus:True",
        "close:db",
    ]
    assert container.lifecycle is ResourceLifecycle.STOPPED


def test_container_deadline_keeps_bus_and_database_owned_while_commands_hang() -> None:
    events: list[str] = []
    db = _Resource("db", events)
    bus = _Bus("bus", events)
    command_started = threading.Event()
    release_command = threading.Event()

    class BlockingCommands(_Commands):
        def shutdown(self, *, wait: bool = True) -> None:
            super().shutdown(wait=wait)
            command_started.set()
            assert release_command.wait(timeout=3)

    commands = BlockingCommands("commands", events)
    container = WebResourceContainer(
        "tmp",
        db_factory=cast("Callable[[str], TradeDB]", lambda _root: db),
        bus_factory=cast("Callable[[TradeDB], EventBus]", lambda _db: bus),
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            lambda _root, _db: object(),
        ),
        command_factory=cast(
            "Callable[[str, TradeDB], RuntimeCommandRunner]",
            lambda _root, _db: commands,
        ),
        service_factory=_services,
        shutdown_timeout_sec=0.05,
    ).start()

    with pytest.raises(RuntimeError, match="deadline exceeded during commands"):
        container.stop()

    assert command_started.is_set()
    assert container.lifecycle is ResourceLifecycle.STOPPING
    assert events == [
        "begin_shutdown:commands",
        "begin_shutdown:bus",
        "shutdown:commands:True",
    ]
    assert container._db is db
    assert container._bus is bus

    release_command.set()
    container.stop()

    assert events == [
        "begin_shutdown:commands",
        "begin_shutdown:bus",
        "shutdown:commands:True",
        "shutdown:bus:True",
        "close:db",
    ]
    assert container.lifecycle is ResourceLifecycle.STOPPED


def test_container_deadline_keeps_database_open_while_bus_hangs() -> None:
    events: list[str] = []
    db = _Resource("db", events)
    bus_started = threading.Event()
    release_bus_shutdown = threading.Event()

    class BlockingBus(_Bus):
        def shutdown(self, wait: bool = True) -> None:
            super().shutdown(wait=wait)
            bus_started.set()
            assert release_bus_shutdown.wait(timeout=3)

    bus = BlockingBus("bus", events)
    container = WebResourceContainer(
        "tmp",
        db_factory=cast("Callable[[str], TradeDB]", lambda _root: db),
        bus_factory=cast("Callable[[TradeDB], EventBus]", lambda _db: bus),
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            lambda _root, _db: object(),
        ),
        service_factory=_services,
        shutdown_timeout_sec=0.05,
    ).start()

    with pytest.raises(RuntimeError, match="deadline exceeded during bus"):
        container.stop()

    assert bus_started.is_set()
    assert container.lifecycle is ResourceLifecycle.STOPPING
    assert events == ["begin_shutdown:bus", "shutdown:bus:True"]
    assert container._db is db

    release_bus_shutdown.set()
    container.stop()

    assert events == ["begin_shutdown:bus", "shutdown:bus:True", "close:db"]
    assert container.lifecycle is ResourceLifecycle.STOPPED


def test_container_retries_command_shutdown_before_bus_and_database() -> None:
    events: list[str] = []
    db = _Resource("db", events)
    bus = _Bus("bus", events)

    class FailOnceCommands(_Commands):
        attempts = 0

        def shutdown(self, *, wait: bool = True) -> None:
            super().shutdown(wait=wait)
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("command shutdown failed")

    commands = FailOnceCommands("commands", events)
    container = WebResourceContainer(
        "tmp",
        db_factory=cast("Callable[[str], TradeDB]", lambda _root: db),
        bus_factory=cast("Callable[[TradeDB], EventBus]", lambda _db: bus),
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            lambda _root, _db: object(),
        ),
        command_factory=cast(
            "Callable[[str, TradeDB], RuntimeCommandRunner]",
            lambda _root, _db: commands,
        ),
        service_factory=_services,
    ).start()

    with pytest.raises(RuntimeError, match="command shutdown failed"):
        container.stop()
    assert container.lifecycle is ResourceLifecycle.STOPPING
    container.stop()

    assert events == [
        "begin_shutdown:commands",
        "begin_shutdown:bus",
        "shutdown:commands:True",
        "shutdown:commands:True",
        "shutdown:bus:True",
        "close:db",
    ]
    assert container.lifecycle is ResourceLifecycle.STOPPED


def test_container_cleans_partial_start_in_reverse_order() -> None:
    events: list[str] = []
    db = _Resource("db", events)
    bus = _Bus("bus", events)

    def fail_inference(_root, _db):
        raise RuntimeError("model startup failed")

    container = WebResourceContainer(
        "tmp",
        db_factory=cast("Callable[[str], TradeDB]", lambda _root: db),
        bus_factory=cast("Callable[[TradeDB], EventBus]", lambda _db: bus),
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            fail_inference,
        ),
        service_factory=_services,
    )

    with pytest.raises(RuntimeError, match="model startup failed"):
        container.start()

    assert events == ["shutdown:bus:True", "close:db"]
    assert container.lifecycle is ResourceLifecycle.STOPPED


def test_partial_start_allows_bus_cleanup_retry() -> None:
    events: list[str] = []
    db = _Resource("db", events)

    class FailOnceBus(_Bus):
        attempts = 0

        def shutdown(self, wait: bool = True) -> None:
            super().shutdown(wait=wait)
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("bus shutdown failed")

    def fail_inference(_root, _db):
        raise RuntimeError("model startup failed")

    container = WebResourceContainer(
        "tmp",
        db_factory=cast("Callable[[str], TradeDB]", lambda _root: db),
        bus_factory=cast(
            "Callable[[TradeDB], EventBus]",
            lambda _db: FailOnceBus("bus", events),
        ),
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            fail_inference,
        ),
        service_factory=_services,
    )

    with pytest.raises(RuntimeError, match="model startup failed"):
        container.start()
    container.stop()

    assert events == [
        "shutdown:bus:True",
        "begin_shutdown:bus",
        "shutdown:bus:True",
        "close:db",
    ]
    assert container.lifecycle is ResourceLifecycle.STOPPED


def test_container_retries_bus_shutdown_before_database() -> None:
    import trade_py.bus as bus_module

    events: list[str] = []
    db = _Resource("db", events)

    class FailOnceBus(_Bus):
        attempts = 0

        def shutdown(self, wait: bool = True) -> None:
            super().shutdown(wait=wait)
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("bus shutdown failed")

    bus = FailOnceBus("bus", events)
    container = WebResourceContainer(
        "tmp",
        db_factory=cast("Callable[[str], TradeDB]", lambda _root: db),
        bus_factory=cast(
            "Callable[[TradeDB], EventBus]",
            lambda _db: bus,
        ),
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            lambda _root, _db: object(),
        ),
        service_factory=_services,
    ).start()
    bus_module.bind_bus(cast("EventBus", bus))

    with pytest.raises(RuntimeError, match="bus shutdown failed"):
        container.stop(wait=False)
    assert container.lifecycle is ResourceLifecycle.STOPPING
    assert bus_module._BUS is bus
    container.stop(wait=True)

    assert events == [
        "begin_shutdown:bus",
        "shutdown:bus:True",
        "shutdown:bus:True",
        "close:db",
    ]
    assert bus_module._BUS is None
    assert container.lifecycle is ResourceLifecycle.STOPPED


def test_concurrent_stop_callers_share_failure_before_later_retry() -> None:
    events: list[str] = []
    db = _Resource("db", events)
    shutdown_started = threading.Event()
    release_failure = threading.Event()

    class BlockingFailOnceBus(_Bus):
        attempts = 0

        def shutdown(self, wait: bool = True) -> None:
            self.events.append(f"shutdown:{self.name}:{wait}")
            self.attempts += 1
            if self.attempts == 1:
                shutdown_started.set()
                assert release_failure.wait(timeout=3)
                raise RuntimeError("bus shutdown failed")

    container = WebResourceContainer(
        "tmp",
        db_factory=cast("Callable[[str], TradeDB]", lambda _root: db),
        bus_factory=cast(
            "Callable[[TradeDB], EventBus]",
            lambda _db: BlockingFailOnceBus("bus", events),
        ),
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            lambda _root, _db: object(),
        ),
        service_factory=_services,
    ).start()
    failures: list[BaseException] = []

    def stop_and_capture() -> None:
        try:
            container.stop(wait=True)
        except BaseException as exc:
            failures.append(exc)

    first = threading.Thread(target=stop_and_capture, name="first-failing-stop")
    second = threading.Thread(target=stop_and_capture, name="second-waiting-stop")
    first.start()
    assert shutdown_started.wait(timeout=2)
    second.start()
    assert second.is_alive()

    release_failure.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert len(failures) == 2
    assert any(str(exc) == "bus shutdown failed" for exc in failures)
    assert any(str(exc) == "Web resource shutdown failed" for exc in failures)
    assert events == ["begin_shutdown:bus", "shutdown:bus:True"]
    assert container.lifecycle is ResourceLifecycle.STOPPING

    container.stop(wait=True)

    assert events == [
        "begin_shutdown:bus",
        "shutdown:bus:True",
        "shutdown:bus:True",
        "close:db",
    ]
    assert container.lifecycle is ResourceLifecycle.STOPPED


def test_concurrent_stop_waits_for_owned_cleanup() -> None:
    events: list[str] = []
    db = _Resource("db", events)
    shutdown_started = threading.Event()
    release_shutdown = threading.Event()

    class BlockingBus(_Bus):
        def shutdown(self, wait: bool = True) -> None:
            self.events.append(f"shutdown:{self.name}:{wait}")
            shutdown_started.set()
            assert release_shutdown.wait(timeout=3)

    container = WebResourceContainer(
        "tmp",
        db_factory=cast("Callable[[str], TradeDB]", lambda _root: db),
        bus_factory=cast(
            "Callable[[TradeDB], EventBus]",
            lambda _db: BlockingBus("bus", events),
        ),
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            lambda _root, _db: object(),
        ),
        service_factory=_services,
    ).start()
    first = threading.Thread(
        target=container.stop,
        kwargs={"wait": True},
        name="first-stop",
    )
    second_finished = threading.Event()

    def second_stop() -> None:
        container.stop(wait=True)
        second_finished.set()

    second = threading.Thread(target=second_stop, name="second-stop")
    first.start()
    assert shutdown_started.wait(timeout=2)
    second.start()
    assert not second_finished.wait(timeout=0.05)

    release_shutdown.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert second_finished.is_set()
    assert events == ["begin_shutdown:bus", "shutdown:bus:True", "close:db"]
    assert container.lifecycle is ResourceLifecycle.STOPPED


def test_wait_false_drains_real_handler_before_closing_sqlite(tmp_path) -> None:
    db = TradeDB(tmp_path)
    bus = EventBus(db)
    handler_started = threading.Event()
    release_handler = threading.Event()
    handler_finished = threading.Event()

    def persist_shutdown_state(_event: Event) -> None:
        handler_started.set()
        assert release_handler.wait(timeout=3)
        db.set("runtime.shutdown.persisted", "yes")
        handler_finished.set()

    container = WebResourceContainer(
        str(tmp_path),
        db_factory=lambda _root: db,
        bus_factory=lambda _db: bus,
        inference_factory=cast(
            "Callable[[str, TradeDB], InferenceService]",
            lambda _root, _db: object(),
        ),
        service_factory=_services,
    ).start()
    bus.subscribe("ops.shutdown", persist_shutdown_state)
    event = bus.publish("ops.shutdown")
    assert handler_started.wait(timeout=2)

    stop_finished = threading.Event()
    stop_failures: list[BaseException] = []

    def stop_without_wait() -> None:
        try:
            container.stop(wait=False)
        except BaseException as exc:
            stop_failures.append(exc)
        finally:
            stop_finished.set()

    stop_thread = threading.Thread(target=stop_without_wait, name="safe-stop")
    stop_thread.start()
    try:
        assert not stop_finished.wait(timeout=0.05)
        assert container.lifecycle is ResourceLifecycle.STOPPING
        assert db.get("runtime.shutdown.persisted") is None
    finally:
        release_handler.set()
        stop_thread.join(timeout=3)

    assert not stop_thread.is_alive()
    assert stop_finished.is_set()
    assert not stop_failures
    assert handler_finished.is_set()
    assert container.lifecycle is ResourceLifecycle.STOPPED

    reopened = TradeDB(tmp_path)
    try:
        assert reopened.get("runtime.shutdown.persisted") == "yes"
        rows = reopened.event_log_recent(topic="ops.shutdown")
        assert rows[0]["id"] == event.id
        assert rows[0]["status"] == "ok"
    finally:
        reopened.close()
