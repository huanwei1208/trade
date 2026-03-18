"""Evidence ingest: wrap Bronze-layer article ingestion.

Delegates to the sentiment CLI pipeline (incremental or streaming mode).
"""
from __future__ import annotations

from typing import Any


def run_ingest(
    date_from: str | None = None,
    date_to: str | None = None,
    data_root: str | None = None,
    *,
    source: str = "rss",
    fetch_mode: str = "incremental",
    semantic_mode: str = "base",
) -> dict[str, Any]:
    """Run Bronze-layer article ingestion.

    Args:
        date_from: start date (YYYY-MM-DD), None = last 3 days
        date_to:   end date   (YYYY-MM-DD), None = today
        data_root: path to data root (default: infra.settings.default_data_root)
        source:    feed source id (default "rss")
        fetch_mode: "incremental" | "streaming"
        semantic_mode: "base" | "hybrid" | "llm"

    Returns:
        dict with summary and article count.
    """
    from trade_py.infra.settings import default_data_root
    _data_root = data_root or str(default_data_root())

    try:
        from trade_py.engine import ingest_articles
        result = ingest_articles(
            source=source,
            data_root=_data_root,
            fetch_mode=fetch_mode,
            semantic_mode=semantic_mode,
            date_from=date_from,
            date_to=date_to,
        )
        return result if isinstance(result, dict) else {"summary": str(result)}
    except Exception as exc:
        return {"summary": f"ingest failed: {exc}", "error": str(exc)}
