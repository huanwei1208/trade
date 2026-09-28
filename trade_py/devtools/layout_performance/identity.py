"""Stable runner identity for package-layout performance evidence."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path, PurePosixPath

from trade_py.devtools.layout_performance.capacity import detected_memory_bytes
from trade_py.devtools.layout_performance.models import RunnerIdentity
from trade_py.devtools.layout_performance.processes import run_process

_SAFE_RUNNER_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}")
_MAX_HARNESS_FILES = 128
_MAX_HARNESS_FILE_BYTES = 1024 * 1024
_MAX_SOURCE_FILES = 20_000
_MAX_SOURCE_FILE_BYTES = 16 * 1024 * 1024
_SOURCE_ROOTS = (
    "layout-authority.toml",
    "pyproject.toml",
    "src/trade",
    "trade",
    "trade_py",
    "trade_web/backend",
    "trade_web/frontend",
    "uv.lock",
)
_SOURCE_ROOT_FILES = frozenset({"layout-authority.toml", "pyproject.toml", "trade", "uv.lock"})
_SOURCE_SUFFIXES = frozenset(
    {
        ".css",
        ".html",
        ".js",
        ".json",
        ".jsx",
        ".py",
        ".scss",
        ".ts",
        ".tsx",
        ".vue",
    }
)
_EXCLUDED_SEGMENTS = frozenset(
    {
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "generated",
        "node_modules",
        "vendor",
    }
)


def capture_runner_identity(repo_root: Path) -> RunnerIdentity:
    root = repo_root.resolve()
    payload = {
        "harness_digest": capture_harness_digest(root),
        "runner_image": _runner_image(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": max(1, os.cpu_count() or 1),
        "memory_limit_bytes": detected_memory_bytes(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_executable_digest": _file_digest(Path(sys.executable).resolve()),
        "uv_lock_digest": _optional_file_digest(root / "uv.lock"),
        "frontend_lock_digest": _optional_file_digest(
            root / "trade_web" / "frontend" / "package-lock.json"
        ),
        "node_version": _tool_version("node"),
        "npm_version": _tool_version("npm"),
    }
    identity_digest = runner_identity_digest(payload)
    return RunnerIdentity(identity_digest=identity_digest, **payload)


def capture_harness_digest(repo_root: Path) -> str:
    root = repo_root.resolve()
    harness_root = root / "trade_py" / "devtools" / "layout_performance"
    paths = tuple(sorted(harness_root.glob("*.py")))
    if not paths or len(paths) > _MAX_HARNESS_FILES:
        raise RuntimeError("layout performance harness source set is unavailable or unbounded")
    digest = hashlib.sha256()
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("layout performance harness sources must be regular files")
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                size += len(chunk)
                if size > _MAX_HARNESS_FILE_BYTES:
                    raise RuntimeError("layout performance harness source exceeds its byte budget")
                digest.update(chunk)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def capture_source_tree_digest(repo_root: Path) -> str:
    root = repo_root.resolve()
    outcome = run_process(
        (
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *_SOURCE_ROOTS,
        ),
        cwd=root,
        timeout_seconds=10,
        output_limit_bytes=8 * 1024 * 1024,
    )
    raw_paths = tuple(sorted({item for item in outcome.stdout.split(b"\0") if item}))
    if not raw_paths or len(raw_paths) > _MAX_SOURCE_FILES:
        raise RuntimeError("performance source tree is unavailable or unbounded")
    digest = hashlib.sha256()
    selected = 0
    for raw in raw_paths:
        relative = PurePosixPath(raw.decode("utf-8", "strict"))
        if not _is_source_path(relative):
            continue
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("performance source tree contains a non-regular source")
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                size += len(chunk)
                if size > _MAX_SOURCE_FILE_BYTES:
                    raise RuntimeError("performance source exceeds its per-file byte budget")
                digest.update(chunk)
        digest.update(b"\0")
        selected += 1
    if selected == 0:
        raise RuntimeError("performance source tree contains no selected source")
    return f"sha256:{digest.hexdigest()}"


def _is_source_path(path: PurePosixPath) -> bool:
    return (
        path.as_posix() in _SOURCE_ROOT_FILES or path.suffix.lower() in _SOURCE_SUFFIXES
    ) and not any(part in _EXCLUDED_SEGMENTS for part in path.parts)


def runner_identity_digest(payload: dict[str, object]) -> str:
    content = dict(payload)
    content.pop("identity_digest", None)
    return _payload_digest(content)


def source_commit(repo_root: Path) -> str:
    outcome = run_process(
        ("git", "rev-parse", "HEAD"),
        cwd=repo_root.resolve(),
        timeout_seconds=5,
        output_limit_bytes=4096,
    )
    value = outcome.stdout.decode("ascii", "strict").strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError("Git did not return a full lowercase source commit")
    return value


def _tool_version(name: str) -> str | None:
    executable = shutil.which(name)
    if executable is None:
        return None
    outcome = run_process(
        (executable, "--version"),
        cwd=Path.cwd(),
        timeout_seconds=5,
        output_limit_bytes=4096,
    )
    value = outcome.stdout.decode("utf-8", "replace").strip()
    return value[:128] or None


def _optional_file_digest(path: Path) -> str:
    return _file_digest(path) if path.is_file() else "unavailable"


def _runner_image() -> str:
    explicit = os.environ.get("TRADE_RUNNER_IMAGE", "").strip()
    if explicit:
        if _SAFE_RUNNER_IMAGE.fullmatch(explicit) is None:
            raise ValueError("TRADE_RUNNER_IMAGE must be a bounded safe identifier")
        return explicit
    return f"local:{_optional_file_digest(Path('/etc/os-release'))}"


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _payload_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "capture_harness_digest",
    "capture_runner_identity",
    "capture_source_tree_digest",
    "runner_identity_digest",
    "source_commit",
]
