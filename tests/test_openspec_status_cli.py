from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from trade_py.cli import dev
from trade_py.devtools.openspec_status.errors import WorkflowError
from trade_py.devtools.openspec_status.models import (
    ArtifactEvidence,
    ChangeWorkflow,
    GovernanceEvidence,
    NativeEvidence,
    NextAction,
    TaskProgress,
    ValidationEvidence,
    WorkflowLimits,
    WorkflowReport,
    WorkflowSource,
)
from trade_py.devtools.openspec_status.render import render_workflow

REPO_ROOT = Path(__file__).resolve().parents[1]


def _report(
    *,
    changes: tuple[ChangeWorkflow, ...] | None = None,
    errors: tuple[WorkflowError, ...] = (),
    limits: WorkflowLimits | None = None,
) -> WorkflowReport:
    design_report = {
        "schema_version": "trade.design.report.v1",
        "status": "PASS",
        "governance_status": "GOVERNED",
        "approval_eligible": True,
        "findings": [],
    }
    default_change = ChangeWorkflow(
        name="change-a",
        collection_status="complete",
        lifecycle="implementation",
        tasks=TaskProgress.from_counts(1, 2),
        native=NativeEvidence(
            schema_name="spec-driven",
            is_complete=True,
            apply_requires=("tasks",),
            artifacts=(
                ArtifactEvidence("proposal", "proposal.md", "done"),
                ArtifactEvidence("tasks", "tasks.md", "done"),
            ),
            validation=ValidationEvidence(valid=True, issues=(), omitted_count=0),
            payload_digests={
                "list": f"sha256:{'1' * 64}",
                "status": f"sha256:{'2' * 64}",
                "validation": f"sha256:{'3' * 64}",
            },
        ),
        governance=GovernanceEvidence(
            required=True,
            requirement_source="existing_governed",
            report=design_report,
        ),
        next_action=NextAction(
            "apply",
            "openspec instructions apply --change change-a",
            "1 implementation task(s) remain.",
        ),
    )
    return WorkflowReport(
        evaluation_date=date(2026, 7, 23),
        source=WorkflowSource(
            git_head="a" * 40,
            base_ref="origin/master",
            base_sha="b" * 40,
            snapshot_digest=f"sha256:{'c' * 64}",
        ),
        changes=changes if changes is not None else (default_change,),
        errors=errors,
        limits=limits or WorkflowLimits(),
    )


def test_openspec_parser_contract_and_lazy_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    args = dev.make_parser().parse_args(["openspec", "change-a", "--format", "json"])

    assert args.cmd == "openspec"
    assert args.change == "change-a"
    assert args.format == "json"

    received: list[argparse.Namespace] = []
    monkeypatch.setattr(dev, "_run_openspec", lambda parsed: received.append(parsed) or 17)

    assert dev.main(["openspec", "change-a", "--format", "json"]) == 17
    assert received[0].change == "change-a"


def test_json_cli_emits_complete_v1_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from trade_py.devtools.openspec_status import cli

    report = _report()
    monkeypatch.setattr(cli, "discover_repo_root", lambda _start: tmp_path)
    monkeypatch.setattr(cli, "collect_workflow", lambda *_args, **_kwargs: report)

    code = dev.main(["openspec", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert set(payload) == {
        "schema_version",
        "status",
        "exit_code",
        "evaluation_date",
        "source",
        "changes",
        "errors",
        "summary",
        "limits",
    }
    assert payload["schema_version"] == "trade.openspec.workflow.v1"
    assert payload["status"] == "PASS"
    assert payload["exit_code"] == 0
    assert payload["evaluation_date"] == "2026-07-23"
    assert set(payload["source"]) == {
        "git_head",
        "base_ref",
        "base_sha",
        "snapshot_digest",
    }
    change = payload["changes"][0]
    assert set(change) == {
        "name",
        "collection_status",
        "lifecycle",
        "tasks",
        "native",
        "governance",
        "next_action",
        "errors",
    }
    assert change["native"]["is_complete"] is True
    assert change["tasks"] == {
        "completed": 1,
        "total": 2,
        "status": "in-progress",
    }
    governance = report.changes[0].governance
    assert governance is not None
    assert change["governance"]["report"] == governance.report
    assert payload["summary"]["implementation"] == 1


def test_text_cli_is_scannable_and_preserves_next_action(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from trade_py.devtools.openspec_status import cli

    monkeypatch.setattr(cli, "discover_repo_root", lambda _start: tmp_path)
    monkeypatch.setattr(cli, "collect_workflow", lambda *_args, **_kwargs: _report())

    code = dev.main(["openspec", "change-a"])
    output = capsys.readouterr().out

    assert code == 0
    assert "OpenSpec workflow: PASS (1 changes, 0 unavailable, 0 errors)" in output
    assert "change-a: implementation [complete]" in output
    assert "tasks: 1/2 (in-progress)" in output
    assert "validation: pass (0 issues, 0 omitted)" in output
    assert "governance: GOVERNED (status=PASS, approval=True" in output
    assert "next: openspec instructions apply --change change-a" in output


def test_repository_discovery_failure_is_a_stable_json_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from trade_py.devtools.openspec_status import cli
    from trade_py.devtools.quality.scope import ScopeError

    def fail_discovery(_start: Path) -> Path:
        raise ScopeError("not inside a Git repository")

    monkeypatch.setattr(cli, "discover_repo_root", fail_discovery)

    code = dev.main(["openspec", "unknown-change", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["status"] == "ERROR"
    assert payload["changes"] == []
    assert payload["source"] is None
    assert payload["errors"][0]["code"] == "workflow.repository.discovery"
    assert payload["errors"][0]["source"] == "git"
    assert payload["errors"][0]["details"] == {}
    assert payload["errors"][0]["change"] == "unknown-change"


def test_unknown_change_report_is_not_an_empty_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from trade_py.devtools.openspec_status import cli

    error = WorkflowError(
        code="workflow.request.unknown_change",
        source="request",
        change="unknown-change",
        message="Requested change is not active: unknown-change",
        remediation="Run ./trade dev openspec to list active changes.",
    )
    report = _report(changes=(), errors=(error,))
    requested: list[str | None] = []
    monkeypatch.setattr(cli, "discover_repo_root", lambda _start: tmp_path)
    monkeypatch.setattr(
        cli,
        "collect_workflow",
        lambda _root, requested_change: requested.append(requested_change) or report,
    )

    code = dev.main(["openspec", "unknown-change", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert requested == ["unknown-change"]
    assert payload["status"] == "ERROR"
    assert payload["changes"] == []
    assert payload["errors"][0]["code"] == "workflow.request.unknown_change"


def test_keyboard_interrupt_is_rendered_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from trade_py.devtools.openspec_status import cli

    def interrupt(*_args: object, **_kwargs: object) -> WorkflowReport:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "discover_repo_root", lambda _start: tmp_path)
    monkeypatch.setattr(cli, "collect_workflow", interrupt)

    code = dev.main(["openspec", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["status"] == "ERROR"
    assert payload["errors"][0]["code"] == "workflow.command.interrupted"
    assert payload["errors"][0]["source"] == "request"
    assert payload["errors"][0]["details"] == {}


def test_partial_change_error_preserves_siblings_and_exit_precedence() -> None:
    error = WorkflowError(
        code="workflow.process.timeout",
        source="openspec",
        change="change-b",
        message="status timed out",
        remediation="repair native status",
    )
    report = _report(
        changes=(
            _report().changes[0],
            ChangeWorkflow.unavailable("change-b", error),
        )
    )

    rendered = render_workflow(report, output_format="json")
    payload = json.loads(rendered.output)

    assert rendered.exit_code == 2
    assert payload["status"] == "ERROR"
    assert [item["name"] for item in payload["changes"]] == ["change-a", "change-b"]
    assert payload["changes"][1]["lifecycle"] is None
    assert payload["summary"]["unavailable"] == 1
    assert payload["errors"] == [error.to_dict()]


def test_report_output_limit_accepts_exact_size_and_fails_closed_one_byte_over() -> None:
    report = _report()
    limit = 1_000_000
    for _ in range(10):
        candidate = replace(
            report,
            limits=replace(report.limits, report_output_bytes=limit),
        )
        encoded = (
            json.dumps(
                candidate.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        new_limit = len(encoded.encode("utf-8"))
        if new_limit == limit:
            report = candidate
            break
        limit = new_limit
    else:
        raise AssertionError("report size did not converge")

    exact = render_workflow(report, output_format="json")
    oversized_report = replace(
        report,
        limits=replace(report.limits, report_output_bytes=limit - 1),
    )
    oversized = render_workflow(oversized_report, output_format="json")
    oversized_payload = json.loads(oversized.output)

    assert len(exact.output.encode("utf-8")) == limit
    assert exact.exit_code == 0
    assert oversized.exit_code == 2
    assert oversized_payload["changes"] == []
    assert oversized_payload["errors"][0]["code"] == "workflow.report.too_large"
    assert oversized_payload["errors"][0]["source"] == "openspec"
    assert oversized_payload["errors"][0]["details"] == {}
    assert oversized_payload["summary"]["errors"] == 1


def test_workflow_error_rejects_undeclared_source_and_details() -> None:
    with pytest.raises(ValueError, match="Unsupported workflow error source"):
        WorkflowError(
            code="workflow.invalid",
            source="report",  # type: ignore[arg-type]
            message="invalid source",
            remediation="use the v1 source enum",
        )
    with pytest.raises(ValueError, match="details do not match"):
        WorkflowError(
            code="workflow.process.timeout",
            source="openspec",
            message="timed out",
            remediation="rerun",
            details={"limit_bytes": "1"},
        )


def test_unsupported_schema_error_requires_exact_contract_details() -> None:
    with pytest.raises(ValueError, match="details do not match"):
        WorkflowError(
            code="workflow.openspec.unsupported_schema",
            source="openspec",
            message="unsupported",
            remediation="add a schema strategy",
            details={"schema_name": "custom"},
        )
    error = WorkflowError(
        code="workflow.openspec.unsupported_schema",
        source="openspec",
        message="unsupported",
        remediation="add a schema strategy",
        details={
            "schema_name": "custom",
            "payload_digest": f"sha256:{'a' * 64}",
        },
    )
    assert error.to_dict()["details"] == {
        "payload_digest": f"sha256:{'a' * 64}",
        "schema_name": "custom",
    }


def test_workflow_error_details_are_immutable_defensive_copy() -> None:
    details = {
        "schema_name": "custom",
        "payload_digest": f"sha256:{'a' * 64}",
    }
    error = WorkflowError(
        code="workflow.openspec.unsupported_schema",
        source="openspec",
        message="unsupported",
        remediation="add a schema strategy",
        details=details,
    )

    details["schema_name"] = "mutated"
    with pytest.raises(TypeError):
        error.details["schema_name"] = "mutated"  # type: ignore[index]

    assert error.to_dict()["details"] == {
        "payload_digest": f"sha256:{'a' * 64}",
        "schema_name": "custom",
    }


def test_shell_openspec_route_is_frozen_no_sync_and_forwards_arguments(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [
            str(REPO_ROOT / "trade"),
            "dev",
            "openspec",
            "change-a",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    lines = result.stdout.splitlines()
    assert lines[:4] == ["run", "--frozen", "--no-sync", "python"]
    assert lines[-5:] == ["dev", "openspec", "change-a", "--format", "json"]


def test_shell_help_lists_openspec_command(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(REPO_ROOT / "trade"), "help"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "./trade dev openspec [change]" in result.stdout


def test_status_package_does_not_import_runtime_or_web_modules() -> None:
    forbidden = (
        "trade_py.data",
        "trade_py.db",
        "trade_py.event",
        "trade_py.intelligence",
        "trade_web",
    )
    for path in (REPO_ROOT / "trade_py" / "devtools" / "openspec_status").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.append(node.module)
        assert not any(
            module == prefix or module.startswith(f"{prefix}.")
            for module in imported
            for prefix in forbidden
        ), path
