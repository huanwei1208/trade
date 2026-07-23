from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from trade_py.cli import data as data_cli
from trade_py.data.operations import PROFILES, read_status, run_check, run_update
from trade_py.db.trade_db import TradeDB


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def _frame() -> pd.DataFrame:
    latest = (date.today() - timedelta(days=1)).isoformat()
    return pd.DataFrame(
        [
            {
                "date": latest,
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 100.0,
            }
        ]
    )


def test_primary_profiles_are_ordered_and_never_include_decision_work() -> None:
    assert [step.step_id for step in PROFILES["core"].steps] == [
        "kline",
        "index",
        "fund-flow",
        "northbound",
    ]
    assert [step.step_id for step in PROFILES["crypto"].steps] == [
        "btc-assurance",
        "crypto-assets",
    ]
    assert PROFILES["crypto"].steps[1].config["exclude_symbols"] == ["BTC"]
    forbidden = {"model_train", "belief_update", "recommend", "evaluate_daily", "sentiment_pipeline"}
    assert not {
        step.job_name for profile in PROFILES.values() for step in profile.steps
    }.intersection(forbidden)


def test_empty_root_status_check_and_dry_run_are_zero_write(tmp_path) -> None:
    root = tmp_path / "absent"

    status = read_status(root)
    check = run_check(root, profile_name="all")
    plan = run_update(root, "crypto", dry_run=True)

    assert status.status == "warn"
    assert status.observed is False
    assert status.exit_code == 1
    assert check.status == "warn"
    assert check.evidence["counts"]["unknown"] > 0
    assert plan.status == "planned"
    assert [step.job_name for step in plan.steps] == [
        "crypto_btc_fetch",
        "asset_batch_ingest",
    ]
    assert not root.exists()


def test_status_reads_existing_metadata_without_mutating_files(tmp_path) -> None:
    db = TradeDB(tmp_path)
    run_id = db.job_run_start("kline_update", stage="fetch")
    db.job_run_finish(run_id, "ok", result_summary="fixture", elapsed_ms=1)
    db.close()
    before = _snapshot(tmp_path)

    result = read_status(tmp_path)

    assert result.observed is True
    assert result.evidence["database"]["mode"] == "ro-immutable-no-wal"
    assert result.evidence["profiles"]["core"]["steps"][0]["status"] == "ok"
    assert _snapshot(tmp_path) == before


def test_status_reads_uncheckpointed_wal_without_mutating_files(tmp_path) -> None:
    db = TradeDB(tmp_path)
    run_id = db.job_run_start("kline_update", stage="fetch")
    db.job_run_finish(run_id, "ok", result_summary="wal fixture", elapsed_ms=1)
    wal_path = tmp_path / ".db" / "trade.db-wal"
    assert wal_path.exists()
    before = _snapshot(tmp_path)

    result = read_status(tmp_path)

    assert result.evidence["database"]["mode"] == "ro-wal-aware"
    assert result.evidence["profiles"]["core"]["steps"][0]["status"] == "ok"
    assert (
        result.evidence["database"]["latest_jobs"]["kline_update"]["result_summary"]
        == "wal fixture"
    )
    assert _snapshot(tmp_path) == before
    db.close()


def test_standard_and_full_checks_validate_parquet_without_writes(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.close()
    for relative in (
        "market/kline/000001_SZ.parquet",
        "market/index/000300_SH.parquet",
        "market/fund_flow/000001_SZ.parquet",
        "market/northbound/hsgt.parquet",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _frame().to_parquet(path, index=False)
    reconciliation = tmp_path / "market" / "kline" / "reconciliation" / "current.json"
    reconciliation.parent.mkdir(parents=True, exist_ok=True)
    reconciliation.write_text(
        json.dumps({
            "schema_version": "kline-reconciliation-v1",
            "status": "pass",
            "metrics": {"checked_rows": 1, "block_rows": 0},
        }),
        encoding="utf-8",
    )
    before = _snapshot(tmp_path)

    standard = run_check(tmp_path, profile_name="core")
    full = run_check(tmp_path, profile_name="core", full=True)

    assert standard.status == "pass"
    assert standard.evidence["checked_files"] == 4
    assert full.status == "pass"
    assert full.operation == "check-full"
    assert _snapshot(tmp_path) == before


def test_check_reports_corrupt_parquet_as_failure(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.close()
    path = tmp_path / "market" / "kline" / "broken.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not-parquet")

    result = run_check(tmp_path, profile_name="core")

    assert result.status == "fail"
    assert result.exit_code == 2
    assert any(item["status"] == "fail" for item in result.evidence["items"])
    assert path.read_bytes() == b"not-parquet"


def test_update_runner_records_steps_and_stops_on_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_run_job(name: str, data_root: str, config: dict[str, Any]) -> str:
        calls.append((name, config))
        if name == "asset_batch_ingest":
            raise RuntimeError("partial persistence")
        return "btc ready"

    monkeypatch.setattr("trade_py.jobs.run_job", fake_run_job)

    result = run_update(tmp_path, "crypto")

    assert result.status == "fail"
    assert result.exit_code == 2
    assert [step.status for step in result.steps] == ["ok", "error"]
    assert calls == [
        ("crypto_btc_fetch", {"canonical_writer": "btc_assurance"}),
        ("asset_batch_ingest", {"asset_class": "crypto", "exclude_symbols": ["BTC"]}),
    ]
    db = TradeDB(tmp_path)
    rows = db._conn.execute(
        "SELECT job_name, status FROM job_runs ORDER BY id"
    ).fetchall()
    db.close()
    assert [(row[0], row[1]) for row in rows] == [
        ("data_update_crypto", "error"),
        ("crypto_btc_fetch", "ok"),
        ("asset_batch_ingest", "error"),
    ]


def test_update_runner_continues_after_quality_warning(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trade_py.jobs import JobQualityWarning

    calls: list[str] = []

    def fake_run_job(name: str, data_root: str, config: dict[str, Any]) -> str:
        calls.append(name)
        if name == "crypto_btc_fetch":
            raise JobQualityWarning("BTC pilot 2/29")
        return "non-BTC ready"

    monkeypatch.setattr("trade_py.jobs.run_job", fake_run_job)

    result = run_update(tmp_path, "crypto")

    assert result.status == "warn"
    assert result.exit_code == 1
    assert [step.status for step in result.steps] == ["warn", "ok"]
    assert calls == ["crypto_btc_fetch", "asset_batch_ingest"]
    db = TradeDB(tmp_path)
    rows = db._conn.execute(
        "SELECT job_name, status FROM job_runs ORDER BY id"
    ).fetchall()
    db.close()
    assert [(row[0], row[1]) for row in rows] == [
        ("data_update_crypto", "warn"),
        ("crypto_btc_fetch", "warn"),
        ("asset_batch_ingest", "ok"),
    ]


def test_crypto_check_reports_newer_unpublished_candidate(tmp_path: Path) -> None:
    runs = tmp_path / "market" / "crypto" / "runs" / "btc"
    current_manifest = runs / "current" / "manifest.json"
    current_manifest.parent.mkdir(parents=True)
    current_manifest.write_text(
        json.dumps({
            "run_id": "current",
            "created_at": "2026-07-12T00:00:00+00:00",
            "data_readiness": "ready",
            "gates": [],
        }),
        encoding="utf-8",
    )
    candidate_manifest = runs / "candidate" / "manifest.json"
    candidate_manifest.parent.mkdir(parents=True)
    candidate_manifest.write_text(
        json.dumps({
            "run_id": "candidate",
            "created_at": "2026-07-16T00:00:00+00:00",
            "data_readiness": "degraded",
            "gates": [{
                "gate": "D1",
                "status": "fail",
                "reason_code": "ACQUISITION_STABILITY_INSUFFICIENT",
            }],
        }),
        encoding="utf-8",
    )
    pointer = tmp_path / "market" / "crypto" / "btc_current.json"
    pointer.write_text(
        json.dumps({"run_id": "current", "manifest_path": str(current_manifest)}),
        encoding="utf-8",
    )

    result = run_check(tmp_path, profile_name="crypto")

    item = next(item for item in result.evidence["items"] if item["name"] == "btc-pointer")
    assert item["status"] == "warn"
    assert "latest_candidate=candidate" in item["detail"]
    assert "ACQUISITION_STABILITY_INSUFFICIENT" in item["detail"]


def test_primary_help_is_concise_and_legacy_parser_remains_callable(capsys) -> None:
    help_text = data_cli.make_parser().format_help()
    assert "{status,update,check}" in help_text
    assert "fundamental" not in help_text
    parsed = data_cli.make_parser().parse_args(["sync", "--crypto", "--data-root", "/tmp/x"])
    assert parsed.command == "sync"
    assert parsed.crypto is True

    assert data_cli.main(["--help-all"]) == 0
    assert "fundamental" in capsys.readouterr().out


def test_status_cli_emits_bounded_json_and_preserves_empty_root(tmp_path, capsys) -> None:
    root = tmp_path / "empty"

    rc = data_cli.main(["status", "--data-root", str(root), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["operation"] == "status"
    assert payload["observed"] is False
    assert len(payload["evidence"]["profiles"]) == 3
    assert not root.exists()
