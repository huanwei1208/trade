from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from trade_py.bus import Event, _dag_row_config, _make_dag_handler
from trade_py.data.ingest.base import IngestResult
from trade_py.data.ingest.batch import (
    BatchIngestEngine,
    ExistingDataReadError,
    WalReadError,
)
from trade_py.db.trade_db import TradeDB
from trade_py.jobs import _job_asset_batch_ingest


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any], int | None]] = []

    def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        parent_event_id: int | None = None,
    ) -> None:
        self.published.append((topic, payload, parent_event_id))


def _event(db: TradeDB, bus: _RecordingBus, topic: str) -> Event:
    event_id = db.event_log_insert(topic, "{}", None)
    return Event(
        id=event_id,
        topic=topic,
        payload={},
        parent_event_id=None,
        created_at=pd.Timestamp("2026-07-16T00:00:00Z").to_pydatetime(),
        bus=bus,  # type: ignore[arg-type]
    )


def test_v22_assigns_btc_to_assurance_writer_and_excludes_generic_ingest(tmp_path) -> None:
    db = TradeDB(tmp_path)

    version = db._conn.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0]
    assert version == 22

    btc = db.asset_registry_get("crypto.BTC")
    assert btc is not None
    assert btc["config"]["canonical_writer"] == "btc_assurance"

    crypto_rows = db._conn.execute(
        "SELECT config_json, description FROM pipeline_dag "
        "WHERE job_name='asset_batch_ingest' AND source='gate.crypto_daily'"
    ).fetchall()
    assert len(crypto_rows) == 1
    config = json.loads(crypto_rows[0][0])
    assert config == {"asset_class": "crypto", "exclude_symbols": ["BTC"]}
    assert "非 BTC" in crypto_rows[0][1]


def test_each_dag_row_keeps_its_exact_config_and_unique_handler_identity(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = TradeDB(tmp_path)
    rows = db._conn.execute(
        "SELECT * FROM pipeline_dag "
        "WHERE job_name='asset_batch_ingest' AND source='gate.morning' ORDER BY id"
    ).fetchall()
    assert len(rows) == 2

    calls: list[dict[str, Any]] = []

    def fake_run_job(name: str, data_root: str, **kwargs: Any) -> str:
        calls.append({"name": name, "data_root": data_root, **kwargs})
        return f"ok:{kwargs['config']['asset_class']}"

    monkeypatch.setattr("trade_py.jobs.run_job", fake_run_job)
    bus = _RecordingBus()
    handlers = []
    for sqlite_row in rows:
        row = dict(sqlite_row)
        handler = _make_dag_handler(
            db,
            dag_id=int(row["id"]),
            job_name=row["job_name"],
            emits=row["emits"],
            stage=row["stage"],
            data_root=str(tmp_path),
            config=_dag_row_config(row),
        )
        handlers.append(handler)
        handler(_event(db, bus, row["source"]))

    assert len({handler.__qualname__ for handler in handlers}) == 2
    assert [call["config"] for call in calls] == [
        {"asset_class": "commodity"},
        {"asset_class": "fx"},
    ]


def test_generic_ingest_never_mutates_btc_canonical_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = TradeDB(tmp_path)
    engine = BatchIngestEngine(tmp_path, db=db)
    btc = db.asset_registry_get("crypto.BTC")
    assert btc is not None
    canonical = engine._asset_output_path(btc)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_bytes(b"assurance-owned-sentinel")
    monkeypatch.setattr(engine, "_ensure_migration", lambda: None)

    results = engine.ingest_by_class("crypto", symbols=["BTC"])

    assert results == []
    assert canonical.read_bytes() == b"assurance-owned-sentinel"


def test_corrupt_existing_parquet_and_wal_fail_closed(tmp_path) -> None:
    db = TradeDB(tmp_path)
    engine = BatchIngestEngine(tmp_path, db=db)
    eth = db.asset_registry_get("crypto.ETH")
    assert eth is not None

    canonical = engine._asset_output_path(eth)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_bytes(b"corrupt-main")
    with pytest.raises(ExistingDataReadError, match="refusing overwrite"):
        engine._load_existing(canonical)
    assert canonical.read_bytes() == b"corrupt-main"

    wal_path = engine._wal_path("crypto.ETH")
    wal_path.parent.mkdir(parents=True, exist_ok=True)
    wal_path.write_bytes(b"corrupt-wal")
    frame = pd.DataFrame(
        [{"date": "2026-07-15", "open": 1, "high": 2, "low": 1, "close": 2}]
    )
    with pytest.raises(WalReadError, match="refusing overwrite"):
        engine._wal_append("crypto.ETH", frame)
    assert wal_path.read_bytes() == b"corrupt-wal"


def test_flush_failure_is_reported_and_buffer_is_kept_for_retry(tmp_path) -> None:
    db = TradeDB(tmp_path)
    engine = BatchIngestEngine(tmp_path, db=db)
    eth = db.asset_registry_get("crypto.ETH")
    assert eth is not None
    canonical = engine._asset_output_path(eth)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_bytes(b"corrupt-main")
    engine._write_buffers["crypto.ETH"] = pd.DataFrame(
        [{"date": "2026-07-15", "open": 1, "high": 2, "low": 1, "close": 2}]
    )

    errors = engine._flush_all()

    assert "crypto.ETH" in errors
    assert "crypto.ETH" in engine._write_buffers
    assert canonical.read_bytes() == b"corrupt-main"


def test_empty_provider_response_requires_current_watermark(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = TradeDB(tmp_path)
    engine = BatchIngestEngine(tmp_path, db=db)
    eth = db.asset_registry_get("crypto.ETH")
    assert eth is not None

    class EmptyIngestor:
        def fetch(self, asset: dict, **kwargs: Any) -> pd.DataFrame:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close"])

        def validate_frame(self, frame: pd.DataFrame, asset_id: str) -> None:
            return None

    monkeypatch.setattr("trade_py.data.ingest.batch.get_ingestor", lambda venue: EmptyIngestor())
    engine.config.retry_max_attempts = 1
    engine.config.retry_base_delay_s = 0

    missing = engine._ingest_single_asset(eth)
    assert missing.success is False
    assert "provider returned zero rows" in str(missing.error)

    current = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)).date().isoformat()
    canonical = engine._asset_output_path(eth)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [{"date": current, "open": 1, "high": 2, "low": 1, "close": 2}]
    ).to_parquet(canonical, index=False)
    ready = engine._ingest_single_asset(eth)
    assert ready.success is True
    assert ready.new_rows == 0
    assert ready.metadata == {"outcome": "already_current"}


@pytest.mark.parametrize(
    "results, message",
    [
        ([], "No eligible assets selected"),
        (
            [
                IngestResult(asset_id="crypto.ETH", success=True),
                IngestResult(asset_id="crypto.SOL", success=False, error="provider timeout"),
            ],
            "Asset ingest incomplete",
        ),
    ],
)
def test_asset_batch_job_rejects_zero_target_and_partial_success(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    results: list[IngestResult],
    message: str,
) -> None:
    class FakeEngine:
        def __init__(self, data_root: str) -> None:
            self.data_root = Path(data_root)

        def ingest_by_class(self, **kwargs: Any) -> list[IngestResult]:
            return results

        def stop(self) -> None:
            return None

    monkeypatch.setattr("trade_py.data.ingest.batch.BatchIngestEngine", FakeEngine)

    with pytest.raises(RuntimeError, match=message):
        _job_asset_batch_ingest(str(tmp_path), {"asset_class": "crypto"})
