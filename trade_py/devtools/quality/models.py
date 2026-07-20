"""Typed contracts shared by quality planning, execution, and rendering."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class GateMode(str, Enum):
    CHECK = "check"
    FIX = "fix"


class ResultStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"


class FailureKind(str, Enum):
    QUALITY = "quality"
    INFRASTRUCTURE = "infrastructure"


class ResourceClass(str, Enum):
    LIGHT = "light"
    HEAVY = "heavy"


@dataclass(frozen=True)
class CheckStep:
    """One shell-free subprocess invocation with an explicit safety policy."""

    check_id: str
    group: str
    name: str
    argv: tuple[str, ...]
    cwd: str = "."
    files: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    required: bool = True
    mutates_source: bool = False
    timeout_seconds: int = 120
    output_limit_bytes: int = 32_768
    resource_class: ResourceClass = ResourceClass.LIGHT
    network_policy: str = "offline"
    permitted_outputs: tuple[str, ...] = ()
    remediation_code: str = "quality.fix"
    remediation: str = "Inspect the diagnostic and fix the owning source."
    nonzero_kind: FailureKind = FailureKind.QUALITY
    exit_code_kinds: tuple[tuple[int, FailureKind], ...] = ()
    structured_output_schema: str | None = None
    version_argv: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resource_class"] = self.resource_class.value
        payload["nonzero_kind"] = self.nonzero_kind.value
        payload["exit_code_kinds"] = [
            {"exit_code": code, "failure_kind": kind.value} for code, kind in self.exit_code_kinds
        ]
        payload["argv"] = list(self.argv)
        payload["files"] = list(self.files)
        payload["prerequisites"] = list(self.prerequisites)
        payload["permitted_outputs"] = list(self.permitted_outputs)
        payload["version_argv"] = list(self.version_argv)
        return payload


@dataclass(frozen=True)
class StepResult:
    check_id: str
    group: str
    name: str
    status: ResultStatus
    duration_ms: int
    exit_code: int | None = None
    failure_kind: FailureKind | None = None
    diagnostic: str = ""
    remediation_code: str = ""
    remediation: str = ""
    files: tuple[str, ...] = ()
    tool_path: str | None = None
    tool_version: str | None = None
    caused_by: str | None = None
    details: dict[str, Any] | None = None

    @property
    def aggregate_exit_code(self) -> int:
        if self.status in {ResultStatus.PASS, ResultStatus.WARN}:
            return 0
        if self.status is ResultStatus.SKIP and not self.failure_kind:
            return 0
        return 2 if self.failure_kind is FailureKind.INFRASTRUCTURE else 1

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["failure_kind"] = self.failure_kind.value if self.failure_kind else None
        payload["files"] = list(self.files)
        return payload


@dataclass(frozen=True)
class ScopeSelection:
    repo_root: str
    base_ref: str
    base_sha: str
    head_sha: str
    files: tuple[str, ...]
    fingerprint: str
    all_mode: bool = False
    added_files: tuple[str, ...] = ()
    deleted_files: tuple[str, ...] = ()
    delta_files: tuple[str, ...] = ()
    new_change_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class Exclusion:
    path: str
    reason: str


@dataclass(frozen=True)
class PlanIssue:
    code: str
    message: str
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class GatePlan:
    mode: GateMode
    selection: ScopeSelection
    steps: tuple[CheckStep, ...]
    eligible_files: tuple[str, ...]
    exclusions: tuple[Exclusion, ...] = ()
    issues: tuple[PlanIssue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "trade.quality.plan.v1",
            "mode": self.mode.value,
            "scope": asdict(self.selection),
            "eligible_files": list(self.eligible_files),
            "exclusions": [asdict(item) for item in self.exclusions],
            "issues": [asdict(item) for item in self.issues],
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class GateReport:
    mode: GateMode
    selection: ScopeSelection
    started_at: str
    duration_ms: int
    results: tuple[StepResult, ...]
    eligible_files: tuple[str, ...]
    exclusions: tuple[Exclusion, ...] = ()
    runner_version: str = "1"
    schema_version: str = "trade.quality.report.v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return max((result.aggregate_exit_code for result in self.results), default=0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runner_version": self.runner_version,
            "mode": self.mode.value,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "scope": asdict(self.selection),
            "eligible_files": list(self.eligible_files),
            "exclusions": [asdict(item) for item in self.exclusions],
            "results": [result.to_dict() for result in self.results],
            "metadata": self.metadata,
        }
