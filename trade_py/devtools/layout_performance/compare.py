"""Frozen package-layout performance thresholds."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from trade_py.devtools.layout_performance.integrity import validate_performance_evidence
from trade_py.devtools.layout_performance.models import (
    PerformanceEvidence,
    PerformanceReport,
)

MIB = 1024 * 1024
GIB = 1024 * MIB


def compare_performance(
    baseline: PerformanceEvidence,
    candidate: PerformanceEvidence,
) -> PerformanceReport:
    validate_performance_evidence(baseline)
    validate_performance_evidence(candidate)
    violations: list[str] = []
    if baseline.runner.identity_digest != candidate.runner.identity_digest:
        violations.append("layout.performance.runner_mismatch")
    if baseline.source_tree_digest != candidate.source_tree_digest:
        violations.append("layout.performance.source_tree_mismatch")
    if candidate.cold_processes != 15 or candidate.warmups != 5 or candidate.warm_samples != 30:
        violations.append("layout.performance.sample_matrix")
    if set(baseline.probes) != set(candidate.probes):
        violations.append("layout.performance.probe_set")
    for name in sorted(set(baseline.probes) & set(candidate.probes)):
        for temperature in ("cold", "warm"):
            expected = getattr(baseline.probes[name], temperature)
            actual = getattr(candidate.probes[name], temperature)
            if actual.sample_count != expected.sample_count:
                violations.append(f"layout.performance.{name}.{temperature}.sample_count")
            if actual.p95_ms > max(expected.p95_ms * 1.20, expected.p95_ms + 50.0):
                violations.append(f"layout.performance.{name}.{temperature}.p95")
            if actual.peak_rss_bytes > max(
                int(expected.peak_rss_bytes * 1.15),
                expected.peak_rss_bytes + 16 * MIB,
            ):
                violations.append(f"layout.performance.{name}.{temperature}.rss")
            if actual.module_count > max(
                int(expected.module_count * 1.10),
                expected.module_count + 10,
            ):
                violations.append(f"layout.performance.{name}.{temperature}.modules")
            if actual.module_digest != expected.module_digest:
                violations.append(f"layout.performance.{name}.{temperature}.module_identity")

    current = candidate.current_index
    scaled = candidate.synthetic_10x_index
    if current.scan_count != 1 or scaled.scan_count != 1:
        violations.append("layout.performance.index.scan_count")
    if scaled.source_count < current.source_count * 10:
        violations.append("layout.performance.index.scale_count")
    if scaled.duration_ms > current.duration_ms * 10 + 5_000:
        violations.append("layout.performance.index.wall")
    if scaled.peak_rss_bytes > current.peak_rss_bytes * 3 + 64 * MIB:
        violations.append("layout.performance.index.rss")

    web = candidate.web
    if not web.available:
        violations.append("layout.performance.web.unavailable_prerequisite")
    else:
        if not baseline.web.available:
            violations.append("layout.performance.web.baseline_unavailable")
        if web.root != "trade_web/frontend":
            violations.append("layout.performance.web.unique_root")
        if (
            not web.cache_key
            or not web.incremental_cache_key
            or not web.dependency_digest
            or not web.cold_output_digest
            or not web.no_change_output_digest
            or not web.incremental_output_digest
        ):
            violations.append("layout.performance.web.identity")
        if not web.no_change_cache_hit:
            violations.append("layout.performance.web.no_change_cache")
        if not web.cache_invalidated or web.incremental_cache_key == web.cache_key:
            violations.append("layout.performance.web.incremental_cache")
        if web.cold_output_digest != web.no_change_output_digest:
            violations.append("layout.performance.web.no_change_output")
        if web.incremental_output_digest == web.cold_output_digest:
            violations.append("layout.performance.web.stale_output")
        if web.dependency_digest != baseline.web.dependency_digest:
            violations.append("layout.performance.web.dependency_mismatch")
        if not web.cleanup_complete:
            violations.append("layout.performance.web.cleanup")
        if web.cold_build_ms is None or web.cold_build_ms > 15 * 60 * 1_000:
            violations.append("layout.performance.web.cold")
        baseline_no_change = baseline.web.no_change_ms
        if web.no_change_ms is None or baseline_no_change is None:
            violations.append("layout.performance.web.no_change_missing")
        elif web.no_change_ms > max(baseline_no_change * 1.20, baseline_no_change + 500):
            violations.append("layout.performance.web.no_change")
        baseline_incremental = baseline.web.incremental_build_ms
        if web.incremental_build_ms is None or baseline_incremental is None:
            violations.append("layout.performance.web.incremental_missing")
        elif web.incremental_build_ms > max(
            baseline_incremental * 1.25,
            baseline_incremental + 5_000,
        ):
            violations.append("layout.performance.web.incremental")

    capacity = candidate.capacity
    expected_workers = min(4, max(1, capacity.available_cpu_count // 2))
    if capacity.ordinary_worker_limit != expected_workers:
        violations.append("layout.performance.capacity.worker_policy")
    if capacity.heavy_job_limit != 2:
        violations.append("layout.performance.capacity.heavy_policy")
    if capacity.install_limit != 2:
        violations.append("layout.performance.capacity.install_policy")
    if capacity.queue_deadline_seconds != 120:
        violations.append("layout.performance.capacity.queue_policy")
    if capacity.rss_limit_bytes > 8 * GIB:
        violations.append("layout.performance.capacity.rss_policy")
    if capacity.temp_limit_bytes != 10 * GIB:
        violations.append("layout.performance.capacity.temp_policy")
    if capacity.ordinary_observed_max > capacity.ordinary_worker_limit:
        violations.append("layout.performance.capacity.ordinary")
    if capacity.heavy_observed_max > capacity.heavy_job_limit:
        violations.append("layout.performance.capacity.heavy")
    if capacity.install_observed_max > capacity.install_limit:
        violations.append("layout.performance.capacity.install")
    if not capacity.queue_refused:
        violations.append("layout.performance.capacity.queue")
    if not capacity.rss_refused:
        violations.append("layout.performance.capacity.rss")
    if not capacity.temp_refused:
        violations.append("layout.performance.capacity.temp")
    if not capacity.cleanup_timed_out or capacity.cleanup_survivors != 0:
        violations.append("layout.performance.capacity.cleanup")
    if capacity.cross_invocation_lease_claimed:
        violations.append("layout.performance.capacity.global_claim")
    if candidate.bridge_count < 0 or candidate.bridge_cumulative_ms < 0:
        violations.append("layout.performance.bridge.evidence")
    if candidate.duplicate_implementation_imports:
        violations.append("layout.performance.bridge.duplicate_import")

    unique = tuple(sorted(set(violations)))
    failure_class = _failure_class(unique)
    return PerformanceReport(
        status="pass" if not unique else failure_class,
        failure_class="none" if not unique else failure_class,
        exit_code={
            "none": 0,
            "regression": 1,
            "unavailable_prerequisite": 3,
            "capacity_refusal": 4,
        }["none" if not unique else failure_class],
        baseline_digest=payload_digest(baseline.to_dict(baseline=True)),
        evidence=candidate,
        violations=unique,
    )


def payload_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _failure_class(violations: tuple[str, ...]) -> str:
    if any(item.endswith("unavailable_prerequisite") for item in violations):
        return "unavailable_prerequisite"
    if any(".capacity." in item for item in violations):
        return "capacity_refusal"
    return "regression"


__all__ = ["GIB", "MIB", "compare_performance", "payload_digest"]
