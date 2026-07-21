"""Explicit lifecycle owner for Trade Web process resources."""

from __future__ import annotations

import inspect
import logging
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from trade_py.bus import EventBus
    from trade_py.bus.models import RuntimeCapacitySnapshot
    from trade_py.db.trade_db import TradeDB
    from trade_py.services.decision_service import DecisionService
    from trade_py.services.explanation_service import ExplanationService
    from trade_py.services.state_service import StateService
    from trade_web.backend.inference import InferenceService
    from trade_web.backend.runtime.commands import CommandRunStore, RuntimeCommandRunner


logger = logging.getLogger(__name__)


class ResourceLifecycle(str, Enum):
    NEW = "new"
    STARTED = "started"
    STOPPING = "stopping"
    STOPPED = "stopped"


class WebResourceContainer:
    """Own one Web database, runtime bus, and service graph."""

    def __init__(
        self,
        data_root: str,
        *,
        db_factory: Callable[[str], TradeDB] | None = None,
        bus_factory: Callable[[TradeDB], EventBus] | None = None,
        inference_factory: Callable[[str, TradeDB], InferenceService] | None = None,
        command_factory: Callable[[str, TradeDB], RuntimeCommandRunner] | None = None,
        service_factory: Callable[
            [str, TradeDB, InferenceService],
            tuple[StateService, DecisionService, ExplanationService],
        ]
        | None = None,
        shutdown_timeout_sec: float = 10.0,
    ) -> None:
        if shutdown_timeout_sec <= 0:
            raise ValueError("shutdown_timeout_sec must be positive")
        self.data_root = data_root
        self._db_factory = db_factory or self._default_db_factory
        self._bus_factory = bus_factory or self._default_bus_factory
        self._inference_factory = inference_factory or self._default_inference_factory
        self._command_factory = command_factory or self._default_command_factory
        self._service_factory = service_factory or self._default_service_factory
        self._lock = threading.RLock()
        self._stop_condition = threading.Condition(self._lock)
        self._stop_attempt_sequence = 0
        self._active_stop_attempt: int | None = None
        self._stop_results: dict[int, Exception | None] = {}
        self._stop_failure: Exception | None = None
        self._shutdown_timeout_sec = float(shutdown_timeout_sec)
        self._shutdown_threads: dict[str, threading.Thread] = {}
        self._shutdown_stage_results: dict[str, BaseException | None] = {}
        self._commands_shutdown_begun = False
        self._bus_shutdown_begun = False
        self._commands_stopped = False
        self._bus_stopped = False
        self._db_closed = False
        self._bus_released = False
        self._lifecycle = ResourceLifecycle.NEW
        self._db: TradeDB | None = None
        self._bus: EventBus | None = None
        self._inference: InferenceService | None = None
        self._commands: RuntimeCommandRunner | None = None
        self._state_service: StateService | None = None
        self._decision_service: DecisionService | None = None
        self._explanation_service: ExplanationService | None = None

    @staticmethod
    def _default_db_factory(data_root: str) -> TradeDB:
        from trade_py.db.trade_db import TradeDB

        return TradeDB(data_root)

    @staticmethod
    def _default_bus_factory(db: TradeDB) -> EventBus:
        from trade_py.bus import EventBus, bind_bus

        bus = EventBus(db)
        try:
            return bind_bus(bus)
        except Exception:
            bus.shutdown(wait=True)
            raise

    @staticmethod
    def _default_inference_factory(data_root: str, db: TradeDB) -> InferenceService:
        from trade_web.backend.inference import InferenceService

        return InferenceService(data_root, db=db)

    @staticmethod
    def _default_command_factory(
        data_root: str,
        db: TradeDB,
    ) -> RuntimeCommandRunner:
        from trade_web.backend.runtime.commands import RuntimeCommandRunner

        return RuntimeCommandRunner(data_root, cast("CommandRunStore", db))

    @staticmethod
    def _default_service_factory(
        data_root: str,
        db: TradeDB,
        inference: InferenceService,
    ) -> tuple[StateService, DecisionService, ExplanationService]:
        from trade_py.services.decision_service import DecisionService
        from trade_py.services.explanation_service import ExplanationService
        from trade_py.services.state_service import StateService

        state_service = StateService(data_root, db=db)
        decision_service = DecisionService(inference=inference)
        explanation_service = ExplanationService(
            state_service,
            decision_service,
            inference=inference,
        )
        return state_service, decision_service, explanation_service

    @property
    def lifecycle(self) -> ResourceLifecycle:
        with self._lock:
            return self._lifecycle

    def start(self) -> WebResourceContainer:
        with self._lock:
            if self._lifecycle is ResourceLifecycle.STARTED:
                return self
            if self._lifecycle is not ResourceLifecycle.NEW:
                raise RuntimeError(f"cannot start Web resources from {self._lifecycle.value}")
            created: list[tuple[str, Any]] = []
            try:
                self._db = self._db_factory(self.data_root)
                created.append(("db", self._db))
                self._bus = self._bus_factory(self._db)
                created.append(("bus", self._bus))
                self._inference = self._inference_factory(self.data_root, self._db)
                created.append(("inference", self._inference))
                (
                    self._state_service,
                    self._decision_service,
                    self._explanation_service,
                ) = self._service_factory(self.data_root, self._db, self._inference)
                self._commands = self._command_factory(self.data_root, self._db)
                created.append(("commands", self._commands))
            except Exception:
                cleanup_failure = self._cleanup_created(created)
                if cleanup_failure is None:
                    self._clear_resources()
                    self._lifecycle = ResourceLifecycle.STOPPED
                else:
                    self._stop_failure = cleanup_failure
                    self._lifecycle = ResourceLifecycle.STOPPING
                raise
            self._lifecycle = ResourceLifecycle.STARTED
            return self

    def stop(self, *, wait: bool = False) -> None:
        """Stop admission and drain DB-writing handlers before closing the owned DB.

        ``wait=False`` remains accepted for caller compatibility, but a container
        that owns a database must promote it to a safe draining shutdown.
        """
        with self._stop_condition:
            if self._lifecycle is ResourceLifecycle.STOPPED:
                return
            if self._lifecycle is ResourceLifecycle.NEW:
                self._lifecycle = ResourceLifecycle.STOPPED
                self._stop_condition.notify_all()
                return
            if self._active_stop_attempt is not None:
                active_attempt = self._active_stop_attempt
                self._stop_condition.wait_for(lambda: active_attempt in self._stop_results)
                failure = self._stop_results[active_attempt]
                if failure is not None:
                    raise RuntimeError("Web resource shutdown failed") from failure
                return
            if self._lifecycle is ResourceLifecycle.STARTED:
                self._lifecycle = ResourceLifecycle.STOPPING
            self._stop_attempt_sequence += 1
            attempt = self._stop_attempt_sequence
            self._active_stop_attempt = attempt
            commands = self._commands
            bus = self._bus
            db = self._db
        try:
            deadline = time.monotonic() + self._shutdown_timeout_sec
            self._stop_owned_resources(
                commands=commands,
                bus=bus,
                db=db,
                deadline=deadline,
            )
        except Exception as exc:
            with self._stop_condition:
                self._stop_failure = exc
                self._stop_results[attempt] = exc
                self._active_stop_attempt = None
                self._stop_condition.notify_all()
            raise
        with self._stop_condition:
            self._stop_failure = None
            self._clear_resources()
            self._lifecycle = ResourceLifecycle.STOPPED
            self._stop_results[attempt] = None
            self._active_stop_attempt = None
            self._stop_condition.notify_all()

    def _stop_owned_resources(
        self,
        *,
        commands: RuntimeCommandRunner | None,
        bus: EventBus | None,
        db: TradeDB | None,
        deadline: float,
    ) -> None:
        if (
            commands is not None
            and not self._commands_stopped
            and not self._commands_shutdown_begun
        ):
            commands.begin_shutdown()
            self._commands_shutdown_begun = True
        if bus is not None and not self._bus_stopped and not self._bus_shutdown_begun:
            bus.begin_shutdown()
            self._bus_shutdown_begun = True
        if commands is not None and not self._commands_stopped:
            self._run_bounded_shutdown(
                "commands",
                lambda: commands.shutdown(wait=True),
                deadline=deadline,
            )
            self._commands_stopped = True
        if bus is not None and not self._bus_stopped:
            self._run_bounded_shutdown(
                "bus",
                lambda: self._shutdown_bus(bus, deadline),
                deadline=deadline,
            )
            self._bus_stopped = True
        if db is not None and not self._db_closed:
            self._run_bounded_shutdown(
                "database",
                db.close,
                deadline=deadline,
            )
            self._db_closed = True
        if bus is not None and not self._bus_released:
            self._release_bus(bus)
            self._bus_released = True

    @staticmethod
    def _shutdown_bus(bus: EventBus, deadline: float) -> None:
        remaining = max(0.01, deadline - time.monotonic())
        parameters = inspect.signature(bus.shutdown).parameters.values()
        accepts_timeout = any(
            parameter.name == "timeout_sec" or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        if accepts_timeout:
            bus.shutdown(wait=True, timeout_sec=remaining)
        else:
            bus.shutdown(wait=True)

    def _run_bounded_shutdown(
        self,
        stage: str,
        shutdown: Callable[[], None],
        *,
        deadline: float,
    ) -> None:
        with self._stop_condition:
            existing = self._shutdown_threads.get(stage)
            if existing is not None and not existing.is_alive():
                previous_failure = self._shutdown_stage_results.pop(stage, None)
                self._shutdown_threads.pop(stage, None)
                if previous_failure is None:
                    return
                existing = None
            if existing is None:
                self._shutdown_stage_results.pop(stage, None)

                def run() -> None:
                    failure: BaseException | None = None
                    try:
                        shutdown()
                    except BaseException as exc:
                        failure = exc
                    with self._stop_condition:
                        self._shutdown_stage_results[stage] = failure
                        self._stop_condition.notify_all()

                existing = threading.Thread(
                    target=run,
                    name=f"web-shutdown-{stage}",
                    daemon=True,
                )
                self._shutdown_threads[stage] = existing
                existing.start()
        existing.join(timeout=max(0.0, deadline - time.monotonic()))
        if existing.is_alive():
            raise RuntimeError(f"Web resource shutdown deadline exceeded during {stage}")
        with self._stop_condition:
            failure = self._shutdown_stage_results.pop(stage, None)
            self._shutdown_threads.pop(stage, None)
        if failure is not None:
            if isinstance(failure, Exception):
                raise failure
            raise RuntimeError(f"Web resource {stage} shutdown failed") from failure

    def _cleanup_created(self, created: list[tuple[str, Any]]) -> Exception | None:
        failure: Exception | None = None
        bus_to_release: EventBus | None = None
        for name, resource in reversed(created):
            if name == "db" and failure is not None:
                logger.error("leaving partially started Web database open after bus drain failure")
                continue
            try:
                if name == "bus":
                    resource.shutdown(wait=True)
                    self._bus_stopped = True
                    bus_to_release = resource
                elif name == "commands":
                    resource.shutdown(wait=True)
                    self._commands_stopped = True
                elif name == "db":
                    resource.close()
                    self._db_closed = True
            except Exception as exc:
                if failure is None:
                    failure = exc
                logger.exception("failed to clean up partially started Web resource %s", name)
        if failure is None and bus_to_release is not None:
            try:
                self._release_bus(bus_to_release)
                self._bus_released = True
            except Exception as exc:
                failure = exc
                logger.exception("failed to release partially started Web bus")
        return failure

    @staticmethod
    def _release_bus(bus: EventBus) -> None:
        from trade_py.bus import release_bus

        release_bus(bus)

    def _clear_resources(self) -> None:
        self._explanation_service = None
        self._decision_service = None
        self._state_service = None
        self._inference = None
        self._commands = None
        self._bus = None
        self._db = None

    def _require(self, name: str, value: Any) -> Any:
        with self._lock:
            if self._lifecycle is not ResourceLifecycle.STARTED or value is None:
                raise RuntimeError(f"Web resource {name} is unavailable in {self._lifecycle.value}")
            return value

    @property
    def db(self) -> TradeDB:
        return self._require("db", self._db)

    @property
    def bus(self) -> EventBus:
        return self._require("bus", self._bus)

    @property
    def inference(self) -> InferenceService:
        return self._require("inference", self._inference)

    @property
    def commands(self) -> RuntimeCommandRunner:
        return self._require("commands", self._commands)

    @property
    def state_service(self) -> StateService:
        return self._require("state_service", self._state_service)

    @property
    def decision_service(self) -> DecisionService:
        return self._require("decision_service", self._decision_service)

    @property
    def explanation_service(self) -> ExplanationService:
        return self._require("explanation_service", self._explanation_service)

    def bus_capacity_snapshot(
        self,
    ) -> tuple[ResourceLifecycle, RuntimeCapacitySnapshot | None]:
        """Read bus capacity atomically with respect to container shutdown."""
        with self._lock:
            lifecycle = self._lifecycle
            if (
                lifecycle
                not in {
                    ResourceLifecycle.STARTED,
                    ResourceLifecycle.STOPPING,
                }
                or self._bus is None
            ):
                return lifecycle, None
            return lifecycle, self._bus.capacity_snapshot()
