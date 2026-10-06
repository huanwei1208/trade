from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, is_dataclass
from enum import Enum
from typing import Generic, NoReturn, TypeVar

from trade.kernel.digest import ContentDigest
from trade.kernel.envelope import EnvelopeMeta
from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import Deadline
from trade.platform.contracts.actor import (
    ActorAssurance,
    ActorContext,
    IdempotencySubjectV1,
    PolicyRefV1,
)

__all__ = [
    "CanonicalJsonError",
    "CanonicalJsonErrorCode",
    "CodecContentPolicy",
    "CommandEnvelope",
    "FingerprintDomain",
    "FingerprintKeySetV1",
    "FingerprintV1",
    "FrozenCodecRegistry",
    "OwnerCodecDescriptor",
    "PayloadPurpose",
    "QueryEnvelope",
    "ReplayAdmissionV1",
    "ReplayContextV1",
    "canonical_idempotency_subject_bytes",
    "decode_bounded_json_v1",
    "derive_command_fingerprint",
    "derive_idempotency_fingerprint",
    "encode_canonical_json_v1",
    "frame_hmac_components",
]

_SCHEMA_NAME_PATTERN = re.compile(r"[a-z0-9._-]{1,96}", re.ASCII)
_TOKEN_PATTERN = re.compile(r"[a-z0-9._:-]{1,96}", re.ASCII)
_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)
_MAX_SCHEMA_VERSION = 2_147_483_647
_MAX_KEY_SET_GENERATION = 9_223_372_036_854_775_807
_MAX_CANONICAL_BYTES = 65_536
_MAX_JSON_CONTAINER_DEPTH = 8
_MAX_JSON_STRING_BYTES = 2_048
_MAX_JSON_INTEGER = 9_999_999_999_999_999_999
_MAX_JSON_INTEGER_DIGITS = 19
_MAX_JSON_CONTAINER_ITEMS = 100
_MAX_JSON_AGGREGATE_ITEMS = 1_024
_MAX_JSON_VALUE_NODES = 2_048
_MIN_SECRET_BYTES = 32
_MAX_RETAINED_KEY_VERSIONS = 3
_JSON_WHITESPACE = frozenset(" \t\r\n")
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_SHORT_ESCAPE_VALUES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
_CANONICAL_CONTROL_ESCAPES = {
    0x08: b"\\b",
    0x09: b"\\t",
    0x0A: b"\\n",
    0x0C: b"\\f",
    0x0D: b"\\r",
}

T = TypeVar("T")


class CanonicalJsonErrorCode(str, Enum):
    RAW_BYTES_EXCEEDED = "raw_bytes_exceeded"
    INVALID_UTF8 = "invalid_utf8"
    BOM_FORBIDDEN = "bom_forbidden"
    INVALID_SYNTAX = "invalid_syntax"
    DUPLICATE_KEY = "duplicate_key"
    INVALID_SURROGATE = "invalid_surrogate"
    STRING_BYTES_EXCEEDED = "string_bytes_exceeded"
    INVALID_INTEGER = "invalid_integer"
    INVALID_SCHEMA = "invalid_schema"
    CONTAINER_DEPTH_EXCEEDED = "container_depth_exceeded"
    CONTAINER_ITEMS_EXCEEDED = "container_items_exceeded"
    AGGREGATE_ITEMS_EXCEEDED = "aggregate_items_exceeded"
    VALUE_NODES_EXCEEDED = "value_nodes_exceeded"
    UNSUPPORTED_VALUE = "unsupported_value"
    OUTPUT_BYTES_EXCEEDED = "output_bytes_exceeded"


class CanonicalJsonError(ValueError):
    __slots__ = ("code",)

    def __init__(self, code: CanonicalJsonErrorCode) -> None:
        if not isinstance(code, CanonicalJsonErrorCode):
            raise TypeError("code must be CanonicalJsonErrorCode")
        self.code = code
        super().__init__(code.value)


class PayloadPurpose(str, Enum):
    COMMAND = "command"
    QUERY = "query"
    EVENT = "event"
    REFERENCE = "reference"
    PROJECTION = "projection"


class CodecContentPolicy(str, Enum):
    INLINE_CONTRACT = "inline_contract"
    IMMUTABLE_REF_ONLY = "immutable_ref_only"


class FingerprintDomain(str, Enum):
    COMMAND = "trade.command.v1"
    IDEMPOTENCY = "trade.idempotency.v1"


@dataclass(frozen=True, slots=True)
class OwnerCodecDescriptor:
    owner_namespace: IdNamespace
    schema_name: str
    schema_version: int
    payload_purpose: PayloadPurpose
    max_canonical_bytes: int
    content_policy: CodecContentPolicy
    codec_identity: ContentDigest

    def __post_init__(self) -> None:
        if not isinstance(self.owner_namespace, IdNamespace):
            raise TypeError("owner_namespace must be IdNamespace")
        if (
            not isinstance(self.schema_name, str)
            or _SCHEMA_NAME_PATTERN.fullmatch(self.schema_name) is None
        ):
            raise ValueError(
                "schema_name must be 1-96 ASCII lower-case letters, digits, '.', '_' or '-'"
            )
        _positive_version(self.schema_version, field_name="schema_version")
        if not isinstance(self.payload_purpose, PayloadPurpose):
            raise TypeError("payload_purpose must be PayloadPurpose")
        if not isinstance(self.max_canonical_bytes, int) or isinstance(
            self.max_canonical_bytes, bool
        ):
            raise TypeError("max_canonical_bytes must be an integer")
        if not 1 <= self.max_canonical_bytes <= _MAX_CANONICAL_BYTES:
            raise ValueError("max_canonical_bytes must be in 1..65,536")
        if not isinstance(self.content_policy, CodecContentPolicy):
            raise TypeError("content_policy must be CodecContentPolicy")
        if not isinstance(self.codec_identity, ContentDigest):
            raise TypeError("codec_identity must be ContentDigest")

    @property
    def registry_key(self) -> tuple[str, str, int, str]:
        return (
            self.owner_namespace.value,
            self.schema_name,
            self.schema_version,
            self.payload_purpose.value,
        )


@dataclass(frozen=True, slots=True)
class FrozenCodecRegistry:
    descriptors: tuple[OwnerCodecDescriptor, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.descriptors, tuple):
            raise TypeError("descriptors must be a tuple")
        if any(not isinstance(item, OwnerCodecDescriptor) for item in self.descriptors):
            raise TypeError("registry entries must be OwnerCodecDescriptor")
        keys = tuple(item.registry_key for item in self.descriptors)
        if len(keys) != len(set(keys)):
            raise ValueError("owner codec registry contains a duplicate descriptor key")
        if keys != tuple(sorted(keys)):
            raise ValueError("owner codec descriptors must be sorted by registry key before freeze")

    @classmethod
    def freeze(cls, descriptors: tuple[OwnerCodecDescriptor, ...]) -> FrozenCodecRegistry:
        if not isinstance(descriptors, tuple):
            raise TypeError("descriptors must be a tuple")
        return cls(tuple(sorted(descriptors, key=lambda item: item.registry_key)))

    def resolve(
        self,
        *,
        owner_namespace: IdNamespace,
        schema_name: str,
        schema_version: int,
        payload_purpose: PayloadPurpose,
    ) -> OwnerCodecDescriptor | None:
        key = (
            owner_namespace.value,
            schema_name,
            schema_version,
            payload_purpose.value,
        )
        return next((item for item in self.descriptors if item.registry_key == key), None)


@dataclass(frozen=True, slots=True)
class FingerprintV1:
    algorithm: str
    domain: FingerprintDomain
    key_version: int
    value: str

    def __post_init__(self) -> None:
        if self.algorithm != "hmac-sha256-v1":
            raise ValueError("fingerprint algorithm must be 'hmac-sha256-v1'")
        if not isinstance(self.domain, FingerprintDomain):
            raise TypeError("fingerprint domain must be FingerprintDomain")
        _positive_version(self.key_version, field_name="key_version")
        if not isinstance(self.value, str) or _FINGERPRINT_PATTERN.fullmatch(self.value) is None:
            raise ValueError("fingerprint value must be 64 lower-case hexadecimal characters")


@dataclass(frozen=True, slots=True)
class FingerprintKeySetV1:
    key_set_generation: int
    active_write_version: int
    retained_read_versions: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.key_set_generation, int) or isinstance(
            self.key_set_generation, bool
        ):
            raise TypeError("key_set_generation must be an integer")
        if not 1 <= self.key_set_generation <= _MAX_KEY_SET_GENERATION:
            raise ValueError("key_set_generation is outside the v1 range")
        _positive_version(self.active_write_version, field_name="active_write_version")
        if not isinstance(self.retained_read_versions, tuple):
            raise TypeError("retained_read_versions must be a tuple")
        if len(self.retained_read_versions) > _MAX_RETAINED_KEY_VERSIONS:
            raise ValueError("at most three retained read-only key versions are allowed")
        for version in self.retained_read_versions:
            _positive_version(version, field_name="retained key version")
        if self.retained_read_versions != tuple(sorted(set(self.retained_read_versions))):
            raise ValueError("retained key versions must be sorted and unique")
        if self.active_write_version in self.retained_read_versions:
            raise ValueError("active write version cannot also be retained read-only")

    @property
    def candidate_versions(self) -> tuple[int, ...]:
        return (self.active_write_version, *self.retained_read_versions)


@dataclass(frozen=True, slots=True)
class CommandEnvelope(Generic[T]):
    meta: EnvelopeMeta
    actor: ActorContext
    deadline: Deadline
    codec: OwnerCodecDescriptor
    payload: T
    canonical_payload: bytes

    def __post_init__(self) -> None:
        _validate_typed_envelope(
            meta=self.meta,
            actor=self.actor,
            deadline=self.deadline,
            codec=self.codec,
            payload=self.payload,
            canonical_payload=self.canonical_payload,
            expected_purpose=PayloadPurpose.COMMAND,
        )
        if not self.actor.can_submit_mutation:
            raise ValueError("command envelope requires a verified authenticated or system actor")


@dataclass(frozen=True, slots=True)
class QueryEnvelope(Generic[T]):
    meta: EnvelopeMeta
    actor: ActorContext
    deadline: Deadline
    codec: OwnerCodecDescriptor
    payload: T
    canonical_payload: bytes

    def __post_init__(self) -> None:
        _validate_typed_envelope(
            meta=self.meta,
            actor=self.actor,
            deadline=self.deadline,
            codec=self.codec,
            payload=self.payload,
            canonical_payload=self.canonical_payload,
            expected_purpose=PayloadPurpose.QUERY,
        )


@dataclass(frozen=True, slots=True)
class ReplayContextV1:
    schema_version: int
    replay_request_message_id: OpaqueId
    replay_request_correlation_id: OpaqueId
    replay_request_causation_id: OpaqueId | None
    historical_message_id: OpaqueId
    historical_actor: ActorContext
    replay_initiator: ActorContext
    replay_policy: PolicyRefV1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("ReplayContextV1 schema_version must be 1")
        _validate_causal_tuple(
            message_id=self.replay_request_message_id,
            correlation_id=self.replay_request_correlation_id,
            causation_id=self.replay_request_causation_id,
            field_prefix="replay request",
        )
        if not isinstance(self.historical_message_id, OpaqueId):
            raise TypeError("historical_message_id must be OpaqueId")
        if not isinstance(self.historical_actor, ActorContext):
            raise TypeError("historical_actor must be ActorContext")
        if self.historical_actor.assurance is not ActorAssurance.UNVERIFIED:
            raise ValueError("historical replay actor must remain unverified attribution")
        if not isinstance(self.replay_initiator, ActorContext):
            raise TypeError("replay_initiator must be ActorContext")
        if not self.replay_initiator.can_submit_mutation:
            raise ValueError("replay initiator must be a verified authenticated or system actor")
        if not isinstance(self.replay_policy, PolicyRefV1):
            raise TypeError("replay_policy must be PolicyRefV1")


@dataclass(frozen=True, slots=True)
class ReplayAdmissionV1:
    schema_version: int
    context: ReplayContextV1
    historical_message_id: OpaqueId
    historical_correlation_id: OpaqueId
    historical_causation_id: OpaqueId | None
    historical_envelope_digest: ContentDigest
    historical_operation_id: OpaqueId
    current_subject: IdempotencySubjectV1
    deadline: Deadline

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("ReplayAdmissionV1 schema_version must be 1")
        if not isinstance(self.context, ReplayContextV1):
            raise TypeError("context must be ReplayContextV1")
        _validate_causal_tuple(
            message_id=self.historical_message_id,
            correlation_id=self.historical_correlation_id,
            causation_id=self.historical_causation_id,
            field_prefix="historical envelope",
        )
        if self.historical_message_id != self.context.historical_message_id:
            raise ValueError("historical message identity must equal ReplayContextV1 attribution")
        if not isinstance(self.historical_envelope_digest, ContentDigest):
            raise TypeError("historical_envelope_digest must be ContentDigest")
        if not isinstance(self.historical_operation_id, OpaqueId):
            raise TypeError("historical_operation_id must be OpaqueId")
        if not isinstance(self.current_subject, IdempotencySubjectV1):
            raise TypeError("current_subject must be IdempotencySubjectV1")
        initiator = self.context.replay_initiator
        if (
            self.current_subject.principal_kind is not initiator.principal_kind
            or self.current_subject.principal_id != initiator.principal_id
        ):
            raise ValueError("current subject must identify the verified replay initiator")
        if not isinstance(self.deadline, Deadline):
            raise TypeError("deadline must be Deadline")


@dataclass(slots=True)
class _JsonScanFrame:
    kind: str
    state: str
    item_count: int = 0
    decoded_keys: set[str] | None = None


class _CanonicalJsonScanner:
    __slots__ = (
        "_aggregate_items",
        "_frames",
        "_index",
        "_root_complete",
        "_root_started",
        "_text",
        "_value_nodes",
    )

    def __init__(self, text: str) -> None:
        self._text = text
        self._index = 0
        self._frames: list[_JsonScanFrame] = []
        self._root_started = False
        self._root_complete = False
        self._aggregate_items = 0
        self._value_nodes = 0

    def scan(self) -> None:
        while True:
            self._skip_whitespace()
            if not self._frames:
                if not self._root_started:
                    if self._at_end:
                        _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)
                    self._root_started = True
                    self._scan_value()
                    continue
                if not self._root_complete or not self._at_end:
                    _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)
                return

            frame = self._frames[-1]
            if frame.kind == "array":
                self._scan_array_state(frame)
            else:
                self._scan_object_state(frame)

    @property
    def _at_end(self) -> bool:
        return self._index >= len(self._text)

    def _skip_whitespace(self) -> None:
        while not self._at_end and self._text[self._index] in _JSON_WHITESPACE:
            self._index += 1

    def _scan_array_state(self, frame: _JsonScanFrame) -> None:
        if frame.state == "first_or_end":
            if self._peek("]"):
                self._close_container("]")
                return
            frame.state = "value"

        if frame.state == "value":
            self._register_container_item(frame)
            frame.state = "comma_or_end"
            self._scan_value()
            return

        if self._consume(","):
            frame.state = "value"
            return
        if self._peek("]"):
            self._close_container("]")
            return
        _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)

    def _scan_object_state(self, frame: _JsonScanFrame) -> None:
        if frame.state == "first_key_or_end":
            if self._peek("}"):
                self._close_container("}")
                return
            self._scan_object_key(frame)
            return

        if frame.state == "key":
            self._scan_object_key(frame)
            return

        if frame.state == "colon":
            if not self._consume(":"):
                _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)
            frame.state = "value"
            return

        if frame.state == "value":
            frame.state = "comma_or_end"
            self._scan_value()
            return

        if self._consume(","):
            frame.state = "key"
            return
        if self._peek("}"):
            self._close_container("}")
            return
        _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)

    def _scan_object_key(self, frame: _JsonScanFrame) -> None:
        if self._at_end or self._text[self._index] != '"':
            _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)
        key = self._scan_string()
        self._register_container_item(frame)
        if frame.decoded_keys is None:
            raise AssertionError("object scanner frame must own decoded keys")
        if key in frame.decoded_keys:
            _raise_json(CanonicalJsonErrorCode.DUPLICATE_KEY)
        frame.decoded_keys.add(key)
        frame.state = "colon"

    def _register_container_item(self, frame: _JsonScanFrame) -> None:
        frame.item_count += 1
        if frame.item_count > _MAX_JSON_CONTAINER_ITEMS:
            _raise_json(CanonicalJsonErrorCode.CONTAINER_ITEMS_EXCEEDED)
        self._aggregate_items += 1
        if self._aggregate_items > _MAX_JSON_AGGREGATE_ITEMS:
            _raise_json(CanonicalJsonErrorCode.AGGREGATE_ITEMS_EXCEEDED)

    def _scan_value(self) -> None:
        self._value_nodes += 1
        if self._value_nodes > _MAX_JSON_VALUE_NODES:
            _raise_json(CanonicalJsonErrorCode.VALUE_NODES_EXCEEDED)
        if self._at_end:
            _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)

        token = self._text[self._index]
        if token == '"':
            self._scan_string()
            self._complete_scalar()
            return
        if token == "{":
            self._start_container("object")
            return
        if token == "[":
            self._start_container("array")
            return
        if token == "t":
            self._scan_literal("true")
            self._complete_scalar()
            return
        if token == "f":
            self._scan_literal("false")
            self._complete_scalar()
            return
        if token == "n":
            self._scan_literal("null")
            self._complete_scalar()
            return
        if "0" <= token <= "9":
            self._scan_integer()
            self._complete_scalar()
            return
        if token in "-+." or token in "NI":
            _raise_json(CanonicalJsonErrorCode.INVALID_INTEGER)
        _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)

    def _start_container(self, kind: str) -> None:
        depth = len(self._frames) + 1
        if depth > _MAX_JSON_CONTAINER_DEPTH:
            _raise_json(CanonicalJsonErrorCode.CONTAINER_DEPTH_EXCEEDED)
        self._index += 1
        if kind == "array":
            self._frames.append(_JsonScanFrame(kind="array", state="first_or_end"))
        else:
            self._frames.append(
                _JsonScanFrame(
                    kind="object",
                    state="first_key_or_end",
                    decoded_keys=set(),
                )
            )

    def _close_container(self, closing_token: str) -> None:
        if not self._consume(closing_token):
            _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)
        self._frames.pop()
        if not self._frames:
            self._root_complete = True

    def _complete_scalar(self) -> None:
        if not self._frames:
            self._root_complete = True

    def _scan_literal(self, literal: str) -> None:
        end = self._index + len(literal)
        if self._text[self._index : end] != literal:
            _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)
        self._index = end

    def _scan_integer(self) -> None:
        start = self._index
        if self._text[self._index] == "0":
            self._index += 1
            if not self._at_end and "0" <= self._text[self._index] <= "9":
                _raise_json(CanonicalJsonErrorCode.INVALID_INTEGER)
        else:
            while not self._at_end and "0" <= self._text[self._index] <= "9":
                self._index += 1
                if self._index - start > _MAX_JSON_INTEGER_DIGITS:
                    _raise_json(CanonicalJsonErrorCode.INVALID_INTEGER)
        if not self._at_end and self._text[self._index] in ".eE":
            _raise_json(CanonicalJsonErrorCode.INVALID_INTEGER)

    def _scan_string(self) -> str:
        self._index += 1
        decoded: list[str] = []
        decoded_bytes = 0
        while not self._at_end:
            value = self._text[self._index]
            self._index += 1
            if value == '"':
                return "".join(decoded)
            if value == "\\":
                value = self._scan_escape()
            elif ord(value) < 0x20:
                _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)
            elif _is_surrogate(value):
                _raise_json(CanonicalJsonErrorCode.INVALID_SURROGATE)
            decoded_bytes += len(value.encode("utf-8"))
            if decoded_bytes > _MAX_JSON_STRING_BYTES:
                _raise_json(CanonicalJsonErrorCode.STRING_BYTES_EXCEEDED)
            decoded.append(value)
        _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)

    def _scan_escape(self) -> str:
        if self._at_end:
            _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)
        escape = self._text[self._index]
        self._index += 1
        if escape in _SHORT_ESCAPE_VALUES:
            return _SHORT_ESCAPE_VALUES[escape]
        if escape != "u":
            _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)

        code_point = self._scan_hex_quad()
        if 0xDC00 <= code_point <= 0xDFFF:
            _raise_json(CanonicalJsonErrorCode.INVALID_SURROGATE)
        if 0xD800 <= code_point <= 0xDBFF:
            if self._text[self._index : self._index + 2] != "\\u":
                _raise_json(CanonicalJsonErrorCode.INVALID_SURROGATE)
            self._index += 2
            low = self._scan_hex_quad()
            if not 0xDC00 <= low <= 0xDFFF:
                _raise_json(CanonicalJsonErrorCode.INVALID_SURROGATE)
            code_point = 0x10000 + ((code_point - 0xD800) << 10) + (low - 0xDC00)
        return chr(code_point)

    def _scan_hex_quad(self) -> int:
        end = self._index + 4
        token = self._text[self._index : end]
        if len(token) != 4 or any(character not in _HEX_DIGITS for character in token):
            _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)
        self._index = end
        return int(token, 16)

    def _consume(self, token: str) -> bool:
        if self._peek(token):
            self._index += 1
            return True
        return False

    def _peek(self, token: str) -> bool:
        return not self._at_end and self._text[self._index] == token


def decode_bounded_json_v1(raw: bytes) -> object:
    if not isinstance(raw, bytes):
        raise TypeError("raw canonical JSON input must be bytes")
    if len(raw) > _MAX_CANONICAL_BYTES:
        _raise_json(CanonicalJsonErrorCode.RAW_BYTES_EXCEEDED)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _raise_json(CanonicalJsonErrorCode.INVALID_UTF8)
    if text.startswith("\ufeff"):
        _raise_json(CanonicalJsonErrorCode.BOM_FORBIDDEN)

    _CanonicalJsonScanner(text).scan()
    try:
        value = json.loads(
            text,
            parse_int=_bounded_parse_int,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except (json.JSONDecodeError, RecursionError):
        _raise_json(CanonicalJsonErrorCode.INVALID_SYNTAX)
    _validate_materialized_json(value)
    return value


def encode_canonical_json_v1(
    value: object,
    *,
    max_bytes: int = _MAX_CANONICAL_BYTES,
) -> bytes:
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool):
        raise TypeError("max_bytes must be an integer")
    if not 1 <= max_bytes <= _MAX_CANONICAL_BYTES:
        raise ValueError("max_bytes must be in 1..65,536")
    _validate_materialized_json(value)

    output = bytearray()
    actions: list[tuple[str, object]] = [("value", value)]
    while actions:
        action, item = actions.pop()
        if action == "raw":
            if not isinstance(item, bytes):
                raise AssertionError("canonical JSON raw action must contain bytes")
            _append_json_bytes(output, item, max_bytes=max_bytes)
            continue
        if action == "string":
            if not isinstance(item, str):
                raise AssertionError("canonical JSON string action must contain str")
            _append_json_bytes(output, _canonical_string_bytes(item), max_bytes=max_bytes)
            continue

        if item is None:
            _append_json_bytes(output, b"null", max_bytes=max_bytes)
        elif item is True:
            _append_json_bytes(output, b"true", max_bytes=max_bytes)
        elif item is False:
            _append_json_bytes(output, b"false", max_bytes=max_bytes)
        elif isinstance(item, int):
            _append_json_bytes(output, str(item).encode("ascii"), max_bytes=max_bytes)
        elif isinstance(item, str):
            _append_json_bytes(output, _canonical_string_bytes(item), max_bytes=max_bytes)
        elif isinstance(item, list):
            _append_json_bytes(output, b"[", max_bytes=max_bytes)
            scheduled: list[tuple[str, object]] = []
            for index, child in enumerate(item):
                if index:
                    scheduled.append(("raw", b","))
                scheduled.append(("value", child))
            scheduled.append(("raw", b"]"))
            actions.extend(reversed(scheduled))
        elif isinstance(item, dict):
            _append_json_bytes(output, b"{", max_bytes=max_bytes)
            scheduled = []
            for index, key in enumerate(sorted(item)):
                if index:
                    scheduled.append(("raw", b","))
                scheduled.extend(
                    (
                        ("string", key),
                        ("raw", b":"),
                        ("value", item[key]),
                    )
                )
            scheduled.append(("raw", b"}"))
            actions.extend(reversed(scheduled))
        else:
            _raise_json(CanonicalJsonErrorCode.UNSUPPORTED_VALUE)
    return bytes(output)


def _validate_materialized_json(root: object) -> None:
    aggregate_items = 0
    value_nodes = 0
    worklist: list[tuple[object, int]] = [(root, 0)]
    while worklist:
        value, parent_depth = worklist.pop()
        value_nodes += 1
        if value_nodes > _MAX_JSON_VALUE_NODES:
            _raise_json(CanonicalJsonErrorCode.VALUE_NODES_EXCEEDED)

        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, int):
            if not 0 <= value <= _MAX_JSON_INTEGER:
                _raise_json(CanonicalJsonErrorCode.INVALID_INTEGER)
            continue
        if isinstance(value, str):
            _validate_json_string(value)
            continue
        if not isinstance(value, (list, dict)):
            _raise_json(CanonicalJsonErrorCode.UNSUPPORTED_VALUE)

        depth = parent_depth + 1
        if depth > _MAX_JSON_CONTAINER_DEPTH:
            _raise_json(CanonicalJsonErrorCode.CONTAINER_DEPTH_EXCEEDED)
        item_count = len(value)
        if item_count > _MAX_JSON_CONTAINER_ITEMS:
            _raise_json(CanonicalJsonErrorCode.CONTAINER_ITEMS_EXCEEDED)
        aggregate_items += item_count
        if aggregate_items > _MAX_JSON_AGGREGATE_ITEMS:
            _raise_json(CanonicalJsonErrorCode.AGGREGATE_ITEMS_EXCEEDED)

        if isinstance(value, list):
            worklist.extend((item, depth) for item in reversed(value))
            continue
        for key in value:
            if not isinstance(key, str):
                _raise_json(CanonicalJsonErrorCode.UNSUPPORTED_VALUE)
            _validate_json_string(key)
        worklist.extend((value[key], depth) for key in reversed(sorted(value)))


def _validate_json_string(value: str) -> None:
    if any(_is_surrogate(character) for character in value):
        _raise_json(CanonicalJsonErrorCode.INVALID_SURROGATE)
    if len(value.encode("utf-8")) > _MAX_JSON_STRING_BYTES:
        _raise_json(CanonicalJsonErrorCode.STRING_BYTES_EXCEEDED)


def _canonical_string_bytes(value: str) -> bytes:
    encoded = bytearray(b'"')
    for character in value:
        code_point = ord(character)
        if code_point == 0x22:
            encoded.extend(b'\\"')
        elif code_point == 0x5C:
            encoded.extend(b"\\\\")
        elif code_point in _CANONICAL_CONTROL_ESCAPES:
            encoded.extend(_CANONICAL_CONTROL_ESCAPES[code_point])
        elif code_point < 0x20:
            encoded.extend(f"\\u00{code_point:02x}".encode("ascii"))
        else:
            encoded.extend(character.encode("utf-8"))
    encoded.extend(b'"')
    return bytes(encoded)


def _bounded_parse_int(token: str) -> int:
    if (
        len(token) > _MAX_JSON_INTEGER_DIGITS
        or not token
        or (token != "0" and (token[0] == "0" or not token.isascii()))
        or not token.isdecimal()
    ):
        _raise_json(CanonicalJsonErrorCode.INVALID_INTEGER)
    return int(token)


def _reject_json_number(_token: str) -> NoReturn:
    _raise_json(CanonicalJsonErrorCode.INVALID_INTEGER)


def _append_json_bytes(output: bytearray, value: bytes, *, max_bytes: int) -> None:
    if len(output) + len(value) > max_bytes:
        _raise_json(CanonicalJsonErrorCode.OUTPUT_BYTES_EXCEEDED)
    output.extend(value)


def _is_surrogate(value: str) -> bool:
    return 0xD800 <= ord(value) <= 0xDFFF


def _raise_json(code: CanonicalJsonErrorCode) -> NoReturn:
    raise CanonicalJsonError(code)


def frame_hmac_components(components: tuple[bytes, ...]) -> bytes:
    if not isinstance(components, tuple):
        raise TypeError("HMAC components must be a tuple")
    framed = bytearray()
    for component in components:
        if not isinstance(component, bytes):
            raise TypeError("HMAC components must be bytes")
        if len(component) > 0xFFFFFFFF:
            raise ValueError("HMAC component exceeds unsigned four-byte length")
        framed.extend(len(component).to_bytes(4, "big"))
        framed.extend(component)
    return bytes(framed)


def derive_command_fingerprint(
    *,
    secret: bytes,
    key_version: int,
    canonical_payload: bytes,
) -> FingerprintV1:
    return _derive_fingerprint(
        secret=secret,
        domain=FingerprintDomain.COMMAND,
        key_version=key_version,
        components=(FingerprintDomain.COMMAND.value.encode("ascii"), canonical_payload),
    )


def derive_idempotency_fingerprint(
    *,
    secret: bytes,
    key_version: int,
    subject: IdempotencySubjectV1,
    command_scope: str,
    raw_key: bytes,
) -> FingerprintV1:
    if not isinstance(subject, IdempotencySubjectV1):
        raise TypeError("subject must be IdempotencySubjectV1")
    if not isinstance(command_scope, str) or _TOKEN_PATTERN.fullmatch(command_scope) is None:
        raise ValueError("command_scope must be a bounded lower-case contract token")
    if not isinstance(raw_key, bytes):
        raise TypeError("raw_key must be bytes")
    return _derive_fingerprint(
        secret=secret,
        domain=FingerprintDomain.IDEMPOTENCY,
        key_version=key_version,
        components=(
            FingerprintDomain.IDEMPOTENCY.value.encode("ascii"),
            canonical_idempotency_subject_bytes(subject),
            command_scope.encode("utf-8"),
            raw_key,
        ),
    )


def canonical_idempotency_subject_bytes(subject: IdempotencySubjectV1) -> bytes:
    if not isinstance(subject, IdempotencySubjectV1):
        raise TypeError("subject must be IdempotencySubjectV1")

    def identity(value: OpaqueId) -> dict[str, str]:
        return {"namespace": value.namespace.value, "value": value.value}

    payload: dict[str, object] = {
        "delegated_subject_ids": [identity(item) for item in subject.delegated_subject_ids],
        "owner_namespace": subject.owner_namespace.value,
        "principal_id": identity(subject.principal_id),
        "principal_kind": subject.principal_kind.value,
        "schema_version": subject.schema_version,
        "tenant_id": identity(subject.tenant_id),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _derive_fingerprint(
    *,
    secret: bytes,
    domain: FingerprintDomain,
    key_version: int,
    components: tuple[bytes, ...],
) -> FingerprintV1:
    if not isinstance(secret, bytes):
        raise TypeError("fingerprint secret must be bytes")
    if len(secret) < _MIN_SECRET_BYTES:
        raise ValueError("fingerprint secret must contain at least 256 bits")
    _positive_version(key_version, field_name="key_version")
    value = hmac.new(secret, frame_hmac_components(components), hashlib.sha256).hexdigest()
    return FingerprintV1(
        algorithm="hmac-sha256-v1",
        domain=domain,
        key_version=key_version,
        value=value,
    )


def _validate_typed_envelope(
    *,
    meta: EnvelopeMeta,
    actor: ActorContext,
    deadline: Deadline,
    codec: OwnerCodecDescriptor,
    payload: object,
    canonical_payload: bytes,
    expected_purpose: PayloadPurpose,
) -> None:
    if not isinstance(meta, EnvelopeMeta):
        raise TypeError("meta must be EnvelopeMeta")
    if not isinstance(actor, ActorContext):
        raise TypeError("actor must be ActorContext")
    if not isinstance(deadline, Deadline):
        raise TypeError("deadline must be Deadline")
    if not isinstance(codec, OwnerCodecDescriptor):
        raise TypeError("codec must be OwnerCodecDescriptor")
    if codec.payload_purpose is not expected_purpose:
        raise ValueError(f"codec payload purpose must be {expected_purpose.value}")
    if meta.schema_name != codec.schema_name or meta.schema_version != codec.schema_version:
        raise ValueError("envelope schema identity must match the owner codec descriptor")
    parameters = getattr(type(payload), "__dataclass_params__", None)
    if not is_dataclass(payload) or parameters is None or not parameters.frozen:
        raise TypeError("envelope payload must be a frozen typed owner dataclass")
    if not isinstance(canonical_payload, bytes):
        raise TypeError("canonical_payload must be bytes")
    if len(canonical_payload) > codec.max_canonical_bytes:
        raise ValueError("canonical payload exceeds the owner codec byte limit")
    if not canonical_payload:
        raise ValueError("canonical payload must not be empty")


def _validate_causal_tuple(
    *,
    message_id: OpaqueId,
    correlation_id: OpaqueId,
    causation_id: OpaqueId | None,
    field_prefix: str,
) -> None:
    if not isinstance(message_id, OpaqueId):
        raise TypeError(f"{field_prefix} message_id must be OpaqueId")
    if not isinstance(correlation_id, OpaqueId):
        raise TypeError(f"{field_prefix} correlation_id must be OpaqueId")
    if causation_id is not None and not isinstance(causation_id, OpaqueId):
        raise TypeError(f"{field_prefix} causation_id must be OpaqueId or None")
    if causation_id is None and correlation_id != message_id:
        raise ValueError(f"root {field_prefix} correlation identity must equal message identity")
    if causation_id is not None and message_id in {correlation_id, causation_id}:
        raise ValueError(f"child {field_prefix} message identity must be new")


def _positive_version(value: int, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    if not 1 <= value <= _MAX_SCHEMA_VERSION:
        raise ValueError(f"{field_name} must be in 1..2,147,483,647")
    return value
