from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path

import pandas as pd

from trade_py.data.access.gateway import DataGateway


def _tree(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def test_cross_asset_reads_only_the_canonical_market_path(tmp_path: Path) -> None:
    canonical_dir = tmp_path / "market" / "cross_asset"
    canonical_dir.mkdir(parents=True)
    expected = pd.DataFrame(
        {
            "date": ["2026-07-07", "2026-07-08"],
            "open": [108_000.0, 109_000.0],
            "high": [110_000.0, 111_000.0],
            "low": [107_000.0, 108_000.0],
            "close": [109_000.0, 110_000.0],
        }
    )
    expected.to_parquet(canonical_dir / "btc.parquet", index=False)
    btc_path = canonical_dir / "btc.parquet"
    (canonical_dir / "btc_current.json").write_text(
        json.dumps(
            {
                "run_id": "fixture-current",
                "canonical_sha256": hashlib.sha256(btc_path.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    before = _tree(tmp_path)

    gateway = DataGateway(tmp_path)
    actual, report = gateway.get_cross_asset("btc")

    pd.testing.assert_frame_equal(actual, expected)
    assert report.action == "hit_local"
    assert report.degraded is False
    assert report.reason_code == ""
    assert report.local_range == "2026-07-07..2026-07-08"
    assert report.api_calls_est == 0
    assert report.api_calls_actual == 0
    assert _tree(tmp_path) == before
    assert not (tmp_path / ".db").exists()
    assert not (tmp_path / ".metadata").exists()


def test_cross_asset_missing_file_degrades_without_creating_data_root(tmp_path: Path) -> None:
    data_root = tmp_path / "missing-data-root"

    gateway = DataGateway(data_root)
    frame, report = gateway.get_cross_asset("btc")

    assert frame.empty
    assert report.action == "degraded"
    assert report.degraded is True
    assert report.reason_code == "no_local_data"
    assert report.api_endpoint == ""
    assert report.api_calls_est == 0
    assert report.api_calls_actual == 0
    assert not data_root.exists()


def test_cross_asset_fx_alias_reads_existing_legacy_file(tmp_path: Path) -> None:
    canonical_dir = tmp_path / "cross_asset"
    canonical_dir.mkdir(parents=True)
    expected = pd.DataFrame({"date": ["2026-07-08"], "close": [7.18]})
    expected.to_parquet(canonical_dir / "fx_cnh.parquet", index=False)
    before = _tree(tmp_path)

    actual, report = DataGateway(tmp_path).get_cross_asset("fx")

    pd.testing.assert_frame_equal(actual, expected)
    assert report.degraded is False
    assert _tree(tmp_path) == before


def test_cross_asset_gold_prefers_the_writer_path_without_mutating_legacy_data(
    tmp_path: Path,
) -> None:
    canonical_dir = tmp_path / "market" / "cross_asset"
    legacy_dir = tmp_path / "cross_asset"
    canonical_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    expected = pd.DataFrame({"date": ["2026-07-08"], "close": [782.5]})
    legacy = pd.DataFrame({"date": ["2026-07-07"], "close": [780.0]})
    expected.to_parquet(canonical_dir / "gold.parquet", index=False)
    legacy.to_parquet(legacy_dir / "gold.parquet", index=False)
    before = _tree(tmp_path)

    actual, report = DataGateway(tmp_path).get_cross_asset("gold")

    pd.testing.assert_frame_equal(actual, expected)
    assert report.degraded is False
    assert report.local_range == "2026-07-08..2026-07-08"
    assert _tree(tmp_path) == before


def test_cross_asset_read_error_degrades_without_metadata_writes(tmp_path: Path) -> None:
    canonical_dir = tmp_path / "market" / "cross_asset"
    canonical_dir.mkdir(parents=True)
    (canonical_dir / "btc.parquet").write_text("not parquet", encoding="utf-8")
    before = _tree(tmp_path)

    gateway = DataGateway(tmp_path)
    frame, report = gateway.get_cross_asset("btc")

    assert frame.empty
    assert report.action == "degraded"
    assert report.degraded is True
    assert report.reason_code == "read_error"
    assert report.error
    assert _tree(tmp_path) == before
    assert not (tmp_path / ".db").exists()
    assert not (tmp_path / ".metadata").exists()


def test_cross_asset_btc_pointer_mismatch_never_serves_partial_publish(tmp_path: Path) -> None:
    canonical_dir = tmp_path / "market" / "cross_asset"
    canonical_dir.mkdir(parents=True)
    pd.DataFrame({"date": ["2026-07-08"], "close": [100.0]}).to_parquet(
        canonical_dir / "btc.parquet",
        index=False,
    )
    (canonical_dir / "btc_current.json").write_text(
        json.dumps({"run_id": "old", "canonical_sha256": "0" * 64}),
        encoding="utf-8",
    )
    before = _tree(tmp_path)

    frame, report = DataGateway(tmp_path).get_cross_asset("btc")

    assert frame.empty
    assert report.degraded is True
    assert report.reason_code == "read_error"
    assert "current pointer" in report.error
    assert _tree(tmp_path) == before


def test_cross_asset_btc_parses_the_same_snapshot_that_was_hash_verified(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical_dir = tmp_path / "market" / "cross_asset"
    canonical_dir.mkdir(parents=True)
    btc_path = canonical_dir / "btc.parquet"
    old = pd.DataFrame({"date": ["2026-07-08"], "close": [100.0]})
    new = pd.DataFrame({"date": ["2026-07-08"], "close": [999.0]})
    old.to_parquet(btc_path, index=False)
    (canonical_dir / "btc_current.json").write_text(
        json.dumps(
            {
                "run_id": "old",
                "canonical_sha256": hashlib.sha256(btc_path.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    original_read_bytes = Path.read_bytes
    swapped = False

    def swap_after_snapshot(path: Path) -> bytes:
        nonlocal swapped
        snapshot = original_read_bytes(path)
        if path == btc_path and not swapped:
            swapped = True
            replacement = canonical_dir / ".replacement.parquet"
            new.to_parquet(replacement, index=False)
            replacement.replace(btc_path)
        return snapshot

    monkeypatch.setattr(Path, "read_bytes", swap_after_snapshot)

    frame, report = DataGateway(tmp_path).get_cross_asset("btc")

    pd.testing.assert_frame_equal(frame, old)
    assert report.degraded is False
    assert pd.read_parquet(btc_path).loc[0, "close"] == 999.0


def test_non_cross_asset_repair_reporting_initializes_metadata_lazily(
    tmp_path: Path,
    monkeypatch,
) -> None:
    gateway = DataGateway(tmp_path)
    assert not (tmp_path / ".db").exists()

    monkeypatch.setattr(gateway, "_attempt_kline_fill", lambda _symbol: (False, "test_failure"))
    frame, report = gateway.get_kline("000001.SZ", end_date=date(2026, 7, 8))

    assert frame.empty
    assert report.degraded is True
    assert (tmp_path / ".db" / "trade.db").is_file()
