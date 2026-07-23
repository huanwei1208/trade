"""Bounded, allowlisted, symlink-safe OpenSpec artifact snapshots."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from trade_py.devtools.design_quality.errors import DesignQualityError
from trade_py.devtools.design_quality.models import Artifact, ChangeSnapshot, Policy

_CHANGE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
_CAPABILITY_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
_TASK_CHECKBOX_RE = re.compile(rb"(?m)^(- \[)[xX](\] \d+\.\d+ )")


@dataclass(frozen=True)
class _Candidate:
    path: Path
    relative: str
    size: int
    signature: tuple[int, int, int]


def validate_change_name(name: str) -> str:
    if not _CHANGE_RE.fullmatch(name):
        raise DesignQualityError(
            f"Invalid change name {name!r}; expected lowercase letters, digits, and hyphens"
        )
    return name


def _signature(path: Path) -> tuple[int, int, int]:
    stat = path.stat(follow_symlinks=False)
    return stat.st_ino, stat.st_size, stat.st_mtime_ns


def _change_dir(repo_root: Path, name: str) -> Path:
    root = repo_root.resolve()
    candidate = root
    for part in ("openspec", "changes", validate_change_name(name)):
        candidate = candidate / part
        if candidate.is_symlink():
            raise DesignQualityError(f"Refusing symlinked OpenSpec path component: {part}")
    changes_root = root / "openspec" / "changes"
    try:
        changes_root = changes_root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(changes_root)
    except (OSError, ValueError) as exc:
        raise DesignQualityError(f"OpenSpec change does not exist or escapes root: {name}") from exc
    if not resolved.is_dir():
        raise DesignQualityError(f"OpenSpec change is not a directory: {name}")
    return resolved


def _collect(change_dir: Path, policy: Policy) -> tuple[_Candidate, ...]:
    paths: list[Path] = [change_dir / item for item in policy.root_files]
    specs_dir = change_dir / "specs"
    if specs_dir.is_symlink():
        raise DesignQualityError("Refusing unsafe specs directory")
    if specs_dir.exists():
        if not specs_dir.is_dir():
            raise DesignQualityError("Refusing unsafe specs directory")
        capabilities: list[Path] = []
        try:
            with os.scandir(specs_dir) as entries:
                for entry in entries:
                    if len(capabilities) >= policy.limits.max_files_per_change:
                        raise DesignQualityError(
                            "Spec capability count exceeds the per-change artifact limit"
                        )
                    if (
                        not _CAPABILITY_RE.fullmatch(entry.name)
                        or entry.is_symlink()
                        or not entry.is_dir(follow_symlinks=False)
                    ):
                        raise DesignQualityError(
                            f"Refusing unsafe spec capability path: {entry.name}"
                        )
                    capabilities.append(Path(entry.path))
        except OSError as exc:
            raise DesignQualityError("Cannot safely enumerate spec capabilities") from exc
        for capability in sorted(capabilities, key=lambda item: item.name):
            paths.append(capability / "spec.md")

    candidates: list[_Candidate] = []
    for path in paths:
        if path.is_symlink():
            raise DesignQualityError(f"Refusing unsafe design artifact: {path.name}")
        if not path.exists():
            continue
        if not path.is_file():
            raise DesignQualityError(f"Refusing unsafe design artifact: {path.name}")
        try:
            relative = path.relative_to(change_dir).as_posix()
        except ValueError as exc:
            raise DesignQualityError(f"Design artifact escapes change root: {path}") from exc
        signature = _signature(path)
        candidates.append(
            _Candidate(path=path, relative=relative, size=signature[1], signature=signature)
        )

    ordered = tuple(sorted(candidates, key=lambda item: item.relative))
    if len(ordered) > policy.limits.max_files_per_change:
        raise DesignQualityError(
            f"Change has {len(ordered)} artifacts; limit is {policy.limits.max_files_per_change}"
        )
    total = sum(item.size for item in ordered)
    if total > policy.limits.max_total_bytes_per_change:
        raise DesignQualityError(
            f"Change artifacts use {total} bytes; limit is {policy.limits.max_total_bytes_per_change}"
        )
    oversized = next((item for item in ordered if item.size > policy.limits.max_file_bytes), None)
    if oversized:
        raise DesignQualityError(
            f"Artifact {oversized.relative} uses {oversized.size} bytes; "
            f"limit is {policy.limits.max_file_bytes}"
        )
    return ordered


_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


@contextmanager
def _change_fd(repo_root: Path, name: str) -> Iterator[int]:
    descriptor = os.open(repo_root, _DIRECTORY_FLAGS)
    try:
        for part in ("openspec", "changes", name):
            next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        yield descriptor
    except OSError as exc:
        raise DesignQualityError(f"Unsafe or concurrently changed OpenSpec path: {name}") from exc
    finally:
        os.close(descriptor)


def _open_artifact(change_descriptor: int, relative: str) -> int:
    parts = tuple(item for item in relative.split("/") if item)
    if not parts or any(item in {".", ".."} for item in parts):
        raise DesignQualityError(f"Unsafe design artifact path: {relative}")
    descriptor = os.dup(change_descriptor)
    try:
        for part in parts[:-1]:
            next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return os.open(parts[-1], _FILE_FLAGS, dir_fd=descriptor)
    except OSError as exc:
        raise DesignQualityError(f"Unsafe or concurrently changed artifact: {relative}") from exc
    finally:
        os.close(descriptor)


def _fd_signature(descriptor: int) -> tuple[int, int, int]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise DesignQualityError("Design artifact is not a regular file")
    return metadata.st_ino, metadata.st_size, metadata.st_mtime_ns


def _read_candidate(repo_root: Path, name: str, candidate: _Candidate, max_bytes: int) -> bytes:
    with _change_fd(repo_root, name) as change_descriptor:
        descriptor = _open_artifact(change_descriptor, candidate.relative)
        try:
            if _fd_signature(descriptor) != candidate.signature:
                raise DesignQualityError(f"Artifact changed before reading: {candidate.relative}")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                payload = stream.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise DesignQualityError(
                    f"Artifact {candidate.relative} exceeds the {max_bytes} byte read limit"
                )
            if _fd_signature(descriptor) != candidate.signature or len(payload) != candidate.size:
                raise DesignQualityError(f"Artifact changed while reading: {candidate.relative}")
            return payload
        finally:
            os.close(descriptor)


def _digest_content(relative: str, content: bytes) -> bytes:
    if relative == "tasks.md":
        return _TASK_CHECKBOX_RE.sub(rb"\1 \2", content)
    return content


def artifact_payload_digest(
    payloads: tuple[tuple[str, bytes], ...], digest_excludes: tuple[str, ...]
) -> str:
    aggregate = hashlib.sha256()
    excluded = set(digest_excludes)
    for relative, payload in sorted(payloads):
        if relative in excluded:
            continue
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(_digest_content(relative, payload))
        aggregate.update(b"\0")
    return f"sha256:{aggregate.hexdigest()}"


def load_snapshots(
    repo_root: Path, names: tuple[str, ...], policy: Policy
) -> tuple[ChangeSnapshot, ...]:
    unique = tuple(sorted(set(names)))
    if not unique:
        raise DesignQualityError("At least one OpenSpec change is required")
    if len(unique) > policy.limits.max_changes_per_batch:
        raise DesignQualityError(
            f"Batch has {len(unique)} changes; limit is {policy.limits.max_changes_per_batch}"
        )

    pending: list[tuple[str, Path, tuple[_Candidate, ...]]] = []
    batch_bytes = 0
    for name in unique:
        change_dir = _change_dir(repo_root, name)
        candidates = _collect(change_dir, policy)
        batch_bytes += sum(item.size for item in candidates)
        pending.append((name, change_dir, candidates))
    if batch_bytes > policy.limits.max_total_bytes_per_batch:
        raise DesignQualityError(
            f"Batch artifacts use {batch_bytes} bytes; "
            f"limit is {policy.limits.max_total_bytes_per_batch}"
        )

    snapshots: list[ChangeSnapshot] = []
    for name, change_dir, candidates in pending:
        artifacts: list[Artifact] = []
        digest_payloads: list[tuple[str, bytes]] = []
        total = 0
        for candidate in candidates:
            payload = _read_candidate(
                repo_root.resolve(), name, candidate, policy.limits.max_file_bytes
            )
            try:
                content = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DesignQualityError(
                    f"Design artifact is not valid UTF-8: {candidate.relative}"
                ) from exc
            digest = hashlib.sha256(payload).hexdigest()
            artifacts.append(
                Artifact(
                    path=candidate.relative,
                    size_bytes=len(payload),
                    digest=f"sha256:{digest}",
                    content=content,
                    stat_signature=candidate.signature,
                )
            )
            total += len(payload)
            digest_payloads.append((candidate.relative, payload))
        snapshots.append(
            ChangeSnapshot(
                name=name,
                repo_root=str(repo_root.resolve()),
                root=str(change_dir),
                artifacts=tuple(artifacts),
                artifact_digest=artifact_payload_digest(
                    tuple(digest_payloads), policy.digest_excludes
                ),
                total_bytes=total,
            )
        )
    return tuple(snapshots)


def verify_snapshot(snapshot: ChangeSnapshot, policy: Policy) -> None:
    root = Path(snapshot.root)
    current = _collect(root, policy)
    inventory = {item.relative: item for item in current}
    original = {item.path: item for item in snapshot.artifacts}
    if set(inventory) != set(original):
        raise DesignQualityError("Design artifact inventory changed during evaluation")
    for relative, artifact in original.items():
        candidate = inventory[relative]
        payload = _read_candidate(
            Path(snapshot.repo_root), snapshot.name, candidate, policy.limits.max_file_bytes
        )
        digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if candidate.signature != artifact.stat_signature or digest != artifact.digest:
            raise DesignQualityError(f"Artifact changed during evaluation: {relative}")
