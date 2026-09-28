"""Closed semantic validation for layout performance evidence."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone

from trade_py.devtools.layout_performance.identity import runner_identity_digest
from trade_py.devtools.layout_performance.models import (
    CapacityEvidence,
    MetricSummary,
    PerformanceEvidence,
    WebBuildEvidence,
)
from trade_py.devtools.layout_performance.probes import (
    COLD_PROCESSES,
    PROBE_NAMES,
    WARM_SAMPLES,
    WARMUPS,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}")


def validate_performance_evidence(evidence: PerformanceEvidence) -> None:
    _require_timestamp(evidence.generated_at)
    _require_commit(evidence.source_commit, "source_commit")
    _require_digest(evidence.source_tree_digest, "source_tree_digest")
    _validate_runner(evidence)

    if (
        evidence.cold_processes != COLD_PROCESSES
        or evidence.warmups != WARMUPS
        or evidence.warm_samples != WARM_SAMPLES
    ):
        raise ValueError("performance evidence uses an unsupported sample matrix")
    if tuple(sorted(evidence.probes)) != tuple(sorted(PROBE_NAMES)):
        raise ValueError("performance evidence uses an unsupported probe set")
    for name, probe in evidence.probes.items():
        _validate_metric(probe.cold, COLD_PROCESSES, f"probes.{name}.cold")
        _validate_metric(probe.warm, WARM_SAMPLES, f"probes.{name}.warm")

    current = evidence.current_index
    synthetic = evidence.synthetic_10x_index
    if current.scale != 1 or synthetic.scale != 10:
        raise ValueError("source index evidence must contain exact 1x and 10x scales")
    if current.scan_count != 1 or synthetic.scan_count != 1:
        raise ValueError("each source index evidence item must use exactly one scan")
    if min(current.source_count, current.source_bytes, current.peak_rss_bytes) < 1:
        raise ValueError("current source index counts and RSS must be positive")
    if synthetic.source_count != current.source_count * 10:
        raise ValueError("synthetic source count must be exactly 10x current")
    if synthetic.source_bytes != current.source_bytes * 10:
        raise ValueError("synthetic source bytes must be exactly 10x current")
    if synthetic.peak_rss_bytes < 1:
        raise ValueError("synthetic source index RSS must be positive")

    _validate_web(evidence.web)
    _validate_capacity(evidence.capacity)
    if evidence.bridge_count < 0 or evidence.bridge_cumulative_ms < 0:
        raise ValueError("bridge evidence must be non-negative")
    if evidence.duplicate_implementation_imports < 0:
        raise ValueError("duplicate implementation import count must be non-negative")


def _validate_runner(evidence: PerformanceEvidence) -> None:
    runner = evidence.runner
    if runner_identity_digest(asdict(runner)) != runner.identity_digest:
        raise ValueError("runner.identity_digest does not match the runner fields")
    for name, value in (
        ("runner.identity_digest", runner.identity_digest),
        ("runner.harness_digest", runner.harness_digest),
        ("runner.python_executable_digest", runner.python_executable_digest),
    ):
        _require_digest(value, name)
    for name, value in (
        ("runner.uv_lock_digest", runner.uv_lock_digest),
        ("runner.frontend_lock_digest", runner.frontend_lock_digest),
    ):
        if value != "unavailable":
            _require_digest(value, name)
    _require_safe_identifier(runner.runner_image, "runner.runner_image")
    for name, value in (
        ("runner.platform", runner.platform),
        ("runner.machine", runner.machine),
        ("runner.python_implementation", runner.python_implementation),
        ("runner.python_version", runner.python_version),
        ("runner.node_version", runner.node_version),
        ("runner.npm_version", runner.npm_version),
    ):
        if value is not None:
            _require_safe_text(value, name)
    if runner.cpu_count < 1 or runner.memory_limit_bytes < 1:
        raise ValueError("runner CPU and memory values must be positive")


def _validate_metric(metric: MetricSummary, expected_samples: int, name: str) -> None:
    if metric.sample_count != expected_samples or len(metric.samples_ms) != expected_samples:
        raise ValueError(f"{name} does not contain the required sample count")
    if tuple(sorted(metric.samples_ms)) != metric.samples_ms:
        raise ValueError(f"{name}.samples_ms must be sorted")
    if metric.p50_ms > metric.p95_ms:
        raise ValueError(f"{name} has p50_ms greater than p95_ms")
    if metric.peak_rss_bytes < 1 or metric.module_count < 1:
        raise ValueError(f"{name} RSS and module count must be positive")
    _require_digest(metric.module_digest, f"{name}.module_digest")
    summarized = MetricSummary.summarize(
        list(metric.samples_ms),
        peak_rss_bytes=metric.peak_rss_bytes,
        module_count=metric.module_count,
        module_digest=metric.module_digest,
    )
    if not math.isclose(metric.p50_ms, summarized.p50_ms, rel_tol=0, abs_tol=1e-9):
        raise ValueError(f"{name}.p50_ms does not match samples_ms")
    if not math.isclose(metric.p95_ms, summarized.p95_ms, rel_tol=0, abs_tol=1e-9):
        raise ValueError(f"{name}.p95_ms does not match samples_ms")


def _validate_web(web: WebBuildEvidence) -> None:
    if web.root != "trade_web/frontend" or not web.cleanup_complete:
        raise ValueError("Web evidence must bind the unique root and complete cleanup")
    identity_values = (
        web.dependency_digest,
        web.cache_key,
        web.incremental_cache_key,
        web.cold_output_digest,
        web.no_change_output_digest,
        web.incremental_output_digest,
    )
    timing_values = (web.no_change_ms, web.cold_build_ms, web.incremental_build_ms)
    if not web.available:
        if (
            any(value is not None for value in (*identity_values, *timing_values))
            or web.no_change_cache_hit
            or web.cache_invalidated
            or web.unavailable_reason is None
        ):
            raise ValueError("unavailable Web evidence contains contradictory fields")
        _require_safe_identifier(web.unavailable_reason, "web.unavailable_reason")
        return
    if (
        any(value is None for value in (*identity_values, *timing_values))
        or not web.no_change_cache_hit
        or not web.cache_invalidated
        or web.unavailable_reason is not None
    ):
        raise ValueError("available Web evidence is incomplete or contradictory")
    for index, value in enumerate(identity_values):
        assert value is not None
        _require_digest(value, f"web.identity[{index}]")
    if web.cache_key == web.incremental_cache_key:
        raise ValueError("Web mutation must invalidate the source cache key")
    if web.cold_output_digest != web.no_change_output_digest:
        raise ValueError("Web no-change build output must remain stable")
    if web.incremental_output_digest == web.cold_output_digest:
        raise ValueError("Web incremental build output must reflect the mutation")


def _validate_capacity(capacity: CapacityEvidence) -> None:
    expected_workers = min(4, max(1, capacity.available_cpu_count // 2))
    if capacity.available_cpu_count < 1:
        raise ValueError("capacity available CPU count must be positive")
    if capacity.ordinary_worker_limit != expected_workers:
        raise ValueError("capacity ordinary worker limit does not match policy")
    if capacity.heavy_job_limit != 2 or capacity.install_limit != 2:
        raise ValueError("capacity heavy and install limits do not match policy")
    if capacity.queue_deadline_seconds != 120:
        raise ValueError("capacity queue deadline does not match policy")
    if capacity.rss_limit_bytes < 1 or capacity.temp_limit_bytes < 1:
        raise ValueError("capacity byte limits must be positive")
    if (
        capacity.ordinary_observed_max != capacity.ordinary_worker_limit
        or capacity.heavy_observed_max != capacity.heavy_job_limit
        or capacity.install_observed_max != capacity.install_limit
    ):
        raise ValueError("capacity proof must exercise each configured concurrency limit")
    if not (
        capacity.queue_refused
        and capacity.rss_refused
        and capacity.temp_refused
        and capacity.cleanup_timed_out
    ):
        raise ValueError("capacity proof must exercise queue, RSS, temp, and timeout refusal")
    if capacity.cleanup_survivors != 0 or capacity.cross_invocation_lease_claimed:
        raise ValueError("capacity proof must leave no descendants or global lease claim")


def _require_digest(value: str, name: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical SHA-256 digest")


def _require_commit(value: str, name: str) -> None:
    if _COMMIT.fullmatch(value) is None:
        raise ValueError(f"{name} must be a full lowercase Git commit")


def _require_timestamp(value: str) -> None:
    if not value.endswith("Z"):
        raise ValueError("generated_at must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError("generated_at must be a valid UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("generated_at must use UTC")


def _require_safe_identifier(value: str, name: str) -> None:
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded safe identifier")


def _require_safe_text(value: str, name: str) -> None:
    if (
        not value
        or len(value) > 256
        or any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)
    ):
        raise ValueError(f"{name} must be bounded text without control characters")


__all__ = ["validate_performance_evidence"]
