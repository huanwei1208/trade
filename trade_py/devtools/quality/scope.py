"""NUL-safe, branch-aware Git scope selection."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, overload

from trade_py.devtools.quality.models import ScopeSelection


class ScopeError(RuntimeError):
    """Raised when Git provenance or a requested path is unsafe."""


@dataclass(frozen=True)
class _Base:
    ref: str
    merge_base: str


def discover_repo_root(start: Path | None = None) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ScopeError(result.stderr.strip() or "not inside a Git repository")
    return Path(result.stdout.strip()).resolve()


@overload
def _git(repo_root: Path, *args: str, text: Literal[True] = True) -> str: ...


@overload
def _git(repo_root: Path, *args: str, text: Literal[False]) -> bytes: ...


def _git(repo_root: Path, *args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=text,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise ScopeError(stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _existing_ref(repo_root: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _resolve_base(repo_root: Path, requested: str | None) -> _Base:
    candidates = (
        [requested]
        if requested
        else [os.environ.get("QUALITY_BASE_REF"), "origin/master", "master"]
    )
    ref = next((item for item in candidates if item and _existing_ref(repo_root, item)), None)
    if not ref:
        raise ScopeError("Cannot resolve base; use --base or set QUALITY_BASE_REF")
    merge_base = str(_git(repo_root, "merge-base", ref, "HEAD")).strip()
    return _Base(ref=ref, merge_base=merge_base)


def _nul_paths(raw: bytes) -> set[str]:
    return {item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item}


def _validate_filter(path: str) -> str:
    if not path or "\0" in path:
        raise ScopeError("--path must be a non-empty repository-relative path")
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ScopeError(f"Path escapes repository: {path!r}")
    normalized = pure.as_posix().removeprefix("./")
    return normalized or "."


def _within_filter(path: str, filters: tuple[str, ...]) -> bool:
    if not filters or filters == (".",):
        return True
    return any(path == item or path.startswith(f"{item.rstrip('/')}/") for item in filters)


def _validate_selected_path(repo_root: Path, path: str) -> None:
    candidate = repo_root / path
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(repo_root)
    except (OSError, ValueError) as exc:
        raise ScopeError(f"Selected path resolves outside repository: {path!r}") from exc


def _scope_fingerprint(
    paths: tuple[str, ...],
    added_files: tuple[str, ...],
    deleted_files: tuple[str, ...],
    delta_files: tuple[str, ...],
    new_change_names: tuple[str, ...],
) -> str:
    digest = hashlib.sha256()
    for label, items in (
        (b"files", paths),
        (b"added", added_files),
        (b"deleted", deleted_files),
        (b"delta", delta_files),
        (b"new-changes", new_change_names),
    ):
        digest.update(label)
        digest.update(b"\0")
        for path in items:
            digest.update(path.encode("utf-8", "surrogateescape"))
            digest.update(b"\0")
    return digest.hexdigest()


def _openspec_change_names(paths: set[str]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        parts = path.split("/")
        if len(parts) >= 4 and parts[:2] == ["openspec", "changes"]:
            names.add(parts[2])
    return names


def _base_openspec_changes(repo_root: Path, base_sha: str) -> set[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-d", "-z", "--name-only", f"{base_sha}:openspec/changes"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return _nul_paths(result.stdout)
    stderr = result.stderr.decode("utf-8", "replace")
    if "Not a valid object name" in stderr or "does not exist" in stderr:
        return set()
    raise ScopeError(stderr.strip() or "Cannot inspect base OpenSpec changes")


def _diff_status(repo_root: Path, *args: str) -> tuple[set[str], set[str], set[str]]:
    raw = _git(
        repo_root,
        "diff",
        "--name-status",
        "-z",
        "--diff-filter=ACMRD",
        *args,
        "--",
        text=False,
    )
    fields = [item for item in raw.split(b"\0") if item]
    selected: set[str] = set()
    added: set[str] = set()
    deleted: set[str] = set()
    index = 0
    while index < len(fields):
        status = fields[index].decode("ascii", "strict")
        index += 1
        code = status[:1]
        if code in {"R", "C"}:
            if index + 1 >= len(fields):
                raise ScopeError("git diff returned a truncated rename/copy record")
            source = fields[index].decode("utf-8", "surrogateescape")
            target = fields[index + 1].decode("utf-8", "surrogateescape")
            index += 2
            selected.add(target)
            added.add(target)
            if code == "R":
                deleted.add(source)
            continue
        if code not in {"A", "M", "D"} or index >= len(fields):
            raise ScopeError(f"git diff returned an unsupported status record: {status!r}")
        path = fields[index].decode("utf-8", "surrogateescape")
        index += 1
        if code == "D":
            deleted.add(path)
        else:
            selected.add(path)
            if code == "A":
                added.add(path)
    return selected, added, deleted


def select_scope(
    repo_root: Path,
    *,
    base_ref: str | None = None,
    all_mode: bool = False,
    paths: tuple[str, ...] = (),
) -> ScopeSelection:
    root = repo_root.resolve()
    base = _resolve_base(root, base_ref)
    head_sha = str(_git(root, "rev-parse", "HEAD")).strip()

    delta, added, deleted = _diff_status(root, base.merge_base, "HEAD")
    for diff_args in ((), ("--cached",)):
        live_delta, added_delta, deleted_delta = _diff_status(root, *diff_args)
        delta.update(live_delta)
        added.update(added_delta)
        deleted.update(deleted_delta)
    untracked = _nul_paths(
        _git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", text=False)
    )
    delta.update(untracked)
    added.update(untracked)
    selected = (
        _nul_paths(_git(root, "ls-files", "-z", text=False)) | untracked if all_mode else set(delta)
    )

    filters = tuple(_validate_filter(path) for path in paths)
    ordered = tuple(sorted(path for path in selected if _within_filter(path, filters)))
    ordered_added = tuple(sorted(path for path in added if _within_filter(path, filters)))
    ordered_deleted = tuple(sorted(path for path in deleted if _within_filter(path, filters)))
    ordered_delta = tuple(sorted(path for path in delta | deleted if _within_filter(path, filters)))
    candidate_changes = _openspec_change_names(set(ordered_delta))
    new_change_names = (
        tuple(sorted(candidate_changes - _base_openspec_changes(root, base.merge_base)))
        if candidate_changes
        else ()
    )
    for path in ordered:
        _validate_selected_path(root, path)
    return ScopeSelection(
        repo_root=str(root),
        base_ref=base.ref,
        base_sha=base.merge_base,
        head_sha=head_sha,
        files=ordered,
        fingerprint=_scope_fingerprint(
            ordered,
            ordered_added,
            ordered_deleted,
            ordered_delta,
            new_change_names,
        ),
        all_mode=all_mode,
        added_files=ordered_added,
        deleted_files=ordered_deleted,
        delta_files=ordered_delta,
        new_change_names=new_change_names,
    )
