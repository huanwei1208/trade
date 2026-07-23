"""Read-only aggregation of active OpenSpec workflow evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trade_py.devtools.openspec_status.service import collect_workflow

__all__ = ["collect_workflow"]


def __getattr__(name: str) -> Any:
    if name != "collect_workflow":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from trade_py.devtools.openspec_status.service import collect_workflow

    globals()[name] = collect_workflow
    return collect_workflow
