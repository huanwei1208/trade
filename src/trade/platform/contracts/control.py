from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import Deadline, DurationMs, UtcInstant
from trade.platform.contracts.actor import ActorContext
from trade.platform.contracts.errors import (
    ErrorCategory,
    ErrorEnvelope,
    ObservationState,
)

__all__ = [
    "ControlClaimIdentityV1",
    "ControlCommitEvidence",
    "ControlDeadlineBudget",
    "ControlDisposition",
    "ControlKind",
    "ControlReceipt",
    "ResidualOwner",
    "ResidualOwnerCategory",
    "ShutdownAttemptEvidence",
    "ShutdownReceipt",
    "ShutdownRecoveryAction",
    "ShutdownRecoveryKind",
    "ShutdownStage",
    "ShutdownState",
    "ShutdownTakeoverEvidence",
    "make_control_error",
    "make_control_receipt_unavailable_error",
    "validate_control_commit",
    "validate_control_receipt_resolution",
    "validate_fence_write",
    "validate_shutdown_attempt",
    "validate_shutdown_control_link",
    "validate_shutdown_receipt_resolution",
    "validate_shutdown_takeover",
]

_TOKEN_PATTERN = re.compile(r"[a-z0-9._:-]{1,96}", re.ASCII)
_REASON_PATTERN = re.compile(r"[A-Z0-9._-]{1,96}", re.ASCII)
_MAX_INT32 = 2_147_483_647
_MAX_INT64 = 9_223_372_036_854_775_807
_MAX_RESIDUAL_OWNERS = 16
_MAX_RECOVERY_ACTIONS = 16


class ControlKind(str, Enum):
    CANCEL = "cancel"
    SHUTDOWN = "shutdown"


class ControlDisposition(str, Enum):
    ACCEPTED = "accepted"
    ALREADY_TERMINAL = "already_terminal"
    DENIED = "denied"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"


class ShutdownState(str, Enum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    FAILED = "failed"


class ShutdownStage(str, Enum):
    CLOSE_ADMISSION = "close_admission"
    REQUEST_GRACEFUL = "request_graceful"
    FORCE_PROCESS_TREE = "force_process_tree"
    DRAIN_DELIVERY = "drain_delivery"
    COMMIT_TERMINAL_AUDIT = "commit_terminal_audit"
    RELEASE_RESOURCES = "release_resources"
    RELEASE_FENCE = "release_fence"
    DONE = "done"


class ResidualOwnerCategory(str, Enum):
    PROCESS_GROUP = "process_group"
    EXECUTOR_TASK = "executor_task"
    PYTHON_THREAD = "python_thread"
    PERSISTENCE_AUDIT = "persistence_audit"
    WRITER_LEASE = "writer_lease"
    INFLIGHT_START = "inflight_start"


class ShutdownRecoveryKind(str, Enum):
    INSPECT_RESIDUAL = "inspect_residual"
    RETRY_TERMINAL_AUDIT = "retry_terminal_audit"
    TERMINATE_PROCESS_GROUP = "terminate_process_group"
    RETRY_SHUTDOWN_WITH_DEADLINE = "retry_shutdown_with_deadline"
    REVOKE_EXPIRED_WRITER_LEASE = "revoke_expired_writer_lease"
    OPERATOR_INTERVENTION = "operator_intervention"


@dataclass(frozen=True, slots=True)
class ControlClaimIdentityV1:
    schema_version: int
    control_operation_id: OpaqueId
    control_kind: ControlKind
    operation_id: OpaqueId | None
    process_id: OpaqueId | None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("ControlClaimIdentityV1 schema_version must be 1")
        if not isinstance(self.control_operation_id, OpaqueId):
            raise TypeError("control_operation_id must be OpaqueId")
        if not isinstance(self.control_kind, ControlKind):
            raise TypeError("control_kind must be ControlKind")
        _validate_exact_target(self.operation_id, self.process_id)


@dataclass(frozen=True, slots=True)
class ControlReceipt:
    schema_name: str
    schema_version: int
    control_id: OpaqueId
    control_kind: ControlKind
    request_message_id: OpaqueId
    correlation_id: OpaqueId
    causation_id: OpaqueId | None
    initiator: ActorContext
    operation_id: OpaqueId | None
    process_id: OpaqueId | None
    requested_at: UtcInstant
    deadline: Deadline
    finished_at: UtcInstant
    disposition: ControlDisposition
    reason_code: str
    target_terminal_receipt_id: OpaqueId | None
    safe_error: ErrorEnvelope | None

    def __post_init__(self) -> None:
        if self.schema_name != "trade.control_receipt":
            raise ValueError("ControlReceipt schema_name must be 'trade.control_receipt'")
        if self.schema_version != 1:
            raise ValueError("ControlReceipt schema_version must be 1")
        if not isinstance(self.control_id, OpaqueId):
            raise TypeError("control_id must be OpaqueId")
        if not isinstance(self.control_kind, ControlKind):
            raise TypeError("control_kind must be ControlKind")
        _validate_causal_tuple(
            request_message_id=self.request_message_id,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
        )
        if not isinstance(self.initiator, ActorContext):
            raise TypeError("initiator must be ActorContext")
        if not self.initiator.can_submit_mutation:
            raise ValueError("control initiator must retain verified mutation authority")
        _validate_exact_target(self.operation_id, self.process_id)
        if not isinstance(self.requested_at, UtcInstant):
            raise TypeError("requested_at must be UtcInstant")
        if not isinstance(self.deadline, Deadline):
            raise TypeError("deadline must be Deadline")
        if self.deadline.wall_clock_expires_at.value < self.requested_at.value:
            raise ValueError("control deadline cannot precede requested_at")
        if not isinstance(self.finished_at, UtcInstant):
            raise TypeError("finished_at must be UtcInstant")
        if self.finished_at.value < self.requested_at.value:
            raise ValueError("finished_at cannot precede requested_at")
        if not isinstance(self.disposition, ControlDisposition):
            raise TypeError("disposition must be ControlDisposition")
        _validate_reason(self.reason_code)
        if self.target_terminal_receipt_id is not None and not isinstance(
            self.target_terminal_receipt_id, OpaqueId
        ):
            raise TypeError("target_terminal_receipt_id must be OpaqueId or None")
        if self.safe_error is not None and not isinstance(self.safe_error, ErrorEnvelope):
            raise TypeError("safe_error must be ErrorEnvelope or None")
        self._validate_disposition_product()

    @property
    def claim_identity(self) -> ControlClaimIdentityV1:
        return ControlClaimIdentityV1(
            schema_version=1,
            control_operation_id=self.control_id,
            control_kind=self.control_kind,
            operation_id=self.operation_id,
            process_id=self.process_id,
        )

    def _validate_disposition_product(self) -> None:
        if self.disposition is ControlDisposition.ACCEPTED:
            self._require_reason("CONTROL_ACCEPTED")
            self._require_no_error_or_terminal_link()
            return
        if self.disposition is ControlDisposition.ALREADY_TERMINAL:
            self._require_reason("CONTROL_ALREADY_TERMINAL")
            if self.target_terminal_receipt_id is None:
                raise ValueError("already_terminal control requires target_terminal_receipt_id")
            if self.safe_error is not None:
                raise ValueError("already_terminal control forbids safe_error")
            return

        if self.target_terminal_receipt_id is not None:
            raise ValueError(f"{self.disposition.value} control forbids terminal receipt link")
        if self.safe_error is None:
            raise ValueError(f"{self.disposition.value} control requires safe_error")
        self._validate_safe_error_identity()
        expected = {
            ControlDisposition.DENIED: (
                "CONTROL_DENIED",
                ErrorCategory.DENIED,
                ObservationState.OBSERVED,
                False,
                False,
            ),
            ControlDisposition.NOT_FOUND: (
                "CONTROL_TARGET_NOT_FOUND",
                ErrorCategory.INVALID,
                ObservationState.OBSERVED,
                False,
                False,
            ),
            ControlDisposition.UNAVAILABLE: (
                "CONTROL_UNAVAILABLE",
                ErrorCategory.UNAVAILABLE,
                ObservationState.UNAVAILABLE,
                True,
                True,
            ),
            ControlDisposition.DEADLINE_EXCEEDED: (
                "CONTROL_DEADLINE_EXCEEDED",
                ErrorCategory.TIMEOUT,
                ObservationState.NOT_OBSERVED,
                True,
                False,
            ),
        }[self.disposition]
        reason, category, observation, retryable, retry_after_required = expected
        self._require_reason(reason)
        error = self.safe_error
        if error.reason_code != reason:
            raise ValueError("control safe_error reason must equal receipt reason")
        if error.category is not category or error.observation_state is not observation:
            raise ValueError("control safe_error category/observation product is invalid")
        if error.retryable is not retryable:
            raise ValueError("control safe_error retryable product is invalid")
        if retry_after_required:
            if error.retry_after_ms is None:
                raise ValueError("unavailable control requires bounded retry_after_ms")
        elif error.retry_after_ms is not None:
            raise ValueError(f"{self.disposition.value} control forbids retry_after_ms")

    def _require_reason(self, expected: str) -> None:
        if self.reason_code != expected:
            raise ValueError(f"{self.disposition.value} control reason must be {expected}")

    def _require_no_error_or_terminal_link(self) -> None:
        if self.safe_error is not None or self.target_terminal_receipt_id is not None:
            raise ValueError(
                f"{self.disposition.value} control forbids safe error and terminal link"
            )

    def _validate_safe_error_identity(self) -> None:
        error = self.safe_error
        if error is None:
            raise ValueError("control safe_error is required")
        if (
            error.request_message_id != self.request_message_id
            or error.correlation_id != self.correlation_id
            or error.causation_id != self.causation_id
        ):
            raise ValueError("control safe_error must preserve request causal identity")
        if error.operation_id != self.operation_id or error.process_id != self.process_id:
            raise ValueError("control safe_error must preserve the exact target link")


@dataclass(frozen=True, slots=True)
class ControlCommitEvidence:
    claim_persisted: bool
    receipt_persisted: bool
    intent_persisted: bool
    outbox_persisted: bool
    receipt_finalization_reserved: bool
    committed_within_deadline: bool

    def __post_init__(self) -> None:
        for field_name in (
            "claim_persisted",
            "receipt_persisted",
            "intent_persisted",
            "outbox_persisted",
            "receipt_finalization_reserved",
            "committed_within_deadline",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be bool")


@dataclass(frozen=True, slots=True)
class ControlDeadlineBudget:
    deadline: Deadline
    receipt_finalization_reserve: DurationMs

    def __post_init__(self) -> None:
        if not isinstance(self.deadline, Deadline):
            raise TypeError("deadline must be Deadline")
        if not isinstance(self.receipt_finalization_reserve, DurationMs):
            raise TypeError("receipt_finalization_reserve must be DurationMs")

    def remaining_target_ms(self, monotonic_now: float) -> int:
        return max(
            0,
            self.deadline.remaining_ms(monotonic_now) - self.receipt_finalization_reserve.value,
        )

    def can_start_target_step(
        self,
        *,
        required_ms: int,
        monotonic_now: float,
    ) -> bool:
        if not isinstance(required_ms, int) or isinstance(required_ms, bool):
            raise TypeError("required_ms must be an integer")
        if required_ms <= 0:
            raise ValueError("required_ms must be positive")
        return required_ms <= self.remaining_target_ms(monotonic_now)


@dataclass(frozen=True, slots=True)
class ResidualOwner:
    category: ResidualOwnerCategory
    count: int
    inspection_selector: OpaqueId
    owner_instance_id: OpaqueId
    fence_generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.category, ResidualOwnerCategory):
            raise TypeError("category must be ResidualOwnerCategory")
        _validate_int(
            self.count,
            field_name="count",
            minimum=1,
            maximum=_MAX_INT32,
        )
        if not isinstance(self.inspection_selector, OpaqueId):
            raise TypeError("inspection_selector must be OpaqueId")
        if not isinstance(self.owner_instance_id, OpaqueId):
            raise TypeError("owner_instance_id must be OpaqueId")
        _validate_generation(self.fence_generation)


@dataclass(frozen=True, slots=True)
class ShutdownRecoveryAction:
    action: ShutdownRecoveryKind
    target_id: OpaqueId
    owner_instance_id: OpaqueId
    fence_generation: int
    reason_code: str
    expires_at: UtcInstant
    required_actor_scope: str

    def __post_init__(self) -> None:
        if not isinstance(self.action, ShutdownRecoveryKind):
            raise TypeError("action must be ShutdownRecoveryKind")
        if not isinstance(self.target_id, OpaqueId):
            raise TypeError("target_id must be OpaqueId")
        if not isinstance(self.owner_instance_id, OpaqueId):
            raise TypeError("owner_instance_id must be OpaqueId")
        _validate_generation(self.fence_generation)
        _validate_reason(self.reason_code)
        if not isinstance(self.expires_at, UtcInstant):
            raise TypeError("expires_at must be UtcInstant")
        _validate_token(self.required_actor_scope, field_name="required_actor_scope")


@dataclass(frozen=True, slots=True)
class ShutdownReceipt:
    schema_name: str
    schema_version: int
    owner_namespace: IdNamespace
    owner_instance_id: OpaqueId
    fence_generation: int
    control_id: OpaqueId
    request_message_id: OpaqueId
    correlation_id: OpaqueId
    causation_id: OpaqueId | None
    operation_id: OpaqueId | None
    process_id: OpaqueId | None
    initiator: ActorContext
    requested_at: UtcInstant
    deadline: Deadline
    finished_at: UtcInstant
    state: ShutdownState
    current_stage: ShutdownStage
    reason_code: str
    graceful_termination_count: int
    forced_termination_count: int
    residual_owners: tuple[ResidualOwner, ...]
    shutdown_recovery_actions: tuple[ShutdownRecoveryAction, ...]
    safe_error: ErrorEnvelope | None

    def __post_init__(self) -> None:
        if self.schema_name != "trade.shutdown_receipt":
            raise ValueError("ShutdownReceipt schema_name must be 'trade.shutdown_receipt'")
        if self.schema_version != 1:
            raise ValueError("ShutdownReceipt schema_version must be 1")
        if not isinstance(self.owner_namespace, IdNamespace):
            raise TypeError("owner_namespace must be IdNamespace")
        if not isinstance(self.owner_instance_id, OpaqueId):
            raise TypeError("owner_instance_id must be OpaqueId")
        _validate_generation(self.fence_generation)
        if not isinstance(self.control_id, OpaqueId):
            raise TypeError("control_id must be OpaqueId")
        _validate_causal_tuple(
            request_message_id=self.request_message_id,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
        )
        _validate_optional_links(self.operation_id, self.process_id)
        if not isinstance(self.initiator, ActorContext):
            raise TypeError("initiator must be ActorContext")
        if not self.initiator.can_submit_mutation:
            raise ValueError("shutdown initiator must retain verified mutation authority")
        if not isinstance(self.requested_at, UtcInstant):
            raise TypeError("requested_at must be UtcInstant")
        if not isinstance(self.deadline, Deadline):
            raise TypeError("deadline must be Deadline")
        if self.deadline.wall_clock_expires_at.value < self.requested_at.value:
            raise ValueError("shutdown deadline cannot precede requested_at")
        if not isinstance(self.finished_at, UtcInstant):
            raise TypeError("finished_at must be UtcInstant")
        if self.finished_at.value < self.requested_at.value:
            raise ValueError("finished_at cannot precede requested_at")
        if not isinstance(self.state, ShutdownState):
            raise TypeError("state must be ShutdownState")
        if not isinstance(self.current_stage, ShutdownStage):
            raise TypeError("current_stage must be ShutdownStage")
        _validate_reason(self.reason_code)
        for field_name in (
            "graceful_termination_count",
            "forced_termination_count",
        ):
            _validate_int(
                getattr(self, field_name),
                field_name=field_name,
                minimum=0,
                maximum=_MAX_INT32,
            )
        self._validate_residuals_and_actions()
        if self.safe_error is not None and not isinstance(self.safe_error, ErrorEnvelope):
            raise TypeError("safe_error must be ErrorEnvelope or None")
        self._validate_state_product()

    def _validate_residuals_and_actions(self) -> None:
        if not isinstance(self.residual_owners, tuple):
            raise TypeError("residual_owners must be a tuple")
        if len(self.residual_owners) > _MAX_RESIDUAL_OWNERS:
            raise ValueError("residual_owners must contain at most 16 entries")
        if any(not isinstance(item, ResidualOwner) for item in self.residual_owners):
            raise TypeError("residual_owners entries must be ResidualOwner")
        if not isinstance(self.shutdown_recovery_actions, tuple):
            raise TypeError("shutdown_recovery_actions must be a tuple")
        if len(self.shutdown_recovery_actions) > _MAX_RECOVERY_ACTIONS:
            raise ValueError("shutdown_recovery_actions must contain at most 16 entries")
        if any(
            not isinstance(item, ShutdownRecoveryAction) for item in self.shutdown_recovery_actions
        ):
            raise TypeError("shutdown_recovery_actions entries must be ShutdownRecoveryAction")
        residual_targets = {residual.inspection_selector for residual in self.residual_owners}
        for residual in self.residual_owners:
            if (
                residual.owner_instance_id != self.owner_instance_id
                or residual.fence_generation != self.fence_generation
            ):
                raise ValueError("residual owner must match shutdown owner instance and fence")
        for action in self.shutdown_recovery_actions:
            if (
                action.owner_instance_id != self.owner_instance_id
                or action.fence_generation != self.fence_generation
            ):
                raise ValueError("shutdown recovery action must match owner instance and fence")
            if action.target_id not in residual_targets:
                raise ValueError("shutdown recovery action must target a reported residual owner")

    def _validate_state_product(self) -> None:
        if self.state is ShutdownState.COMPLETED:
            if self.current_stage is not ShutdownStage.DONE:
                raise ValueError("completed shutdown requires done stage")
            if self.reason_code != "SHUTDOWN_COMPLETED":
                raise ValueError("completed shutdown requires SHUTDOWN_COMPLETED")
            if self.safe_error is not None:
                raise ValueError("completed shutdown forbids safe_error")
            if self.residual_owners or self.shutdown_recovery_actions:
                raise ValueError("completed shutdown requires no residual or recovery")
            return

        if self.current_stage is ShutdownStage.DONE:
            raise ValueError("non-completed shutdown forbids done stage")
        if not self.residual_owners or not self.shutdown_recovery_actions:
            raise ValueError("non-completed shutdown requires residual and recovery evidence")
        if self.safe_error is None:
            raise ValueError("non-completed shutdown requires safe_error")
        self._validate_safe_error_identity()
        error = self.safe_error
        if error.observation_state is not ObservationState.OBSERVED:
            raise ValueError("shutdown safe_error observation must be observed")

        if self.state is ShutdownState.DEADLINE_EXCEEDED:
            if self.reason_code != "SHUTDOWN_DEADLINE_EXCEEDED":
                raise ValueError("deadline_exceeded shutdown requires SHUTDOWN_DEADLINE_EXCEEDED")
            if error.category is not ErrorCategory.TIMEOUT:
                raise ValueError("deadline_exceeded shutdown requires timeout error")
        elif self.state is ShutdownState.INCOMPLETE:
            if self.reason_code in {
                "SHUTDOWN_COMPLETED",
                "SHUTDOWN_DEADLINE_EXCEEDED",
            }:
                raise ValueError("incomplete shutdown requires stable non-deadline reason")
            if error.category not in {
                ErrorCategory.BLOCKED,
                ErrorCategory.UNAVAILABLE,
            }:
                raise ValueError("incomplete shutdown requires blocked or unavailable error")
        else:
            if self.reason_code in {
                "SHUTDOWN_COMPLETED",
                "SHUTDOWN_DEADLINE_EXCEEDED",
            }:
                raise ValueError("failed shutdown requires stable failure reason")
            if error.category not in {
                ErrorCategory.INTERNAL,
                ErrorCategory.UNAVAILABLE,
            }:
                raise ValueError("failed shutdown requires internal or unavailable error")
        if error.reason_code != self.reason_code:
            raise ValueError("shutdown safe_error reason must equal receipt reason")

    def _validate_safe_error_identity(self) -> None:
        error = self.safe_error
        if error is None:
            raise ValueError("shutdown safe_error is required")
        if (
            error.request_message_id != self.request_message_id
            or error.correlation_id != self.correlation_id
            or error.causation_id != self.causation_id
        ):
            raise ValueError("shutdown safe_error must preserve request causal identity")
        if error.operation_id != self.operation_id or error.process_id != self.process_id:
            raise ValueError("shutdown safe_error must preserve public links")


@dataclass(frozen=True, slots=True)
class ShutdownAttemptEvidence:
    live_owned_work_count: int
    terminal_audit_committed: bool
    resources_released: bool
    released_fence_generation: int | None
    fence_retained: bool
    returned_within_deadline: bool

    def __post_init__(self) -> None:
        _validate_int(
            self.live_owned_work_count,
            field_name="live_owned_work_count",
            minimum=0,
            maximum=_MAX_INT32,
        )
        for field_name in (
            "terminal_audit_committed",
            "resources_released",
            "fence_retained",
            "returned_within_deadline",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be bool")
        if self.released_fence_generation is not None:
            _validate_generation(self.released_fence_generation)


@dataclass(frozen=True, slots=True)
class ShutdownTakeoverEvidence:
    previous_owner_instance_id: OpaqueId
    previous_generation: int
    next_owner_instance_id: OpaqueId
    next_generation: int
    prior_lease_expired: bool
    prior_lease_revoked: bool
    takeover_causation_id: OpaqueId

    def __post_init__(self) -> None:
        if not isinstance(self.previous_owner_instance_id, OpaqueId):
            raise TypeError("previous_owner_instance_id must be OpaqueId")
        if not isinstance(self.next_owner_instance_id, OpaqueId):
            raise TypeError("next_owner_instance_id must be OpaqueId")
        _validate_generation(self.previous_generation)
        _validate_generation(self.next_generation)
        if not isinstance(self.prior_lease_expired, bool):
            raise TypeError("prior_lease_expired must be bool")
        if not isinstance(self.prior_lease_revoked, bool):
            raise TypeError("prior_lease_revoked must be bool")
        if not isinstance(self.takeover_causation_id, OpaqueId):
            raise TypeError("takeover_causation_id must be OpaqueId")


def validate_control_commit(
    receipt: ControlReceipt,
    evidence: ControlCommitEvidence,
) -> None:
    if not isinstance(receipt, ControlReceipt):
        raise TypeError("receipt must be ControlReceipt")
    if not isinstance(evidence, ControlCommitEvidence):
        raise TypeError("evidence must be ControlCommitEvidence")
    if not evidence.claim_persisted or not evidence.receipt_persisted:
        raise ValueError("returned control receipt requires atomic claim and receipt")
    if not evidence.receipt_finalization_reserved:
        raise ValueError("control commit requires reserved receipt finalization budget")
    if not evidence.committed_within_deadline:
        raise ValueError("control receipt must commit within its monotonic deadline")
    expected_intent = receipt.disposition is ControlDisposition.ACCEPTED
    if evidence.intent_persisted is not expected_intent:
        raise ValueError("control intent durability does not match disposition")
    if evidence.outbox_persisted is not expected_intent:
        raise ValueError("control outbox durability does not match disposition")


def validate_control_receipt_resolution(
    original: ControlReceipt,
    resolved: ControlReceipt,
) -> None:
    if not isinstance(original, ControlReceipt):
        raise TypeError("original must be ControlReceipt")
    if not isinstance(resolved, ControlReceipt):
        raise TypeError("resolved must be ControlReceipt")
    if resolved != original:
        raise ValueError("control retry or redelivery must resolve the original receipt")


def validate_shutdown_attempt(
    receipt: ShutdownReceipt,
    evidence: ShutdownAttemptEvidence,
) -> None:
    if not isinstance(receipt, ShutdownReceipt):
        raise TypeError("receipt must be ShutdownReceipt")
    if not isinstance(evidence, ShutdownAttemptEvidence):
        raise TypeError("evidence must be ShutdownAttemptEvidence")
    if not evidence.returned_within_deadline:
        raise ValueError("shutdown attempt must return within its shared deadline")
    if receipt.state is ShutdownState.COMPLETED:
        if evidence.live_owned_work_count != 0:
            raise ValueError("completed shutdown requires zero live owned work")
        if not evidence.terminal_audit_committed:
            raise ValueError("completed shutdown requires durable terminal audit")
        if not evidence.resources_released:
            raise ValueError("completed shutdown requires released resources")
        if evidence.released_fence_generation != receipt.fence_generation:
            raise ValueError("completed shutdown must release only its matching fence")
        if evidence.fence_retained:
            raise ValueError("completed shutdown cannot retain its fence")
        return

    if not evidence.fence_retained:
        raise ValueError("non-completed shutdown must retain its fence")
    if evidence.released_fence_generation is not None:
        raise ValueError("non-completed shutdown cannot release a fence")
    residual_count = sum(item.count for item in receipt.residual_owners)
    if evidence.live_owned_work_count > residual_count:
        raise ValueError("live owned work must be represented by residual ownership")


def validate_shutdown_receipt_resolution(
    original: ShutdownReceipt,
    resolved: ShutdownReceipt,
) -> None:
    if not isinstance(original, ShutdownReceipt):
        raise TypeError("original must be ShutdownReceipt")
    if not isinstance(resolved, ShutdownReceipt):
        raise TypeError("resolved must be ShutdownReceipt")
    if resolved != original:
        raise ValueError("concurrent shutdown callers must resolve one immutable receipt")


def validate_shutdown_control_link(
    shutdown: ShutdownReceipt,
    control: ControlReceipt,
) -> None:
    if not isinstance(shutdown, ShutdownReceipt):
        raise TypeError("shutdown must be ShutdownReceipt")
    if not isinstance(control, ControlReceipt):
        raise TypeError("control must be ControlReceipt")
    if control.control_kind is not ControlKind.SHUTDOWN:
        raise ValueError("shutdown receipt requires a shutdown control")
    linked_fields = (
        ("control_id", control.control_id),
        ("request_message_id", control.request_message_id),
        ("correlation_id", control.correlation_id),
        ("causation_id", control.causation_id),
        ("initiator", control.initiator),
        ("operation_id", control.operation_id),
        ("process_id", control.process_id),
        ("requested_at", control.requested_at),
        ("deadline", control.deadline),
    )
    for field_name, expected in linked_fields:
        if getattr(shutdown, field_name) != expected:
            raise ValueError(f"shutdown/control link mismatch for {field_name}")
    if shutdown.finished_at.value < control.finished_at.value:
        raise ValueError("shutdown finished_at cannot precede control admission")


def validate_fence_write(
    *,
    claimed_generation: int,
    writer_generation: int,
) -> None:
    _validate_generation(claimed_generation)
    _validate_generation(writer_generation)
    if writer_generation != claimed_generation:
        raise ValueError("writer generation does not match the durable owner fence")


def validate_shutdown_takeover(evidence: ShutdownTakeoverEvidence) -> None:
    if not isinstance(evidence, ShutdownTakeoverEvidence):
        raise TypeError("evidence must be ShutdownTakeoverEvidence")
    if evidence.next_owner_instance_id == evidence.previous_owner_instance_id:
        raise ValueError("takeover must use a new owner instance identity")
    if evidence.next_generation != evidence.previous_generation + 1:
        raise ValueError("takeover must claim exactly the next fence generation")
    if evidence.prior_lease_expired is evidence.prior_lease_revoked:
        raise ValueError("takeover requires exactly one expired or revoked lease proof")


def make_control_error(
    *,
    disposition: ControlDisposition,
    request_message_id: OpaqueId,
    correlation_id: OpaqueId,
    causation_id: OpaqueId | None,
    operation_id: OpaqueId | None,
    process_id: OpaqueId | None,
    occurred_at: UtcInstant,
    safe_message: str,
    retry_after_ms: int | None = None,
) -> ErrorEnvelope:
    product = {
        ControlDisposition.DENIED: (
            "CONTROL_DENIED",
            ErrorCategory.DENIED,
            ObservationState.OBSERVED,
            False,
            "Request authorization under the current control policy.",
        ),
        ControlDisposition.NOT_FOUND: (
            "CONTROL_TARGET_NOT_FOUND",
            ErrorCategory.INVALID,
            ObservationState.OBSERVED,
            False,
            "Verify the control target identity before retrying.",
        ),
        ControlDisposition.UNAVAILABLE: (
            "CONTROL_UNAVAILABLE",
            ErrorCategory.UNAVAILABLE,
            ObservationState.UNAVAILABLE,
            True,
            "Inspect the control owner dependency and retry after recovery.",
        ),
        ControlDisposition.DEADLINE_EXCEEDED: (
            "CONTROL_DEADLINE_EXCEEDED",
            ErrorCategory.TIMEOUT,
            ObservationState.NOT_OBSERVED,
            True,
            "Observe the target separately or retry with a fresh finite deadline.",
        ),
    }.get(disposition)
    if product is None:
        raise ValueError("disposition does not carry a safe control error")
    reason, category, observation, retryable, recovery_hint = product
    return ErrorEnvelope(
        schema_name="trade.error",
        schema_version=1,
        reason_code=reason,
        category=category,
        observation_state=observation,
        retryable=retryable,
        retry_after_ms=retry_after_ms,
        request_message_id=request_message_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        operation_id=operation_id,
        process_id=process_id,
        occurred_at=occurred_at,
        safe_message=safe_message,
        recovery_hint=recovery_hint,
    )


def make_control_receipt_unavailable_error(
    *,
    request_message_id: OpaqueId,
    correlation_id: OpaqueId,
    causation_id: OpaqueId | None,
    occurred_at: UtcInstant,
    safe_message: str,
    retry_after_ms: int,
) -> ErrorEnvelope:
    if not 1 <= retry_after_ms <= 1_000:
        raise ValueError("CONTROL_RECEIPT_UNAVAILABLE retry_after_ms must be in 1..1,000")
    return ErrorEnvelope(
        schema_name="trade.error",
        schema_version=1,
        reason_code="CONTROL_RECEIPT_UNAVAILABLE",
        category=ErrorCategory.UNAVAILABLE,
        observation_state=ObservationState.UNAVAILABLE,
        retryable=True,
        retry_after_ms=retry_after_ms,
        request_message_id=request_message_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        operation_id=None,
        process_id=None,
        occurred_at=occurred_at,
        safe_message=safe_message,
        recovery_hint=(
            "Inspect Platform control receipt persistence and retry the same request "
            "after recovery."
        ),
    )


def _validate_exact_target(
    operation_id: OpaqueId | None,
    process_id: OpaqueId | None,
) -> None:
    _validate_optional_links(operation_id, process_id)
    if (operation_id is None) == (process_id is None):
        raise ValueError("control requires exactly one operation or process target")


def _validate_optional_links(
    operation_id: OpaqueId | None,
    process_id: OpaqueId | None,
) -> None:
    if operation_id is not None and not isinstance(operation_id, OpaqueId):
        raise TypeError("operation_id must be OpaqueId or None")
    if process_id is not None and not isinstance(process_id, OpaqueId):
        raise TypeError("process_id must be OpaqueId or None")


def _validate_causal_tuple(
    *,
    request_message_id: OpaqueId,
    correlation_id: OpaqueId,
    causation_id: OpaqueId | None,
) -> None:
    if not isinstance(request_message_id, OpaqueId):
        raise TypeError("request_message_id must be OpaqueId")
    if not isinstance(correlation_id, OpaqueId):
        raise TypeError("correlation_id must be OpaqueId")
    if causation_id is not None and not isinstance(causation_id, OpaqueId):
        raise TypeError("causation_id must be OpaqueId or None")
    if causation_id is None and correlation_id != request_message_id:
        raise ValueError("root control correlation identity must equal request identity")
    if causation_id is not None and request_message_id in {
        correlation_id,
        causation_id,
    }:
        raise ValueError("child control request identity must be new")


def _validate_generation(value: int) -> int:
    return _validate_int(
        value,
        field_name="fence_generation",
        minimum=1,
        maximum=_MAX_INT64,
    )


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


def _validate_reason(value: str) -> str:
    if not isinstance(value, str) or _REASON_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "reason_code must be 1-96 ASCII upper-case letters, digits, '.', '_' or '-'"
        )
    return value


def _validate_token(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be 1-96 ASCII lower-case letters, digits, '.', '_', ':' or '-'"
        )
    return value
