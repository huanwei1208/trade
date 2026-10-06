from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

from trade.kernel.digest import ContentDigest
from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import Deadline, UtcInstant
from trade.platform.contracts.errors import ErrorEnvelope, ObservationState
from trade.platform.contracts.operations import DeadlineTerminalEvidence

__all__ = [
    "HistoryWindow",
    "ProcessState",
    "ProcessStartKeyV1",
    "ProcessTransition",
    "ProcessView",
    "RecoveryAction",
    "RecoveryActionDescriptor",
    "validate_process_transition",
    "validate_process_view_transition",
]

_TOKEN_PATTERN = re.compile(r"[a-z0-9._:-]{1,96}", re.ASCII)
_REASON_PATTERN = re.compile(r"[A-Z0-9._-]{1,96}", re.ASCII)
_SEMANTIC_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
    re.ASCII,
)
_MAX_INT32 = 2_147_483_647
_MAX_INT64 = 9_223_372_036_854_775_807
_MAX_HISTORY_ITEMS = 50
_MAX_RECOVERY_ACTIONS = 16


class ProcessState(str, Enum):
    REQUESTED = "requested"
    RUNNING = "running"
    WAITING = "waiting"
    RETRY_SCHEDULED = "retry_scheduled"
    COMPENSATION_PENDING = "compensation_pending"
    COMPLETED = "completed"
    COMPENSATED = "compensated"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    DEADLINE_EXCEEDED = "deadline_exceeded"

    @property
    def is_terminal(self) -> bool:
        return self in {
            ProcessState.COMPLETED,
            ProcessState.COMPENSATED,
            ProcessState.FAILED,
            ProcessState.CANCELLED,
            ProcessState.DEADLINE_EXCEEDED,
        }


_PROCESS_TRANSITIONS = {
    ProcessState.REQUESTED: frozenset(
        {
            ProcessState.RUNNING,
            ProcessState.WAITING,
            ProcessState.FAILED,
            ProcessState.CANCELLED,
            ProcessState.DEADLINE_EXCEEDED,
        }
    ),
    ProcessState.RUNNING: frozenset(
        {
            ProcessState.WAITING,
            ProcessState.RETRY_SCHEDULED,
            ProcessState.COMPENSATION_PENDING,
            ProcessState.BLOCKED,
            ProcessState.COMPLETED,
            ProcessState.FAILED,
            ProcessState.CANCELLED,
            ProcessState.DEADLINE_EXCEEDED,
        }
    ),
    ProcessState.WAITING: frozenset(
        {
            ProcessState.RUNNING,
            ProcessState.RETRY_SCHEDULED,
            ProcessState.BLOCKED,
            ProcessState.FAILED,
            ProcessState.CANCELLED,
            ProcessState.DEADLINE_EXCEEDED,
        }
    ),
    ProcessState.RETRY_SCHEDULED: frozenset(
        {
            ProcessState.RUNNING,
            ProcessState.WAITING,
            ProcessState.BLOCKED,
            ProcessState.FAILED,
            ProcessState.CANCELLED,
            ProcessState.DEADLINE_EXCEEDED,
        }
    ),
    ProcessState.COMPENSATION_PENDING: frozenset(
        {
            ProcessState.COMPENSATED,
            ProcessState.BLOCKED,
            ProcessState.FAILED,
            ProcessState.DEADLINE_EXCEEDED,
        }
    ),
    ProcessState.BLOCKED: frozenset(
        {
            ProcessState.RUNNING,
            ProcessState.RETRY_SCHEDULED,
            ProcessState.COMPENSATION_PENDING,
            ProcessState.FAILED,
            ProcessState.CANCELLED,
            ProcessState.DEADLINE_EXCEEDED,
        }
    ),
    ProcessState.COMPLETED: frozenset(),
    ProcessState.COMPENSATED: frozenset(),
    ProcessState.FAILED: frozenset(),
    ProcessState.CANCELLED: frozenset(),
    ProcessState.DEADLINE_EXCEEDED: frozenset(),
}


class RecoveryAction(str, Enum):
    INSPECT = "inspect"
    CANCEL_OPERATION = "cancel_operation"
    RETRY_PROCESS_STEP = "retry_process_step"
    RESUME_PROCESS = "resume_process"
    REDELIVER_MESSAGE = "redeliver_message"
    REPLAY_IMMUTABLE_INPUT = "replay_immutable_input"
    REQUEST_NEW_EXTERNAL_INTERACTION = "request_new_external_interaction"


@dataclass(frozen=True, slots=True)
class ProcessStartKeyV1:
    schema_version: int
    process_type: str
    triggering_operation_id: OpaqueId
    workflow_key: ContentDigest

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("ProcessStartKeyV1 schema_version must be 1")
        _validate_token(self.process_type, field_name="process_type")
        if not isinstance(self.triggering_operation_id, OpaqueId):
            raise TypeError("triggering_operation_id must be OpaqueId")
        if not isinstance(self.workflow_key, ContentDigest):
            raise TypeError("workflow_key must be ContentDigest")

    def canonical_bytes(self) -> bytes:
        payload = {
            "process_type": self.process_type,
            "schema_version": self.schema_version,
            "triggering_operation_id": self.triggering_operation_id.to_dict(),
            "workflow_key": self.workflow_key.to_dict(),
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ProcessTransition:
    sequence: int
    transition_id: OpaqueId
    state: ProcessState
    step: str
    reason_code: str | None
    observed_at: UtcInstant

    def __post_init__(self) -> None:
        _validate_int(
            self.sequence,
            field_name="sequence",
            minimum=0,
            maximum=_MAX_INT64,
        )
        if not isinstance(self.transition_id, OpaqueId):
            raise TypeError("transition_id must be OpaqueId")
        if not isinstance(self.state, ProcessState):
            raise TypeError("state must be ProcessState")
        _validate_token(self.step, field_name="step")
        _validate_optional_reason(self.reason_code)
        _validate_process_reason(self.state, self.reason_code)
        if not isinstance(self.observed_at, UtcInstant):
            raise TypeError("observed_at must be UtcInstant")


@dataclass(frozen=True, slots=True)
class HistoryWindow:
    items: tuple[ProcessTransition, ...]
    total_count: int
    returned_count: int
    first_sequence: int | None
    last_sequence: int | None
    omitted_before_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise TypeError("items must be a tuple")
        if any(not isinstance(item, ProcessTransition) for item in self.items):
            raise TypeError("history items must be ProcessTransition")
        if len(self.items) > _MAX_HISTORY_ITEMS:
            raise ValueError("history window must contain at most 50 transitions")
        for field_name in ("total_count", "returned_count", "omitted_before_count"):
            _validate_int(
                getattr(self, field_name),
                field_name=field_name,
                minimum=0,
                maximum=_MAX_INT32,
            )
        if self.returned_count != len(self.items):
            raise ValueError("returned_count must equal the number of history items")
        if self.total_count < self.returned_count:
            raise ValueError("total_count cannot be smaller than returned_count")
        if self.omitted_before_count != self.total_count - self.returned_count:
            raise ValueError("omitted_before_count must equal total_count - returned_count")
        if not self.items:
            if self.first_sequence is not None or self.last_sequence is not None:
                raise ValueError("empty history requires absent first and last sequence")
            if self.total_count != 0 or self.omitted_before_count != 0:
                raise ValueError("empty history requires zero counts")
            return
        for field_name in ("first_sequence", "last_sequence"):
            value = getattr(self, field_name)
            if value is None:
                raise ValueError(f"non-empty history requires {field_name}")
            _validate_int(
                value,
                field_name=field_name,
                minimum=0,
                maximum=_MAX_INT64,
            )
        sequences = tuple(item.sequence for item in self.items)
        if any(
            current <= previous for previous, current in zip(sequences, sequences[1:], strict=False)
        ):
            raise ValueError("history owner sequences must be strictly increasing")
        if self.first_sequence != sequences[0] or self.last_sequence != sequences[-1]:
            raise ValueError("history sequence metadata must match the returned items")


@dataclass(frozen=True, slots=True)
class RecoveryActionDescriptor:
    owner_namespace: IdNamespace
    action: RecoveryAction
    target_id: OpaqueId
    policy_namespace: IdNamespace
    policy_version: str
    reason_code: str
    expires_at: UtcInstant
    required_actor_scope: str

    def __post_init__(self) -> None:
        if not isinstance(self.owner_namespace, IdNamespace):
            raise TypeError("owner_namespace must be IdNamespace")
        if not isinstance(self.action, RecoveryAction):
            raise TypeError("action must be RecoveryAction")
        if not isinstance(self.target_id, OpaqueId):
            raise TypeError("target_id must be OpaqueId")
        if not isinstance(self.policy_namespace, IdNamespace):
            raise TypeError("policy_namespace must be IdNamespace")
        if (
            not isinstance(self.policy_version, str)
            or _SEMANTIC_VERSION_PATTERN.fullmatch(self.policy_version) is None
            or len(self.policy_version.encode("ascii")) > 96
        ):
            raise ValueError("policy_version must be a SemVer 2.0 value of at most 96 bytes")
        _validate_reason(self.reason_code)
        if not isinstance(self.expires_at, UtcInstant):
            raise TypeError("expires_at must be UtcInstant")
        _validate_token(self.required_actor_scope, field_name="required_actor_scope")


@dataclass(frozen=True, slots=True)
class ProcessView:
    schema_name: str
    schema_version: int
    process_id: OpaqueId
    process_type: str
    triggering_operation_id: OpaqueId
    correlation_id: OpaqueId
    causation_id: OpaqueId | None
    state: ProcessState
    observation_state: ObservationState
    current_step: str
    reason_code: str | None
    retry_count: int
    retry_limit: int
    next_attempt_at: UtcInstant | None
    deadline: Deadline
    last_error: ErrorEnvelope | None
    compensation_state: str | None
    dead_letter_state: str | None
    bounded_history: HistoryWindow
    permitted_recovery_actions: tuple[RecoveryActionDescriptor, ...]
    created_at: UtcInstant
    updated_at: UtcInstant
    terminal_at: UtcInstant | None

    def __post_init__(self) -> None:
        if self.schema_name != "trade.process_view":
            raise ValueError("ProcessView schema_name must be 'trade.process_view'")
        if self.schema_version != 1:
            raise ValueError("ProcessView schema_version must be 1")
        if not isinstance(self.process_id, OpaqueId):
            raise TypeError("process_id must be OpaqueId")
        _validate_token(self.process_type, field_name="process_type")
        if not isinstance(self.triggering_operation_id, OpaqueId):
            raise TypeError("triggering_operation_id must be OpaqueId")
        if not isinstance(self.correlation_id, OpaqueId):
            raise TypeError("correlation_id must be OpaqueId")
        if self.causation_id is not None and not isinstance(self.causation_id, OpaqueId):
            raise TypeError("causation_id must be OpaqueId or None")
        if not isinstance(self.state, ProcessState):
            raise TypeError("state must be ProcessState")
        if not isinstance(self.observation_state, ObservationState):
            raise TypeError("observation_state must be ObservationState")
        _validate_token(self.current_step, field_name="current_step")
        _validate_optional_reason(self.reason_code)
        _validate_process_reason(self.state, self.reason_code)
        _validate_int(
            self.retry_count,
            field_name="retry_count",
            minimum=0,
            maximum=_MAX_INT32,
        )
        _validate_int(
            self.retry_limit,
            field_name="retry_limit",
            minimum=0,
            maximum=_MAX_INT32,
        )
        if self.retry_count > self.retry_limit:
            raise ValueError("retry_count cannot exceed retry_limit")
        if self.next_attempt_at is not None and not isinstance(self.next_attempt_at, UtcInstant):
            raise TypeError("next_attempt_at must be UtcInstant or None")
        if self.state is ProcessState.RETRY_SCHEDULED:
            if self.next_attempt_at is None:
                raise ValueError("retry_scheduled process requires next_attempt_at")
        elif self.next_attempt_at is not None:
            raise ValueError("next_attempt_at is only valid for retry_scheduled")
        if not isinstance(self.deadline, Deadline):
            raise TypeError("deadline must be Deadline")
        if self.last_error is not None and not isinstance(self.last_error, ErrorEnvelope):
            raise TypeError("last_error must be ErrorEnvelope or None")
        if self.compensation_state is not None:
            _validate_token(self.compensation_state, field_name="compensation_state")
        if self.dead_letter_state is not None:
            _validate_token(self.dead_letter_state, field_name="dead_letter_state")
        if not isinstance(self.bounded_history, HistoryWindow):
            raise TypeError("bounded_history must be HistoryWindow")
        if not isinstance(self.permitted_recovery_actions, tuple):
            raise TypeError("permitted_recovery_actions must be a tuple")
        if len(self.permitted_recovery_actions) > _MAX_RECOVERY_ACTIONS:
            raise ValueError("at most 16 recovery actions are permitted")
        if any(
            not isinstance(item, RecoveryActionDescriptor)
            for item in self.permitted_recovery_actions
        ):
            raise TypeError("permitted_recovery_actions entries must be RecoveryActionDescriptor")
        if not isinstance(self.created_at, UtcInstant):
            raise TypeError("created_at must be UtcInstant")
        if not isinstance(self.updated_at, UtcInstant):
            raise TypeError("updated_at must be UtcInstant")
        if self.updated_at.value < self.created_at.value:
            raise ValueError("updated_at cannot precede created_at")
        if self.terminal_at is not None and not isinstance(self.terminal_at, UtcInstant):
            raise TypeError("terminal_at must be UtcInstant or None")
        if self.state.is_terminal:
            if self.terminal_at is None:
                raise ValueError("terminal process state requires terminal_at")
            if not self.created_at.value <= self.terminal_at.value <= self.updated_at.value:
                raise ValueError("terminal_at must be between created_at and updated_at")
        elif self.terminal_at is not None:
            raise ValueError("non-terminal process state forbids terminal_at")


def validate_process_transition(
    previous: ProcessState,
    current: ProcessState,
    *,
    deadline_evidence: DeadlineTerminalEvidence | None = None,
) -> None:
    if not isinstance(previous, ProcessState):
        raise TypeError("previous must be ProcessState")
    if not isinstance(current, ProcessState):
        raise TypeError("current must be ProcessState")
    if current is previous:
        if deadline_evidence is not None:
            raise ValueError("idempotent state observation forbids new deadline evidence")
        return
    if current not in _PROCESS_TRANSITIONS[previous]:
        raise ValueError(f"process transition {previous.value} -> {current.value} is not allowed")
    if current is ProcessState.DEADLINE_EXCEEDED:
        if not isinstance(deadline_evidence, DeadlineTerminalEvidence):
            raise ValueError(
                "owner deadline_exceeded requires worker-exit or durable-fence evidence"
            )
    elif deadline_evidence is not None:
        raise ValueError("deadline terminal evidence is valid only for deadline_exceeded")


def validate_process_view_transition(
    previous: ProcessView,
    current: ProcessView,
    *,
    deadline_evidence: DeadlineTerminalEvidence | None = None,
) -> None:
    if not isinstance(previous, ProcessView):
        raise TypeError("previous must be ProcessView")
    if not isinstance(current, ProcessView):
        raise TypeError("current must be ProcessView")
    immutable_fields = (
        "schema_name",
        "schema_version",
        "process_id",
        "process_type",
        "triggering_operation_id",
        "correlation_id",
        "causation_id",
        "created_at",
    )
    for field_name in immutable_fields:
        if getattr(previous, field_name) != getattr(current, field_name):
            raise ValueError(f"process identity field {field_name} is immutable")
    validate_process_transition(
        previous.state,
        current.state,
        deadline_evidence=deadline_evidence,
    )
    if current.retry_count < previous.retry_count:
        raise ValueError("retry_count cannot decrease")
    if current.updated_at.value < previous.updated_at.value:
        raise ValueError("process updated_at cannot move backwards")
    if previous.state.is_terminal and current != previous:
        raise ValueError("terminal process view is immutable")
    if previous.terminal_at is not None and current.terminal_at != previous.terminal_at:
        raise ValueError("process terminal_at is immutable once established")
    if (
        previous.bounded_history.last_sequence is not None
        and current.bounded_history.last_sequence is not None
        and current.bounded_history.last_sequence < previous.bounded_history.last_sequence
    ):
        raise ValueError("process history cannot move backwards")


def _validate_process_reason(state: ProcessState, reason_code: str | None) -> None:
    required = {
        ProcessState.BLOCKED,
        ProcessState.RETRY_SCHEDULED,
        ProcessState.FAILED,
        ProcessState.CANCELLED,
        ProcessState.DEADLINE_EXCEEDED,
    }
    forbidden = {
        ProcessState.REQUESTED,
        ProcessState.RUNNING,
        ProcessState.WAITING,
        ProcessState.COMPLETED,
        ProcessState.COMPENSATED,
    }
    if state in required and reason_code is None:
        raise ValueError(f"{state.value} process state requires reason_code")
    if state in forbidden and reason_code is not None:
        raise ValueError(f"{state.value} process state forbids reason_code")


def _validate_token(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be 1-96 ASCII lower-case letters, digits, '.', '_', ':' or '-'"
        )
    return value


def _validate_reason(value: str) -> str:
    if not isinstance(value, str) or _REASON_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "reason_code must be 1-96 ASCII upper-case letters, digits, '.', '_' or '-'"
        )
    return value


def _validate_optional_reason(value: str | None) -> None:
    if value is not None:
        _validate_reason(value)


def _validate_int(
    value: int,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be in {minimum}..{maximum}")
    return value
