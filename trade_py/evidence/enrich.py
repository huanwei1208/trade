"""Evidence enrich: Bronze → Silver per-article sentiment scoring."""
from __future__ import annotations

from typing import Any


def run_enrich(
    asof_date: str | None = None,
    data_root: str | None = None,
    *,
    mode: str = "base",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Run Silver-layer enrichment: per-article sentiment scoring.

    Args:
        asof_date: target date (YYYY-MM-DD), defaults to today
        data_root: path to data root
        mode:      semantic scoring mode "base" | "hybrid" | "llm"
        date_from: optional window start
        date_to:   optional window end

    Returns:
        dict with summary and file count.
    """
    from trade_py.infra.settings import default_data_root
    from datetime import date
    _data_root = data_root or str(default_data_root())
    _asof = asof_date or date.today().isoformat()

    try:
        from trade_py.engine import build_silver
        result = build_silver(
            asof_date=_asof,
            data_root=_data_root,
            semantic_mode=mode,
            date_from=date_from,
            date_to=date_to,
        )
        return result if isinstance(result, dict) else {"summary": str(result)}
    except Exception as exc:
        return {"summary": f"enrich failed: {exc}", "error": str(exc)}
