from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from trade_py.cli import dev
from trade_py.devtools.design_quality import cli as design_cli
from trade_py.devtools.quality.config import QualityConfig
from trade_py.devtools.quality.executor import SubprocessExecutor
from trade_py.devtools.quality.models import CheckStep, FailureKind

REPO_ROOT = Path(__file__).resolve().parents[1]


def _historical_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    shutil.copytree(REPO_ROOT / "design-policy", repo / "design-policy")
    change = repo / "openspec" / "changes" / "historical-change"
    change.mkdir(parents=True)
    (change / "proposal.md").write_text("historical\n", encoding="utf-8")
    return repo


def test_design_parser_contract() -> None:
    args = dev.make_parser().parse_args(
        [
            "design-check",
            "add-design-quality-gates",
            "--strict",
            "--format",
            "json",
            "--as-of",
            "2026-07-20",
        ]
    )

    assert args.cmd == "design-check"
    assert args.change == "add-design-quality-gates"
    assert args.strict is True
    assert args.format == "json"
    assert args.as_of == "2026-07-20"


def test_direct_cli_is_lazy_no_db_and_machine_readable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    sys.modules.pop("trade_py.db.trade_db", None)

    code = dev.main(["design-check", "add-design-quality-gates", "--strict", "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema_version"] == "trade.design.report.v1"
    assert payload["approval_eligible"] is True
    assert payload["status"] == "PASS"
    assert "trade_py.db.trade_db" not in sys.modules


def test_historical_strict_cli_is_stable_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO_ROOT)

    code = dev.main(
        [
            "design-check",
            "add-design-quality-gates",
            "--strict",
            "--as-of",
            "2020-01-01",
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["schema_version"] == "trade.design.error.v1"
    assert payload["code"] == "design.request.invalid"
    assert payload["remediation"]
    assert "diagnostic-only" in payload["error"]


def test_direct_strict_requires_governance_and_never_exits_zero_for_not_governed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_historical_repo(tmp_path))

    code = dev.main(["design-check", "historical-change", "--strict", "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["approval_eligible"] is False
    assert payload["governance_status"] == "REQUIRED_MISSING"


def test_internal_batch_cli_returns_structured_reports(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO_ROOT)

    code = design_cli.main(
        [
            "--change",
            "add-design-quality-gates",
            "--strict",
            "--require-governance",
            "add-design-quality-gates",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema_version"] == "trade.design.batch.v1"
    assert payload["summary"] == {
        "changes": 1,
        "errors": 0,
        "failed": 0,
        "not_governed": 0,
        "passed": 1,
    }
    assert payload["reports"][0]["approval_eligible"] is True


def test_internal_batch_rejects_orphaned_governance_requirement(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO_ROOT)

    code = design_cli.main(
        [
            "--change",
            "add-design-quality-gates",
            "--require-governance",
            "typo-change",
            "--strict",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["reports"] == []
    assert "must reference a supplied --change" in payload["errors"][0]["message"]


def test_internal_batch_reports_deleted_governance_with_complete_schema(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO_ROOT)

    code = design_cli.main(["--missing-required", "deleted-change", "--strict"])

    payload = json.loads(capsys.readouterr().out)
    report = payload["reports"][0]
    assert code == 1
    assert payload["summary"]["failed"] == 1
    assert report["governance_status"] == "REQUIRED_MISSING"
    assert report["policy_version"] == "v1"
    assert report["counts"]["blockers"] == 1
    assert report["metadata"]["missing_from_changed_scope"] is True


def test_internal_batch_caps_deleted_and_mixed_targets_before_report_creation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    accepted = [
        argument for index in range(100) for argument in ("--missing-required", f"gone-{index}")
    ]

    accepted_code = design_cli.main([*accepted, "--strict"])
    accepted_payload = json.loads(capsys.readouterr().out)
    rejected_code = design_cli.main([*accepted, "--missing-required", "gone-100", "--strict"])
    rejected_payload = json.loads(capsys.readouterr().out)

    assert accepted_code == 1
    assert accepted_payload["summary"]["changes"] == 100
    assert rejected_code == 2
    assert rejected_payload["reports"] == []
    assert "limit is 100" in rejected_payload["errors"][0]["message"]


def test_internal_batch_reports_immutable_policy_edit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO_ROOT)

    code = design_cli.main(["--immutable-policy-edit", "design-policy/v1.toml", "--strict"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["reports"][0]["findings"][0]["rule_id"] == "core.policy.immutable"


@pytest.mark.parametrize(
    "arguments",
    (
        ("--missing-required", "deleted-change", "--strict"),
        ("--immutable-policy-edit", "design-policy/v1.toml", "--strict"),
    ),
)
def test_synthetic_quality_failures_preserve_parent_exit_one(arguments: tuple[str, ...]) -> None:
    executor = SubprocessExecutor(REPO_ROOT, QualityConfig())

    result = executor.run_step(
        CheckStep(
            "design.synthetic-failure",
            "design",
            "synthetic design failure",
            (
                sys.executable,
                "-m",
                "trade_py.devtools.design_quality.cli",
                *arguments,
            ),
            exit_code_kinds=((1, FailureKind.QUALITY), (2, FailureKind.INFRASTRUCTURE)),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.QUALITY
    assert result.aggregate_exit_code == 1


def test_shell_design_route_is_frozen_and_no_sync(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(REPO_ROOT / "trade"), "dev", "design-check", "add-design-quality-gates"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.splitlines()[:4] == ["run", "--frozen", "--no-sync", "python"]
    assert result.stdout.splitlines()[-3:] == ["dev", "design-check", "add-design-quality-gates"]


def test_root_help_documents_single_design_sequence() -> None:
    shell = (REPO_ROOT / "trade").read_text(encoding="utf-8")

    assert "设计证据预检/严格批准（先预检→六角色评审→strict）" in shell
