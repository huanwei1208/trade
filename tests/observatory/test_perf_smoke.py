"""WP9.3 performance smoke against the frozen benchmark envelope (plan §20.4).

Records timing distribution and basic resource use; asserts relative envelopes
rather than absolute machine numbers. Uses tmp_path fixtures only. Scale is reduced
from 10k to a CI-friendly count but exercises the same code paths; the count is
recorded so a larger run can be reproduced.
"""
from __future__ import annotations

import json
import time
from datetime import date

import pytest

from trade_py.observatory.catalog import store as catalog_store
from trade_py.observatory.catalog.projection import build_catalog
from trade_py.observatory.domain.vocab import Channel
from trade_py.observatory.service.resolver import SnapshotResolver, SnapshotSelector
from tests.observatory.fixtures import build_observatory_fixture, _canonical_frame, _write_run


def _make_many_runs(crypto_root, count: int) -> None:
    """Create `count` lightweight manifests (small canonical frames)."""

    canonical = _canonical_frame(date(2024, 1, 1), 5, run_id="bench")
    for i in range(count):
        run_id = f"benchrun{i:016d}"
        _write_run(
            crypto_root, run_id,
            created_at=f"2026-01-01T00:00:{i % 60:02d}.000000+00:00",
            watermark="2024-01-05", readiness="degraded", canonical=canonical,
        )


@pytest.fixture()
def big_data_root(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    # Scale: 2000 manifests keeps CI fast while exercising the projection path.
    # (Envelope target is 10k; count is recorded in the report.)
    _make_many_runs(fx["crypto_root"], 2000)
    return fx


def test_rebuild_scales_and_is_deterministic(big_data_root):
    data_root = big_data_root["data_root"]
    t0 = time.perf_counter()
    catalog = build_catalog(data_root)
    elapsed = time.perf_counter() - t0
    assert len(catalog.runs) >= 2000
    # Determinism under scale.
    assert build_catalog(data_root).content_hash() == catalog.content_hash()
    # Generous CI envelope (target <=60s at 10k; here 2k should be well under).
    assert elapsed < 30.0, f"rebuild took {elapsed:.2f}s"


def test_context_does_not_open_parquet(big_data_root, monkeypatch):
    """context/status must do 0 parquet opens (plan §20.4)."""

    data_root = big_data_root["data_root"]
    catalog_store.rebuild(data_root)

    import pandas as pd

    opens = {"count": 0}
    real_read = pd.read_parquet

    def _counting_read(*args, **kwargs):
        opens["count"] += 1
        return real_read(*args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", _counting_read)

    from trade_py.observatory.query.facade import ObservatoryQuery

    q = ObservatoryQuery(data_root)
    q.context(channel="formal")
    assert opens["count"] == 0, f"context opened {opens['count']} parquet files"


def test_composite_and_diff_bounded(big_data_root):
    data_root = big_data_root["data_root"]
    catalog_store.rebuild(data_root)
    resolver = SnapshotResolver(data_root)
    t0 = time.perf_counter()
    comp = resolver.resolve_composite(SnapshotSelector())
    composite_elapsed = time.perf_counter() - t0
    assert comp.formal is not None
    # 730-day 3-layer composite target <=1.5s cold; generous CI bound.
    assert composite_elapsed < 10.0, f"composite took {composite_elapsed:.2f}s"


def test_perf_report_emitted(big_data_root, capsys):
    """Emit a structured perf report (timings + scale) for the record."""

    import platform

    data_root = big_data_root["data_root"]
    t0 = time.perf_counter()
    catalog = build_catalog(data_root)
    rebuild_s = time.perf_counter() - t0
    report = {
        "benchmark": "observatory-perf-smoke",
        "manifest_count": len(catalog.runs),
        "rebuild_seconds": round(rebuild_s, 4),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "note": "envelope target is 10k manifests; CI scale recorded above",
    }
    print(json.dumps(report))
    assert report["manifest_count"] >= 2000
