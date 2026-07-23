"""Stable status-service error contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ErrorSource = Literal["request", "git", "openspec", "design_quality", "snapshot"]
_ERROR_SOURCES = frozenset({"request", "git", "openspec", "design_quality", "snapshot"})


@dataclass(frozen=True)
class WorkflowError:
    code: str
    source: ErrorSource
    message: str
    remediation: str
    change: str | None = None
    details: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source not in _ERROR_SOURCES:
            raise ValueError(f"Unsupported workflow error source: {self.source}")
        if not self.code or not self.message or not self.remediation:
            raise ValueError("Workflow errors require code, message, and remediation")
        expected_details = (
            {"schema_name", "payload_digest"}
            if self.code == "workflow.openspec.unsupported_schema"
            else set()
        )
        if set(self.details) != expected_details or not all(self.details.values()):
            raise ValueError(f"Workflow error details do not match the v1 contract: {self.code}")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "source": self.source,
            "change": self.change,
            "message": self.message,
            "remediation": self.remediation,
            "details": dict(sorted(self.details.items())),
        }


class WorkflowCollectionError(RuntimeError):
    def __init__(self, error: WorkflowError) -> None:
        super().__init__(error.message)
        self.error = error
