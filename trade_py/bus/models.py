from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, TypeVar


class BusLifecycle(str, Enum):
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"


class RuntimeCapacityStatus(str, Enum):
    READY = "ready"
    SATURATED = "saturated"
    STOPPING = "stopping"
    STOPPED = "stopped"
    UNAVAILABLE = "unavailable"


class AdmissionOutcome(str, Enum):
    ACCEPTED = "accepted"
    SATURATED = "saturated"
    SHUTTING_DOWN = "shutting_down"
    SUBMISSION_FAILED = "submission_failed"


@dataclass(frozen=True)
class ChannelConfig:
    workers: int
    capacity: int


@dataclass(frozen=True)
class HandlerAdmissionResult:
    event_id: int
    handler_name: str
    channel: str
    outcome: AdmissionOutcome
    detail: str | None = None
    cause: Exception | None = None


EventT = TypeVar("EventT")


@dataclass(frozen=True)
class PublishResult(Generic[EventT]):
    event: EventT
    outcome: AdmissionOutcome
    handlers: tuple[HandlerAdmissionResult, ...]

    @property
    def accepted(self) -> bool:
        return self.outcome is AdmissionOutcome.ACCEPTED


@dataclass(frozen=True)
class ChannelCapacitySnapshot:
    name: str
    lifecycle: BusLifecycle
    workers: int
    capacity: int
    admitted: int
    active: int
    available: int
    accepted_count: int
    saturated_count: int
    shutting_down_count: int
    submission_failed_count: int
    last_saturation_at: datetime | None


@dataclass(frozen=True)
class RuntimeCapacitySnapshot:
    generation: str
    status: RuntimeCapacityStatus
    lifecycle: BusLifecycle
    started_at: datetime
    channels: tuple[ChannelCapacitySnapshot, ...]
