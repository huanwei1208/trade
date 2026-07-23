from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from trade_py.bus.models import (
    AdmissionOutcome,
    BusLifecycle,
    ChannelCapacitySnapshot,
    ChannelConfig,
)

MAX_CHANNEL_CAPACITY = 256


def validate_channel_config(
    name: str,
    *,
    workers: int,
    capacity: int,
) -> ChannelConfig:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers <= 0:
        raise ValueError(f"{name} workers must be positive")
    if isinstance(capacity, bool) or not isinstance(capacity, int):
        raise ValueError(f"{name} capacity must be an integer")
    if capacity < workers:
        raise ValueError(f"{name} capacity must be at least its worker count")
    if capacity > MAX_CHANNEL_CAPACITY:
        raise ValueError(f"{name} capacity must not exceed reviewed bound {MAX_CHANNEL_CAPACITY}")
    return ChannelConfig(workers=workers, capacity=capacity)


class AdmissionPermit:
    def __init__(self, owner: ChannelAdmission) -> None:
        self._owner = owner
        self._active = False
        self._released = False
        self._lock = threading.Lock()

    def mark_active(self) -> None:
        with self._lock:
            if self._released:
                raise RuntimeError("cannot activate a released admission permit")
            if self._active:
                return
            self._active = True
        self._owner._mark_active()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
            was_active = self._active
        self._owner._release(was_active=was_active)

    def __enter__(self) -> AdmissionPermit:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


class ChannelAdmission:
    def __init__(self, name: str, config: ChannelConfig) -> None:
        self.name = name
        self.config = config
        self._semaphore = threading.BoundedSemaphore(config.capacity)
        self._lock = threading.RLock()
        self._lifecycle = BusLifecycle.READY
        self._admitted = 0
        self._active = 0
        self._accepted_count = 0
        self._saturated_count = 0
        self._shutting_down_count = 0
        self._submission_failed_count = 0
        self._last_saturation_at: datetime | None = None
        self._last_saturation_log_at: float | None = None

    @property
    def lifecycle(self) -> BusLifecycle:
        with self._lock:
            return self._lifecycle

    def acquire(self) -> tuple[AdmissionOutcome, AdmissionPermit | None]:
        with self._lock:
            if self._lifecycle is not BusLifecycle.READY:
                self._shutting_down_count += 1
                return AdmissionOutcome.SHUTTING_DOWN, None
            if not self._semaphore.acquire(blocking=False):
                self._saturated_count += 1
                self._last_saturation_at = datetime.now(timezone.utc)
                return AdmissionOutcome.SATURATED, None
            self._admitted += 1
            return AdmissionOutcome.ACCEPTED, AdmissionPermit(self)

    def record_submission_success(self) -> None:
        with self._lock:
            self._accepted_count += 1

    def record_submission_failure(self) -> None:
        with self._lock:
            self._submission_failed_count += 1

    def should_log_saturation(self, *, interval_seconds: float = 30.0) -> bool:
        now = time.monotonic()
        with self._lock:
            if (
                self._last_saturation_log_at is not None
                and now - self._last_saturation_log_at < max(0.0, interval_seconds)
            ):
                return False
            self._last_saturation_log_at = now
            return True

    def begin_shutdown(self) -> None:
        with self._lock:
            if self._lifecycle is BusLifecycle.READY:
                self._lifecycle = BusLifecycle.STOPPING

    def finish_shutdown(self) -> None:
        with self._lock:
            self._lifecycle = BusLifecycle.STOPPED

    def snapshot(self) -> ChannelCapacitySnapshot:
        with self._lock:
            return ChannelCapacitySnapshot(
                name=self.name,
                lifecycle=self._lifecycle,
                workers=self.config.workers,
                capacity=self.config.capacity,
                admitted=self._admitted,
                active=self._active,
                available=self.config.capacity - self._admitted,
                accepted_count=self._accepted_count,
                saturated_count=self._saturated_count,
                shutting_down_count=self._shutting_down_count,
                submission_failed_count=self._submission_failed_count,
                last_saturation_at=self._last_saturation_at,
            )

    def _mark_active(self) -> None:
        with self._lock:
            if self._active >= self._admitted:
                raise RuntimeError(f"{self.name} active work exceeds admitted work")
            self._active += 1

    def _release(self, *, was_active: bool) -> None:
        with self._lock:
            if self._admitted <= 0:
                raise RuntimeError(f"{self.name} permit accounting underflow")
            self._admitted -= 1
            if was_active:
                if self._active <= 0:
                    raise RuntimeError(f"{self.name} active accounting underflow")
                self._active -= 1
        self._semaphore.release()
