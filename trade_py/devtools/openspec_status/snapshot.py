"""Immutable source-generation capture for native OpenSpec collection."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from trade_py.devtools.design_quality.errors import DesignQualityError
from trade_py.devtools.design_quality.governance import (
    GovernanceResolution,
    resolve_governance_requirements,
)
from trade_py.devtools.design_quality.models import ChangeSnapshot, Policy
from trade_py.devtools.design_quality.snapshot import (
    load_snapshots,
    verify_snapshot,
)
from trade_py.devtools.openspec_status.errors import (
    WorkflowCollectionError,
    WorkflowError,
)
from trade_py.devtools.openspec_status.executor import BoundedProcessExecutor
from trade_py.devtools.openspec_status.models import WorkflowLimits, WorkflowSource

_CHANGE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_CONFIG_LIMIT = 262_144
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class SourceGeneration:
    repo_root: Path
    snapshots: tuple[ChangeSnapshot, ...]
    config_payload: bytes
    config_signature: tuple[int, int, int]
    base_ref_sha: str
    source: WorkflowSource
    governance: GovernanceResolution
    executor: BoundedProcessExecutor
    deadline: float
    limits: WorkflowLimits

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.snapshots)

    def verify(self, policy: Policy) -> dict[str, WorkflowError]:
        names = _active_change_names(self.repo_root, self.limits.max_changes)
        if names != self.names:
            raise WorkflowCollectionError(
                WorkflowError(
                    code="workflow.snapshot.scope_changed",
                    source="snapshot",
                    message="Active OpenSpec change scope changed during collection.",
                    remediation="Stop concurrent edits and rerun the workflow status command.",
                )
            )
        errors: dict[str, WorkflowError] = {}
        for snapshot in self.snapshots:
            try:
                verify_snapshot(snapshot, policy)
            except DesignQualityError:
                errors[snapshot.name] = WorkflowError(
                    code="workflow.snapshot.changed",
                    source="snapshot",
                    change=snapshot.name,
                    message=(
                        "OpenSpec design artifacts changed during workflow "
                        f"collection: {snapshot.name}"
                    ),
                    remediation="Stop concurrent edits and rerun the workflow status command.",
                )
        payload, signature = _read_config(self.repo_root)
        if payload != self.config_payload or signature != self.config_signature:
            raise WorkflowCollectionError(
                WorkflowError(
                    code="workflow.snapshot.changed",
                    source="snapshot",
                    message="OpenSpec project configuration changed during collection.",
                    remediation="Stop concurrent edits and rerun the workflow status command.",
                )
            )
        head = _git_commit(
            self.executor,
            self.repo_root,
            self.deadline,
            self.limits,
            "HEAD",
        )
        base_ref_sha = _git_commit(
            self.executor,
            self.repo_root,
            self.deadline,
            self.limits,
            self.source.base_ref,
        )
        if head != self.source.git_head or base_ref_sha != self.base_ref_sha:
            _raise_git("Git HEAD or base ref changed during workflow collection.")
        return errors

    @contextmanager
    def materialize(self) -> Iterator[Path]:
        with tempfile.TemporaryDirectory(prefix="trade-openspec-status-") as raw:
            root = Path(raw)
            config = root / "openspec" / "config.yaml"
            config.parent.mkdir(parents=True)
            config.write_bytes(self.config_payload)
            os.utime(config, ns=(self.config_signature[2], self.config_signature[2]))
            changes_root = root / "openspec" / "changes"
            changes_root.mkdir()
            for snapshot in self.snapshots:
                change_root = changes_root / snapshot.name
                change_root.mkdir()
                for artifact in snapshot.artifacts:
                    destination = change_root / artifact.path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(artifact.content, encoding="utf-8")
                    mtime_ns = artifact.stat_signature[2]
                    os.utime(destination, ns=(mtime_ns, mtime_ns))
            manifest = _materialized_manifest(
                root,
                byte_limit=self.limits.report_output_bytes + _CONFIG_LIMIT,
            )
            try:
                yield root
            except BaseException:
                raise
            else:
                if _materialized_manifest(
                    root,
                    byte_limit=self.limits.report_output_bytes + _CONFIG_LIMIT,
                ) != manifest:
                    raise WorkflowCollectionError(
                        WorkflowError(
                            code="workflow.snapshot.temporary_changed",
                            source="snapshot",
                            message="Native OpenSpec modified its temporary evidence snapshot.",
                            remediation=(
                                "Repair the native read command so it is non-mutating, then rerun."
                            ),
                        )
                    )


def capture_source_generation(
    repo_root: Path,
    *,
    executor: BoundedProcessExecutor,
    deadline: float,
    policy: Policy,
    limits: WorkflowLimits,
) -> SourceGeneration:
    root = repo_root.resolve()
    head = _git_commit(executor, root, deadline, limits, "HEAD")
    base_ref = _resolve_base_ref(executor, root, deadline, limits)
    base_ref_sha = _git_commit(executor, root, deadline, limits, base_ref)
    base_sha = _git_text(
        executor,
        root,
        deadline,
        limits,
        ("merge-base", base_ref_sha, head),
    ).strip()
    if not _COMMIT_RE.fullmatch(base_sha):
        _raise_git("Git merge base is not a full commit SHA.")
    names = _active_change_names(root, limits.max_changes)
    snapshots = load_snapshots(root, names, policy) if names else ()
    config_payload, config_signature = _read_config(root)
    base_paths = _base_openspec_paths(executor, root, deadline, limits, base_sha)
    base_names = {
        parts[2]
        for path in base_paths
        if len(parts := path.split("/")) >= 4 and parts[:2] == ["openspec", "changes"]
    }
    base_markers = {
        parts[2]
        for path in base_paths
        if len(parts := path.split("/")) == 4
        and parts[:2] == ["openspec", "changes"]
        and parts[3] == "design-quality.toml"
    }
    current_markers = {
        snapshot.name for snapshot in snapshots if snapshot.text("design-quality.toml") is not None
    }
    new_names = set(names) - base_names
    deleted_markers = tuple(
        f"openspec/changes/{name}/design-quality.toml"
        for name in sorted(base_markers - current_markers)
        if name in names
    )
    governance = resolve_governance_requirements(
        root,
        names,
        new_change_names=new_names,
        deleted_files=deleted_markers,
    )
    snapshot_digest = _snapshot_digest(config_payload, snapshots)
    return SourceGeneration(
        repo_root=root,
        snapshots=snapshots,
        config_payload=config_payload,
        config_signature=config_signature,
        base_ref_sha=base_ref_sha,
        source=WorkflowSource(
            git_head=head,
            base_ref=base_ref,
            base_sha=base_sha,
            snapshot_digest=snapshot_digest,
        ),
        governance=governance,
        executor=executor,
        deadline=deadline,
        limits=limits,
    )


def _active_change_names(repo_root: Path, limit: int) -> tuple[str, ...]:
    changes = repo_root / "openspec" / "changes"
    if changes.is_symlink() or not changes.is_dir():
        raise WorkflowCollectionError(
            WorkflowError(
                code="workflow.snapshot.changes_missing",
                source="snapshot",
                message="The repository has no safe openspec/changes directory.",
                remediation="Initialize or repair OpenSpec in this repository and rerun.",
            )
        )
    names: list[str] = []
    try:
        with os.scandir(changes) as entries:
            for entry in entries:
                if entry.name == "archive":
                    continue
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    continue
                if not _CHANGE_RE.fullmatch(entry.name):
                    raise WorkflowCollectionError(
                        WorkflowError(
                            code="workflow.snapshot.change_name",
                            source="snapshot",
                            change=entry.name,
                            message=f"Unsafe active OpenSpec change name: {entry.name}",
                            remediation="Rename the change to a lowercase hyphenated slug.",
                        )
                    )
                names.append(entry.name)
    except OSError as exc:
        raise WorkflowCollectionError(
            WorkflowError(
                code="workflow.snapshot.enumeration",
                source="snapshot",
                message=f"Cannot safely enumerate active OpenSpec changes: {exc}",
                remediation="Repair repository permissions and rerun.",
            )
        ) from exc
    ordered = tuple(sorted(names))
    if len(ordered) > limit:
        raise WorkflowCollectionError(
            WorkflowError(
                code="workflow.snapshot.change_limit",
                source="snapshot",
                message=f"Active change count {len(ordered)} exceeds limit {limit}.",
                remediation="Archive completed changes or inspect a smaller reviewed scope.",
            )
        )
    return ordered


def _read_config(repo_root: Path) -> tuple[bytes, tuple[int, int, int]]:
    path = repo_root / "openspec" / "config.yaml"
    try:
        descriptor = os.open(path, _FILE_FLAGS)
    except OSError as exc:
        raise WorkflowCollectionError(
            WorkflowError(
                code="workflow.snapshot.config",
                source="snapshot",
                message=f"Cannot safely read openspec/config.yaml: {exc}",
                remediation="Repair the OpenSpec project configuration and rerun.",
            )
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _CONFIG_LIMIT:
            raise OSError("configuration is not a bounded regular file")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            payload = stream.read(_CONFIG_LIMIT + 1)
        after = os.fstat(descriptor)
        signature = (before.st_ino, before.st_size, before.st_mtime_ns)
        if len(payload) > _CONFIG_LIMIT or signature != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise OSError("configuration changed while reading")
        return payload, signature
    except OSError as exc:
        raise WorkflowCollectionError(
            WorkflowError(
                code="workflow.snapshot.config",
                source="snapshot",
                message=f"Cannot safely snapshot openspec/config.yaml: {exc}",
                remediation="Stop concurrent edits, repair the file, and rerun.",
            )
        ) from exc
    finally:
        os.close(descriptor)


def _resolve_base_ref(
    executor: BoundedProcessExecutor,
    repo_root: Path,
    deadline: float,
    limits: WorkflowLimits,
) -> str:
    candidates = (
        os.environ.get("QUALITY_BASE_REF"),
        "origin/master",
        "master",
    )
    for candidate in candidates:
        if not candidate:
            continue
        result = executor.run(
            ("git", "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"),
            cwd=repo_root,
            deadline=deadline,
            timeout_seconds=limits.subprocess_timeout_seconds,
            output_limit_bytes=limits.native_output_bytes,
            source="git",
            allowed_returncodes=frozenset({0, 1, 128}),
        )
        if result.returncode == 0:
            return candidate
    _raise_git("Cannot resolve a merge base from QUALITY_BASE_REF, origin/master, or master.")


def _base_openspec_paths(
    executor: BoundedProcessExecutor,
    repo_root: Path,
    deadline: float,
    limits: WorkflowLimits,
    base_sha: str,
) -> tuple[str, ...]:
    raw = _git_bytes(
        executor,
        repo_root,
        deadline,
        limits,
        ("ls-tree", "-r", "-z", "--name-only", base_sha, "--", "openspec/changes"),
    )
    return tuple(
        sorted(item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item)
    )


def _git_text(
    executor: BoundedProcessExecutor,
    repo_root: Path,
    deadline: float,
    limits: WorkflowLimits,
    args: tuple[str, ...],
) -> str:
    return _git_bytes(executor, repo_root, deadline, limits, args).decode("utf-8", "strict")


def _git_commit(
    executor: BoundedProcessExecutor,
    repo_root: Path,
    deadline: float,
    limits: WorkflowLimits,
    ref: str,
) -> str:
    commit = _git_text(
        executor,
        repo_root,
        deadline,
        limits,
        ("rev-parse", "--verify", f"{ref}^{{commit}}"),
    ).strip()
    if not _COMMIT_RE.fullmatch(commit):
        _raise_git(f"Git ref does not resolve to a full commit SHA: {ref}")
    return commit


def _git_bytes(
    executor: BoundedProcessExecutor,
    repo_root: Path,
    deadline: float,
    limits: WorkflowLimits,
    args: tuple[str, ...],
) -> bytes:
    return executor.run(
        ("git", *args),
        cwd=repo_root,
        deadline=deadline,
        timeout_seconds=limits.subprocess_timeout_seconds,
        output_limit_bytes=limits.native_output_bytes,
        source="git",
    ).stdout


def _materialized_manifest(
    root: Path,
    *,
    byte_limit: int,
) -> tuple[tuple[str, int, int, int, str], ...]:
    rows: list[tuple[str, int, int, int, str]] = []
    total = 0
    try:
        paths = sorted(root.rglob("*"))
        for path in paths:
            relative = path.relative_to(root).as_posix()
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                rows.append(
                    (
                        f"{relative}/",
                        stat.S_IMODE(metadata.st_mode),
                        metadata.st_mtime_ns,
                        0,
                        "directory",
                    )
                )
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError(f"temporary snapshot contains a non-regular entry: {relative}")
            total += metadata.st_size
            if total > byte_limit:
                raise OSError("temporary snapshot exceeds its byte limit")
            rows.append(
                (
                    relative,
                    stat.S_IMODE(metadata.st_mode),
                    metadata.st_mtime_ns,
                    metadata.st_size,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
    except OSError as exc:
        raise WorkflowCollectionError(
            WorkflowError(
                code="workflow.snapshot.temporary_changed",
                source="snapshot",
                message=f"Cannot verify the temporary OpenSpec snapshot: {exc}",
                remediation="Repair the native read command so it is non-mutating, then rerun.",
            )
        ) from exc
    return tuple(rows)


def _snapshot_digest(
    config_payload: bytes,
    snapshots: tuple[ChangeSnapshot, ...],
) -> str:
    digest = hashlib.sha256()
    digest.update(b"openspec/config.yaml\0")
    digest.update(config_payload)
    digest.update(b"\0")
    for snapshot in snapshots:
        for artifact in snapshot.artifacts:
            digest.update(f"openspec/changes/{snapshot.name}/{artifact.path}".encode())
            digest.update(b"\0")
            digest.update(artifact.content.encode("utf-8"))
            digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _raise_git(message: str) -> NoReturn:
    raise WorkflowCollectionError(
        WorkflowError(
            code="workflow.git.provenance",
            source="git",
            message=message,
            remediation="Fetch the base branch or set QUALITY_BASE_REF, then rerun.",
        )
    )
