"""Typed contracts for design-quality policy, snapshots, and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class Severity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: Severity
    suppressible: bool
    remediation: str


@dataclass(frozen=True)
class Limits:
    max_files_per_change: int
    max_file_bytes: int
    max_total_bytes_per_change: int
    max_findings: int
    max_changes_per_batch: int
    max_total_bytes_per_batch: int


@dataclass(frozen=True)
class EvidenceSchema:
    kind: str
    minimum: float | None = None
    maximum: float | None = None
    equals: str | int | float | bool | None = None
    values: tuple[str, ...] = ()
    required_values: tuple[str, ...] = ()
    fields: dict[str, EvidenceSchema] = field(default_factory=dict)
    allow_extra: bool = False
    min_length: int = 12


@dataclass(frozen=True)
class Profile:
    name: str
    impacts: tuple[str, ...]
    required_sections: tuple[str, ...]
    finding_rule: str | None
    required_evidence: tuple[str, ...]
    evidence_schema: dict[str, EvidenceSchema] = field(default_factory=dict)


@dataclass(frozen=True)
class Policy:
    schema_version: int
    policy_version: str
    digest: str
    limits: Limits
    root_files: tuple[str, ...]
    required_root_files: tuple[str, ...]
    minimum_spec_files: int
    spec_pattern: str
    digest_excludes: tuple[str, ...]
    required_sections: tuple[str, ...]
    placeholders: tuple[str, ...]
    minimum_section_characters: int
    required_impacts: tuple[str, ...]
    impact_signals: dict[str, tuple[str, ...]]
    profiles: tuple[Profile, ...]
    required_roles: tuple[str, ...]
    bootstrap_changes: tuple[str, ...]
    rules: tuple[Rule, ...]

    def rule(self, rule_id: str) -> Rule:
        try:
            return next(item for item in self.rules if item.rule_id == rule_id)
        except StopIteration as exc:
            raise KeyError(f"Unknown design rule: {rule_id}") from exc


@dataclass(frozen=True)
class Artifact:
    path: str
    size_bytes: int
    digest: str
    content: str
    stat_signature: tuple[int, int, int]


@dataclass(frozen=True)
class ChangeSnapshot:
    name: str
    repo_root: str
    root: str
    artifacts: tuple[Artifact, ...]
    artifact_digest: str
    total_bytes: int

    def text(self, path: str) -> str | None:
        item = next((artifact for artifact in self.artifacts if artifact.path == path), None)
        return item.content if item else None

    @property
    def inventory(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {"path": item.path, "size_bytes": item.size_bytes, "digest": item.digest}
            for item in self.artifacts
        )


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    path: str
    message: str
    remediation: str
    suppressed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        return payload


@dataclass(frozen=True)
class ExceptionRecord:
    rule_id: str
    owner: str
    reason: str
    expires: date
    state: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expires"] = self.expires.isoformat()
        return payload


@dataclass(frozen=True)
class DesignReport:
    change: str
    policy_version: str
    policy_digest: str
    artifact_digest: str
    strict: bool
    effective_date: date
    approval_eligible: bool
    governance_status: str
    profiles: tuple[str, ...]
    findings: tuple[Finding, ...]
    exceptions: tuple[ExceptionRecord, ...]
    artifacts: tuple[dict[str, Any], ...]
    schema_version: str = "trade.design.report.v1"
    checker_version: str = "1"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        active = tuple(item for item in self.findings if not item.suppressed)
        if any(item.severity is Severity.BLOCKER for item in active):
            return 1
        if self.strict and any(item.severity is Severity.WARNING for item in active):
            return 1
        return 0

    @property
    def status(self) -> str:
        if self.governance_status == "NOT_GOVERNED":
            return "NOT_GOVERNED"
        if self.exit_code:
            return "FAIL"
        return "PASS" if self.approval_eligible else "DIAGNOSTIC"

    def to_dict(self) -> dict[str, Any]:
        counts = {
            "blockers": sum(
                item.severity is Severity.BLOCKER and not item.suppressed for item in self.findings
            ),
            "warnings": sum(
                item.severity is Severity.WARNING and not item.suppressed for item in self.findings
            ),
            "suppressed": sum(item.suppressed for item in self.findings),
        }
        return {
            "schema_version": self.schema_version,
            "checker_version": self.checker_version,
            "policy_version": self.policy_version,
            "policy_digest": self.policy_digest,
            "artifact_digest": self.artifact_digest,
            "change": self.change,
            "strict": self.strict,
            "effective_date": self.effective_date.isoformat(),
            "approval_eligible": self.approval_eligible,
            "governance_status": self.governance_status,
            "status": self.status,
            "exit_code": self.exit_code,
            "profiles": list(self.profiles),
            "findings": [item.to_dict() for item in self.findings],
            "exceptions": [item.to_dict() for item in self.exceptions],
            "artifacts": list(self.artifacts),
            "counts": counts,
            "metadata": self.metadata,
        }
