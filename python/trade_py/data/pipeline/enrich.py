"""Silver enrichment: Bronze → Silver Parquet with incremental LLM cache.

Already-processed content_hashes (status='ok' in enrichment_status) are
skipped, making re-runs cheap and safe.
"""

from __future__ import annotations

import logging
from datetime import date, timezone, timedelta
from pathlib import Path

import pandas as pd

from trade_py.db.pipeline_db import PipelineDb

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def _bronze_path(data_root: Path, source_id: str, d: date) -> Path:
    y, m, day = d.year, d.month, d.day
    return (data_root / "raw" / "sentiment" / source_id
            / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{day:02d}.parquet")


def _silver_path(data_root: Path, d: date) -> Path:
    y, m, day = d.year, d.month, d.day
    return (data_root / "sentiment" / "silver"
            / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{day:02d}.parquet")


def _upsert_parquet(path: Path, new_df: pd.DataFrame,
                    key_cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=key_cols, keep="last")
    else:
        combined = new_df
    combined.to_parquet(path, index=False)


def enrich(
    data_root: Path,
    article_date: date,
    sources: list[str],
    client,
    db: PipelineDb,
    dry_run: bool = False,
) -> dict:
    """Read Bronze for article_date, skip cached hashes, call LLM, write Silver.

    Returns:
        Stats dict: bronze_rows, skipped, analysed, silver_rows, model.
    """
    from trade_py.intelligence.enricher import build_silver_rows

    # Read Bronze
    bronze_rows: list[dict] = []
    for source_id in sources:
        path = _bronze_path(data_root, source_id, article_date)
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            bronze_rows.append({
                "content_hash": str(row.get("content_hash", "")),
                "source": str(row.get("source", source_id)),
                "title": str(row.get("title", "")),
                "text": str(row.get("text", "")),
                "published_at": str(row.get("published_at", "")),
            })

    if not bronze_rows:
        logger.info("No Bronze articles for %s", article_date)
        return {"bronze_rows": 0, "skipped": 0, "analysed": 0, "silver_rows": 0}

    if dry_run:
        return {"bronze_rows": len(bronze_rows), "skipped": 0,
                "analysed": 0, "silver_rows": 0, "mode": "dry_run"}

    # Determine which hashes are already enriched (incremental cache)
    all_hashes = [r["content_hash"] for r in bronze_rows if r["content_hash"]]
    already_enriched = db.get_enriched_hashes(all_hashes)

    silver_df, newly_enriched = build_silver_rows(
        bronze_rows=bronze_rows,
        article_date=article_date,
        client=client,
        data_root=data_root,
        already_enriched=already_enriched,
    )

    if not silver_df.empty:
        path = _silver_path(data_root, article_date)
        _upsert_parquet(path, silver_df,
                        key_cols=["date", "symbol", "source", "content_hash"])
        logger.info("Silver %s: wrote %d rows to %s",
                    article_date, len(silver_df), path)

    # Mark newly enriched in DB
    model = getattr(client, "model", "")
    if newly_enriched:
        db.mark_enriched_batch(newly_enriched, model=model)

    return {
        "bronze_rows": len(bronze_rows),
        "skipped": len(already_enriched),
        "analysed": len(newly_enriched),
        "silver_rows": len(silver_df),
        "model": model,
    }
