"""Typed public contracts for OpenSpec workflow status v1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

from trade_py.devtools.openspec_status.errors import WorkflowError

CollectionStatus = Literal["complete", "unavailable"]
Lifecycle = Literal["authoring", "review", "implementation", "archive-ready", "blocked"]
TaskStatus = Literal["no-tasks", "in-progress", "complete"]
ActionKind = Literal["author", "review", "apply", "archive", "repair", "none"]


@dataclass(frozen=True)
class WorkflowLimits:
    max_changes: int = 100
    status_workers: int = 4
    subprocess_timeout_seconds: int = 10
    command_deadline_seconds: int = 60
    native_output_bytes: int = 1_048_576
    report_output_bytes: int = 16_777_216


@dataclass(frozen=True)
class WorkflowSource:
    git_head: str
    base_ref: str
    base_sha: str
    snapshot_digest: str


@dataclass(frozen=True)
class TaskProgress:
    completed: int
    total: int
    status: TaskStatus

    @classmethod
    def from_counts(cls, completed: int, total: int) -> TaskProgress:
        status: TaskStatus
        if total == 0:
            status = "no-tasks"
        elif completed == total:
            status = "complete"
        else:
            status = "in-progress"
        return cls(completed=completed, total=total, status=status)


@dataclass(frozen=True)
class ArtifactEvidence:
    id: str
    output_path: str
    status: Literal["ready", "blocked", "done"]
    missing_deps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "output_path": self.output_path,
            "status": self.status,
            "missing_deps": list(self.missing_deps),
        }


@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["error", "warning"]
    path: str | None
    message: str


@dataclass(frozen=True)
class ValidationEvidence:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    omitted_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "issues": [asdict(item) for item in self.issues],
            "omitted_count": self.omitted_count,
        }


@dataclass(frozen=True)
class NativeEvidence:
    schema_name: str
    is_complete: bool
    apply_requires: tuple[str, ...]
    artifacts: tuple[ArtifactEvidence, ...]
    validation: ValidationEvidence
    payload_digests: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "is_complete": self.is_complete,
            "apply_requires": list(self.apply_requires),
            "artifacts": [item.to_dict() for item in self.artifacts],
            "validation": self.validation.to_dict(),
            "payload_digests": dict(sorted(self.payload_digests.items())),
        }


@dataclass(frozen=True)
class GovernanceEvidence:
    required: bool
    requirement_source: str
    report: dict[str, Any]

    def to_dict(self) -> dict[str, object]:
        return {
            "required": self.required,
            "requirement_source": self.requirement_source,
            "report": self.report,
        }


@dataclass(frozen=True)
class NextAction:
    kind: ActionKind
    command: str | None
    reason: str


@dataclass(frozen=True)
class ChangeWorkflow:
    name: str
    collection_status: CollectionStatus
    lifecycle: Lifecycle | None
    tasks: TaskProgress | None
    native: NativeEvidence | None
    governance: GovernanceEvidence | None
    next_action: NextAction
    errors: tuple[WorkflowError, ...] = ()

    @classmethod
    def unavailable(cls, name: str, error: WorkflowError) -> ChangeWorkflow:
        return cls(
            name=name,
            collection_status="unavailable",
            lifecycle=None,
            tasks=None,
            native=None,
            governance=None,
            next_action=NextAction(
                kind="repair",
                command=None,
                reason=error.remediation,
            ),
            errors=(error,),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "collection_status": self.collection_status,
            "lifecycle": self.lifecycle,
            "tasks": asdict(self.tasks) if self.tasks else None,
            "native": self.native.to_dict() if self.native else None,
            "governance": self.governance.to_dict() if self.governance else None,
            "next_action": asdict(self.next_action),
            "errors": [item.to_dict() for item in self.errors],
        }


@dataclass(frozen=True)
class WorkflowReport:
    evaluation_date: date
    source: WorkflowSource | None
    changes: tuple[ChangeWorkflow, ...]
    errors: tuple[WorkflowError, ...] = ()
    limits: WorkflowLimits = WorkflowLimits()
    schema_version: str = "trade.openspec.workflow.v1"

    @property
    def exit_code(self) -> int:
        all_errors = (*self.errors, *(error for item in self.changes for error in item.errors))
        if all_errors or any(item.collection_status == "unavailable" for item in self.changes):
            return 2
        return 1 if any(item.lifecycle == "blocked" for item in self.changes) else 0

    @property
    def status(self) -> str:
        return ("PASS", "BLOCKED", "ERROR")[self.exit_code]

    def to_dict(self) -> dict[str, object]:
        changes = tuple(sorted(self.changes, key=lambda item: item.name))
        change_errors = tuple(error for item in changes for error in item.errors)
        errors = tuple(
            sorted(
                (*self.errors, *change_errors),
                key=lambda item: (item.change or "", item.source, item.code, item.message),
            )
        )
        lifecycle_counts = {
            name: sum(item.lifecycle == value for item in changes)
            for name, value in (
                ("authoring", "authoring"),
                ("review", "review"),
                ("implementation", "implementation"),
                ("archive_ready", "archive-ready"),
                ("blocked", "blocked"),
            )
        }
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "exit_code": self.exit_code,
            "evaluation_date": self.evaluation_date.isoformat(),
            "source": asdict(self.source) if self.source else None,
            "changes": [item.to_dict() for item in changes],
            "errors": [item.to_dict() for item in errors],
            "summary": {
                "changes": len(changes),
                **lifecycle_counts,
                "unavailable": sum(item.collection_status == "unavailable" for item in changes),
                "errors": len(errors),
            },
            "limits": asdict(self.limits),
        }
