from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NoReturn

from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import UtcInstant
from trade.platform.contracts.messages import (
    CanonicalJsonError,
    CanonicalJsonErrorCode,
    decode_bounded_json_v1,
    encode_canonical_json_v1,
)

__all__ = [
    "ErrorCategory",
    "ErrorEnvelope",
    "ObservationState",
    "QueryCondition",
    "QueryStatus",
    "decode_error_envelope_v1",
    "encode_error_envelope_v1",
    "make_admission_error",
]

_REASON_PATTERN = re.compile(r"[A-Z0-9._-]{1,96}", re.ASCII)
_MAX_SAFE_TEXT_BYTES = 1_024
_MAX_RETRY_AFTER_MS = 86_400_000
_ERROR_ENVELOPE_FIELDS = frozenset(
    {
        "schema_name",
        "schema_version",
        "reason_code",
        "category",
        "observation_state",
        "retryable",
        "retry_after_ms",
        "request_message_id",
        "correlation_id",
        "causation_id",
        "operation_id",
        "process_id",
        "occurred_at",
        "safe_message",
        "recovery_hint",
    }
)


class ErrorCategory(str, Enum):
    INVALID = "invalid"
    DENIED = "denied"
    CONFLICT = "conflict"
    SATURATED = "saturated"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    QUARANTINED = "quarantined"
    STALE = "stale"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


class ObservationState(str, Enum):
    OBSERVED = "observed"
    NOT_OBSERVED = "not_observed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class QueryCondition(str, Enum):
    PRESENT = "present"
    EMPTY = "empty"
    PARTIAL = "partial"
    STALE = "stale"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class _AdmissionErrorProduct:
    category: ErrorCategory
    observation_state: ObservationState
    retryable: bool
    retry_after_required: bool
    occurred_at_required: bool
    recovery_hint: str


_ADMISSION_ERROR_PRODUCTS = {
    "REPLAY_OPERATION_NOT_FOUND": _AdmissionErrorProduct(
        category=ErrorCategory.INVALID,
        observation_state=ObservationState.OBSERVED,
        retryable=False,
        retry_after_required=False,
        occurred_at_required=True,
        recovery_hint=(
            "Verify the historical operation identity or submit a newly authorized "
            "replay-derived command."
        ),
    ),
    "REPLAY_ADMISSION_CONFLICT": _AdmissionErrorProduct(
        category=ErrorCategory.CONFLICT,
        observation_state=ObservationState.OBSERVED,
        retryable=False,
        retry_after_required=False,
        occurred_at_required=True,
        recovery_hint=("Retry the original replay binding or use a new replay request identity."),
    ),
    "REPLAY_AUDIT_CLOCK_UNAVAILABLE": _AdmissionErrorProduct(
        category=ErrorCategory.UNAVAILABLE,
        observation_state=ObservationState.UNAVAILABLE,
        retryable=True,
        retry_after_required=True,
        occurred_at_required=False,
        recovery_hint=(
            "Inspect the Platform trusted wall-clock source and retry the same replay "
            "request after recovery."
        ),
    ),
    "REPLAY_AUDIT_UNAVAILABLE": _AdmissionErrorProduct(
        category=ErrorCategory.UNAVAILABLE,
        observation_state=ObservationState.UNAVAILABLE,
        retryable=True,
        retry_after_required=True,
        occurred_at_required=True,
        recovery_hint=(
            "Inspect Platform replay-audit persistence and retry the same replay request "
            "after recovery."
        ),
    ),
    "IDEMPOTENCY_COMMAND_CONFLICT": _AdmissionErrorProduct(
        category=ErrorCategory.CONFLICT,
        observation_state=ObservationState.OBSERVED,
        retryable=False,
        retry_after_required=False,
        occurred_at_required=True,
        recovery_hint=("Submit the original command or use a new idempotency identity."),
    ),
    "IDEMPOTENCY_CLAIM_CORRUPT": _AdmissionErrorProduct(
        category=ErrorCategory.INTERNAL,
        observation_state=ObservationState.OBSERVED,
        retryable=False,
        retry_after_required=False,
        occurred_at_required=True,
        recovery_hint="Require audited operator inspection before retrying.",
    ),
    "IDEMPOTENCY_KEYSET_CONTENTION": _AdmissionErrorProduct(
        category=ErrorCategory.UNAVAILABLE,
        observation_state=ObservationState.UNAVAILABLE,
        retryable=True,
        retry_after_required=True,
        occurred_at_required=True,
        recovery_hint=("Retry the same command and identity with a fresh finite deadline."),
    ),
    "IDEMPOTENCY_AUDIT_UNAVAILABLE": _AdmissionErrorProduct(
        category=ErrorCategory.UNAVAILABLE,
        observation_state=ObservationState.UNAVAILABLE,
        retryable=True,
        retry_after_required=True,
        occurred_at_required=True,
        recovery_hint="Inspect Platform persistence and retry after recovery.",
    ),
}


@dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    schema_name: str
    schema_version: int
    reason_code: str
    category: ErrorCategory
    observation_state: ObservationState
    retryable: bool
    retry_after_ms: int | None
    request_message_id: OpaqueId
    correlation_id: OpaqueId
    causation_id: OpaqueId | None
    operation_id: OpaqueId | None
    process_id: OpaqueId | None
    occurred_at: UtcInstant | None
    safe_message: str
    recovery_hint: str

    def __post_init__(self) -> None:
        if self.schema_name != "trade.error":
            raise ValueError("ErrorEnvelope schema_name must be 'trade.error'")
        if self.schema_version != 1:
            raise ValueError("ErrorEnvelope schema_version must be 1")
        _validate_reason(self.reason_code)
        if not isinstance(self.category, ErrorCategory):
            raise TypeError("category must be ErrorCategory")
        if not isinstance(self.observation_state, ObservationState):
            raise TypeError("observation_state must be ObservationState")
        if not isinstance(self.retryable, bool):
            raise TypeError("retryable must be bool")
        _validate_retry_after(self.retry_after_ms)
        _validate_causal_tuple(
            request_message_id=self.request_message_id,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
        )
        if self.operation_id is not None and not isinstance(self.operation_id, OpaqueId):
            raise TypeError("operation_id must be OpaqueId or None")
        if self.process_id is not None and not isinstance(self.process_id, OpaqueId):
            raise TypeError("process_id must be OpaqueId or None")
        if self.occurred_at is not None and not isinstance(self.occurred_at, UtcInstant):
            raise TypeError("occurred_at must be UtcInstant or None")
        _validate_safe_text(self.safe_message, field_name="safe_message")
        _validate_safe_text(self.recovery_hint, field_name="recovery_hint")
        self._validate_occurrence_time()
        self._validate_admission_product()

    def _validate_occurrence_time(self) -> None:
        if self.reason_code == "REPLAY_AUDIT_CLOCK_UNAVAILABLE":
            if self.occurred_at is not None:
                raise ValueError("REPLAY_AUDIT_CLOCK_UNAVAILABLE must not contain occurred_at")
            return
        if self.occurred_at is None:
            raise ValueError("occurred_at is required except for REPLAY_AUDIT_CLOCK_UNAVAILABLE")

    def _validate_admission_product(self) -> None:
        product = _ADMISSION_ERROR_PRODUCTS.get(self.reason_code)
        if product is None:
            return
        if self.category is not product.category:
            raise ValueError(f"{self.reason_code} has an invalid error category")
        if self.observation_state is not product.observation_state:
            raise ValueError(f"{self.reason_code} has an invalid observation state")
        if self.retryable is not product.retryable:
            raise ValueError(f"{self.reason_code} has an invalid retryable value")
        if product.retry_after_required:
            if self.retry_after_ms is None or not 1 <= self.retry_after_ms <= 1_000:
                raise ValueError(f"{self.reason_code} requires retry_after_ms in 1..1,000")
        elif self.retry_after_ms is not None:
            raise ValueError(f"{self.reason_code} forbids retry_after_ms")
        if (self.occurred_at is not None) is not product.occurred_at_required:
            raise ValueError(f"{self.reason_code} has an invalid occurred_at product")
        if self.operation_id is not None or self.process_id is not None:
            raise ValueError(f"{self.reason_code} forbids operation and process links")
        if self.recovery_hint != product.recovery_hint:
            raise ValueError(f"{self.reason_code} requires its exact safe recovery hint")


@dataclass(frozen=True, slots=True)
class QueryStatus:
    observation_state: ObservationState
    condition: QueryCondition | None
    error: ErrorEnvelope | None

    def __post_init__(self) -> None:
        if not isinstance(self.observation_state, ObservationState):
            raise TypeError("observation_state must be ObservationState")
        if self.condition is not None and not isinstance(self.condition, QueryCondition):
            raise TypeError("condition must be QueryCondition or None")
        if self.error is not None and not isinstance(self.error, ErrorEnvelope):
            raise TypeError("error must be ErrorEnvelope or None")

        expected_category: ErrorCategory | None
        if self.observation_state is ObservationState.OBSERVED:
            if self.condition is None:
                raise ValueError("observed query status requires a condition")
            if self.condition in {QueryCondition.PRESENT, QueryCondition.EMPTY}:
                expected_category = None
            else:
                expected_category = {
                    QueryCondition.PARTIAL: ErrorCategory.UNAVAILABLE,
                    QueryCondition.STALE: ErrorCategory.STALE,
                    QueryCondition.QUARANTINED: ErrorCategory.QUARANTINED,
                    QueryCondition.BLOCKED: ErrorCategory.BLOCKED,
                }.get(self.condition)
                if expected_category is None:
                    raise ValueError("observed query status has an unsupported condition")
        else:
            if self.condition is not None:
                raise ValueError("non-observed query status forbids a condition")
            expected_category = {
                ObservationState.NOT_OBSERVED: ErrorCategory.TIMEOUT,
                ObservationState.UNAVAILABLE: ErrorCategory.UNAVAILABLE,
                ObservationState.UNKNOWN: ErrorCategory.INTERNAL,
            }[self.observation_state]

        if expected_category is None:
            if self.error is not None:
                raise ValueError("healthy observed query status forbids an error")
            return
        if self.error is None:
            raise ValueError("unhealthy query status requires an error")
        if self.error.category is not expected_category:
            raise ValueError("query status error category does not match its state product")
        if self.error.observation_state is not self.observation_state:
            raise ValueError("query status error observation does not match the status")


def encode_error_envelope_v1(error: ErrorEnvelope) -> bytes:
    if not isinstance(error, ErrorEnvelope):
        raise TypeError("error must be ErrorEnvelope")
    return encode_canonical_json_v1(
        {
            "category": error.category.value,
            "causation_id": _optional_id_to_wire(error.causation_id),
            "correlation_id": error.correlation_id.to_dict(),
            "observation_state": error.observation_state.value,
            "occurred_at": None if error.occurred_at is None else error.occurred_at.to_wire(),
            "operation_id": _optional_id_to_wire(error.operation_id),
            "process_id": _optional_id_to_wire(error.process_id),
            "reason_code": error.reason_code,
            "recovery_hint": error.recovery_hint,
            "request_message_id": error.request_message_id.to_dict(),
            "retry_after_ms": error.retry_after_ms,
            "retryable": error.retryable,
            "safe_message": error.safe_message,
            "schema_name": error.schema_name,
            "schema_version": error.schema_version,
        }
    )


def decode_error_envelope_v1(raw: bytes) -> ErrorEnvelope:
    value = decode_bounded_json_v1(raw)
    payload = _exact_object(value, fields=_ERROR_ENVELOPE_FIELDS)
    if (
        payload["schema_name"] != "trade.error"
        or payload["schema_version"] != 1
        or isinstance(payload["schema_version"], bool)
    ):
        _raise_invalid_schema()
    try:
        return ErrorEnvelope(
            schema_name=_string_field(payload, "schema_name"),
            schema_version=_integer_field(payload, "schema_version"),
            reason_code=_string_field(payload, "reason_code"),
            category=ErrorCategory(_string_field(payload, "category")),
            observation_state=ObservationState(_string_field(payload, "observation_state")),
            retryable=_boolean_field(payload, "retryable"),
            retry_after_ms=_optional_integer_field(payload, "retry_after_ms"),
            request_message_id=_id_from_wire(payload["request_message_id"]),
            correlation_id=_id_from_wire(payload["correlation_id"]),
            causation_id=_optional_id_from_wire(payload["causation_id"]),
            operation_id=_optional_id_from_wire(payload["operation_id"]),
            process_id=_optional_id_from_wire(payload["process_id"]),
            occurred_at=_optional_instant_from_wire(payload["occurred_at"]),
            safe_message=_string_field(payload, "safe_message"),
            recovery_hint=_string_field(payload, "recovery_hint"),
        )
    except (TypeError, ValueError):
        _raise_invalid_schema()


def make_admission_error(
    *,
    reason_code: str,
    request_message_id: OpaqueId,
    correlation_id: OpaqueId,
    causation_id: OpaqueId | None,
    occurred_at: UtcInstant | None,
    safe_message: str,
    retry_after_ms: int | None = None,
) -> ErrorEnvelope:
    product = _ADMISSION_ERROR_PRODUCTS.get(reason_code)
    if product is None:
        raise ValueError("reason_code is not a closed replay or idempotency product")
    return ErrorEnvelope(
        schema_name="trade.error",
        schema_version=1,
        reason_code=reason_code,
        category=product.category,
        observation_state=product.observation_state,
        retryable=product.retryable,
        retry_after_ms=retry_after_ms,
        request_message_id=request_message_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        operation_id=None,
        process_id=None,
        occurred_at=occurred_at,
        safe_message=safe_message,
        recovery_hint=product.recovery_hint,
    )


def _exact_object(value: object, *, fields: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        _raise_invalid_schema()
    if any(not isinstance(key, str) for key in value):
        _raise_invalid_schema()
    return value


def _id_from_wire(value: object) -> OpaqueId:
    payload = _exact_object(value, fields=frozenset({"namespace", "value"}))
    return OpaqueId(
        namespace=IdNamespace(_string_field(payload, "namespace")),
        value=_string_field(payload, "value"),
    )


def _optional_id_to_wire(value: OpaqueId | None) -> dict[str, str] | None:
    return None if value is None else value.to_dict()


def _optional_id_from_wire(value: object) -> OpaqueId | None:
    return None if value is None else _id_from_wire(value)


def _optional_instant_from_wire(value: object) -> UtcInstant | None:
    return None if value is None else UtcInstant.from_wire(_expect_string(value))


def _string_field(payload: dict[str, object], name: str) -> str:
    return _expect_string(payload[name])


def _expect_string(value: object) -> str:
    if not isinstance(value, str):
        _raise_invalid_schema()
    return value


def _integer_field(payload: dict[str, object], name: str) -> int:
    value = payload[name]
    if not isinstance(value, int) or isinstance(value, bool):
        _raise_invalid_schema()
    return value


def _optional_integer_field(payload: dict[str, object], name: str) -> int | None:
    value = payload[name]
    return None if value is None else _integer_field(payload, name)


def _boolean_field(payload: dict[str, object], name: str) -> bool:
    value = payload[name]
    if not isinstance(value, bool):
        _raise_invalid_schema()
    return value


def _raise_invalid_schema() -> NoReturn:
    raise CanonicalJsonError(CanonicalJsonErrorCode.INVALID_SCHEMA)


def _validate_reason(value: str) -> str:
    if not isinstance(value, str) or _REASON_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "reason_code must be 1-96 ASCII upper-case letters, digits, '.', '_' or '-'"
        )
    return value


def _validate_retry_after(value: int | None) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("retry_after_ms must be an integer or None")
    if not 0 <= value <= _MAX_RETRY_AFTER_MS:
        raise ValueError("retry_after_ms must be in 0..86,400,000")


def _validate_safe_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field_name} must be valid UTF-8") from error
    if len(encoded) > _MAX_SAFE_TEXT_BYTES:
        raise ValueError(f"{field_name} must contain at most 1,024 UTF-8 bytes")
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
        raise ValueError("root error correlation identity must equal request identity")
    if causation_id is not None and request_message_id in {correlation_id, causation_id}:
        raise ValueError("child error request identity must be new")
