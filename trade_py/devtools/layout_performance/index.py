"""Current and synthetic-10x source-index performance evidence."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath

from trade_py.devtools.layout.tree_index import (
    SOURCE_EXCLUDED_NAME_PATTERNS,
    SOURCE_EXCLUDED_SEGMENTS,
    SOURCE_SUFFIXES,
    read_regular_relative,
)
from trade_py.devtools.layout_performance.capacity import ValidationCapacity
from trade_py.devtools.layout_performance.models import IndexEvidence
from trade_py.devtools.layout_performance.processes import run_process

INCLUDED_ROOTS = ("src/trade", "trade_py")
MAX_GIT_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 1024 * 1024
MAX_SYNTHETIC_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SYNTHETIC_FILES = 8192


def capture_index_evidence(
    repo_root: Path,
    *,
    capacity: ValidationCapacity,
) -> tuple[IndexEvidence, IndexEvidence]:
    root = repo_root.resolve()
    with capacity.admit(
        "ordinary",
        timeout_seconds=capacity.queue_deadline_seconds,
        rss_bytes=512 * 1024 * 1024,
        temp_bytes=64 * 1024 * 1024,
    ):
        current = _run_index_worker(root, INCLUDED_ROOTS, scale=1)
    with capacity.admit(
        "heavy",
        timeout_seconds=capacity.queue_deadline_seconds,
        rss_bytes=1024 * 1024 * 1024,
        temp_bytes=1024 * 1024 * 1024,
    ):
        with tempfile.TemporaryDirectory(prefix="trade-layout-index-10x-") as temporary:
            synthetic_root = Path(temporary) / "repo"
            _build_synthetic_repo(root, synthetic_root)
            synthetic = _run_index_worker(synthetic_root, ("synthetic",), scale=10)
    return current, synthetic


def _run_index_worker(
    repo_root: Path,
    roots: tuple[str, ...],
    *,
    scale: int,
) -> IndexEvidence:
    command = [
        sys.executable,
        "-m",
        "trade_py.devtools.layout_performance.worker",
        "index",
        "--repo-root",
        str(repo_root),
    ]
    for root in roots:
        command.extend(("--root", root))
    outcome = run_process(
        tuple(command),
        cwd=Path(__file__).resolve().parents[3],
        timeout_seconds=120,
        output_limit_bytes=64 * 1024,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        },
    )
    if outcome.timed_out:
        raise RuntimeError("layout source-index worker exceeded 120 seconds")
    if outcome.cleanup_survivors:
        raise RuntimeError("layout source-index worker left residual processes")
    payload = json.loads(outcome.stdout)
    return IndexEvidence(
        scale=scale,
        source_count=_positive_int(payload, "source_count"),
        source_bytes=_positive_int(payload, "source_bytes"),
        duration_ms=_non_negative_float(payload, "duration_ms"),
        peak_rss_bytes=_positive_int(payload, "peak_rss_bytes"),
        scan_count=_positive_int(payload, "scan_count"),
    )


def _build_synthetic_repo(source_root: Path, target_root: Path) -> None:
    source_paths = _tracked_source_paths(source_root)
    if not source_paths:
        raise RuntimeError("current repository has no tracked production Python source")
    target_root.mkdir(parents=True)
    run_process(("git", "init", "-q"), cwd=target_root, timeout_seconds=10)
    source_bytes = 0
    file_count = 0
    for replica in range(10):
        for relative in source_paths:
            source = read_regular_relative(
                source_root,
                relative,
                max_bytes=MAX_SOURCE_FILE_BYTES,
            )
            source_bytes += len(source)
            file_count += 1
            if source_bytes > MAX_SYNTHETIC_SOURCE_BYTES or file_count > MAX_SYNTHETIC_FILES:
                raise RuntimeError("synthetic 10x source exceeds its reviewed budget")
            target = target_root / "synthetic" / f"r{replica:02d}" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source)
    run_process(
        ("git", "add", "--", "synthetic"),
        cwd=target_root,
        timeout_seconds=60,
        output_limit_bytes=64 * 1024,
    )


def _tracked_source_paths(repo_root: Path) -> tuple[str, ...]:
    outcome = run_process(
        ("git", "ls-files", "-z", "--", *INCLUDED_ROOTS),
        cwd=repo_root,
        timeout_seconds=10,
        output_limit_bytes=MAX_GIT_OUTPUT_BYTES,
    )
    paths: list[str] = []
    for raw in outcome.stdout.split(b"\0"):
        if not raw:
            continue
        value = raw.decode("utf-8", "strict")
        path = PurePosixPath(value)
        if _is_source(path):
            paths.append(path.as_posix())
    return tuple(sorted(paths))


def _is_source(path: PurePosixPath) -> bool:
    if path.suffix not in SOURCE_SUFFIXES:
        return False
    if any(part in SOURCE_EXCLUDED_SEGMENTS for part in path.parts):
        return False
    return not any(path.match(pattern) for pattern in SOURCE_EXCLUDED_NAME_PATTERNS)


def _positive_int(payload: object, key: str) -> int:
    if not isinstance(payload, dict):
        raise TypeError("worker evidence must be an object")
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise TypeError(f"worker evidence {key} must be positive")
    return value


def _non_negative_float(payload: object, key: str) -> float:
    if not isinstance(payload, dict):
        raise TypeError("worker evidence must be an object")
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise TypeError(f"worker evidence {key} must be non-negative")
    return float(value)


__all__ = ["INCLUDED_ROOTS", "capture_index_evidence"]
