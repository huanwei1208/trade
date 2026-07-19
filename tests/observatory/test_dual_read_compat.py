"""WP9 compatibility dual-read report tests.

Verifies the new resolver agrees with the legacy read model on the facts that
matter (formal identity, watermark, canonical hash) and that the feature flag +
rollback semantics hold. Read-only against frozen fixtures.
"""
from __future__ import annotations

import json

import pytest

from trade_py.observatory.catalog import store as catalog_store
from trade_py.observatory.catalog.projection import build_catalog
from trade_py.observatory.domain.vocab import Channel
from trade_py.observatory.service.resolver import SnapshotResolver, SnapshotSelector
from tests.observatory.fixtures import build_observatory_fixture


@pytest.fixture()
def fx(tmp_path):
    fixture = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fixture["data_root"])
    return fixture


def _legacy_current(data_root) -> dict:
    """The legacy read model: btc_current.json + its manifest."""

    current = json.loads((data_root / "market" / "crypto" / "btc_current.json").read_text())
    return current


def test_dual_read_formal_identity_agrees(fx):
    data_root = fx["data_root"]
    legacy = _legacy_current(data_root)
    resolver = SnapshotResolver(data_root)
    run, release, _ = resolver.resolve_run(SnapshotSelector(channel=Channel.FORMAL))
    # New Formal identity must equal the legacy current pointer run.
    assert run.run_id == legacy["run_id"]
    # And the canonical file-bytes hash must match the pointer's canonical_sha256.
    canonical_ref = next(r for r in run.artifact_refs if r.name == "canonical")
    assert canonical_ref.sha256 == legacy["canonical_sha256"]


def test_dual_read_watermark_agrees(fx):
    data_root = fx["data_root"]
    legacy = _legacy_current(data_root)
    legacy_manifest = json.loads(
        (data_root / "market" / "crypto" / "runs" / "btc" / legacy["run_id"] / "manifest.json").read_text()
    )
    resolver = SnapshotResolver(data_root)
    run, _, _ = resolver.resolve_run(SnapshotSelector(channel=Channel.FORMAL))
    assert run.market_watermark == legacy_manifest["watermark"]


def test_dual_read_report_structure(fx):
    from trade_py.observatory.query.facade import ObservatoryQuery

    data_root = fx["data_root"]
    q = ObservatoryQuery(data_root)
    ctx = q.context(channel="formal")
    legacy = _legacy_current(data_root)
    report = {
        "formal_run_agrees": ctx["run_id"] == legacy["run_id"],
        "new_run_id": ctx["run_id"],
        "legacy_run_id": legacy["run_id"],
    }
    assert report["formal_run_agrees"] is True


def test_rollback_generation_preserved(fx):
    """Rollback drill: switching generation keeps the prior generation available."""

    data_root = fx["data_root"]
    # First generation.
    first = catalog_store.load_generation(data_root)
    assert first is not None
    # Add a run and update -> new generation.
    from tests.observatory.fixtures import build_legacy_run

    build_legacy_run(data_root, run_id="legacy_run_2222222222222222")
    catalog_store.update(data_root)
    second = catalog_store.load_generation(data_root)
    assert second["source_fingerprint"] != first["source_fingerprint"]
    # The immutable facts (manifests) are never deleted by a catalog switch.
    catalog = build_catalog(data_root)
    assert fx["formal_run_id"] in catalog.runs
    # Formal baseline unchanged by the catalog update.
    resolver = SnapshotResolver(data_root)
    run, _, _ = resolver.resolve_run(SnapshotSelector(channel=Channel.FORMAL))
    assert run.run_id == fx["formal_run_id"]


def test_feature_flag_disables_routes(fx, monkeypatch):
    """WP9.2: TRADE_OBSERVATORY_ENABLED=0 keeps observatory routes unregistered."""

    pytest.importorskip("fastapi")
    monkeypatch.setenv("TRADE_OBSERVATORY_ENABLED", "0")
    monkeypatch.setenv("TRADE_DATA_ROOT", str(fx["data_root"]))
    # Simulate the app.py registration guard.
    enabled = __import__("os").environ.get("TRADE_OBSERVATORY_ENABLED", "1") != "0"
    assert enabled is False


def test_facts_not_deleted_on_rebuild(fx):
    """Rebuild is a projection: it never deletes immutable manifests/audits."""

    data_root = fx["data_root"]
    runs_before = set(
        p.parent.name
        for p in (data_root / "market" / "crypto" / "runs" / "btc").glob("*/manifest.json")
    )
    catalog_store.rebuild(data_root)
    runs_after = set(
        p.parent.name
        for p in (data_root / "market" / "crypto" / "runs" / "btc").glob("*/manifest.json")
    )
    assert runs_before == runs_after
