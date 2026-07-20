"""WP7 crypto research workflow tests (plan §27 owner: test_btc_observatory_research)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from trade_py.cli import observatory as observatory_cli
from trade_py.observatory.catalog import store as catalog_store
from trade_py.observatory.domain.vocab import ObservatoryError, ReasonCode
from trade_py.observatory.research import adapter, workflow
from tests.observatory.fixtures import build_observatory_fixture

REPO_ROOT = Path(__file__).resolve().parents[1]
TRADE_WRAPPER = REPO_ROOT / "trade"


@pytest.fixture()
def data_root(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    return fx["data_root"]


def test_hypotheses_lists_h1(data_root):
    hyps = adapter.hypotheses(data_root)
    assert len(hyps) == 1
    assert hyps[0]["hypothesis_id"] == "H1"
    assert hyps[0]["directional"] is False


def test_read_current_research_none_without_pointer(data_root):
    # No ADS validation pointer in the fixture -> None (never fabricated).
    assert adapter.read_current_research(data_root) is None


def test_run_dry_run_writes_nothing(data_root):
    result = workflow.run(data_root, dry_run=True)
    assert result["dry_run"] is True
    assert result["dataset_snapshot_id"]
    # No research dir created.
    research_dir = data_root / "market" / "crypto" / "observatory" / "research"
    assert not research_dir.exists()


def test_run_unknown_hypothesis_rejected(data_root):
    with pytest.raises(ObservatoryError) as exc:
        workflow.run(data_root, hypothesis="H99", dry_run=True)
    assert exc.value.reason_code == ReasonCode.RESEARCH_NOT_ELIGIBLE


def test_import_requires_fields(data_root, tmp_path):
    bad_bundle = tmp_path / "bad.json"
    bad_bundle.write_text(json.dumps({"snapshot_id": "abc"}), encoding="utf-8")
    with pytest.raises(ObservatoryError) as exc:
        workflow.import_notebook_bundle(data_root, bundle_path=bad_bundle, dry_run=False)
    assert exc.value.reason_code == ReasonCode.RESEARCH_NOT_ELIGIBLE


def test_import_creates_exploratory_only(data_root, tmp_path):
    bundle = tmp_path / "bundle.json"
    bundle.write_text(
        json.dumps(
            {
                "snapshot_id": "snap-1",
                "code_hash": "code-1",
                "environment_hash": "env-1",
                "hypothesis_version": "btc-vol-persistence-v1",
            }
        ),
        encoding="utf-8",
    )
    result = workflow.import_notebook_bundle(data_root, bundle_path=bundle, dry_run=False)
    assert result["receipt"]["namespace"] == "exploratory"
    assert result["receipt"]["moves_current_pointer"] is False
    assert (data_root / "market" / "crypto" / "observatory" / "research" / "exploratory").exists()
    # The ADS current pointer is never created by import.
    ads_pointer = data_root / "warehouse" / "ads" / "_crypto_validation_current.json"
    assert not ads_pointer.exists()


def test_promote_requires_exploratory_prefix(data_root):
    with pytest.raises(ObservatoryError) as exc:
        workflow.promote(data_root, research_run_id="validated:xyz", dry_run=True)
    assert exc.value.reason_code == ReasonCode.RESEARCH_NOT_ELIGIBLE


def test_promote_appends_receipt_without_rewriting_source(data_root, tmp_path):
    bundle = tmp_path / "bundle.json"
    bundle.write_text(
        json.dumps(
            {
                "snapshot_id": "snap-1",
                "code_hash": "code-1",
                "environment_hash": "env-1",
                "hypothesis_version": "btc-vol-persistence-v1",
            }
        ),
        encoding="utf-8",
    )
    imported = workflow.import_notebook_bundle(data_root, bundle_path=bundle, dry_run=False)
    rr_id = imported["receipt"]["research_run_id"]
    source_path = data_root / "market" / "crypto" / "observatory" / "research" / "exploratory" / f"{rr_id.split(':')[1]}.json"
    source_before = source_path.read_text(encoding="utf-8")

    promoted = workflow.promote(data_root, research_run_id=rr_id, dry_run=False)
    assert promoted["rewrites_original"] is False
    assert "promotion_receipt_path" in promoted
    # Original exploratory receipt is untouched.
    assert source_path.read_text(encoding="utf-8") == source_before
    # Promotion receipt exists and does not move the pointer.
    promo = json.loads(__import__("pathlib").Path(promoted["promotion_receipt_path"]).read_text())
    assert promo["moves_current_pointer"] is False


def test_cli_research_run_dry_run_by_default(data_root, capsys):
    rc = observatory_cli.main(["research", "run", "--data-root", str(data_root), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True


def test_run_non_dry_run_delegates_to_existing_authority(data_root):
    result = workflow.run(data_root, dry_run=False)
    assert result["pointer_moved_by"] == "existing lifecycle activate_run only"
    assert "delegated_to" in result


# ── RA.1: real ./trade research btc wrapper dispatch (docs/27 Phase A, F10) ────


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv required for ./trade wrapper")
def test_real_trade_research_btc_run_reaches_workflow(data_root):
    """`./trade research btc run --dry-run --json` reaches the BTC workflow.

    Baseline (F10): `trade research` only accepted model/factor/evaluate, so `btc`
    raised "invalid choice: 'btc'". It must now route into the shared BTC research
    parser and produce a dry-run plan (writes nothing).
    """

    proc = subprocess.run(
        [str(TRADE_WRAPPER), "research", "btc", "run", "--dry-run", "--data-root", str(data_root), "--json"],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["dry_run"] is True
    assert payload["dataset_snapshot_id"]
    # Dry-run must not create the research dir.
    research_dir = data_root / "market" / "crypto" / "observatory" / "research"
    assert not research_dir.exists()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv required for ./trade wrapper")
def test_real_trade_research_still_accepts_legacy_groups():
    """Existing research groups (model/factor/evaluate) still parse (no regression)."""

    proc = subprocess.run(
        [str(TRADE_WRAPPER), "research", "factor", "--help"],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "trade research factor" in proc.stdout


def test_research_btc_and_observatory_share_one_parser():
    """RA.1: `trade research btc` must reuse the observatory research parser rather
    than duplicating workflow logic between CLI modules (plan §5.3)."""

    from trade_py.cli import research as research_cli

    # The research CLI delegates btc to the observatory research entrypoint.
    assert hasattr(observatory_cli, "research_btc_main")
    assert research_cli._btc_research_entrypoint() is observatory_cli.research_btc_main


def test_research_btc_run_dry_run_via_research_group(data_root, capsys):
    """`trade research btc run` (in-process) reaches the same dry-run workflow."""

    from trade_py.cli import research as research_cli

    rc = research_cli.main(["btc", "run", "--data-root", str(data_root), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
