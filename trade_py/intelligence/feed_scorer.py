"""FeedScorer: compute data quality metrics per source from Bronze/Silver/PipelineDb."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.data.pipeline.paths import bronze_path, bronze_root
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

    bronze_base = bronze_root(data_root) / source_id

    days_with_data = 0
    total_records = 0
    total_dup_hashes = 0
    timeliness_values: list[float] = []

    cur = start_date
    while cur <= end_date:
        p = bronze_path(data_root, source_id, cur)
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
                "WHERE source_id = ? AND fetched_at >= ?",
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
        bronze_base = bronze_root(data_root)
        source_ids = (
            [d.name for d in bronze_base.iterdir() if d.is_dir()]
            if bronze_base.exists()
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

    # Write InfluenceSignal records to TradeDB (EBRT Phase 6)
    try:
        _write_influence_signals(data_root, scores)
    except Exception:
        pass

    return scores


def update_source_reliability(
    source_id: str,
    brier_loss: float,
    lr: float = 0.1,
    db: Any | None = None,
    data_root: Path | None = None,
) -> None:
    """Exponential weight update for per-source reliability based on Brier loss.

    w_new = w_old * exp(-lr * brier_loss), then normalized to [0, 1].

    Args:
        source_id: the source identifier (matches InfluenceSignal.source_id)
        brier_loss: Brier score for this source's recent predictions
        lr: learning rate (default 0.1)
        db: optional TradeDB instance (if None, opens from data_root)
        data_root: optional data root path (used if db is None)
    """
    import math
    from trade_py.db.trade_db import TradeDB

    if db is None and data_root is None:
        return

    owned = False
    if db is None:
        db = TradeDB(data_root)
        owned = True

    try:
        current = db.source_reliability_get(source_id)
        # Exponential update: w * exp(-lr * brier); brier in [0,1], lr in (0,1)
        updated = current * math.exp(-lr * float(brier_loss))
        # Clip to [0.01, 1.0] — never fully zero
        updated = max(0.01, min(1.0, round(updated, 6)))
        from datetime import date
        db.source_reliability_upsert(source_id, updated, date.today().isoformat())
    finally:
        if owned:
            db.close()


def get_source_reliability(
    source_id: str,
    data_root: Path,
) -> float:
    """Get the current reliability score for a source."""
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(data_root)
    try:
        return db.source_reliability_get(source_id)
    finally:
        db.close()


def _write_influence_signals(data_root: Path, scores: list[FeedScore]) -> None:
    """Write InfluenceSignal rows from FeedScore results.

    reputation_score = reliability × uniqueness
    cross_confirm_1h = signal_density (proxy for cross-source confirmation)
    """
    import hashlib
    from datetime import datetime, timezone

    from trade_py.db.trade_db import TradeDB

    if not scores:
        return

    db = TradeDB(data_root)
    try:
        published_at = datetime.now(timezone.utc).isoformat()
        for score in scores:
            reputation = round(
                float(score.reliability) * float(score.uniqueness), 4
            )
            cross_confirm = round(float(score.signal_density), 4)
            manipulation_risk = round(
                max(0.0, 1.0 - float(score.uniqueness)), 4
            )
            influence_id = hashlib.md5(
                f"{score.feed_name}:{published_at[:10]}".encode()
            ).hexdigest()
            with db._conn_lock:
                db._conn.execute(
                    "INSERT OR REPLACE INTO InfluenceSignal "
                    "(influence_id, source_id, platform, published_at, "
                    " reputation_score, manipulation_risk, "
                    " cross_confirm_1h, cross_confirm_24h) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        influence_id,
                        score.feed_name,
                        "rss",
                        published_at,
                        reputation,
                        manipulation_risk,
                        cross_confirm,
                        round(cross_confirm * 0.8, 4),
                    ),
                )
                db._conn.commit()
    finally:
        db.close()
