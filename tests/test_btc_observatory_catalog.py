"""WP1 Snapshot Catalog tests (plan §27 owner: test_btc_observatory_catalog)."""
from __future__ import annotations

import json

import pytest

from trade_py.observatory.catalog import store
from trade_py.observatory.catalog.projection import build_catalog
from trade_py.observatory.domain.vocab import LifecycleState, ObservatoryError, ReasonCode
from tests.observatory.fixtures import build_observatory_fixture


@pytest.fixture()
def data_root(tmp_path):
    return build_observatory_fixture(tmp_path / "data")["data_root"]


def test_rebuild_is_deterministic(data_root):
    a = build_catalog(data_root)
    b = build_catalog(data_root)
    assert a.content_hash() == b.content_hash()
    assert a.source_fingerprint == b.source_fingerprint
    assert set(a.runs) == set(b.runs)


def test_catalog_resolves_formal_and_current(data_root):
    catalog = build_catalog(data_root)
    assert catalog.current_run_id == "formal_run_0000000000000001"
    # exactly one active (published) release, others superseded
    published = [r for r in catalog.releases if r.lifecycle_state == LifecycleState.PUBLISHED]
    assert len(published) == 1
    assert published[0].run_id == "formal_run_0000000000000001"
    formal_run = catalog.runs["formal_run_0000000000000001"]
    assert formal_run.lifecycle_state == LifecycleState.PUBLISHED


def test_rebuild_after_delete_matches(data_root):
    before = build_catalog(data_root)
    store.rebuild(data_root)
    db_path, _ = store._catalog_paths(data_root)
    assert db_path.exists()
    # Delete the projection DB and rebuild; resolved identities must match.
    db_path.unlink()
    store.rebuild(data_root)
    after = build_catalog(data_root)
    assert before.content_hash() == after.content_hash()
    assert before.current_run_id == after.current_run_id


def test_incremental_update_equals_full_rebuild(data_root):
    full = store.rebuild(data_root)
    upd = store.update(data_root)
    # No source change since rebuild -> update short-circuits.
    assert upd["changed"] is False
    assert full["content_hash"] == build_catalog(data_root).content_hash()


def test_update_detects_new_run_and_matches_full(data_root, tmp_path):
    store.rebuild(data_root)
    # Add a new run to the immutable facts.
    from tests.observatory.fixtures import build_legacy_run

    build_legacy_run(data_root, run_id="legacy_run_9999999999999999")
    upd = store.update(data_root)
    assert upd["changed"] is True
    # After update, generation matches a fresh full rebuild.
    fresh = build_catalog(data_root)
    stored = store.load_generation(data_root)
    assert stored["content_hash"] == fresh.content_hash()


def test_stale_read_fails_closed(data_root):
    store.rebuild(data_root)
    # Mutate immutable facts without rebuilding the catalog.
    from tests.observatory.fixtures import build_legacy_run

    build_legacy_run(data_root, run_id="legacy_run_8888888888888888")
    with pytest.raises(ObservatoryError) as exc:
        store.load_catalog_checked(data_root)
    assert exc.value.reason_code == ReasonCode.CATALOG_STALE
    assert exc.value.retryable is True


def test_read_without_built_catalog_is_stale(data_root):
    with pytest.raises(ObservatoryError) as exc:
        store.load_catalog_checked(data_root)
    assert exc.value.reason_code == ReasonCode.CATALOG_STALE


def test_dry_run_writes_temp_not_generation(data_root):
    report = store.rebuild(data_root, dry_run=True)
    assert report["dry_run"] is True
    assert "dry_run_db" in report
    # No committed generation pointer from a dry run.
    assert store.load_generation(data_root) is None


def test_verify_reports_current_then_stale(data_root):
    store.rebuild(data_root)
    assert store.verify(data_root)["status"] == "current"
    from tests.observatory.fixtures import build_legacy_run

    build_legacy_run(data_root, run_id="legacy_run_7777777777777777")
    assert store.verify(data_root)["status"] == "stale"


def test_corruption_recovery_skips_bad_manifest(data_root):
    # Corrupt one manifest; build_catalog must skip it, not crash.
    bad = data_root / "market" / "crypto" / "runs" / "btc" / "empty_run_00000000000000001" / "manifest.json"
    bad.write_text("{ not json", encoding="utf-8")
    catalog = build_catalog(data_root)
    assert "empty_run_00000000000000001" not in catalog.runs
    # Other runs still present.
    assert "formal_run_0000000000000001" in catalog.runs


def test_source_fingerprint_ignores_other_asset_noise(data_root, tmp_path):
    fp1 = store.current_source_fingerprint(data_root)
    # Add an unrelated file outside the BTC crypto tree.
    (data_root / "market").mkdir(parents=True, exist_ok=True)
    (data_root / "market" / "unrelated.txt").write_text("noise", encoding="utf-8")
    fp2 = store.current_source_fingerprint(data_root)
    assert fp1 == fp2
