"""Provider protocol and argv batching helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from trade_py.devtools.quality.config import QualityConfig
from trade_py.devtools.quality.models import CheckStep, GateMode


@dataclass(frozen=True)
class ProviderContext:
    repo_root: Path
    config: QualityConfig
    mode: GateMode
    all_mode: bool


class QualityProvider(Protocol):
    name: str

    def matches(self, path: str) -> bool: ...

    def plan(self, files: tuple[str, ...], context: ProviderContext) -> tuple[CheckStep, ...]: ...


def batched_paths(
    files: tuple[str, ...],
    *,
    argv_prefix: tuple[str, ...],
    max_bytes: int,
) -> tuple[tuple[str, ...], ...]:
    """Keep subprocess argv comfortably below platform limits."""
    base_bytes = sum(len(part.encode("utf-8", "surrogateescape")) + 1 for part in argv_prefix)
    batches: list[tuple[str, ...]] = []
    current: list[str] = []
    current_bytes = base_bytes
    for path in files:
        path_bytes = len(path.encode("utf-8", "surrogateescape")) + 1
        if current and current_bytes + path_bytes > max_bytes:
            batches.append(tuple(current))
            current = []
            current_bytes = base_bytes
        if current_bytes + path_bytes > max_bytes:
            raise ValueError(f"Path exceeds quality argv budget: {path!r}")
        current.append(path)
        current_bytes += path_bytes
    if current:
        batches.append(tuple(current))
    return tuple(batches)


def batch_id(base: str, index: int, total: int) -> str:
    return base if total == 1 else f"{base}.{index + 1:03d}"
