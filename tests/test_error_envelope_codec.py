from __future__ import annotations

import json
from dataclasses import replace

import pytest

from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import UtcInstant
from trade.platform.contracts.errors import (
    ErrorCategory,
    ErrorEnvelope,
    ObservationState,
    decode_error_envelope_v1,
    encode_error_envelope_v1,
    make_admission_error,
)
from trade.platform.contracts.messages import (
    CanonicalJsonError,
    CanonicalJsonErrorCode,
)


def _id(namespace: str, value: str) -> OpaqueId:
    return OpaqueId(IdNamespace(namespace), value)


def _instant(microsecond: int = 0) -> UtcInstant:
    return UtcInstant.from_wire(f"2026-07-27T00:00:00.{microsecond:06d}Z")


def _root_error() -> ErrorEnvelope:
    request = _id("message", "request")
    return make_admission_error(
        reason_code="REPLAY_OPERATION_NOT_FOUND",
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        occurred_at=_instant(1),
        safe_message="Historical operation was not found.",
    )


def _assert_schema_error(raw: bytes) -> None:
    with pytest.raises(CanonicalJsonError) as raised:
        decode_error_envelope_v1(raw)

    assert raised.value.code is CanonicalJsonErrorCode.INVALID_SCHEMA


@pytest.mark.parametrize("microsecond", [0, 1, 999_999])
def test_error_envelope_codec_round_trips_exact_utc_instants(microsecond: int) -> None:
    error = replace(_root_error(), occurred_at=_instant(microsecond))

    canonical = encode_error_envelope_v1(error)

    assert decode_error_envelope_v1(canonical) == error
    assert f".{microsecond:06d}Z".encode() in canonical
    assert encode_error_envelope_v1(decode_error_envelope_v1(canonical)) == canonical


def test_error_envelope_codec_emits_one_exact_golden_shape() -> None:
    canonical = encode_error_envelope_v1(_root_error())

    assert canonical == (
        b'{"category":"invalid","causation_id":null,'
        b'"correlation_id":{"namespace":"message","value":"request"},'
        b'"observation_state":"observed","occurred_at":"2026-07-27T00:00:00.000001Z",'
        b'"operation_id":null,"process_id":null,"reason_code":"REPLAY_OPERATION_NOT_FOUND",'
        b'"recovery_hint":"Verify the historical operation identity or submit a newly '
        b'authorized replay-derived command.",'
        b'"request_message_id":{"namespace":"message","value":"request"},'
        b'"retry_after_ms":null,"retryable":false,'
        b'"safe_message":"Historical operation was not found.",'
        b'"schema_name":"trade.error","schema_version":1}'
    )


def test_error_envelope_codec_preserves_child_causation_and_optional_links() -> None:
    error = ErrorEnvelope(
        schema_name="trade.error",
        schema_version=1,
        reason_code="PROCESS_BLOCKED",
        category=ErrorCategory.BLOCKED,
        observation_state=ObservationState.OBSERVED,
        retryable=False,
        retry_after_ms=None,
        request_message_id=_id("message", "child"),
        correlation_id=_id("message", "root"),
        causation_id=_id("message", "parent"),
        operation_id=_id("operation", "op-1"),
        process_id=_id("process", "process-1"),
        occurred_at=_instant(),
        safe_message="Process is blocked.",
        recovery_hint="Inspect the owner state.",
    )

    assert decode_error_envelope_v1(encode_error_envelope_v1(error)) == error


def test_clock_unavailable_is_the_only_clockless_codec_product() -> None:
    request = _id("message", "request")
    error = make_admission_error(
        reason_code="REPLAY_AUDIT_CLOCK_UNAVAILABLE",
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        occurred_at=None,
        retry_after_ms=100,
        safe_message="Trusted wall clock unavailable.",
    )

    canonical = encode_error_envelope_v1(error)

    assert b'"occurred_at":null' in canonical
    assert decode_error_envelope_v1(canonical) == error


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_name", "trade.error.v2"),
        ("schema_version", 2),
        ("schema_version", True),
        ("category", "mystery"),
        ("observation_state", "missing"),
        ("retryable", 1),
        ("retry_after_ms", True),
        ("safe_message", 7),
        ("occurred_at", "2026-07-27T00:00:00Z"),
        ("occurred_at", "2026-07-27T00:00:00.000000+00:00"),
        ("occurred_at", "2026-07-27T00:00:60.000000Z"),
    ],
)
def test_error_envelope_decoder_rejects_wrong_field_types_values_and_instants(
    field: str,
    value: object,
) -> None:
    payload = json.loads(encode_error_envelope_v1(_root_error()))
    payload[field] = value

    _assert_schema_error(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def test_error_envelope_decoder_rejects_missing_and_unknown_fields() -> None:
    payload = json.loads(encode_error_envelope_v1(_root_error()))
    missing = dict(payload)
    missing.pop("safe_message")
    unknown = {**payload, "extra": "forbidden"}

    _assert_schema_error(json.dumps(missing, sort_keys=True, separators=(",", ":")).encode())
    _assert_schema_error(json.dumps(unknown, sort_keys=True, separators=(",", ":")).encode())


def test_error_envelope_decoder_preserves_structural_scanner_errors() -> None:
    valid = encode_error_envelope_v1(_root_error())
    duplicate = valid.replace(
        b'{"category":"invalid"',
        b'{"category":"invalid","\\u0063ategory":"invalid"',
        1,
    )

    with pytest.raises(CanonicalJsonError) as raised:
        decode_error_envelope_v1(duplicate)

    assert raised.value.code is CanonicalJsonErrorCode.DUPLICATE_KEY


def test_error_envelope_decoder_rejects_one_byte_identity_tamper() -> None:
    canonical = encode_error_envelope_v1(_root_error())
    tampered = canonical.replace(
        b'"correlation_id":{"namespace":"message","value":"request"}',
        b'"correlation_id":{"namespace":"message","value":"different"}',
        1,
    )

    _assert_schema_error(tampered)


def test_error_envelope_codec_public_boundary_rejects_wrong_types() -> None:
    with pytest.raises(TypeError, match="ErrorEnvelope"):
        encode_error_envelope_v1(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="bytes"):
        decode_error_envelope_v1("{}")  # type: ignore[arg-type]
