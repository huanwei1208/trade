from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from trade_py.data.access.gateway import DataGateway
from trade_py.data.market.kline.akshare import KlineFetcher
from trade_py.utils.data_inspector import _resolve_kline_glob, kline_coverage_stats, kline_stats


def _frame(symbol: str, dates: list[str]) -> pd.DataFrame:
    rows = []
    for idx, d in enumerate(dates, start=1):
        rows.append(
            {
                "symbol": symbol,
                "date": d,
                "open": float(idx),
                "high": float(idx) + 0.5,
                "low": float(idx) - 0.5,
                "close": float(idx),
                "volume": float(100 * idx),
                "amount": float(1000 * idx),
                "turnover_rate": float(idx) / 10,
                "prev_close": float(idx) - 0.1,
                "vwap": float(idx),
            }
        )
    return pd.DataFrame(rows)


def test_save_parquet_writes_flat_file_and_manifest(tmp_path: Path) -> None:
    fetcher = KlineFetcher(tmp_path)
    frame = _frame("000001.SZ", ["2026-01-02", "2026-02-03"])

    fetcher.save_parquet("000001.SZ", frame)

    flat_path = tmp_path / "market" / "kline" / "000001_SZ.parquet"
    manifest_path = tmp_path / "market" / "kline" / "_manifest.json"
    assert flat_path.exists()
    assert manifest_path.exists()
    assert not (tmp_path / "market" / "kline" / "2026-01").exists()

    saved = pd.read_parquet(flat_path)
    assert saved["date"].tolist() == ["2026-01-02", "2026-02-03"]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["entries"]["000001_SZ"]
    assert entry["rows"] == 2
    assert entry["date_min"] == "2026-01-02"
    assert entry["date_max"] == "2026-02-03"
    assert manifest["layout"] == "per_symbol"


def test_save_parquet_merges_legacy_monthly_shards_into_flat(tmp_path: Path) -> None:
    kline_root = tmp_path / "market" / "kline"
    (kline_root / "2026-01").mkdir(parents=True)
    (kline_root / "2026-02").mkdir(parents=True)
    _frame("000001.SZ", ["2026-01-02"]).to_parquet(kline_root / "2026-01" / "000001_SZ.parquet", index=False)
    _frame("000001.SZ", ["2026-02-03"]).to_parquet(kline_root / "2026-02" / "000001_SZ.parquet", index=False)

    fetcher = KlineFetcher(tmp_path)
    fetcher.save_parquet("000001.SZ", _frame("000001.SZ", ["2026-03-04"]))

    saved = pd.read_parquet(kline_root / "000001_SZ.parquet")
    assert saved["date"].tolist() == ["2026-01-02", "2026-02-03", "2026-03-04"]


def test_gateway_prefers_flat_file_then_legacy_months(tmp_path: Path) -> None:
    kline_root = tmp_path / "market" / "kline"
    kline_root.mkdir(parents=True)
    flat = _frame("000001.SZ", ["2026-03-04", "2026-03-05"])
    flat.to_parquet(kline_root / "000001_SZ.parquet", index=False)

    gateway = DataGateway(tmp_path)
    loaded = gateway._load_kline_local("000001.SZ")
    assert loaded["date"].tolist() == ["2026-03-04", "2026-03-05"]

    (kline_root / "000001_SZ.parquet").unlink()
    (kline_root / "2026-03").mkdir()
    _frame("000001.SZ", ["2026-03-04"]).to_parquet(kline_root / "2026-03" / "000001_SZ.parquet", index=False)
    loaded_legacy = gateway._load_kline_local("000001.SZ")
    assert loaded_legacy["date"].tolist() == ["2026-03-04"]


def test_inspector_prefers_manifest_for_stats_and_coverage(tmp_path: Path) -> None:
    fetcher = KlineFetcher(tmp_path)
    fetcher._db.upsert_instrument("000001.SZ", "Ping An")
    fetcher._db.upsert_instrument("000002.SZ", "Vanke")
    fetcher.save_parquet("000001.SZ", _frame("000001.SZ", ["2026-01-02", "2026-01-03"]))

    stats = kline_stats(tmp_path)
    coverage = kline_coverage_stats(tmp_path)

    assert stats["manifest"] is True
    assert stats["symbols"] == 1
    assert stats["rows"] == 2
    assert coverage["source"] == "manifest"
    assert coverage["missing_symbols"] == 1
    assert coverage["missing_sample"] == ["000002.SZ"]


def test_resolve_kline_glob_prefers_top_level_flat_files(tmp_path: Path) -> None:
    kline_root = tmp_path / "market" / "kline"
    kline_root.mkdir(parents=True)
    _frame("000001.SZ", ["2026-01-02"]).to_parquet(kline_root / "000001_SZ.parquet", index=False)
    (kline_root / "2026-01").mkdir()
    _frame("000001.SZ", ["2026-01-02"]).to_parquet(kline_root / "2026-01" / "000001_SZ.parquet", index=False)

    glob = _resolve_kline_glob(tmp_path)
    assert glob.endswith("market/kline/*.parquet")
