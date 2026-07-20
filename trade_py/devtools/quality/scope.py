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


def _scope_fingerprint(paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
    return digest.hexdigest()


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

    if all_mode:
        selected = _nul_paths(_git(root, "ls-files", "-z", text=False))
    else:
        selected = _nul_paths(
            _git(
                root,
                "diff",
                "--name-only",
                "-z",
                "--diff-filter=ACMR",
                base.merge_base,
                "HEAD",
                "--",
                text=False,
            )
        )
        selected.update(
            _nul_paths(
                _git(root, "diff", "--name-only", "-z", "--diff-filter=ACMR", "--", text=False)
            )
        )
        selected.update(
            _nul_paths(
                _git(
                    root,
                    "diff",
                    "--cached",
                    "--name-only",
                    "-z",
                    "--diff-filter=ACMR",
                    "--",
                    text=False,
                )
            )
        )
    selected.update(
        _nul_paths(_git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", text=False))
    )

    filters = tuple(_validate_filter(path) for path in paths)
    ordered = tuple(sorted(path for path in selected if _within_filter(path, filters)))
    for path in ordered:
        _validate_selected_path(root, path)
    return ScopeSelection(
        repo_root=str(root),
        base_ref=base.ref,
        base_sha=base.merge_base,
        head_sha=head_sha,
        files=ordered,
        fingerprint=_scope_fingerprint(ordered),
        all_mode=all_mode,
    )
