"""Bounded JSON serialization for layout performance evidence."""

from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
from typing import Any

from trade_py.devtools.layout_performance.integrity import validate_performance_evidence
from trade_py.devtools.layout_performance.models import (
    BASELINE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    CapacityEvidence,
    IndexEvidence,
    MetricSummary,
    PerformanceEvidence,
    ProbeEvidence,
    RunnerIdentity,
    WebBuildEvidence,
)
from trade_py.devtools.layout_performance.probes import WARM_SAMPLES

MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


def load_performance_evidence(
    path: Path,
    *,
    baseline: bool,
) -> PerformanceEvidence:
    payload = _read_json_object(path)
    expected_schema = BASELINE_SCHEMA_VERSION if baseline else SCHEMA_VERSION
    _exact_keys(
        payload,
        {
            "schema_version",
            "generated_at",
            "source_commit",
            "source_tree_digest",
            "runner",
            "cold_processes",
            "warmups",
            "warm_samples",
            "probes",
            "current_index",
            "synthetic_10x_index",
            "web",
            "capacity",
            "bridge_count",
            "bridge_cumulative_ms",
            "duplicate_implementation_imports",
        },
        "evidence",
    )
    if payload["schema_version"] != expected_schema:
        raise ValueError(f"evidence schema must be {expected_schema}")
    probes_payload = _mapping(payload, "probes")
    probes = {
        name: _parse_probe(_object(value, f"probes.{name}"), f"probes.{name}")
        for name, value in sorted(probes_payload.items())
    }
    evidence = PerformanceEvidence(
        generated_at=_string(payload, "generated_at"),
        source_commit=_string(payload, "source_commit"),
        source_tree_digest=_string(payload, "source_tree_digest"),
        runner=_parse_runner(_object(payload["runner"], "runner")),
        cold_processes=_integer(payload, "cold_processes"),
        warmups=_integer(payload, "warmups"),
        warm_samples=_integer(payload, "warm_samples"),
        probes=probes,
        current_index=_parse_index(_object(payload["current_index"], "current_index")),
        synthetic_10x_index=_parse_index(
            _object(payload["synthetic_10x_index"], "synthetic_10x_index")
        ),
        web=_parse_web(_object(payload["web"], "web")),
        capacity=_parse_capacity(_object(payload["capacity"], "capacity")),
        bridge_count=_integer(payload, "bridge_count"),
        bridge_cumulative_ms=_number(payload, "bridge_cumulative_ms"),
        duplicate_implementation_imports=_integer(payload, "duplicate_implementation_imports"),
    )
    validate_performance_evidence(evidence)
    return evidence


def render_evidence(evidence: PerformanceEvidence, *, baseline: bool) -> str:
    return (
        json.dumps(
            evidence.to_dict(baseline=baseline),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    descriptor = os.open(path, _OPEN_FLAGS)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("performance evidence must be a regular file")
        if metadata.st_size > MAX_EVIDENCE_BYTES:
            raise ValueError("performance evidence exceeds its byte budget")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) != metadata.st_size:
            raise ValueError("performance evidence ended before its recorded size")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda token: _raise_non_finite(token),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"performance evidence is invalid JSON: {exc}") from exc
    payload = _object(value, "evidence")
    canonical = (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if raw != canonical:
        raise ValueError("performance evidence must use canonical JSON encoding")
    return payload


def _parse_metric(payload: dict[str, Any], name: str) -> MetricSummary:
    _exact_keys(
        payload,
        {
            "samples_ms",
            "sample_count",
            "p50_ms",
            "p95_ms",
            "peak_rss_bytes",
            "module_count",
            "module_digest",
        },
        name,
    )
    metric = MetricSummary(
        samples_ms=_number_tuple(payload, "samples_ms"),
        sample_count=_integer(payload, "sample_count"),
        p50_ms=_number(payload, "p50_ms"),
        p95_ms=_number(payload, "p95_ms"),
        peak_rss_bytes=_integer(payload, "peak_rss_bytes"),
        module_count=_integer(payload, "module_count"),
        module_digest=_string(payload, "module_digest"),
    )
    if not metric.samples_ms:
        raise ValueError(f"{name}.samples_ms must not be empty")
    if metric.sample_count != len(metric.samples_ms):
        raise ValueError(f"{name}.sample_count does not match samples_ms")
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
    return metric


def _parse_probe(payload: dict[str, Any], name: str) -> ProbeEvidence:
    _exact_keys(payload, {"cold", "warm"}, name)
    return ProbeEvidence(
        cold=_parse_metric(_object(payload["cold"], f"{name}.cold"), f"{name}.cold"),
        warm=_parse_metric(_object(payload["warm"], f"{name}.warm"), f"{name}.warm"),
    )


def _parse_index(payload: dict[str, Any]) -> IndexEvidence:
    _exact_keys(
        payload,
        {
            "scale",
            "source_count",
            "source_bytes",
            "duration_ms",
            "peak_rss_bytes",
            "scan_count",
        },
        "index",
    )
    return IndexEvidence(
        scale=_integer(payload, "scale"),
        source_count=_integer(payload, "source_count"),
        source_bytes=_integer(payload, "source_bytes"),
        duration_ms=_number(payload, "duration_ms"),
        peak_rss_bytes=_integer(payload, "peak_rss_bytes"),
        scan_count=_integer(payload, "scan_count"),
    )


def _parse_web(payload: dict[str, Any]) -> WebBuildEvidence:
    _exact_keys(
        payload,
        {
            "available",
            "root",
            "dependency_digest",
            "cache_key",
            "incremental_cache_key",
            "no_change_cache_hit",
            "cache_invalidated",
            "no_change_ms",
            "cold_build_ms",
            "incremental_build_ms",
            "cold_output_digest",
            "no_change_output_digest",
            "incremental_output_digest",
            "cleanup_complete",
            "unavailable_reason",
        },
        "web",
    )
    return WebBuildEvidence(
        available=_boolean(payload, "available"),
        root=_optional_string(payload, "root"),
        dependency_digest=_optional_string(payload, "dependency_digest"),
        cache_key=_optional_string(payload, "cache_key"),
        incremental_cache_key=_optional_string(payload, "incremental_cache_key"),
        no_change_cache_hit=_boolean(payload, "no_change_cache_hit"),
        cache_invalidated=_boolean(payload, "cache_invalidated"),
        no_change_ms=_optional_number(payload, "no_change_ms"),
        cold_build_ms=_optional_number(payload, "cold_build_ms"),
        incremental_build_ms=_optional_number(payload, "incremental_build_ms"),
        cold_output_digest=_optional_string(payload, "cold_output_digest"),
        no_change_output_digest=_optional_string(payload, "no_change_output_digest"),
        incremental_output_digest=_optional_string(payload, "incremental_output_digest"),
        cleanup_complete=_boolean(payload, "cleanup_complete"),
        unavailable_reason=_optional_string(payload, "unavailable_reason"),
    )


def _parse_capacity(payload: dict[str, Any]) -> CapacityEvidence:
    fields = {
        "available_cpu_count",
        "ordinary_worker_limit",
        "heavy_job_limit",
        "install_limit",
        "rss_limit_bytes",
        "temp_limit_bytes",
        "queue_deadline_seconds",
        "ordinary_observed_max",
        "heavy_observed_max",
        "install_observed_max",
        "queue_refused",
        "rss_refused",
        "temp_refused",
        "cleanup_timed_out",
        "cleanup_survivors",
        "cross_invocation_lease_claimed",
    }
    _exact_keys(payload, fields, "capacity")
    return CapacityEvidence(
        available_cpu_count=_integer(payload, "available_cpu_count"),
        ordinary_worker_limit=_integer(payload, "ordinary_worker_limit"),
        heavy_job_limit=_integer(payload, "heavy_job_limit"),
        install_limit=_integer(payload, "install_limit"),
        rss_limit_bytes=_integer(payload, "rss_limit_bytes"),
        temp_limit_bytes=_integer(payload, "temp_limit_bytes"),
        queue_deadline_seconds=_integer(payload, "queue_deadline_seconds"),
        ordinary_observed_max=_integer(payload, "ordinary_observed_max"),
        heavy_observed_max=_integer(payload, "heavy_observed_max"),
        install_observed_max=_integer(payload, "install_observed_max"),
        queue_refused=_boolean(payload, "queue_refused"),
        rss_refused=_boolean(payload, "rss_refused"),
        temp_refused=_boolean(payload, "temp_refused"),
        cleanup_timed_out=_boolean(payload, "cleanup_timed_out"),
        cleanup_survivors=_integer(payload, "cleanup_survivors"),
        cross_invocation_lease_claimed=_boolean(payload, "cross_invocation_lease_claimed"),
    )


def _parse_runner(payload: dict[str, Any]) -> RunnerIdentity:
    fields = {
        "identity_digest",
        "harness_digest",
        "runner_image",
        "platform",
        "machine",
        "cpu_count",
        "memory_limit_bytes",
        "python_implementation",
        "python_version",
        "python_executable_digest",
        "uv_lock_digest",
        "frontend_lock_digest",
        "node_version",
        "npm_version",
    }
    _exact_keys(payload, fields, "runner")
    return RunnerIdentity(
        identity_digest=_string(payload, "identity_digest"),
        harness_digest=_string(payload, "harness_digest"),
        runner_image=_string(payload, "runner_image"),
        platform=_string(payload, "platform"),
        machine=_string(payload, "machine"),
        cpu_count=_integer(payload, "cpu_count"),
        memory_limit_bytes=_integer(payload, "memory_limit_bytes"),
        python_implementation=_string(payload, "python_implementation"),
        python_version=_string(payload, "python_version"),
        python_executable_digest=_string(payload, "python_executable_digest"),
        uv_lock_digest=_string(payload, "uv_lock_digest"),
        frontend_lock_digest=_string(payload, "frontend_lock_digest"),
        node_version=_optional_string(payload, "node_version"),
        npm_version=_optional_string(payload, "npm_version"),
    )


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be an object with string keys")
    return value


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return _object(payload.get(key), key)


def _exact_keys(payload: dict[str, Any], expected: set[str], name: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{name} fields differ: missing={sorted(expected - actual)} "
            f"unknown={sorted(actual - expected)}"
        )


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise TypeError(f"{key} must be a bounded non-empty string")
    return value


def _number_tuple(payload: dict[str, Any], key: str) -> tuple[float, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or len(value) > WARM_SAMPLES:
        raise TypeError(f"{key} must be a bounded array")
    return tuple(_standalone_number(item, key) for item in value)


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise TypeError(f"{key} must be null or a bounded non-empty string")
    return value


def _integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError(f"{key} must be a non-negative integer")
    return value


def _number(payload: dict[str, Any], key: str) -> float:
    return _standalone_number(payload.get(key), key)


def _standalone_number(value: object, key: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
        or not math.isfinite(float(value))
    ):
        raise TypeError(f"{key} must be a non-negative finite number")
    return float(value)


def _optional_number(payload: dict[str, Any], key: str) -> float | None:
    return None if payload.get(key) is None else _number(payload, key)


def _boolean(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value


def _raise_non_finite(token: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {token}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


__all__ = [
    "MAX_EVIDENCE_BYTES",
    "load_performance_evidence",
    "render_evidence",
]
