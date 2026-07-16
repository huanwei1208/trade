from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any


class ExitCode(IntEnum):
    PASS = 0
    WARN = 1
    FAILURE = 2
    EXECUTION_ERROR = 3
    INTERRUPTED = 130


@dataclass(frozen=True)
class OperationStep:
    step_id: str
    job_name: str
    description: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataProfile:
    name: str
    version: int
    description: str
    steps: tuple[OperationStep, ...]


@dataclass
class StepResult:
    step_id: str
    job_name: str
    status: str
    summary: str
    elapsed_ms: int = 0
    run_id: int | None = None


@dataclass
class OperationResult:
    operation: str
    status: str
    exit_code: int
    profile: str | None = None
    profile_version: int | None = None
    observed: bool = False
    dry_run: bool = False
    elapsed_ms: int = 0
    run_id: int | None = None
    steps: list[StepResult] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
