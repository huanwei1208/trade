"""Evidence aggregate: Silver → Gold per-symbol/date sentiment aggregation."""
from __future__ import annotations

from typing import Any


def run_aggregate(
    asof_date: str | None = None,
    data_root: str | None = None,
) -> dict[str, Any]:
    """Run Gold-layer aggregation: per-symbol/date sentiment with EMA smoothing.

    After base aggregation, applies EMA smoothing via evidence.quality module.

    Args:
        asof_date: target date (YYYY-MM-DD), defaults to today
        data_root: path to data root

    Returns:
        dict with summary, file count, and smoothed symbols count.
    """
    from trade_py.infra.settings import default_data_root
    from datetime import date
    _data_root = data_root or str(default_data_root())
    _asof = asof_date or date.today().isoformat()

    try:
        from trade_py.engine import build_gold
        result = build_gold(asof_date=_asof, data_root=_data_root)
        base_summary = result if isinstance(result, dict) else {"summary": str(result)}
    except Exception as exc:
        base_summary = {"summary": f"aggregate failed: {exc}", "error": str(exc)}

    # Apply EMA smoothing (Gold-level denoising)
    smoothed = 0
    try:
        from trade_py.evidence.quality import smooth_gold_sentiment
        smooth_result = smooth_gold_sentiment(asof_date=_asof, data_root=_data_root)
        smoothed = smooth_result.get("smoothed_symbols", 0)
    except Exception:
        pass

    return {**base_summary, "smoothed_symbols": smoothed}
