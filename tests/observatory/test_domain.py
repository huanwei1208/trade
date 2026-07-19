"""WP1.1 observatory domain model tests."""
from __future__ import annotations

import pytest

from trade_py.observatory.catalog.projection import run_from_manifest
from trade_py.observatory.domain.models import LayeredComparison
from trade_py.observatory.domain.vocab import (
    AcquisitionState,
    LifecycleState,
    ObservatoryError,
    QualityState,
    ReasonCode,
)
from tests.observatory.fixtures import build_legacy_run, build_observatory_fixture


def test_run_from_manifest_projects_states(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    import json

    manifest = json.loads(
        (fx["crypto_root"] / "runs" / "btc" / fx["candidate_run_id"] / "manifest.json").read_text()
    )
    run = run_from_manifest(manifest)
    assert run.run_id == fx["candidate_run_id"]
    assert run.quality_state == QualityState.DEGRADED
    assert run.market_watermark == "2026-07-18"
    assert run.blocking_gate == "D1"
    # Candidate has a D1 fail -> a finding is projected.
    assert any(f.gate == "D1" for f in run.findings)


def test_order_keys_are_descending_tuples(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    import json

    def load(run_id):
        return run_from_manifest(
            json.loads((fx["crypto_root"] / "runs" / "btc" / run_id / "manifest.json").read_text())
        )

    observed = load(fx["observed_run_id"])
    candidate = load(fx["candidate_run_id"])
    # Observed watermark 2026-07-19 sorts after candidate 2026-07-18.
    assert observed.order_key_observed() > candidate.order_key_observed()


def test_empty_run_has_no_final_bar(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    import json

    manifest = json.loads(
        (fx["crypto_root"] / "runs" / "btc" / fx["empty_run_id"] / "manifest.json").read_text()
    )
    run = run_from_manifest(manifest)
    assert run.canonical_rows == 0
    assert run.has_final_bar is False
    assert run.acquisition_state in {AcquisitionState.EMPTY, AcquisitionState.FAILED}


def test_invalid_manifest_missing_run_id_raises():
    with pytest.raises(ObservatoryError) as exc:
        run_from_manifest({"contract_version": "btc-data-v1"})
    assert exc.value.reason_code == ReasonCode.MANIFEST_INVALID


def test_composite_refuses_to_be_a_dataset():
    comp = LayeredComparison(asset_id="crypto.BTC", formal=None, evaluated_candidate=None, latest_observed=None)
    with pytest.raises(ObservatoryError) as exc:
        comp.as_dataset()
    assert exc.value.reason_code == ReasonCode.COMPOSITE_NOT_DATASET
