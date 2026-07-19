"""WP1.4 observatory catalog CLI tests."""
from __future__ import annotations

import json

import pytest

from trade_py.cli import observatory as observatory_cli
from trade_py.observatory.catalog import store
from tests.observatory.fixtures import build_observatory_fixture, build_legacy_run


@pytest.fixture()
def data_root(tmp_path):
    return str(build_observatory_fixture(tmp_path / "data")["data_root"])


def test_cli_rebuild_then_status(data_root, capsys):
    rc = observatory_cli.main(["catalog", "rebuild", "--data-root", data_root, "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["committed"] is True
    assert out["run_count"] >= 5

    rc = observatory_cli.main(["catalog", "status", "--data-root", data_root, "--json"])
    assert rc == 0
    status = json.loads(capsys.readouterr().out)
    assert status["db_exists"] is True
    assert status["verify"]["status"] == "current"


def test_cli_dry_run_does_not_commit(data_root, capsys):
    rc = observatory_cli.main(["catalog", "rebuild", "--data-root", data_root, "--dry-run", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert store.load_generation(data_root) is None


def test_cli_update_reports_stale_after_new_run(data_root, capsys):
    observatory_cli.main(["catalog", "rebuild", "--data-root", data_root, "--json"])
    capsys.readouterr()
    build_legacy_run(__import__("pathlib").Path(data_root), run_id="legacy_run_5555555555555555")
    rc = observatory_cli.main(["catalog", "verify", "--data-root", data_root, "--json"])
    assert rc == 0
    verify = json.loads(capsys.readouterr().out)
    assert verify["status"] == "stale"

    observatory_cli.main(["catalog", "update", "--data-root", data_root, "--json"])
    update = json.loads(capsys.readouterr().out)
    assert update["changed"] is True


def test_cli_no_args_prints_help_and_returns_2():
    rc = observatory_cli.main([])
    assert rc == 2
