"""Per-invocation validation capacity policy and proof fixtures."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from trade_py.devtools.layout_performance.models import CapacityEvidence
from trade_py.devtools.layout_performance.processes import run_process

GIB = 1024 * 1024 * 1024


class CapacityRefused(RuntimeError):
    pass


@dataclass
class ValidationCapacity:
    available_cpu_count: int = field(default_factory=lambda: max(1, os.cpu_count() or 1))
    available_memory_bytes: int = 8 * GIB
    ordinary_worker_limit: int = field(init=False)
    heavy_job_limit: int = 2
    install_limit: int = 2
    temp_limit_bytes: int = 10 * GIB
    queue_deadline_seconds: int = 120
    _ordinary: threading.BoundedSemaphore = field(init=False, repr=False)
    _heavy: threading.BoundedSemaphore = field(init=False, repr=False)
    _install: threading.BoundedSemaphore = field(init=False, repr=False)
    _resource_condition: threading.Condition = field(init=False, repr=False)
    _reserved_rss_bytes: int = field(default=0, init=False, repr=False)
    _reserved_temp_bytes: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.ordinary_worker_limit = min(4, max(1, self.available_cpu_count // 2))
        self._ordinary = threading.BoundedSemaphore(self.ordinary_worker_limit)
        self._heavy = threading.BoundedSemaphore(self.heavy_job_limit)
        self._install = threading.BoundedSemaphore(self.install_limit)
        self._resource_condition = threading.Condition()

    @property
    def rss_limit_bytes(self) -> int:
        return min(int(self.available_memory_bytes * 0.75), 8 * GIB)

    @contextmanager
    def admit(
        self,
        resource_class: str,
        *,
        timeout_seconds: float,
        rss_bytes: int = 0,
        temp_bytes: int = 0,
    ) -> Iterator[None]:
        if timeout_seconds <= 0 or rss_bytes < 0 or temp_bytes < 0:
            raise ValueError("capacity requests must be finite and non-negative")
        self.require_rss(rss_bytes)
        self.require_temp(temp_bytes)
        semaphore = {
            "ordinary": self._ordinary,
            "heavy": self._heavy,
            "install": self._install,
        }.get(resource_class)
        if semaphore is None:
            raise ValueError(f"unknown validation resource class: {resource_class}")
        deadline = time.monotonic() + min(timeout_seconds, self.queue_deadline_seconds)
        if not semaphore.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise CapacityRefused(f"{resource_class} queue deadline exceeded")
        try:
            with self._resource_condition:
                admitted = self._resource_condition.wait_for(
                    lambda: (
                        self._reserved_rss_bytes + rss_bytes <= self.rss_limit_bytes
                        and self._reserved_temp_bytes + temp_bytes <= self.temp_limit_bytes
                    ),
                    timeout=max(0.0, deadline - time.monotonic()),
                )
                if not admitted:
                    raise CapacityRefused("validation resource queue deadline exceeded")
                self._reserved_rss_bytes += rss_bytes
                self._reserved_temp_bytes += temp_bytes
            try:
                yield
            finally:
                with self._resource_condition:
                    self._reserved_rss_bytes -= rss_bytes
                    self._reserved_temp_bytes -= temp_bytes
                    self._resource_condition.notify_all()
        finally:
            semaphore.release()

    def require_rss(self, requested_bytes: int) -> None:
        if requested_bytes > self.rss_limit_bytes:
            raise CapacityRefused("validation RSS request exceeds its process-tree budget")

    def require_temp(self, requested_bytes: int) -> None:
        if requested_bytes > self.temp_limit_bytes:
            raise CapacityRefused("temporary output request exceeds its process-tree budget")


def prove_capacity_policy(capacity: ValidationCapacity | None = None) -> CapacityEvidence:
    if capacity is None:
        capacity = ValidationCapacity(available_memory_bytes=detected_memory_bytes())
    ordinary_max = _measure_concurrency(capacity, "ordinary", capacity.ordinary_worker_limit + 2)
    heavy_max = _measure_concurrency(capacity, "heavy", capacity.heavy_job_limit + 2)
    install_max = _measure_concurrency(capacity, "install", capacity.install_limit + 2)
    queue_refused = False
    with ExitStack() as stack:
        for _index in range(capacity.ordinary_worker_limit):
            stack.enter_context(capacity.admit("ordinary", timeout_seconds=0.1))
        try:
            capacity.admit("ordinary", timeout_seconds=0.01).__enter__()
        except CapacityRefused:
            queue_refused = True
    rss_refused = _measured_rss_refusal()
    temp_refused = _measured_temp_refusal()
    cleanup = run_process(
        (
            sys.executable,
            "-c",
            (
                "import subprocess,sys,time;"
                "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                "time.sleep(30)"
            ),
        ),
        cwd=Path.cwd(),
        timeout_seconds=0.05,
        allow_timeout=True,
    )
    return CapacityEvidence(
        available_cpu_count=capacity.available_cpu_count,
        ordinary_worker_limit=capacity.ordinary_worker_limit,
        heavy_job_limit=capacity.heavy_job_limit,
        install_limit=capacity.install_limit,
        rss_limit_bytes=capacity.rss_limit_bytes,
        temp_limit_bytes=capacity.temp_limit_bytes,
        queue_deadline_seconds=capacity.queue_deadline_seconds,
        ordinary_observed_max=ordinary_max,
        heavy_observed_max=heavy_max,
        install_observed_max=install_max,
        queue_refused=queue_refused,
        rss_refused=rss_refused,
        temp_refused=temp_refused,
        cleanup_timed_out=cleanup.timed_out,
        cleanup_survivors=cleanup.cleanup_survivors,
        cross_invocation_lease_claimed=False,
    )


def _measure_concurrency(
    capacity: ValidationCapacity,
    resource_class: str,
    tasks: int,
) -> int:
    active = 0
    maximum = 0
    lock = threading.Lock()

    def work() -> None:
        nonlocal active, maximum
        token = capacity.admit(resource_class, timeout_seconds=1)
        token.__enter__()
        try:
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.01)
            with lock:
                active -= 1
        finally:
            token.__exit__(None, None, None)

    with ThreadPoolExecutor(max_workers=tasks) as executor:
        tuple(executor.map(lambda _index: work(), range(tasks)))
    return maximum


def _measured_rss_refusal() -> bool:
    try:
        run_process(
            (sys.executable, "-c", "import time;time.sleep(.2)"),
            cwd=Path.cwd(),
            timeout_seconds=2,
            rss_limit_bytes=1024 * 1024,
        )
    except Exception as exc:
        return getattr(exc, "code", None) == "layout.performance.capacity_rss"
    return False


def _measured_temp_refusal() -> bool:
    with tempfile.TemporaryDirectory(prefix="trade-layout-capacity-temp-") as temporary:
        root = Path(temporary)
        try:
            run_process(
                (
                    sys.executable,
                    "-c",
                    (
                        "import pathlib,time;"
                        f"pathlib.Path({str(root / 'overflow.bin')!r}).write_bytes(b'x'*4096);"
                        "time.sleep(.2)"
                    ),
                ),
                cwd=root,
                timeout_seconds=2,
                temp_limit_bytes=1024,
                temp_root=root,
            )
        except Exception as exc:
            return getattr(exc, "code", None) == "layout.performance.capacity_temp"
    return False


def detected_memory_bytes() -> int:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return 8 * GIB
    if not isinstance(pages, int) or not isinstance(page_size, int):
        return 8 * GIB
    host_memory = max(GIB, pages * page_size)
    cgroup_limit = _cgroup_memory_limit()
    return min(host_memory, cgroup_limit) if cgroup_limit is not None else host_memory


def _cgroup_memory_limit() -> int | None:
    for candidate in (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ):
        try:
            value = candidate.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            continue
        if value == "max":
            continue
        try:
            parsed = int(value)
        except ValueError:
            continue
        if parsed > 0:
            return parsed
    return None


__all__ = [
    "CapacityRefused",
    "ValidationCapacity",
    "detected_memory_bytes",
    "prove_capacity_policy",
]
