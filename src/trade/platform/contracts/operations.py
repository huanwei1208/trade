from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from trade.kernel.digest import ContentDigest
from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import UtcInstant
from trade.platform.contracts.actor import ActorContext, PolicyRefV1
from trade.platform.contracts.errors import ErrorEnvelope
from trade.platform.contracts.messages import (
    FingerprintDomain,
    FingerprintV1,
    ReplayAdmissionV1,
    canonical_idempotency_subject_bytes,
)

__all__ = [
    "ADMISSION_OUTCOME_COUNTER_NAME",
    "AdmissionOutcome",
    "AdmissionOutcomeLabels",
    "AdmissionRefusalEventV1",
    "AdmissionRefusalAuditV1",
    "DeadlineTerminalEvidence",
    "OperationReceipt",
    "OperationState",
    "ReplayAdmissionBindingDigestV1",
    "ReplayAuditFactV1",
    "ReplayAuditFailureKind",
    "ReplayAuditHealthSignalV1",
    "ReplayAuditKey",
    "ReplayAuditOutcome",
    "ReplayAuditOwnerPort",
    "ReplayAuditOwnerResult",
    "ReplayAuditResourceUsage",
    "canonical_replay_audit_fact_bytes",
    "derive_replay_admission_binding_digest",
    "validate_operation_receipt_transition",
    "validate_operation_transition",
]

_LOWER_TOKEN_PATTERN = re.compile(r"[a-z0-9._:-]{1,96}", re.ASCII)
_REASON_PATTERN = re.compile(r"[A-Z0-9._-]{1,96}", re.ASCII)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)
_MAX_INT32 = 2_147_483_647
_MAX_INT64 = 9_223_372_036_854_775_807
_MAX_REPLAY_AUDIT_BYTES = 2_048
ADMISSION_OUTCOME_COUNTER_NAME = "platform_idempotency_admission_outcomes_total"
_REPLAY_BINDING_DOMAIN = "trade.replay-admission-binding.v1"
_REPLAY_BINDING_PREFIX = _REPLAY_BINDING_DOMAIN.encode("ascii") + b"\0"
_TERMINAL_STATES = frozenset(
    {
        "completed",
        "compensated",
        "failed",
        "cancelled",
        "deadline_exceeded",
    }
)


class OperationState(str, Enum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
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
        return self.value in _TERMINAL_STATES


_OPERATION_TRANSITIONS = {
    OperationState.REQUESTED: frozenset(
        {
            OperationState.ACCEPTED,
            OperationState.FAILED,
            OperationState.CANCELLED,
            OperationState.DEADLINE_EXCEEDED,
        }
    ),
    OperationState.ACCEPTED: frozenset(
        {
            OperationState.RUNNING,
            OperationState.WAITING,
            OperationState.RETRY_SCHEDULED,
            OperationState.BLOCKED,
            OperationState.COMPLETED,
            OperationState.FAILED,
            OperationState.CANCELLED,
            OperationState.DEADLINE_EXCEEDED,
        }
    ),
    OperationState.RUNNING: frozenset(
        {
            OperationState.WAITING,
            OperationState.RETRY_SCHEDULED,
            OperationState.COMPENSATION_PENDING,
            OperationState.BLOCKED,
            OperationState.COMPLETED,
            OperationState.FAILED,
            OperationState.CANCELLED,
            OperationState.DEADLINE_EXCEEDED,
        }
    ),
    OperationState.WAITING: frozenset(
        {
            OperationState.RUNNING,
            OperationState.RETRY_SCHEDULED,
            OperationState.BLOCKED,
            OperationState.FAILED,
            OperationState.CANCELLED,
            OperationState.DEADLINE_EXCEEDED,
        }
    ),
    OperationState.RETRY_SCHEDULED: frozenset(
        {
            OperationState.RUNNING,
            OperationState.WAITING,
            OperationState.BLOCKED,
            OperationState.FAILED,
            OperationState.CANCELLED,
            OperationState.DEADLINE_EXCEEDED,
        }
    ),
    OperationState.COMPENSATION_PENDING: frozenset(
        {
            OperationState.COMPENSATED,
            OperationState.BLOCKED,
            OperationState.FAILED,
            OperationState.DEADLINE_EXCEEDED,
        }
    ),
    OperationState.BLOCKED: frozenset(
        {
            OperationState.RUNNING,
            OperationState.RETRY_SCHEDULED,
            OperationState.COMPENSATION_PENDING,
            OperationState.FAILED,
            OperationState.CANCELLED,
            OperationState.DEADLINE_EXCEEDED,
        }
    ),
    OperationState.COMPLETED: frozenset(),
    OperationState.COMPENSATED: frozenset(),
    OperationState.FAILED: frozenset(),
    OperationState.CANCELLED: frozenset(),
    OperationState.DEADLINE_EXCEEDED: frozenset(),
}


class AdmissionOutcome(str, Enum):
    CREATED = "created"
    REPLAYED = "replayed"
    COMMAND_CONFLICT = "command_conflict"
    CLAIM_CORRUPT = "claim_corrupt"
    KEYSET_CONTENTION = "keyset_contention"
    AUDIT_UNAVAILABLE = "audit_unavailable"


_REFUSAL_OUTCOMES = {
    "IDEMPOTENCY_COMMAND_CONFLICT": AdmissionOutcome.COMMAND_CONFLICT,
    "IDEMPOTENCY_CLAIM_CORRUPT": AdmissionOutcome.CLAIM_CORRUPT,
    "IDEMPOTENCY_KEYSET_CONTENTION": AdmissionOutcome.KEYSET_CONTENTION,
    "IDEMPOTENCY_AUDIT_UNAVAILABLE": AdmissionOutcome.AUDIT_UNAVAILABLE,
}


@dataclass(frozen=True, slots=True)
class AdmissionOutcomeLabels:
    owner_namespace: IdNamespace
    outcome: AdmissionOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.owner_namespace, IdNamespace):
            raise TypeError("owner_namespace must be IdNamespace")
        if not isinstance(self.outcome, AdmissionOutcome):
            raise TypeError("outcome must be AdmissionOutcome")


@dataclass(frozen=True, slots=True)
class AdmissionRefusalEventV1:
    schema_name: str
    schema_version: int
    reason_code: str
    outcome: AdmissionOutcome
    request_message_id: OpaqueId
    correlation_id: OpaqueId
    causation_id: OpaqueId | None
    owner_namespace: IdNamespace
    matched_key_versions: tuple[int, ...]
    key_set_generation: int
    attempt_count: int

    def __post_init__(self) -> None:
        if self.schema_name != "trade.idempotency_admission_refusal":
            raise ValueError(
                "AdmissionRefusalEventV1 schema_name must be 'trade.idempotency_admission_refusal'"
            )
        if self.schema_version != 1:
            raise ValueError("AdmissionRefusalEventV1 schema_version must be 1")
        expected_outcome = _REFUSAL_OUTCOMES.get(self.reason_code)
        if expected_outcome is None:
            raise ValueError("refusal event reason is not a closed terminal outcome")
        if self.outcome is not expected_outcome:
            raise ValueError("refusal event outcome does not match its reason")
        _validate_refusal_evidence(
            request_message_id=self.request_message_id,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            owner_namespace=self.owner_namespace,
            matched_key_versions=self.matched_key_versions,
            key_set_generation=self.key_set_generation,
            attempt_count=self.attempt_count,
        )
        _validate_matched_versions_for_reason(
            reason_code=self.reason_code,
            matched_key_versions=self.matched_key_versions,
            audit_required=False,
        )


class DeadlineTerminalEvidence(str, Enum):
    ALL_OWNED_WORKERS_EXITED = "all_owned_workers_exited"
    RESIDUAL_WRITES_DURABLY_FENCED = "residual_writes_durably_fenced"


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    schema_name: str
    schema_version: int
    operation_id: OpaqueId
    operation_kind: str
    command_name: str
    command_fingerprint: FingerprintV1
    actor: ActorContext
    request_message_id: OpaqueId
    correlation_id: OpaqueId
    causation_id: OpaqueId | None
    idempotency_scope: str
    idempotency_fingerprint: FingerprintV1
    state: OperationState
    reason_code: str
    accepted_at: UtcInstant
    updated_at: UtcInstant
    terminal_at: UtcInstant | None
    process_id: OpaqueId | None

    def __post_init__(self) -> None:
        if self.schema_name != "trade.operation_receipt":
            raise ValueError("OperationReceipt schema_name must be 'trade.operation_receipt'")
        if self.schema_version != 1:
            raise ValueError("OperationReceipt schema_version must be 1")
        if not isinstance(self.operation_id, OpaqueId):
            raise TypeError("operation_id must be OpaqueId")
        _validate_lower_token(self.operation_kind, field_name="operation_kind")
        _validate_lower_token(self.command_name, field_name="command_name")
        if (
            not isinstance(self.command_fingerprint, FingerprintV1)
            or self.command_fingerprint.domain is not FingerprintDomain.COMMAND
        ):
            raise ValueError("command_fingerprint must use the command fingerprint domain")
        if not isinstance(self.actor, ActorContext):
            raise TypeError("actor must be ActorContext")
        if not self.actor.can_submit_mutation:
            raise ValueError("operation receipt actor must retain verified mutation authority")
        _validate_causal_tuple(
            request_message_id=self.request_message_id,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
        )
        _validate_lower_token(self.idempotency_scope, field_name="idempotency_scope")
        if (
            not isinstance(self.idempotency_fingerprint, FingerprintV1)
            or self.idempotency_fingerprint.domain is not FingerprintDomain.IDEMPOTENCY
        ):
            raise ValueError("idempotency_fingerprint must use the idempotency fingerprint domain")
        if not isinstance(self.state, OperationState):
            raise TypeError("state must be OperationState")
        _validate_reason(self.reason_code)
        if not isinstance(self.accepted_at, UtcInstant):
            raise TypeError("accepted_at must be UtcInstant")
        if not isinstance(self.updated_at, UtcInstant):
            raise TypeError("updated_at must be UtcInstant")
        if self.updated_at.value < self.accepted_at.value:
            raise ValueError("updated_at cannot precede accepted_at")
        if self.terminal_at is not None and not isinstance(self.terminal_at, UtcInstant):
            raise TypeError("terminal_at must be UtcInstant or None")
        if self.state.is_terminal:
            if self.terminal_at is None:
                raise ValueError("terminal operation state requires terminal_at")
            if not self.accepted_at.value <= self.terminal_at.value <= self.updated_at.value:
                raise ValueError("terminal_at must be between accepted_at and updated_at")
        elif self.terminal_at is not None:
            raise ValueError("non-terminal operation state forbids terminal_at")
        if self.process_id is not None and not isinstance(self.process_id, OpaqueId):
            raise TypeError("process_id must be OpaqueId or None")


@dataclass(frozen=True, slots=True)
class ReplayAdmissionBindingDigestV1:
    algorithm: str
    domain: str
    value: str

    def __post_init__(self) -> None:
        if self.algorithm != "sha256":
            raise ValueError("replay admission binding digest algorithm must be 'sha256'")
        if self.domain != _REPLAY_BINDING_DOMAIN:
            raise ValueError(
                "replay admission binding digest domain must be 'trade.replay-admission-binding.v1'"
            )
        if not isinstance(self.value, str) or _SHA256_PATTERN.fullmatch(self.value) is None:
            raise ValueError(
                "replay admission binding digest must be 64 lower-case hexadecimal characters"
            )


@dataclass(frozen=True, slots=True)
class ReplayAuditKey:
    owner_namespace: IdNamespace
    replay_request_message_id: OpaqueId

    def __post_init__(self) -> None:
        if not isinstance(self.owner_namespace, IdNamespace):
            raise TypeError("owner_namespace must be IdNamespace")
        if not isinstance(self.replay_request_message_id, OpaqueId):
            raise TypeError("replay_request_message_id must be OpaqueId")

    @property
    def storage_key(self) -> tuple[IdNamespace, OpaqueId]:
        return (self.owner_namespace, self.replay_request_message_id)


class ReplayAuditOutcome(str, Enum):
    RESOLVED_NEW_AUDIT = "resolved_new_audit"
    RESOLVED_EXISTING_AUDIT = "resolved_existing_audit"
    OPERATION_NOT_FOUND = "operation_not_found"
    ADMISSION_CONFLICT = "admission_conflict"
    CLOCK_UNAVAILABLE = "clock_unavailable"
    TRANSACTION_UNAVAILABLE = "transaction_unavailable"
    PERSISTENCE_UNAVAILABLE = "persistence_unavailable"


class ReplayAuditFailureKind(str, Enum):
    CLOCK_UNAVAILABLE = "clock_unavailable"
    TRANSACTION_UNAVAILABLE = "transaction_unavailable"
    PERSISTENCE_UNAVAILABLE = "persistence_unavailable"


@dataclass(frozen=True, slots=True)
class ReplayAuditFactV1:
    schema_name: str
    schema_version: int
    owner_namespace: IdNamespace
    replay_request_message_id: OpaqueId
    replay_request_correlation_id: OpaqueId
    replay_request_causation_id: OpaqueId | None
    historical_message_id: OpaqueId
    historical_operation_id: OpaqueId
    historical_envelope_digest: ContentDigest
    admission_binding_digest: ReplayAdmissionBindingDigestV1
    current_safe_principal_id: OpaqueId
    replay_policy: PolicyRefV1
    outcome: str
    occurred_at: UtcInstant

    def __post_init__(self) -> None:
        if self.schema_name != "trade.replay_audit":
            raise ValueError("ReplayAuditFactV1 schema_name must be 'trade.replay_audit'")
        if self.schema_version != 1:
            raise ValueError("ReplayAuditFactV1 schema_version must be 1")
        if not isinstance(self.owner_namespace, IdNamespace):
            raise TypeError("owner_namespace must be IdNamespace")
        _validate_causal_tuple(
            request_message_id=self.replay_request_message_id,
            correlation_id=self.replay_request_correlation_id,
            causation_id=self.replay_request_causation_id,
        )
        if not isinstance(self.historical_message_id, OpaqueId):
            raise TypeError("historical_message_id must be OpaqueId")
        if not isinstance(self.historical_operation_id, OpaqueId):
            raise TypeError("historical_operation_id must be OpaqueId")
        if not isinstance(self.historical_envelope_digest, ContentDigest):
            raise TypeError("historical_envelope_digest must be ContentDigest")
        if not isinstance(
            self.admission_binding_digest,
            ReplayAdmissionBindingDigestV1,
        ):
            raise TypeError("admission_binding_digest must be ReplayAdmissionBindingDigestV1")
        if not isinstance(self.current_safe_principal_id, OpaqueId):
            raise TypeError("current_safe_principal_id must be OpaqueId")
        if not isinstance(self.replay_policy, PolicyRefV1):
            raise TypeError("replay_policy must be PolicyRefV1")
        if self.outcome != "resolved":
            raise ValueError("ReplayAuditFactV1 outcome must be 'resolved'")
        if not isinstance(self.occurred_at, UtcInstant):
            raise TypeError("occurred_at must be UtcInstant")
        if len(canonical_replay_audit_fact_bytes(self)) > _MAX_REPLAY_AUDIT_BYTES:
            raise ValueError("ReplayAuditFactV1 canonical form must contain at most 2,048 bytes")

    @property
    def audit_key(self) -> ReplayAuditKey:
        return ReplayAuditKey(
            owner_namespace=self.owner_namespace,
            replay_request_message_id=self.replay_request_message_id,
        )


@dataclass(frozen=True, slots=True)
class ReplayAuditHealthSignalV1:
    schema_name: str
    schema_version: int
    owner_namespace: IdNamespace
    replay_request_message_id: OpaqueId
    replay_request_correlation_id: OpaqueId
    replay_request_causation_id: OpaqueId | None
    failure_kind: ReplayAuditFailureKind

    def __post_init__(self) -> None:
        if self.schema_name != "trade.replay_audit_health":
            raise ValueError(
                "ReplayAuditHealthSignalV1 schema_name must be 'trade.replay_audit_health'"
            )
        if self.schema_version != 1:
            raise ValueError("ReplayAuditHealthSignalV1 schema_version must be 1")
        if not isinstance(self.owner_namespace, IdNamespace):
            raise TypeError("owner_namespace must be IdNamespace")
        _validate_causal_tuple(
            request_message_id=self.replay_request_message_id,
            correlation_id=self.replay_request_correlation_id,
            causation_id=self.replay_request_causation_id,
        )
        if not isinstance(self.failure_kind, ReplayAuditFailureKind):
            raise TypeError("failure_kind must be ReplayAuditFailureKind")


@dataclass(frozen=True, slots=True)
class ReplayAuditResourceUsage:
    transaction_count: int
    audit_key_lookup_count: int
    operation_lookup_count: int
    audit_clock_attempt_count: int
    audit_commit_count: int
    persistence_retry_count: int
    background_continuation_count: int
    health_signal_count: int

    def __post_init__(self) -> None:
        for field_name in (
            "transaction_count",
            "audit_key_lookup_count",
            "operation_lookup_count",
            "audit_clock_attempt_count",
            "audit_commit_count",
            "health_signal_count",
        ):
            _validate_int(
                getattr(self, field_name),
                field_name=field_name,
                minimum=0,
                maximum=1,
            )
        for field_name in (
            "persistence_retry_count",
            "background_continuation_count",
        ):
            _validate_int(
                getattr(self, field_name),
                field_name=field_name,
                minimum=0,
                maximum=0,
            )
        if self.audit_key_lookup_count > self.transaction_count:
            raise ValueError("audit key lookup requires the owner transaction")
        if self.operation_lookup_count > self.audit_key_lookup_count:
            raise ValueError("operation lookup requires the prior audit key lookup")
        if self.audit_clock_attempt_count > self.operation_lookup_count:
            raise ValueError("audit clock sampling requires a resolved operation lookup")
        if self.audit_commit_count > self.audit_clock_attempt_count:
            raise ValueError("audit commit requires one successful audit clock attempt")


@dataclass(frozen=True, slots=True)
class ReplayAuditOwnerResult:
    outcome: ReplayAuditOutcome
    receipt: OperationReceipt | None
    audit_fact: ReplayAuditFactV1 | None
    error: ErrorEnvelope | None
    health_signal: ReplayAuditHealthSignalV1 | None
    resource_usage: ReplayAuditResourceUsage

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ReplayAuditOutcome):
            raise TypeError("outcome must be ReplayAuditOutcome")
        if self.receipt is not None and not isinstance(self.receipt, OperationReceipt):
            raise TypeError("receipt must be OperationReceipt or None")
        if self.audit_fact is not None and not isinstance(
            self.audit_fact,
            ReplayAuditFactV1,
        ):
            raise TypeError("audit_fact must be ReplayAuditFactV1 or None")
        if self.error is not None and not isinstance(self.error, ErrorEnvelope):
            raise TypeError("error must be ErrorEnvelope or None")
        if self.health_signal is not None and not isinstance(
            self.health_signal,
            ReplayAuditHealthSignalV1,
        ):
            raise TypeError("health_signal must be ReplayAuditHealthSignalV1 or None")
        if not isinstance(self.resource_usage, ReplayAuditResourceUsage):
            raise TypeError("resource_usage must be ReplayAuditResourceUsage")
        self._validate_product()

    def _validate_product(self) -> None:
        if self.outcome in {
            ReplayAuditOutcome.RESOLVED_NEW_AUDIT,
            ReplayAuditOutcome.RESOLVED_EXISTING_AUDIT,
        }:
            self._validate_resolved_product()
            return

        if self.receipt is not None or self.audit_fact is not None:
            raise ValueError("non-resolved replay audit outcome forbids receipt and audit")
        expected_reason = {
            ReplayAuditOutcome.OPERATION_NOT_FOUND: "REPLAY_OPERATION_NOT_FOUND",
            ReplayAuditOutcome.ADMISSION_CONFLICT: "REPLAY_ADMISSION_CONFLICT",
            ReplayAuditOutcome.CLOCK_UNAVAILABLE: "REPLAY_AUDIT_CLOCK_UNAVAILABLE",
            ReplayAuditOutcome.TRANSACTION_UNAVAILABLE: "REPLAY_AUDIT_UNAVAILABLE",
            ReplayAuditOutcome.PERSISTENCE_UNAVAILABLE: "REPLAY_AUDIT_UNAVAILABLE",
        }[self.outcome]
        if self.error is None or self.error.reason_code != expected_reason:
            raise ValueError(f"{self.outcome.value} requires exact {expected_reason} error")
        expected_failure = {
            ReplayAuditOutcome.CLOCK_UNAVAILABLE: ReplayAuditFailureKind.CLOCK_UNAVAILABLE,
            ReplayAuditOutcome.TRANSACTION_UNAVAILABLE: (
                ReplayAuditFailureKind.TRANSACTION_UNAVAILABLE
            ),
            ReplayAuditOutcome.PERSISTENCE_UNAVAILABLE: (
                ReplayAuditFailureKind.PERSISTENCE_UNAVAILABLE
            ),
        }.get(self.outcome)
        if expected_failure is None:
            if self.health_signal is not None:
                raise ValueError("missing/conflicting replay outcome forbids a health signal")
            if self.resource_usage.health_signal_count != 0:
                raise ValueError("missing/conflicting replay outcome requires zero health signals")
        else:
            if self.health_signal is None:
                if self.resource_usage.health_signal_count != 0:
                    raise ValueError("absent replay health signal requires zero signal count")
            else:
                if self.health_signal.failure_kind is not expected_failure:
                    raise ValueError(f"{self.outcome.value} requires its exact health failure kind")
                if self.resource_usage.health_signal_count != 1:
                    raise ValueError("present replay health signal requires one signal count")
                if (
                    self.error.request_message_id != self.health_signal.replay_request_message_id
                    or self.error.correlation_id != self.health_signal.replay_request_correlation_id
                    or self.error.causation_id != self.health_signal.replay_request_causation_id
                ):
                    raise ValueError(
                        "replay audit error and health signal must share the current causal tuple"
                    )
        self._validate_failure_usage()

    def _validate_resolved_product(self) -> None:
        if self.receipt is None or self.audit_fact is None:
            raise ValueError("resolved replay audit requires receipt and audit fact")
        if self.error is not None or self.health_signal is not None:
            raise ValueError("resolved replay audit forbids error and health signal")
        if self.resource_usage.health_signal_count != 0:
            raise ValueError("resolved replay audit requires zero health signals")
        if self.audit_fact.historical_operation_id != self.receipt.operation_id:
            raise ValueError("replay audit operation must match the historical receipt")
        if self.audit_fact.historical_message_id != self.receipt.request_message_id:
            raise ValueError("replay audit historical message must match the historical receipt")
        expected_usage = (
            1,
            1,
            1,
            1 if self.outcome is ReplayAuditOutcome.RESOLVED_NEW_AUDIT else 0,
            1 if self.outcome is ReplayAuditOutcome.RESOLVED_NEW_AUDIT else 0,
        )
        actual_usage = (
            self.resource_usage.transaction_count,
            self.resource_usage.audit_key_lookup_count,
            self.resource_usage.operation_lookup_count,
            self.resource_usage.audit_clock_attempt_count,
            self.resource_usage.audit_commit_count,
        )
        if actual_usage != expected_usage:
            raise ValueError(
                f"{self.outcome.value} has invalid transaction/lookup/clock/commit counts"
            )

    def _validate_failure_usage(self) -> None:
        usage = self.resource_usage
        if usage.audit_commit_count != 0:
            raise ValueError("failed replay audit outcome forbids an audit commit")
        if self.outcome is ReplayAuditOutcome.OPERATION_NOT_FOUND:
            expected = (1, 1, 1, 0)
        elif self.outcome is ReplayAuditOutcome.ADMISSION_CONFLICT:
            expected = (1, 1, 0, 0)
        elif self.outcome is ReplayAuditOutcome.CLOCK_UNAVAILABLE:
            expected = (1, 1, 1, 1)
        else:
            return
        actual = (
            usage.transaction_count,
            usage.audit_key_lookup_count,
            usage.operation_lookup_count,
            usage.audit_clock_attempt_count,
        )
        if actual != expected:
            raise ValueError(f"{self.outcome.value} has invalid bounded resource counts")


class ReplayAuditOwnerPort(Protocol):
    def resolve_authorized_replay(
        self,
        *,
        owner_namespace: IdNamespace,
        admission: ReplayAdmissionV1,
        binding_digest: ReplayAdmissionBindingDigestV1,
    ) -> ReplayAuditOwnerResult: ...


@dataclass(frozen=True, slots=True)
class AdmissionRefusalAuditV1:
    schema_name: str
    schema_version: int
    reason_code: str
    request_message_id: OpaqueId
    correlation_id: OpaqueId
    causation_id: OpaqueId | None
    owner_namespace: IdNamespace
    matched_key_versions: tuple[int, ...]
    key_set_generation: int
    attempt_count: int
    occurred_at: UtcInstant

    def __post_init__(self) -> None:
        if self.schema_name != "trade.idempotency_refusal_audit":
            raise ValueError(
                "AdmissionRefusalAuditV1 schema_name must be 'trade.idempotency_refusal_audit'"
            )
        if self.schema_version != 1:
            raise ValueError("AdmissionRefusalAuditV1 schema_version must be 1")
        if self.reason_code not in {
            "IDEMPOTENCY_COMMAND_CONFLICT",
            "IDEMPOTENCY_CLAIM_CORRUPT",
            "IDEMPOTENCY_KEYSET_CONTENTION",
        }:
            raise ValueError("refusal audit reason is not a durable terminal outcome")
        _validate_refusal_evidence(
            request_message_id=self.request_message_id,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            owner_namespace=self.owner_namespace,
            matched_key_versions=self.matched_key_versions,
            key_set_generation=self.key_set_generation,
            attempt_count=self.attempt_count,
        )
        if not isinstance(self.occurred_at, UtcInstant):
            raise TypeError("occurred_at must be UtcInstant")
        _validate_matched_versions_for_reason(
            reason_code=self.reason_code,
            matched_key_versions=self.matched_key_versions,
            audit_required=True,
        )


def _validate_refusal_evidence(
    *,
    request_message_id: OpaqueId,
    correlation_id: OpaqueId,
    causation_id: OpaqueId | None,
    owner_namespace: IdNamespace,
    matched_key_versions: tuple[int, ...],
    key_set_generation: int,
    attempt_count: int,
) -> None:
    _validate_causal_tuple(
        request_message_id=request_message_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    if not isinstance(owner_namespace, IdNamespace):
        raise TypeError("owner_namespace must be IdNamespace")
    if not isinstance(matched_key_versions, tuple):
        raise TypeError("matched_key_versions must be a tuple")
    if len(matched_key_versions) > 4:
        raise ValueError("matched_key_versions must contain at most four entries")
    for version in matched_key_versions:
        _validate_int(
            version,
            field_name="matched key version",
            minimum=1,
            maximum=_MAX_INT32,
        )
    if matched_key_versions != tuple(sorted(set(matched_key_versions))):
        raise ValueError("matched_key_versions must be sorted and unique")
    _validate_int(
        key_set_generation,
        field_name="key_set_generation",
        minimum=1,
        maximum=_MAX_INT64,
    )
    _validate_int(
        attempt_count,
        field_name="attempt_count",
        minimum=1,
        maximum=3,
    )


def _validate_matched_versions_for_reason(
    *,
    reason_code: str,
    matched_key_versions: tuple[int, ...],
    audit_required: bool,
) -> None:
    if reason_code == "IDEMPOTENCY_COMMAND_CONFLICT":
        if len(matched_key_versions) != 1:
            raise ValueError("command conflict evidence requires one matched key version")
    elif reason_code == "IDEMPOTENCY_CLAIM_CORRUPT":
        if not matched_key_versions:
            raise ValueError("claim corruption evidence requires matched key versions")
    elif reason_code == "IDEMPOTENCY_KEYSET_CONTENTION" and matched_key_versions:
        raise ValueError("key-set contention evidence forbids matched key versions")
    elif audit_required and reason_code == "IDEMPOTENCY_AUDIT_UNAVAILABLE":
        raise ValueError("audit-unavailable cannot be represented as a committed audit")


def validate_operation_transition(
    previous: OperationState,
    current: OperationState,
    *,
    deadline_evidence: DeadlineTerminalEvidence | None = None,
) -> None:
    if not isinstance(previous, OperationState):
        raise TypeError("previous must be OperationState")
    if not isinstance(current, OperationState):
        raise TypeError("current must be OperationState")
    if current is previous:
        if deadline_evidence is not None:
            raise ValueError("idempotent state observation forbids new deadline evidence")
        return
    if current not in _OPERATION_TRANSITIONS[previous]:
        raise ValueError(f"operation transition {previous.value} -> {current.value} is not allowed")
    _validate_deadline_evidence(current, deadline_evidence)


def validate_operation_receipt_transition(
    previous: OperationReceipt,
    current: OperationReceipt,
    *,
    deadline_evidence: DeadlineTerminalEvidence | None = None,
) -> None:
    if not isinstance(previous, OperationReceipt):
        raise TypeError("previous must be OperationReceipt")
    if not isinstance(current, OperationReceipt):
        raise TypeError("current must be OperationReceipt")
    immutable_fields = (
        "schema_name",
        "schema_version",
        "operation_id",
        "operation_kind",
        "command_name",
        "command_fingerprint",
        "actor",
        "request_message_id",
        "correlation_id",
        "causation_id",
        "idempotency_scope",
        "idempotency_fingerprint",
        "accepted_at",
    )
    for field_name in immutable_fields:
        if getattr(previous, field_name) != getattr(current, field_name):
            raise ValueError(f"operation admission field {field_name} is immutable")
    validate_operation_transition(
        previous.state,
        current.state,
        deadline_evidence=deadline_evidence,
    )
    if current.updated_at.value < previous.updated_at.value:
        raise ValueError("operation receipt updated_at cannot move backwards")
    if previous.process_id is not None and current.process_id != previous.process_id:
        raise ValueError("operation process link cannot be replaced or removed")
    if previous.state.is_terminal and current != previous:
        raise ValueError("terminal operation receipt is immutable")
    if previous.terminal_at is not None and current.terminal_at != previous.terminal_at:
        raise ValueError("operation terminal_at is immutable once established")


def _validate_lower_token(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or _LOWER_TOKEN_PATTERN.fullmatch(value) is None:
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
        raise ValueError("root operation correlation identity must equal request identity")
    if causation_id is not None and request_message_id in {correlation_id, causation_id}:
        raise ValueError("child operation request identity must be new")


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


def _validate_deadline_evidence(
    current: OperationState,
    evidence: DeadlineTerminalEvidence | None,
) -> None:
    if current is OperationState.DEADLINE_EXCEEDED:
        if not isinstance(evidence, DeadlineTerminalEvidence):
            raise ValueError(
                "owner deadline_exceeded requires worker-exit or durable-fence evidence"
            )
    elif evidence is not None:
        raise ValueError("deadline terminal evidence is valid only for deadline_exceeded")


def derive_replay_admission_binding_digest(
    admission: ReplayAdmissionV1,
) -> ReplayAdmissionBindingDigestV1:
    if not isinstance(admission, ReplayAdmissionV1):
        raise TypeError("admission must be ReplayAdmissionV1")
    context = admission.context
    canonical_binding = _frame_components(
        (
            str(admission.schema_version).encode("ascii"),
            str(context.schema_version).encode("ascii"),
            _canonical_id(context.replay_request_message_id),
            _canonical_id(context.replay_request_correlation_id),
            _canonical_optional_id(context.replay_request_causation_id),
            _canonical_id(context.historical_message_id),
            _canonical_actor(context.historical_actor),
            _canonical_actor(context.replay_initiator),
            _canonical_policy(context.replay_policy),
            _canonical_id(admission.historical_message_id),
            _canonical_id(admission.historical_correlation_id),
            _canonical_optional_id(admission.historical_causation_id),
            _canonical_content_digest(admission.historical_envelope_digest),
            _canonical_id(admission.historical_operation_id),
            canonical_idempotency_subject_bytes(admission.current_subject),
        )
    )
    return ReplayAdmissionBindingDigestV1(
        algorithm="sha256",
        domain=_REPLAY_BINDING_DOMAIN,
        value=hashlib.sha256(_REPLAY_BINDING_PREFIX + canonical_binding).hexdigest(),
    )


def canonical_replay_audit_fact_bytes(fact: ReplayAuditFactV1) -> bytes:
    if not isinstance(fact, ReplayAuditFactV1):
        raise TypeError("fact must be ReplayAuditFactV1")

    def identity(value: OpaqueId) -> dict[str, str]:
        return {"namespace": value.namespace.value, "value": value.value}

    def digest(value: ContentDigest) -> dict[str, str]:
        return {"algorithm": value.algorithm, "value": value.value}

    policy = fact.replay_policy
    payload = {
        "admission_binding_digest": {
            "algorithm": fact.admission_binding_digest.algorithm,
            "domain": fact.admission_binding_digest.domain,
            "value": fact.admission_binding_digest.value,
        },
        "current_safe_principal_id": identity(fact.current_safe_principal_id),
        "historical_envelope_digest": digest(fact.historical_envelope_digest),
        "historical_message_id": identity(fact.historical_message_id),
        "historical_operation_id": identity(fact.historical_operation_id),
        "occurred_at": fact.occurred_at.to_wire(),
        "outcome": fact.outcome,
        "owner_namespace": fact.owner_namespace.value,
        "replay_policy": {
            "content_digest": digest(policy.content_digest),
            "policy_name": policy.policy_name,
            "policy_namespace": policy.policy_namespace.value,
            "semantic_version": policy.semantic_version,
        },
        "replay_request_causation_id": (
            None
            if fact.replay_request_causation_id is None
            else identity(fact.replay_request_causation_id)
        ),
        "replay_request_correlation_id": identity(fact.replay_request_correlation_id),
        "replay_request_message_id": identity(fact.replay_request_message_id),
        "schema_name": fact.schema_name,
        "schema_version": fact.schema_version,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_actor(actor: ActorContext) -> bytes:
    return _frame_components(
        (
            str(actor.schema_version).encode("ascii"),
            actor.origin.value.encode("ascii"),
            actor.principal_kind.value.encode("ascii"),
            _canonical_id(actor.principal_id),
            _frame_components(tuple(scope.encode("ascii") for scope in actor.authority_scopes)),
            _frame_components(tuple(item.canonical_bytes() for item in actor.delegation_chain)),
            actor.assurance.value.encode("ascii"),
            actor.provenance.canonical_bytes(),
            actor.established_at.to_wire().encode("ascii"),
        )
    )


def _canonical_policy(policy: PolicyRefV1) -> bytes:
    return _frame_components(
        (
            policy.policy_namespace.value.encode("ascii"),
            policy.policy_name.encode("ascii"),
            policy.semantic_version.encode("ascii"),
            _canonical_content_digest(policy.content_digest),
        )
    )


def _canonical_content_digest(digest: ContentDigest) -> bytes:
    return _frame_components(
        (
            digest.algorithm.encode("ascii"),
            digest.value.encode("ascii"),
        )
    )


def _canonical_id(value: OpaqueId) -> bytes:
    return _frame_components(
        (
            value.namespace.value.encode("ascii"),
            value.value.encode("ascii"),
        )
    )


def _canonical_optional_id(value: OpaqueId | None) -> bytes:
    if value is None:
        return b"\x00"
    return b"\x01" + _canonical_id(value)


def _frame_components(components: tuple[bytes, ...]) -> bytes:
    framed = bytearray()
    for component in components:
        framed.extend(len(component).to_bytes(4, "big"))
        framed.extend(component)
    return bytes(framed)
