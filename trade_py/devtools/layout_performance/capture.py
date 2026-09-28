"""Orchestration for explicit package-layout performance capture."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trade_py.devtools.layout.tree_index import read_regular_relative
from trade_py.devtools.layout_performance.capacity import (
    CapacityRefused,
    ValidationCapacity,
    detected_memory_bytes,
    prove_capacity_policy,
)
from trade_py.devtools.layout_performance.identity import (
    capture_runner_identity,
    capture_source_tree_digest,
    source_commit,
)
from trade_py.devtools.layout_performance.index import capture_index_evidence
from trade_py.devtools.layout_performance.models import PerformanceEvidence
from trade_py.devtools.layout_performance.probes import (
    COLD_PROCESSES,
    WARM_SAMPLES,
    WARMUPS,
    capture_probe_evidence,
)
from trade_py.devtools.layout_performance.web import capture_web_build_evidence
from trade_py.devtools.toml_compat import tomllib


class PerformanceCaptureError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        completed_stages: tuple[str, ...],
        partial_evidence: dict[str, Any],
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.completed_stages = completed_stages
        self.partial_evidence = partial_evidence


def capture_performance(
    repo_root: Path,
    *,
    node_modules: Path | None,
) -> PerformanceEvidence:
    root = repo_root.resolve()
    completed: list[str] = []
    partial: dict[str, Any] = {}
    try:
        runner = capture_runner_identity(root)
        commit = source_commit(root)
        source_tree = capture_source_tree_digest(root)
        completed.append("runner_identity")
        partial["runner"] = asdict(runner)
        partial["source_commit"] = commit
        partial["source_tree_digest"] = source_tree

        capacity = ValidationCapacity(available_memory_bytes=detected_memory_bytes())
        probes = capture_probe_evidence(root, capacity=capacity)
        completed.append("startup_probes")
        partial["probes"] = {name: asdict(evidence) for name, evidence in sorted(probes.items())}

        current_index, synthetic_index = capture_index_evidence(
            root,
            capacity=capacity,
        )
        completed.append("source_indexes")
        partial["current_index"] = asdict(current_index)
        partial["synthetic_10x_index"] = asdict(synthetic_index)

        web = capture_web_build_evidence(
            root,
            node_modules=node_modules,
            capacity=capacity,
        )
        completed.append("web_build")
        partial["web"] = asdict(web)

        capacity_evidence = prove_capacity_policy(capacity)
        completed.append("capacity_policy")
        partial["capacity"] = asdict(capacity_evidence)

        bridge_count, bridge_cumulative_ms, duplicate_imports = _bridge_evidence(root)
        completed.append("bridge_evidence")
        partial["bridge"] = {
            "bridge_count": bridge_count,
            "bridge_cumulative_ms": bridge_cumulative_ms,
            "duplicate_implementation_imports": duplicate_imports,
        }
    except Exception as exc:
        raise PerformanceCaptureError(
            _capture_error_code(exc),
            _bounded_detail(exc),
            completed_stages=tuple(completed),
            partial_evidence=partial,
        ) from exc

    return PerformanceEvidence(
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        source_commit=commit,
        source_tree_digest=source_tree,
        runner=runner,
        cold_processes=COLD_PROCESSES,
        warmups=WARMUPS,
        warm_samples=WARM_SAMPLES,
        probes=probes,
        current_index=current_index,
        synthetic_10x_index=synthetic_index,
        web=web,
        capacity=capacity_evidence,
        bridge_count=bridge_count,
        bridge_cumulative_ms=bridge_cumulative_ms,
        duplicate_implementation_imports=duplicate_imports,
    )


def _bridge_evidence(repo_root: Path) -> tuple[int, float, int]:
    content = read_regular_relative(
        repo_root,
        "layout-authority.toml",
        max_bytes=256 * 1024,
    )
    payload = tomllib.loads(content.decode("utf-8"))
    if set(payload) != {
        "schema_version",
        "rules_version",
        "included_roots",
        "foundation_modules",
        "authorities",
    }:
        raise ValueError("layout authority manifest has unexpected fields")
    authorities = payload.get("authorities")
    if not isinstance(authorities, list):
        raise TypeError("layout authority manifest authorities must be an array")
    if authorities:
        raise PerformanceCaptureError(
            "layout.performance.bridge_timing_unavailable",
            "migrated authorities require explicit per-bridge timing evidence",
            completed_stages=(),
            partial_evidence={},
        )
    return 0, 0.0, 0


def _capture_error_code(error: Exception) -> str:
    if isinstance(error, CapacityRefused):
        return "layout.performance.capacity_refusal"
    code = getattr(error, "code", None)
    if isinstance(code, str) and code.startswith("layout.performance."):
        return code
    return "layout.performance.tool_failure"


def _bounded_detail(error: Exception) -> str:
    detail = getattr(error, "detail", None)
    value = str(detail if isinstance(detail, str) else error)
    return value[:2048]


__all__ = ["PerformanceCaptureError", "capture_performance"]
