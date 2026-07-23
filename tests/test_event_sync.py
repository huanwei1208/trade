from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from trade_py.data.pipeline.paths import bronze_path
from trade_py.db.settings_db import SettingsDB
from trade_py.event.service import sync_events
from trade_py.intelligence.clients.base import parse_result


def _silver_path(data_root: Path, d: date) -> Path:
    return data_root / "sentiment" / "silver" / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.isoformat()}.parquet"


def test_sync_events_treats_empty_event_dates_as_complete(tmp_path: Path) -> None:
    target = date(2026, 1, 1)
    silver = pd.DataFrame(
        [
            {
                "date": target.isoformat(),
                "symbol": "_MARKET_",
                "event_type": "other",
                "event_magnitude": 0.9,
                "affected_sectors": "",
                "sentiment_score": 0.3,
                "content_hash": "h1",
                "summary": "no-op",
            }
        ]
    )
    path = _silver_path(tmp_path, target)
    path.parent.mkdir(parents=True, exist_ok=True)
    silver.to_parquet(path, index=False)

    summary = sync_events(str(tmp_path), start=target.isoformat(), end=target.isoformat())

    assert summary.scanned_dates == 1
    assert summary.dates_with_silver == 1
    assert summary.empty_dates == 1
    assert summary.synced_events == 0
    assert SettingsDB(str(tmp_path)).get_events(limit=10) == []


def test_sync_events_is_idempotent_for_non_kg_events(tmp_path: Path) -> None:
    target = date(2026, 1, 2)
    silver = pd.DataFrame(
        [
            {
                "date": target.isoformat(),
                "symbol": "_MARKET_",
                "event_type": "earnings_miss",
                "event_magnitude": 0.8,
                "affected_sectors": "SW_Electronics",
                "sentiment_score": -0.5,
                "content_hash": "h2",
                "summary": "earnings miss",
            }
        ]
    )
    path = _silver_path(tmp_path, target)
    path.parent.mkdir(parents=True, exist_ok=True)
    silver.to_parquet(path, index=False)

    first = sync_events(str(tmp_path), start=target.isoformat(), end=target.isoformat())
    second = sync_events(str(tmp_path), start=target.isoformat(), end=target.isoformat())

    assert first.synced_events == 1
    assert second.synced_events == 0
    rows = SettingsDB(str(tmp_path)).get_events(limit=10)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "earnings_miss"
    assert rows[0]["affected_stocks"] == 0


def test_sync_events_reports_legacy_silver_taxonomy(tmp_path: Path) -> None:
    target = date(2026, 1, 4)
    silver = pd.DataFrame(
        [
            {
                "date": target.isoformat(),
                "symbol": "_MARKET_",
                "event_type": "legacy_macro",
                "event_magnitude": 0.8,
                "affected_sectors": "SW_Electronics",
                "sentiment_score": 0.1,
                "content_hash": "h3",
                "summary": "legacy type",
            }
        ]
    )
    path = _silver_path(tmp_path, target)
    path.parent.mkdir(parents=True, exist_ok=True)
    silver.to_parquet(path, index=False)

    summary = sync_events(str(tmp_path), start=target.isoformat(), end=target.isoformat())

    assert summary.empty_dates == 1
    assert summary.legacy_dates == 1


def test_parse_result_rejects_non_taxonomy_event_type() -> None:
    result = parse_result(
        {
            "event_type": "macro",
            "sentiment_score": 0.2,
            "sentiment_label": "neutral",
            "event_magnitude": 0.5,
        },
        model="test",
    )

    assert result.event_type == "other"


def test_bronze_path_is_under_sentiment_directory(tmp_path: Path) -> None:
    target = date(2026, 1, 3)
    path = bronze_path(tmp_path, "rss", target)

    assert path == tmp_path / "sentiment" / "bronze" / "rss" / "2026" / "01" / "2026-01-03.parquet"
