"""Stable status-service error contracts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkflowError:
    code: str
    source: str
    message: str
    remediation: str
    change: str | None = None
    details: dict[str, str] = field(default_factory=dict)

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
