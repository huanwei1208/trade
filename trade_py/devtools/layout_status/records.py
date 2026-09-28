"""Bounded content-addressed JSON records for layout status."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final, NoReturn

from trade_py.devtools.layout_status.deadline import InvocationDeadline
from trade_py.devtools.layout_status.errors import LayoutStatusInvalid, invalid

SCHEMA_VERSION: Final = "trade.layout.record.v1"
RECORD_TYPES: Final = frozenset(
    {
        "layout_status_manifest",
        "consumer_inventory",
        "module_authority",
        "package_generation",
        "validation_report",
        "layout_selector_snapshot",
        "operation_status_snapshot",
        "prepared_evidence",
        "migration_evidence",
    }
)
_DIGEST_PREFIX: Final = "sha256:"
_OPEN_FLAGS: Final = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY_FLAGS: Final = _OPEN_FLAGS | getattr(os, "O_DIRECTORY", 0)
_LEAF_FLAGS: Final = _OPEN_FLAGS | getattr(os, "O_NONBLOCK", 0)
_MAX_JSON_DEPTH: Final = 64


@dataclass(frozen=True)
class ReaderLimits:
    max_records: int = 32
    max_depth: int = 8
    max_record_bytes: int = 256 * 1024
    max_aggregate_bytes: int = 4 * 1024 * 1024
    deadline_seconds: float = 5.0


_DEFAULT_LIMITS: Final = ReaderLimits()


@dataclass(frozen=True)
class RecordReference:
    name: str
    path: str
    digest: str


@dataclass(frozen=True)
class EvidenceRecord:
    record_type: str
    record_id: str
    references: tuple[RecordReference, ...]
    payload: dict[str, Any]
    record_digest: str
    path: str


@dataclass(frozen=True)
class EvidenceGraph:
    root: EvidenceRecord
    records: tuple[EvidenceRecord, ...]
    aggregate_bytes: int

    def by_type(self, record_type: str) -> tuple[EvidenceRecord, ...]:
        return tuple(item for item in self.records if item.record_type == record_type)

    def by_digest(self, digest: str) -> EvidenceRecord:
        for item in self.records:
            if item.record_digest == digest:
                return item
        raise invalid(
            "layout.status.reference_missing",
            "A selected record digest is not present in the explicit evidence graph.",
        )


class ExplicitRecordReader:
    """Read one finite graph rooted at an explicitly selected regular file."""

    def __init__(
        self,
        manifest: Path,
        *,
        limits: ReaderLimits = _DEFAULT_LIMITS,
        monotonic: Callable[[], float] = time.monotonic,
        deadline: InvocationDeadline | None = None,
    ) -> None:
        raw_manifest = os.fspath(manifest)
        if (
            contains_unsafe_text(raw_manifest)
            or not manifest.is_absolute()
            or any(part in {".", ".."} for part in manifest.parts)
        ):
            raise invalid(
                "layout.status.manifest_not_absolute",
                (
                    "TRADE_LAYOUT_STATUS_MANIFEST must be a normalized absolute path "
                    "without control characters."
                ),
            )
        self._manifest = manifest
        self._root = manifest.parent
        self._limits = limits
        self._deadline = deadline or InvocationDeadline(
            seconds=limits.deadline_seconds,
            monotonic=monotonic,
        )
        self._aggregate_bytes = 0

    @property
    def deadline(self) -> InvocationDeadline:
        return self._deadline

    def read(self) -> EvidenceGraph:
        pending: list[tuple[str, str | None, int]] = [(self._manifest.name, None, 0)]
        records: dict[str, EvidenceRecord] = {}
        record_ids: dict[str, str] = {}
        expected_digests: dict[str, str] = {}
        while pending:
            self._check_deadline()
            relative, expected_digest, depth = pending.pop()
            if depth > self._limits.max_depth:
                self._raise(
                    "layout.status.reference_depth",
                    "Evidence reference depth exceeds the limit of eight.",
                    relative,
                )
            previous = expected_digests.get(relative)
            if previous is not None:
                if expected_digest is not None and previous != expected_digest:
                    self._raise(
                        "layout.status.reference_conflict",
                        "One evidence path is referenced with conflicting digests.",
                        relative,
                    )
                continue
            if len(expected_digests) >= self._limits.max_records:
                self._raise(
                    "layout.status.record_count",
                    "Evidence graph exceeds the limit of 32 records.",
                    relative,
                )
            if expected_digest is not None:
                expected_digests[relative] = expected_digest
            else:
                expected_digests[relative] = ""
            payload = self._read_relative(relative)
            record = parse_record(payload, path=relative, deadline=self._deadline)
            if depth > 0 and record.references:
                self._raise(
                    "layout.status.non_root_references",
                    ("Version-one evidence records may be referenced only by the root manifest."),
                    relative,
                )
            if expected_digest is not None and record.record_digest != expected_digest:
                self._raise(
                    "layout.status.reference_digest",
                    "Referenced evidence digest does not match its record.",
                    relative,
                )
            existing = records.get(record.record_digest)
            if existing is not None and existing.path != relative:
                self._raise(
                    "layout.status.duplicate_digest",
                    "One evidence digest is stored under multiple explicit paths.",
                    relative,
                )
            prior_id_path = record_ids.get(record.record_id)
            if prior_id_path is not None and prior_id_path != relative:
                self._raise(
                    "layout.status.duplicate_record_id",
                    "Evidence record IDs must be unique within one explicit graph.",
                    relative,
                )
            record_ids[record.record_id] = relative
            records[record.record_digest] = record
            for reference in reversed(record.references):
                pending.append((reference.path, reference.digest, depth + 1))

        root = next((item for item in records.values() if item.path == self._manifest.name), None)
        if root is None or root.record_type != "layout_status_manifest":
            self._raise(
                "layout.status.root_type",
                "The selected root is not a layout status manifest.",
                self._manifest.name,
            )
        _assert_acyclic(records.values(), root.path, deadline=self._deadline)
        self._check_deadline()
        return EvidenceGraph(
            root=root,
            records=tuple(sorted(records.values(), key=lambda item: item.path)),
            aggregate_bytes=self._aggregate_bytes,
        )

    def _read_relative(self, relative: str) -> bytes:
        normalized = _validate_relative_path(relative)
        components = normalized.parts
        directory_fd: int | None = None
        try:
            directory_fd = _open_absolute_directory(self._root)
            for component in components[:-1]:
                next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            file_fd = os.open(components[-1], _LEAF_FLAGS, dir_fd=directory_fd)
            try:
                metadata = os.fstat(file_fd)
                if not stat.S_ISREG(metadata.st_mode):
                    self._raise(
                        "layout.status.not_regular",
                        "Every selected evidence record must be a regular file.",
                        relative,
                    )
                if metadata.st_size > self._limits.max_record_bytes:
                    self._raise(
                        "layout.status.record_size",
                        "One evidence record exceeds 256 KiB.",
                        relative,
                    )
                remaining = self._limits.max_aggregate_bytes - self._aggregate_bytes
                if metadata.st_size > remaining:
                    self._raise(
                        "layout.status.aggregate_size",
                        "Evidence input exceeds the aggregate 4 MiB budget.",
                        relative,
                    )
                chunks: list[bytes] = []
                consumed = 0
                while True:
                    self._check_deadline()
                    chunk = os.read(
                        file_fd, min(65_536, self._limits.max_record_bytes + 1 - consumed)
                    )
                    if not chunk:
                        break
                    chunks.append(chunk)
                    consumed += len(chunk)
                    if consumed > self._limits.max_record_bytes:
                        self._raise(
                            "layout.status.record_size",
                            "One evidence record exceeds 256 KiB.",
                            relative,
                        )
                    if self._aggregate_bytes + consumed > self._limits.max_aggregate_bytes:
                        self._raise(
                            "layout.status.aggregate_size",
                            "Evidence input exceeds the aggregate 4 MiB budget.",
                            relative,
                        )
                payload = b"".join(chunks)
            finally:
                os.close(file_fd)
        except LayoutStatusInvalid:
            raise
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise invalid(
                "layout.status.record_missing",
                "A selected evidence record is unavailable.",
                record=relative,
            ) from exc
        except OSError as exc:
            raise invalid(
                "layout.status.record_open",
                "A selected evidence record cannot be opened safely.",
                record=relative,
            ) from exc
        finally:
            if directory_fd is not None:
                os.close(directory_fd)
        self._aggregate_bytes += len(payload)
        self._check_deadline()
        return payload

    def _check_deadline(self) -> None:
        self._deadline.check()

    @staticmethod
    def _raise(code: str, message: str, record: str | None) -> NoReturn:
        raise invalid(code, message, record=record)


def parse_record(
    raw: bytes,
    *,
    path: str,
    deadline: InvocationDeadline | None = None,
) -> EvidenceRecord:
    _check(deadline)
    try:
        _validate_json_depth(raw, path=path, deadline=deadline)
        text = raw.decode("utf-8", "strict")
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise invalid(
            "layout.status.record_json",
            "A selected evidence record is not canonical finite JSON.",
            record=path,
        ) from exc
    if not isinstance(decoded, dict):
        raise invalid(
            "layout.status.record_shape",
            "Every evidence record must be a JSON object.",
            record=path,
        )
    expected = {
        "schema_version",
        "record_type",
        "record_id",
        "references",
        "payload",
        "record_digest",
    }
    if set(decoded) != expected:
        raise invalid(
            "layout.status.record_shape",
            "An evidence record has missing or unknown top-level fields.",
            record=path,
        )
    if decoded["schema_version"] != SCHEMA_VERSION:
        raise invalid(
            "layout.status.schema",
            "An evidence record uses an unsupported schema version.",
            record=path,
        )
    record_type = _required_string(decoded, "record_type", path)
    record_id = _required_string(decoded, "record_id", path)
    record_digest = _required_digest(decoded, "record_digest", path)
    if record_type not in RECORD_TYPES:
        raise invalid(
            "layout.status.record_type",
            "An evidence record uses an unsupported record type.",
            record=path,
        )
    raw_payload = decoded["payload"]
    if not isinstance(raw_payload, dict):
        raise invalid(
            "layout.status.record_shape",
            "Evidence record payload must be an object.",
            record=path,
        )
    references = _parse_references(decoded["references"], path)
    _check(deadline)
    try:
        canonical = canonical_record_digest(decoded)
        canonical_payload = canonical_json(decoded)
    except (RecursionError, ValueError) as exc:
        raise invalid(
            "layout.status.record_json",
            "A selected evidence record exceeds canonical JSON limits.",
            record=path,
        ) from exc
    if record_digest != canonical:
        raise invalid(
            "layout.status.record_digest",
            "Evidence record content does not match its canonical digest.",
            record=path,
        )
    if len(canonical_payload) > 256 * 1024:
        raise invalid(
            "layout.status.record_size",
            "Canonical evidence record exceeds 256 KiB.",
            record=path,
        )
    if raw not in {canonical_payload, canonical_payload + b"\n"}:
        raise invalid(
            "layout.status.record_canonical",
            "Evidence records must use canonical JSON encoding.",
            record=path,
        )
    _check(deadline)
    return EvidenceRecord(
        record_type=record_type,
        record_id=record_id,
        references=references,
        payload=dict(raw_payload),
        record_digest=record_digest,
        path=path,
    )


def canonical_record_digest(record: dict[str, Any]) -> str:
    content = dict(record)
    content.pop("record_digest", None)
    return _DIGEST_PREFIX + hashlib.sha256(canonical_json(content)).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _parse_references(value: Any, path: str) -> tuple[RecordReference, ...]:
    if not isinstance(value, list):
        raise invalid(
            "layout.status.record_shape",
            "Evidence references must be an array.",
            record=path,
        )
    references: list[RecordReference] = []
    names: set[str] = set()
    paths: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {"name", "path", "digest"}:
            raise invalid(
                "layout.status.record_shape",
                "Every evidence reference must contain name, path, and digest.",
                record=path,
            )
        name = _required_string(raw, "name", path)
        relative_value = raw.get("path")
        if not isinstance(relative_value, str) or not relative_value or len(relative_value) > 256:
            raise invalid(
                "layout.status.record_shape",
                "Evidence reference path must be a bounded non-empty string.",
                record=path,
            )
        relative = relative_value
        digest = _required_digest(raw, "digest", path)
        _validate_relative_path(relative)
        if name in names or relative in paths:
            raise invalid(
                "layout.status.reference_duplicate",
                "Evidence reference names and paths must be unique per record.",
                record=path,
            )
        names.add(name)
        paths.add(relative)
        references.append(RecordReference(name=name, path=relative, digest=digest))
    return tuple(sorted(references, key=lambda item: item.name))


def _validate_relative_path(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if (
        not raw
        or contains_unsafe_text(raw)
        or path.is_absolute()
        or "\\" in raw
        or any(part in {"", ".", ".."} for part in path.parts)
        or len(path.parts) > 16
        or len(raw.encode("utf-8")) > 512
    ):
        raise invalid(
            "layout.status.reference_path",
            "Evidence references must be bounded root-relative POSIX paths.",
            record=raw or None,
        )
    return path


def contains_unsafe_text(value: str) -> bool:
    """Reject terminal controls and unencodable surrogate code points."""

    return any(unicodedata.category(character) in {"Cc", "Cs"} for character in value)


def _required_string(value: dict[str, Any], key: str, path: str) -> str:
    result = value.get(key)
    if (
        not isinstance(result, str)
        or not result
        or len(result) > 256
        or contains_unsafe_text(result)
    ):
        raise invalid(
            "layout.status.record_shape",
            f"Evidence field {key} must be a bounded non-empty string.",
            record=path,
        )
    return result


def _required_digest(value: dict[str, Any], key: str, path: str) -> str:
    result = _required_string(value, key, path)
    suffix = result.removeprefix(_DIGEST_PREFIX)
    if not result.startswith(_DIGEST_PREFIX) or len(suffix) != 64:
        raise invalid(
            "layout.status.record_shape",
            f"Evidence field {key} must be a complete SHA-256 digest.",
            record=path,
        )
    try:
        int(suffix, 16)
    except ValueError as exc:
        raise invalid(
            "layout.status.record_shape",
            f"Evidence field {key} must be a complete SHA-256 digest.",
            record=path,
        ) from exc
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number: {value}")


def _assert_acyclic(
    records: Iterable[EvidenceRecord],
    root_path: str,
    *,
    deadline: InvocationDeadline | None = None,
) -> None:
    by_path = {item.path: item for item in records}
    visited: set[str] = set()
    active: set[str] = set()

    def visit(path: str) -> None:
        _check(deadline)
        if path in active:
            raise invalid(
                "layout.status.reference_cycle",
                "Evidence references must form an acyclic graph.",
                record=path,
            )
        if path in visited:
            return
        record = by_path.get(path)
        if record is None:
            raise invalid(
                "layout.status.reference_missing",
                "An explicit evidence reference is unavailable.",
                record=path,
            )
        active.add(path)
        for reference in record.references:
            visit(reference.path)
        active.remove(path)
        visited.add(path)

    visit(root_path)


def _validate_json_depth(
    raw: bytes,
    *,
    path: str,
    deadline: InvocationDeadline | None,
) -> None:
    depth = 0
    in_string = False
    escaped = False
    for index, value in enumerate(raw):
        if index % 4096 == 0:
            _check(deadline)
        if in_string:
            if escaped:
                escaped = False
            elif value == ord("\\"):
                escaped = True
            elif value == ord('"'):
                in_string = False
            continue
        if value == ord('"'):
            in_string = True
        elif value in {ord("{"), ord("[")}:
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                raise invalid(
                    "layout.status.record_json",
                    "A selected evidence record exceeds the JSON nesting limit.",
                    record=path,
                )
        elif value in {ord("}"), ord("]")}:
            depth = max(0, depth - 1)


def _check(deadline: InvocationDeadline | None) -> None:
    if deadline is not None:
        deadline.check()


def _open_absolute_directory(path: Path) -> int:
    components = path.parts
    if not components or components[0] != os.sep:
        raise OSError("evidence root is not absolute")
    descriptor = os.open(os.sep, _DIRECTORY_FLAGS)
    try:
        for component in components[1:]:
            next_descriptor = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


__all__ = [
    "EvidenceGraph",
    "EvidenceRecord",
    "ExplicitRecordReader",
    "ReaderLimits",
    "RecordReference",
    "canonical_json",
    "canonical_record_digest",
    "contains_unsafe_text",
    "parse_record",
]
