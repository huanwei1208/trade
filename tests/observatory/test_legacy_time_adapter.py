"""WP1.2 legacy timestamp adapter tests."""
from __future__ import annotations

from trade_py.observatory.catalog import legacy_time
from tests.observatory.fixtures import build_legacy_run


def test_missing_stage_times_are_proxies_and_unproven(tmp_path):
    manifest = build_legacy_run(tmp_path / "data")
    staged = legacy_time.derive_staged_at(manifest)
    assurance = legacy_time.derive_assurance_completed_at(manifest)
    capture = legacy_time.derive_capture_completed_at(manifest)
    for t in (staged, assurance, capture):
        assert t.provenance == "manifest.created_at"
        assert t.precision == "proxy"
        assert t.unproven is True
        assert t.value == manifest["created_at"]


def test_exact_stage_times_are_receipt_and_proven(tmp_path):
    manifest = build_legacy_run(tmp_path / "data")
    manifest["staged_at"] = "2026-07-01T01:02:03+00:00"
    staged = legacy_time.derive_staged_at(manifest)
    assert staged.provenance == "receipt"
    assert staged.precision == "exact"
    assert staged.unproven is False
    assert staged.value == "2026-07-01T01:02:03+00:00"


def test_effective_as_of_prefers_acquisition_evidence(tmp_path):
    manifest = build_legacy_run(tmp_path / "data")
    assert legacy_time.derive_effective_as_of(manifest) == manifest["acquisition_evidence"]["as_of"]


def test_summary_reports_legacy_time_unproven(tmp_path):
    manifest = build_legacy_run(tmp_path / "data")
    summary = legacy_time.time_provenance_summary(manifest)
    assert summary["legacy_time_unproven"] is True
    assert summary["adapter_version"] == legacy_time.ADAPTER_VERSION
    assert summary["first_proven_present_at"] == manifest["created_at"]


def test_adapter_never_reads_mtime(tmp_path):
    # The adapter only accepts a dict manifest; there is no filesystem access path.
    manifest = {"created_at": "2026-01-01T00:00:00+00:00"}
    staged = legacy_time.derive_staged_at(manifest)
    assert staged.value == "2026-01-01T00:00:00+00:00"
    assert staged.unproven is True
