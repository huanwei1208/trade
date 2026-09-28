"""Typed evidence for package-layout performance validation."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

SCHEMA_VERSION = "trade.layout.performance.v1"
BASELINE_SCHEMA_VERSION = "trade.layout.performance-baseline.v1"


@dataclass(frozen=True)
class MetricSummary:
    samples_ms: tuple[float, ...]
    sample_count: int
    p50_ms: float
    p95_ms: float
    peak_rss_bytes: int
    module_count: int
    module_digest: str

    @classmethod
    def summarize(
        cls,
        durations_ms: list[float],
        *,
        peak_rss_bytes: int,
        module_count: int,
        module_digest: str,
    ) -> MetricSummary:
        if not durations_ms:
            raise ValueError("performance evidence requires at least one sample")
        ordered = sorted(durations_ms)
        return cls(
            samples_ms=tuple(ordered),
            sample_count=len(ordered),
            p50_ms=_percentile(ordered, 0.50),
            p95_ms=_percentile(ordered, 0.95),
            peak_rss_bytes=peak_rss_bytes,
            module_count=module_count,
            module_digest=module_digest,
        )


@dataclass(frozen=True)
class ProbeEvidence:
    cold: MetricSummary
    warm: MetricSummary


@dataclass(frozen=True)
class IndexEvidence:
    scale: int
    source_count: int
    source_bytes: int
    duration_ms: float
    peak_rss_bytes: int
    scan_count: int


@dataclass(frozen=True)
class WebBuildEvidence:
    available: bool
    root: str | None
    dependency_digest: str | None
    cache_key: str | None
    incremental_cache_key: str | None
    no_change_cache_hit: bool
    cache_invalidated: bool
    no_change_ms: float | None
    cold_build_ms: float | None
    incremental_build_ms: float | None
    cold_output_digest: str | None
    no_change_output_digest: str | None
    incremental_output_digest: str | None
    cleanup_complete: bool
    unavailable_reason: str | None


@dataclass(frozen=True)
class CapacityEvidence:
    available_cpu_count: int
    ordinary_worker_limit: int
    heavy_job_limit: int
    install_limit: int
    rss_limit_bytes: int
    temp_limit_bytes: int
    queue_deadline_seconds: int
    ordinary_observed_max: int
    heavy_observed_max: int
    install_observed_max: int
    queue_refused: bool
    rss_refused: bool
    temp_refused: bool
    cleanup_timed_out: bool
    cleanup_survivors: int
    cross_invocation_lease_claimed: bool


@dataclass(frozen=True)
class RunnerIdentity:
    identity_digest: str
    harness_digest: str
    runner_image: str
    platform: str
    machine: str
    cpu_count: int
    memory_limit_bytes: int
    python_implementation: str
    python_version: str
    python_executable_digest: str
    uv_lock_digest: str
    frontend_lock_digest: str
    node_version: str | None
    npm_version: str | None


@dataclass(frozen=True)
class PerformanceEvidence:
    generated_at: str
    source_commit: str
    source_tree_digest: str
    runner: RunnerIdentity
    cold_processes: int
    warmups: int
    warm_samples: int
    probes: dict[str, ProbeEvidence]
    current_index: IndexEvidence
    synthetic_10x_index: IndexEvidence
    web: WebBuildEvidence
    capacity: CapacityEvidence
    bridge_count: int
    bridge_cumulative_ms: float
    duplicate_implementation_imports: int

    def to_dict(self, *, baseline: bool) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = BASELINE_SCHEMA_VERSION if baseline else SCHEMA_VERSION
        return payload


@dataclass(frozen=True)
class PerformanceReport:
    status: str
    failure_class: str
    exit_code: int
    baseline_digest: str
    evidence: PerformanceEvidence
    violations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "failure_class": self.failure_class,
            "exit_code": self.exit_code,
            "baseline_digest": self.baseline_digest,
            "evidence": self.evidence.to_dict(baseline=False),
            "violations": list(self.violations),
        }


def _percentile(ordered: list[float], fraction: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    rank = fraction * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


__all__ = [
    "BASELINE_SCHEMA_VERSION",
    "CapacityEvidence",
    "IndexEvidence",
    "MetricSummary",
    "PerformanceEvidence",
    "PerformanceReport",
    "ProbeEvidence",
    "RunnerIdentity",
    "SCHEMA_VERSION",
    "WebBuildEvidence",
]
