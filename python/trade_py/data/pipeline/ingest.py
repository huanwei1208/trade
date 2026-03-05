"""Bronze ingestion: Source → Bronze Parquet + pipeline state update."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

import pandas as pd

from trade_py.data.source import DataSource, RawRecord
from trade_py.db.pipeline_db import PipelineDb

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def _bronze_path(data_root: Path, source_id: str, d: date) -> Path:
    y, m, day = d.year, d.month, d.day
    return (data_root / "raw" / "sentiment" / source_id
            / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{day:02d}.parquet")


def _upsert_parquet(path: Path, new_df: pd.DataFrame,
                    key_cols: list[str]) -> int:
    """Merge new_df into existing parquet. Returns count of net-new rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_parquet(path)
        old_len = len(existing)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=key_cols, keep="last")
        new_count = len(combined) - old_len
    else:
        combined = new_df
        new_count = len(new_df)
    combined.to_parquet(path, index=False)
    return max(0, new_count)


def _load_existing_hashes(data_root: Path, source_id: str,
                           since_date: date, until_date: date) -> set[str]:
    """Return all content_hashes already stored in Bronze for this source+range."""
    hashes: set[str] = set()
    cur = since_date
    while cur <= until_date:
        path = _bronze_path(data_root, source_id, cur)
        if path.exists():
            df = pd.read_parquet(path, columns=["content_hash"])
            hashes.update(df["content_hash"].dropna().tolist())
        cur += timedelta(days=1)
    return hashes


def ingest(
    source: DataSource,
    since: datetime,
    until: datetime,
    data_root: Path,
    db: PipelineDb,
    diagnostics_out: list | None = None,
    progress_cb=None,
) -> dict:
    """Fetch records from source, write Bronze Parquet, update pipeline state.

    Args:
        source: Any DataSource implementation.
        since/until: Inclusive fetch window (timezone-aware datetime).
        data_root: Root data directory.
        db: PipelineDb instance for state recording.
        diagnostics_out: If provided, fetch diagnostics are appended here.
        progress_cb: Optional callable(msg: str) for real-time progress output.

    Returns:
        Summary dict: records_fetched, records_new, records_skipped, by_date, error.
    """
    import inspect as _inspect

    since_date = since.astimezone(CST).date()
    until_date = until.astimezone(CST).date()

    # Load hashes already in Bronze — sources can use them for early-stop
    known_hashes = _load_existing_hashes(data_root, source.source_id,
                                          since_date, until_date)
    if known_hashes and progress_cb:
        progress_cb(f"[{source.source_id}] {len(known_hashes)} articles already in bronze")

    # Build kwargs supported by the concrete fetch method
    def _supported_kwargs(fn) -> dict:
        params = set(_inspect.signature(fn).parameters)
        kw: dict = {}
        if "known_hashes" in params:
            kw["known_hashes"] = known_hashes
        if "progress_cb" in params:
            kw["progress_cb"] = progress_cb
        return kw

    # Call fetch — support optional diagnostics extension
    try:
        fetch_with_diag = getattr(source, "fetch_with_diagnostics", None)
        if fetch_with_diag is not None and diagnostics_out is not None:
            records, diag = fetch_with_diag(since, until,
                                             **_supported_kwargs(fetch_with_diag))
            if isinstance(diag, list):
                diagnostics_out.extend(diag)
            elif isinstance(diag, dict):
                diagnostics_out.append(diag)
        else:
            records = source.fetch(since, until, **_supported_kwargs(source.fetch))
        status = "ok"
        error = ""
    except Exception as exc:
        logger.error("Ingest failed for %s: %s", source.source_id, exc)
        db.record_run(source.source_id, since_date, until_date, 0, 0, "error", str(exc))
        return {"records_fetched": 0, "records_new": 0, "records_skipped": 0,
                "by_date": {}, "error": str(exc)}

    # Filter out already-known records (source may not have done this itself)
    new_records = [r for r in records if r.content_hash not in known_hashes]
    skipped = len(records) - len(new_records)

    # Group new records by CST date
    by_date: dict[date, list[dict]] = defaultdict(list)
    for r in new_records:
        d = r.published_at.astimezone(CST).date()
        if d < since_date or d > until_date:
            continue
        by_date[d].append({
            "source": r.source_id,
            "url": r.url,
            "title": r.title,
            "text": r.text,
            "published_at": r.published_at.isoformat(),
            "content_hash": r.content_hash,
        })

    total_new = 0
    bronze_counts: dict[str, int] = {}
    for d, rows in by_date.items():
        df = pd.DataFrame(rows)
        path = _bronze_path(data_root, source.source_id, d)
        new_count = _upsert_parquet(path, df, key_cols=["content_hash"])
        total_new += new_count
        bronze_counts[d.isoformat()] = len(rows)
        db.update_coverage(source.source_id, d, len(rows))
        logger.info("Bronze %s %s: %d articles (%d new)",
                    source.source_id, d, len(rows), new_count)

    if progress_cb:
        progress_cb(f"[{source.source_id}] done: "
                    f"{len(records)} fetched, {total_new} new, {skipped} skipped")

    db.record_run(
        source.source_id, since_date, until_date,
        len(records), total_new, status, error,
    )
    return {
        "records_fetched": len(records),
        "records_new": total_new,
        "records_skipped": skipped,
        "by_date": bronze_counts,
        "error": "",
    }
