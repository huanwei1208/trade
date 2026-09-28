"""Cold and warm package-layout startup probe collection."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from trade_py.devtools.layout_performance.capacity import ValidationCapacity
from trade_py.devtools.layout_performance.models import MetricSummary, ProbeEvidence
from trade_py.devtools.layout_performance.processes import (
    PerformanceProcessError,
    ProcessOutcome,
    run_process,
)

COLD_PROCESSES = 15
WARMUPS = 5
WARM_SAMPLES = 30
PROBE_TIMEOUT_SECONDS = 60
PROBE_NAMES = (
    "console_help",
    "domain_help",
    "factory_construct",
    "import_trade",
    "import_trade_web",
    "root_help",
)


def capture_probe_evidence(
    repo_root: Path,
    *,
    capacity: ValidationCapacity,
) -> dict[str, ProbeEvidence]:
    root = repo_root.resolve()
    result: dict[str, ProbeEvidence] = {}
    with tempfile.TemporaryDirectory(prefix="trade-layout-probe-data-") as data_root:
        for name in PROBE_NAMES:
            cold_payloads = _cold_payloads(root, name, capacity, Path(data_root))
            warm_payload = _run_probe_worker(
                root,
                name=name,
                samples=WARM_SAMPLES,
                warmups=WARMUPS,
                capacity=capacity,
                data_root=Path(data_root),
            )
            result[name] = ProbeEvidence(
                cold=_summary(cold_payloads),
                warm=_summary((warm_payload,)),
            )
    return result


def _cold_payloads(
    repo_root: Path,
    name: str,
    capacity: ValidationCapacity,
    data_root: Path,
) -> tuple[dict[str, Any], ...]:
    def collect(_index: int) -> dict[str, Any]:
        return _run_probe_worker(
            repo_root,
            name=name,
            samples=1,
            warmups=0,
            capacity=capacity,
            data_root=data_root,
        )

    with ThreadPoolExecutor(max_workers=capacity.ordinary_worker_limit) as executor:
        return tuple(executor.map(collect, range(COLD_PROCESSES)))


def _run_probe_worker(
    repo_root: Path,
    *,
    name: str,
    samples: int,
    warmups: int,
    capacity: ValidationCapacity,
    data_root: Path,
) -> dict[str, Any]:
    with capacity.admit(
        "ordinary",
        timeout_seconds=capacity.queue_deadline_seconds,
        rss_bytes=256 * 1024 * 1024,
        temp_bytes=16 * 1024 * 1024,
    ):
        outcome = run_process(
            (
                sys.executable,
                "-m",
                "trade_py.devtools.layout_performance.worker",
                "probe",
                "--probe",
                name,
                "--samples",
                str(samples),
                "--warmups",
                str(warmups),
            ),
            cwd=repo_root,
            timeout_seconds=PROBE_TIMEOUT_SECONDS,
            output_limit_bytes=128 * 1024,
            rss_limit_bytes=256 * 1024 * 1024,
            temp_limit_bytes=16 * 1024 * 1024,
            temp_root=data_root,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PIP_NO_INDEX": "1",
                "TRADE_DATA_ROOT": str(data_root),
                "UV_FROZEN": "1",
                "UV_NO_SYNC": "1",
                "UV_OFFLINE": "1",
            },
        )
    _require_completed(outcome, name)
    payload = json.loads(outcome.stdout)
    if not isinstance(payload, dict):
        raise TypeError(f"probe {name} evidence must be an object")
    measured_rss = payload.get("peak_rss_bytes")
    if not isinstance(measured_rss, int) or isinstance(measured_rss, bool):
        raise TypeError(f"probe {name} RSS evidence must be an integer")
    payload["peak_rss_bytes"] = max(
        measured_rss,
        outcome.peak_process_tree_rss_bytes,
    )
    if samples == 1 and warmups == 0:
        payload["durations_ms"] = [outcome.duration_ms]
    return payload


def _require_completed(outcome: ProcessOutcome, name: str) -> None:
    if outcome.timed_out:
        raise PerformanceProcessError(
            "layout.performance.probe_timeout",
            f"probe {name} exceeded {PROBE_TIMEOUT_SECONDS} seconds",
        )
    if outcome.cleanup_survivors:
        raise PerformanceProcessError(
            "layout.performance.probe_cleanup",
            f"probe {name} left {outcome.cleanup_survivors} process groups",
        )


def _summary(payloads: tuple[dict[str, Any], ...]) -> MetricSummary:
    durations: list[float] = []
    peak_rss = 0
    module_count = 0
    module_rows: list[str] = []
    for payload in payloads:
        raw_durations = payload.get("durations_ms")
        if not isinstance(raw_durations, list) or not raw_durations:
            raise TypeError("probe durations_ms must be a non-empty list")
        for value in raw_durations:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise TypeError("probe duration must be a non-negative number")
            durations.append(float(value))
        rss = _positive_int(payload, "peak_rss_bytes")
        modules = _positive_int(payload, "module_count")
        digest = payload.get("module_digest")
        if not _is_digest(digest):
            raise TypeError("probe module_digest must be a SHA-256 digest")
        peak_rss = max(peak_rss, rss)
        module_count = max(module_count, modules)
        module_rows.append(str(digest))
    digest = hashlib.sha256()
    for row in sorted(module_rows):
        digest.update(row.encode("ascii"))
        digest.update(b"\n")
    return MetricSummary.summarize(
        durations,
        peak_rss_bytes=peak_rss,
        module_count=module_count,
        module_digest=f"sha256:{digest.hexdigest()}",
    )


def _positive_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise TypeError(f"probe {key} must be a positive integer")
    return value


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


__all__ = [
    "COLD_PROCESSES",
    "PROBE_NAMES",
    "WARMUPS",
    "WARM_SAMPLES",
    "capture_probe_evidence",
]
