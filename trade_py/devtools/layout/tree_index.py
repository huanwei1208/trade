"""Bounded, deterministic source index for package-layout validation."""

from __future__ import annotations

import hashlib
import os
import selectors
import signal
import stat
import subprocess
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SCANNER_NAME = "trade.layout.tree-index"
SCANNER_VERSION = "1"
_REGULAR_MODES = frozenset({"100644", "100755"})
_EXCLUDED_SEGMENTS = frozenset(
    {
        ".cache",
        "__pycache__",
        "build",
        "dist",
        "fixtures",
        "generated",
        "gen",
        "node_modules",
        "out",
        "target",
        "test",
        "tests",
        "third_party",
        "vendor",
    }
)
SOURCE_EXCLUDED_SEGMENTS = tuple(sorted(_EXCLUDED_SEGMENTS))
SOURCE_SUFFIXES = (".py", ".pyi")
SOURCE_EXCLUDED_NAME_PATTERNS = ("test_*.py", "*_test.py")


@dataclass(frozen=True)
class TreeIndexLimits:
    max_git_output_bytes: int = 4 * 1024 * 1024
    max_git_error_bytes: int = 16 * 1024
    max_paths: int = 8_192
    max_path_bytes: int = 1_024
    max_file_bytes: int = 1 * 1024 * 1024
    max_source_bytes: int = 64 * 1024 * 1024
    deadline_seconds: float = 30.0


DEFAULT_LIMITS = TreeIndexLimits()
_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
_DIRECTORY_FLAGS = _OPEN_FLAGS | getattr(os, "O_DIRECTORY", 0)


@dataclass(frozen=True)
class TreeEntry:
    path: str
    mode: str
    source_bytes: int
    source_digest: str


@dataclass(frozen=True)
class TreeIndex:
    scanner_name: str
    scanner_version: str
    scanner_source_digest: str
    rules_digest: str
    excluded_segments: tuple[str, ...]
    tree_digest: str
    entries: tuple[TreeEntry, ...]
    source_bytes: int

    def partition(self, roots: Iterable[str]) -> tuple[TreeEntry, ...]:
        prefixes = tuple(_normalized_root(root) for root in roots)
        return tuple(
            entry
            for entry in self.entries
            if any(_is_under(entry.path, prefix) for prefix in prefixes)
        )


@dataclass
class TreeIndexSession:
    """One explicit scan shared by all partitions in a validation invocation."""

    repo_root: Path
    included_roots: tuple[str, ...]
    rules_digest: str
    candidate_paths: tuple[str, ...] = ()
    limits: TreeIndexLimits = DEFAULT_LIMITS
    _index: TreeIndex | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def index(self) -> TreeIndex:
        if self._index is None:
            with self._lock:
                if self._index is None:
                    self._index = scan_repository(
                        self.repo_root,
                        included_roots=self.included_roots,
                        rules_digest=self.rules_digest,
                        candidate_paths=self.candidate_paths,
                        limits=self.limits,
                    )
        return self._index


class TreeIndexError(RuntimeError):
    """A stable source-index refusal."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def scan_repository(
    repo_root: Path,
    *,
    included_roots: Iterable[str],
    rules_digest: str,
    candidate_paths: Iterable[str] = (),
    limits: TreeIndexLimits = DEFAULT_LIMITS,
    deadline_at: float | None = None,
) -> TreeIndex:
    """Build one immutable index from the current Git-indexed source tree."""

    deadline = (
        float(deadline_at)
        if deadline_at is not None
        else time.monotonic() + limits.deadline_seconds
    )
    _check_deadline(deadline)
    root = repo_root.resolve()
    roots = tuple(sorted({_normalized_root(value) for value in included_roots}))
    if not roots:
        raise TreeIndexError("layout.index.roots_empty", "at least one source root is required")
    raw = _git_index_output(root, roots, limits, deadline_at=deadline)
    records = _parse_records(raw, roots, limits)
    seen = {path for _mode, path in records}
    for candidate in sorted(set(candidate_paths)):
        _check_deadline(deadline)
        normalized = _normalized_path(candidate)
        if normalized in seen or not _is_selected_source(normalized, roots):
            continue
        candidate_path = root / normalized
        if not candidate_path.exists():
            continue
        records.append((_filesystem_mode(candidate_path), normalized))
        seen.add(normalized)
        if len(records) > limits.max_paths:
            raise TreeIndexError(
                "layout.index.path_budget",
                f"selected source exceeds {limits.max_paths} paths",
            )
    entries: list[TreeEntry] = []
    source_bytes = 0
    for mode, path in records:
        _check_deadline(deadline)
        content = read_regular_relative(
            root,
            path,
            max_bytes=limits.max_file_bytes,
            deadline_at=deadline,
        )
        source_bytes += len(content)
        if source_bytes > limits.max_source_bytes:
            raise TreeIndexError(
                "layout.index.source_budget",
                f"selected source exceeds {limits.max_source_bytes} bytes",
            )
        entries.append(
            TreeEntry(
                path=path,
                mode=mode,
                source_bytes=len(content),
                source_digest=_sha256(content),
            )
        )
    _check_deadline(deadline)
    entries.sort(key=lambda item: item.path)
    scanner_source_digest = _sha256(
        read_regular_relative(
            Path(__file__).parent,
            Path(__file__).name,
            max_bytes=limits.max_file_bytes,
            deadline_at=deadline,
        )
    )
    tree_digest = _digest_rows(
        f"{entry.mode}\0{entry.path}\0{entry.source_bytes}\0{entry.source_digest}"
        for entry in entries
    )
    return TreeIndex(
        scanner_name=SCANNER_NAME,
        scanner_version=SCANNER_VERSION,
        scanner_source_digest=scanner_source_digest,
        rules_digest=rules_digest,
        excluded_segments=SOURCE_EXCLUDED_SEGMENTS,
        tree_digest=tree_digest,
        entries=tuple(entries),
        source_bytes=source_bytes,
    )


def read_regular_relative(
    root: Path,
    relative: str,
    *,
    max_bytes: int,
    deadline_at: float | None = None,
) -> bytes:
    """Read one repository-relative regular file without following symlinks."""

    _check_deadline(deadline_at)
    path = _normalized_path(relative)
    parts = PurePosixPath(path).parts
    descriptor = os.open(root, _DIRECTORY_FLAGS)
    try:
        for part in parts[:-1]:
            _check_deadline(deadline_at)
            next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        _check_deadline(deadline_at)
        file_descriptor = os.open(parts[-1], _OPEN_FLAGS, dir_fd=descriptor)
        try:
            before = os.fstat(file_descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise TreeIndexError(
                    "layout.index.unsafe_source",
                    f"source is not a regular file: {path}",
                )
            if before.st_size > max_bytes:
                raise TreeIndexError(
                    "layout.index.file_budget",
                    f"source exceeds {max_bytes} bytes: {path}",
                )
            content = _read_exact(
                file_descriptor,
                before.st_size,
                deadline_at=deadline_at,
            )
            after = os.fstat(file_descriptor)
            signature_before = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            signature_after = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if signature_before != signature_after:
                raise TreeIndexError(
                    "layout.index.source_changed",
                    f"source changed while being read: {path}",
                )
            return content
        finally:
            os.close(file_descriptor)
    except (NotADirectoryError, FileNotFoundError, PermissionError, OSError) as exc:
        raise TreeIndexError(
            "layout.index.unsafe_source",
            f"cannot safely read source {path}: {exc}",
        ) from exc
    finally:
        os.close(descriptor)


def _git_index_output(
    root: Path,
    roots: tuple[str, ...],
    limits: TreeIndexLimits,
    *,
    deadline_at: float,
) -> bytes:
    environment = os.environ.copy()
    for name in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    ):
        environment.pop(name, None)
    try:
        process = subprocess.Popen(
            ["git", "-C", str(root), "ls-files", "-z", "--stage", "--", *roots],
            cwd=root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise TreeIndexError("layout.index.tool_failure", f"cannot start Git: {exc}") from exc

    assert process.stdout is not None
    assert process.stderr is not None
    streams = selectors.DefaultSelector()
    streams.register(process.stdout, selectors.EVENT_READ, "stdout")
    streams.register(process.stderr, selectors.EVENT_READ, "stderr")
    output = bytearray()
    error = bytearray()
    try:
        while streams.get_map():
            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                raise TreeIndexError(
                    "layout.index.timeout",
                    f"Git index scan exceeded {limits.deadline_seconds:g} seconds",
                )
            ready = streams.select(min(remaining, 0.1))
            for key, _ in ready:
                chunk = os.read(key.fd, 8_192)
                if not chunk:
                    streams.unregister(key.fileobj)
                    continue
                target = output if key.data == "stdout" else error
                target.extend(chunk)
                limit = (
                    limits.max_git_output_bytes
                    if key.data == "stdout"
                    else limits.max_git_error_bytes
                )
                if len(target) > limit:
                    raise TreeIndexError(
                        "layout.index.output_budget",
                        f"Git {key.data} exceeded {limit} bytes",
                    )
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            raise TreeIndexError("layout.index.timeout", "Git index scan exceeded its deadline")
        return_code = process.wait(timeout=remaining)
        if return_code != 0:
            detail = bytes(error).decode("utf-8", "replace").strip()
            raise TreeIndexError(
                "layout.index.tool_failure",
                f"Git index scan failed with exit {return_code}: {detail[:512]}",
            )
        return bytes(output)
    except subprocess.TimeoutExpired as exc:
        raise TreeIndexError(
            "layout.index.timeout", "Git index scan exceeded its deadline"
        ) from exc
    finally:
        streams.close()
        try:
            _terminate_process_tree(process)
        finally:
            process.stdout.close()
            process.stderr.close()


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    process_group = process.pid
    process.poll()
    if not _process_group_exists(process_group):
        return
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise TreeIndexError(
            "layout.index.cleanup_failed",
            f"cannot terminate Git process group {process_group}: {exc}",
        ) from exc
    if _wait_for_process_group_exit(process, process_group, timeout=0.5):
        return
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise TreeIndexError(
            "layout.index.cleanup_failed",
            f"cannot kill Git process group {process_group}: {exc}",
        ) from exc
    if not _wait_for_process_group_exit(process, process_group, timeout=0.5):
        raise TreeIndexError(
            "layout.index.cleanup_failed",
            f"Git process group {process_group} survived TERM-to-KILL cleanup",
        )


def _wait_for_process_group_exit(
    process: subprocess.Popen[bytes],
    process_group: int,
    *,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        process.poll()
        if not _process_group_exists(process_group):
            return True
        time.sleep(0.01)
    process.poll()
    return not _process_group_exists(process_group)


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _parse_records(
    raw: bytes,
    roots: tuple[str, ...],
    limits: TreeIndexLimits,
) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            mode_bytes, _object_id, stage = metadata.split(b" ", 2)
            mode = mode_bytes.decode("ascii")
            path = encoded_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise TreeIndexError(
                "layout.index.invalid_record",
                "Git index emitted a malformed record",
            ) from exc
        if stage != b"0":
            raise TreeIndexError(
                "layout.index.unmerged",
                f"Git index contains an unmerged source: {path}",
            )
        if len(encoded_path) > limits.max_path_bytes:
            raise TreeIndexError(
                "layout.index.path_budget",
                f"source path exceeds {limits.max_path_bytes} bytes",
            )
        normalized = _normalized_path(path)
        if mode not in _REGULAR_MODES or not _is_selected_source(normalized, roots):
            continue
        parsed.append((mode, normalized))
        if len(parsed) > limits.max_paths:
            raise TreeIndexError(
                "layout.index.path_budget",
                f"selected source exceeds {limits.max_paths} paths",
            )
    return parsed


def _is_selected_source(path: str, roots: tuple[str, ...]) -> bool:
    pure = PurePosixPath(path)
    if pure.suffix not in SOURCE_SUFFIXES:
        return False
    if not any(_is_under(path, root) for root in roots):
        return False
    if any(part in _EXCLUDED_SEGMENTS for part in pure.parts):
        return False
    return not pure.name.startswith("test_") and not pure.name.endswith("_test.py")


def _filesystem_mode(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise TreeIndexError(
            "layout.index.unsafe_source",
            f"cannot inspect candidate source {path}: {exc}",
        ) from exc
    if not stat.S_ISREG(mode):
        raise TreeIndexError(
            "layout.index.unsafe_source",
            f"candidate source is not a regular file: {path}",
        )
    return "100755" if mode & stat.S_IXUSR else "100644"


def _normalized_root(value: str) -> str:
    path = _normalized_path(value)
    return path.rstrip("/")


def _normalized_path(value: str) -> str:
    if not value or "\\" in value or "\0" in value:
        raise TreeIndexError("layout.index.unsafe_path", f"unsafe relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TreeIndexError("layout.index.unsafe_path", f"unsafe relative path: {value!r}")
    return path.as_posix()


def _is_under(path: str, root: str) -> bool:
    return path == root or path.startswith(f"{root}/")


def _read_exact(
    descriptor: int,
    size: int,
    *,
    deadline_at: float | None,
) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        _check_deadline(deadline_at)
        chunk = os.read(descriptor, min(remaining, 65_536))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) != size:
        raise TreeIndexError("layout.index.short_read", "source ended before its recorded size")
    return content


def _check_deadline(deadline_at: float | None) -> None:
    if deadline_at is not None and time.monotonic() >= deadline_at:
        raise TreeIndexError(
            "layout.index.timeout",
            "Source index validation exceeded its monotonic deadline",
        )


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _digest_rows(rows: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


__all__ = [
    "DEFAULT_LIMITS",
    "SCANNER_NAME",
    "SCANNER_VERSION",
    "SOURCE_EXCLUDED_NAME_PATTERNS",
    "SOURCE_EXCLUDED_SEGMENTS",
    "SOURCE_SUFFIXES",
    "TreeEntry",
    "TreeIndex",
    "TreeIndexError",
    "TreeIndexLimits",
    "TreeIndexSession",
    "read_regular_relative",
    "scan_repository",
]
