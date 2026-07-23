"""Read-only, evidence-based design quality evaluation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trade_py.devtools.design_quality.evaluate import evaluate_change, evaluate_changes
    from trade_py.devtools.design_quality.models import DesignReport, Finding, Severity

__all__ = ["DesignReport", "Finding", "Severity", "evaluate_change", "evaluate_changes"]


def __getattr__(name: str) -> Any:
    if name in {"evaluate_change", "evaluate_changes"}:
        from trade_py.devtools.design_quality import evaluate

        value = getattr(evaluate, name)
    elif name in {"DesignReport", "Finding", "Severity"}:
        from trade_py.devtools.design_quality import models

        value = getattr(models, name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
