from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

import pytest

from trade.kernel.digest import ContentDigest
from trade.kernel.envelope import Envelope, EnvelopeMeta
from trade.kernel.errors import ContractErrorCode, ContractViolation
from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.result import Result
from trade.kernel.time import Deadline, DurationMs, UtcInstant

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "value",
    ["a", "legacy.job_run", "a" * 64, "0", "capture-artifact", "study_result"],
)
def test_identifier_namespace_accepts_exact_grammar(value: str) -> None:
    assert IdNamespace(value).value == value


@pytest.mark.parametrize(
    "value",
    ["", "a" * 65, "UPPER", "space value", "a:b", "数据", ".\n"],
)
def test_identifier_namespace_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        IdNamespace(value)


def test_opaque_identifier_is_bounded_explicit_and_frozen() -> None:
    namespace = IdNamespace("legacy.job_run")
    identity = OpaqueId(namespace, "!" + "x" * 126 + "~")

    assert identity.to_dict() == {
        "namespace": "legacy.job_run",
        "value": "!" + "x" * 126 + "~",
    }
    with pytest.raises(FrozenInstanceError):
        identity.value = "other"  # type: ignore[misc]

    for value in ("", "x" * 129, "contains space", "\t", "数据", "\x7f"):
        with pytest.raises(ValueError):
            OpaqueId(namespace, value)


def test_generated_opaque_identifier_is_uuid4_without_ordering() -> None:
    first = OpaqueId.generate(IdNamespace("message"))
    second = OpaqueId.generate(IdNamespace("message"))

    assert first != second
    assert first.value[14] == "4"
    with pytest.raises(TypeError):
        _ = first < second  # type: ignore[operator]


@pytest.mark.parametrize(
    ("wire", "microsecond"),
    [
        ("0001-01-01T00:00:00.000000Z", 0),
        ("2026-07-27T01:02:03.000001Z", 1),
        ("2026-07-27T01:02:59.999999Z", 999_999),
        ("9999-12-31T23:59:59.999999Z", 999_999),
    ],
)
def test_utc_instant_uses_one_exact_wire_form(wire: str, microsecond: int) -> None:
    instant = UtcInstant.from_wire(wire)

    assert instant.value.microsecond == microsecond
    assert instant.to_wire() == wire


@pytest.mark.parametrize(
    "wire",
    [
        "2026-07-27T01:02:03+00:00",
        "2026-07-27T01:02:03Z",
        "2026-07-27T01:02:03.0Z",
        "2026-07-27T01:02:03.00000Z",
        "2026-07-27T01:02:03.0000000Z",
        "2026-07-27T01:02:60.000000Z",
        "0000-01-01T00:00:00.000000Z",
        "10000-01-01T00:00:00.000000Z",
    ],
)
def test_utc_instant_rejects_alternate_or_invalid_wire_values(wire: str) -> None:
    with pytest.raises(ValueError):
        UtcInstant.from_wire(wire)


class _NonZeroOffset(tzinfo):
    def utcoffset(self, _value: datetime | None) -> timedelta:
        return timedelta(minutes=1)

    def dst(self, _value: datetime | None) -> timedelta:
        return timedelta(0)


def test_utc_instant_constructor_rejects_naive_and_non_zero_offset() -> None:
    with pytest.raises(ValueError):
        UtcInstant(datetime(2026, 7, 27))
    with pytest.raises(ValueError):
        UtcInstant(datetime(2026, 7, 27, tzinfo=_NonZeroOffset()))

    original = datetime(2026, 7, 27, 1, 2, 3, 456789, tzinfo=timezone.utc)
    assert UtcInstant(original).value is original


@pytest.mark.parametrize("value", [1, 86_400_000])
def test_duration_accepts_exact_boundaries(value: int) -> None:
    assert DurationMs(value).value == value


@pytest.mark.parametrize("value", [0, 86_400_001, -1, True, 1.0])
def test_duration_rejects_out_of_range_or_non_integer(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        DurationMs(value)  # type: ignore[arg-type]


def test_deadline_uses_monotonic_time_after_admission() -> None:
    started_at = UtcInstant.from_wire("2026-07-27T00:00:00.000000Z")
    deadline = Deadline.from_duration(
        wall_clock_started_at=started_at,
        monotonic_started_at=100.0,
        duration=DurationMs(2_500),
    )

    assert deadline.wall_clock_expires_at.to_wire() == "2026-07-27T00:00:02.500000Z"
    assert deadline.remaining_ms(100.0) == 2_500
    assert deadline.remaining_ms(101.9999) == 501
    assert deadline.remaining_ms(102.5) == 0
    assert deadline.is_expired(10_000.0)


def test_content_digest_is_exact_and_algorithm_qualified() -> None:
    digest = ContentDigest.from_bytes(b"trade")

    assert digest == ContentDigest("sha256", digest.value)
    assert digest.to_dict() == {"algorithm": "sha256", "value": digest.value}
    with pytest.raises(ValueError):
        ContentDigest("sha512", "0" * 64)
    with pytest.raises(ValueError):
        ContentDigest("sha256", "A" * 64)
    with pytest.raises(ValueError):
        ContentDigest("sha256", "0" * 63)


def test_contract_violation_is_closed_bounded_and_has_no_live_cause() -> None:
    violation = ContractViolation(ContractErrorCode.INVALID_VALUE, "safe detail")

    assert violation.to_dict() == {"code": "invalid_value", "detail": "safe detail"}
    assert violation.__cause__ is None
    assert violation.__context__ is None
    assert ContractViolation(ContractErrorCode.OUT_OF_BOUNDS, "").detail == ""
    assert (
        len(ContractViolation(ContractErrorCode.OUT_OF_BOUNDS, "x" * 1_024).detail.encode())
        == 1_024
    )
    with pytest.raises(ValueError):
        ContractViolation(ContractErrorCode.OUT_OF_BOUNDS, "x" * 1_025)
    assert (
        len(ContractViolation(ContractErrorCode.OUT_OF_BOUNDS, "界" * 341).detail.encode()) == 1023
    )


def test_result_requires_exactly_one_explicit_branch_without_truthiness() -> None:
    success = Result[int, ContractViolation].ok(0)
    failure = Result[int, ContractViolation].err(
        ContractViolation(ContractErrorCode.INVALID_VALUE, "invalid")
    )
    optional_success = Result[None, ContractViolation].ok(None)

    assert success.is_ok and not success.is_err and success.value == 0
    assert failure.is_err and not failure.is_ok
    assert failure.error.code is ContractErrorCode.INVALID_VALUE
    assert optional_success.value is None
    with pytest.raises(ValueError):
        _ = success.error
    with pytest.raises(ValueError):
        _ = failure.value
    with pytest.raises(TypeError):
        bool(success)
    with pytest.raises(ValueError):
        Result[int, str]()
    with pytest.raises(ValueError):
        Result(value=1, error="error")


def _message(value: str) -> OpaqueId:
    return OpaqueId(IdNamespace("message"), value)


def test_envelope_root_child_and_redelivery_causality() -> None:
    created_at = UtcInstant.from_wire("2026-07-27T00:00:00.000000Z")
    root = EnvelopeMeta.root(
        schema_name="capture.request",
        schema_version=1,
        envelope_created_at=created_at,
        message_id=_message("root"),
    )
    child = EnvelopeMeta.child(
        schema_name="dataset.build",
        schema_version=1,
        envelope_created_at=created_at,
        parent=root,
        message_id=_message("child"),
    )
    envelope = Envelope(meta=child, payload=("dataset", 1))

    assert root.correlation_id == root.message_id
    assert root.causation_id is None
    assert child.correlation_id == root.correlation_id
    assert child.causation_id == root.message_id
    assert envelope.payload == ("dataset", 1)
    assert Envelope(meta=child, payload=envelope.payload).meta == child


def test_envelope_rejects_invalid_causality_schema_and_metadata() -> None:
    created_at = UtcInstant.from_wire("2026-07-27T00:00:00.000000Z")
    with pytest.raises(ValueError):
        EnvelopeMeta(
            schema_name="capture.request",
            schema_version=1,
            message_id=_message("message"),
            correlation_id=_message("other"),
            causation_id=None,
            envelope_created_at=created_at,
        )
    with pytest.raises(ValueError):
        EnvelopeMeta(
            schema_name="Capture Request",
            schema_version=1,
            message_id=_message("message"),
            correlation_id=_message("message"),
            causation_id=None,
            envelope_created_at=created_at,
        )
    with pytest.raises(ValueError):
        EnvelopeMeta.root(
            schema_name="capture.request",
            schema_version=0,
            envelope_created_at=created_at,
            message_id=_message("message"),
        )
    with pytest.raises(ValueError):
        EnvelopeMeta.child(
            schema_name="dataset.build",
            schema_version=1,
            envelope_created_at=created_at,
            parent=EnvelopeMeta.root(
                schema_name="capture.request",
                schema_version=1,
                envelope_created_at=created_at,
                message_id=_message("same"),
            ),
            message_id=_message("same"),
        )


def test_kernel_has_exact_module_allowlist_and_no_aggregate_exports() -> None:
    kernel_root = REPO_ROOT / "src/trade/kernel"
    modules = {path.stem for path in kernel_root.glob("*.py") if path.name != "__init__.py"}

    assert modules == {"ids", "time", "digest", "errors", "result", "envelope"}
    assert not (kernel_root / "refs.py").exists()
    package = importlib.import_module("trade.kernel")
    assert package.__dict__.keys().isdisjoint(
        {"OpaqueId", "UtcInstant", "ContentDigest", "Result", "Envelope"}
    )


def test_kernel_imports_are_standard_library_only_and_side_effect_free() -> None:
    probe = """
import importlib
import json
import sys

before = set(sys.modules)
for name in ("ids", "time", "digest", "errors", "result", "envelope"):
    importlib.import_module(f"trade.kernel.{name}")
after = set(sys.modules)
forbidden = sorted(
    name for name in after - before
    if name == "trade_py"
    or name.startswith(("trade_py.", "trade_web", "fastapi", "pydantic", "pandas", "sqlalchemy"))
)
print(json.dumps({"forbidden": forbidden, "modules": sorted(after - before)}))
"""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT / "src",
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["forbidden"] == []
