"""FeedScorer: compute data quality metrics per source from Bronze/Silver/PipelineDb."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from trade_py.meta.feed.score import FeedScore


def compute_feed_score(
    source_id: str,
    data_root: Path,
    lookback_days: int = 30,
) -> FeedScore:
    """Compute quality score for a single source from Bronze/Silver data."""
    now = datetime.now(timezone.utc)
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days - 1)

    bronze_base = data_root / "raw" / "sentiment" / source_id

    days_with_data = 0
    total_records = 0
    total_dup_hashes = 0
    timeliness_values: list[float] = []

    cur = start_date
    while cur <= end_date:
        p = bronze_base / f"{cur.year:04d}" / f"{cur.month:02d}" / f"{cur.isoformat()}.parquet"
        if p.exists():
            try:
                df = pd.read_parquet(p)
                n = len(df)
                if n > 0:
                    days_with_data += 1
                    total_records += n
                    if "content_hash" in df.columns:
                        total_dup_hashes += n - df["content_hash"].nunique()
                    if "ingested_at" in df.columns and "published_at" in df.columns:
                        try:
                            ingested = pd.to_datetime(df["ingested_at"], utc=True)
                            published = pd.to_datetime(df["published_at"], utc=True)
                            diff = (ingested - published).dt.total_seconds() / 60
                            valid = diff[(diff >= 0) & (diff < 1440)]
                            timeliness_values.extend(valid.tolist())
                        except Exception:
                            pass
            except Exception:
                pass
        cur += timedelta(days=1)

    coverage_30d = days_with_data / lookback_days
    uniqueness = (1.0 - total_dup_hashes / total_records) if total_records > 0 else 1.0
    timeliness_minutes = float(pd.Series(timeliness_values).median()) if timeliness_values else 60.0

    # Signal density from Silver (filter by source column if present)
    silver_base = data_root / "sentiment" / "silver"
    silver_records = 0
    silver_signal = 0
    cur = start_date
    while cur <= end_date:
        sp = silver_base / f"{cur.year:04d}" / f"{cur.month:02d}" / f"{cur.isoformat()}.parquet"
        if sp.exists():
            try:
                sdf = pd.read_parquet(sp)
                if "source" in sdf.columns:
                    sdf = sdf[sdf["source"].str.lower() == source_id.lower()]
                n = len(sdf)
                if n > 0:
                    silver_records += n
                    label_col = (
                        "sentiment_label" if "sentiment_label" in sdf.columns
                        else "sentiment" if "sentiment" in sdf.columns
                        else None
                    )
                    if label_col:
                        silver_signal += int((sdf[label_col] != "neutral").sum())
            except Exception:
                pass
        cur += timedelta(days=1)

    signal_density = silver_signal / silver_records if silver_records > 0 else 0.0

    # Reliability from PipelineDb.ingest_runs
    reliability = 1.0
    try:
        from trade_py.db.pipeline_db import PipelineDb
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        with PipelineDb(data_root) as db:
            rows = db._con.execute(
                "SELECT status FROM ingest_runs "
                "WHERE source_id = ? AND fetched_at >= TIMESTAMPTZ ?",
                [source_id, cutoff],
            ).fetchall()
        if rows:
            ok_runs = sum(1 for r in rows if r[0] == "ok")
            reliability = ok_runs / len(rows)
    except Exception:
        pass

    timeliness_score = max(0.0, 1.0 - timeliness_minutes / 120.0)
    composite = (
        coverage_30d * 0.25
        + uniqueness * 0.20
        + signal_density * 0.25
        + reliability * 0.20
        + timeliness_score * 0.10
    )

    return FeedScore(
        feed_name=source_id,
        computed_at=now,
        coverage_30d=round(coverage_30d, 4),
        uniqueness=round(uniqueness, 4),
        signal_density=round(signal_density, 4),
        reliability=round(reliability, 4),
        timeliness_minutes=round(timeliness_minutes, 2),
        composite=round(composite, 4),
    )


def score_all_sources(
    data_root: Path,
    source_ids: list[str] | None = None,
) -> list[FeedScore]:
    """Score all registered (or specified) sources and persist to MetaStore."""
    if source_ids is None:
        bronze_root = data_root / "raw" / "sentiment"
        source_ids = (
            [d.name for d in bronze_root.iterdir() if d.is_dir()]
            if bronze_root.exists()
            else []
        )

    scores: list[FeedScore] = []
    for sid in source_ids:
        try:
            score = compute_feed_score(sid, data_root)
            scores.append(score)
        except Exception:
            pass

    try:
        from trade_py.meta.store.duckdb_store import DuckDbMetaStore
        with DuckDbMetaStore(data_root) as store:
            for score in scores:
                store.upsert_feed_score(score)
    except Exception:
        pass

    return scores
