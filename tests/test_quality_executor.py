from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trade_py.devtools.design_quality.policy import load_policy
from trade_py.devtools.design_quality.report_binding import load_report_bindings
from trade_py.devtools.quality.config import QualityConfig
from trade_py.devtools.quality.executor import (
    SubprocessExecutor,
    _design_envelope_error,
    _design_invocation,
    execute_steps,
    validate_design_batch_payload,
)
from trade_py.devtools.quality.models import (
    CheckStep,
    FailureKind,
    ResultStatus,
    StepResult,
)
from trade_py.devtools.quality.render import _design_detail_lines

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY = load_policy(REPO_ROOT)


@pytest.fixture(autouse=True)
def _trusted_policy_fixture(tmp_path: Path) -> None:
    shutil.copytree(REPO_ROOT / "design-policy", tmp_path / "design-policy")


class ScriptedExecutor:
    def __init__(self, results: dict[str, StepResult]) -> None:
        self.results = results
        self.called: list[str] = []

    def run_step(self, step: CheckStep) -> StepResult:
        self.called.append(step.check_id)
        return self.results[step.check_id]


def _result(check_id: str, *, kind: FailureKind | None = None) -> StepResult:
    return StepResult(
        check_id=check_id,
        group="test",
        name=check_id,
        status=ResultStatus.FAIL if kind else ResultStatus.PASS,
        duration_ms=1,
        failure_kind=kind,
    )


def _design_report_payload(**overrides: object) -> dict[str, object]:
    today = datetime.now(timezone.utc).date().isoformat()
    payload: dict[str, object] = {
        "schema_version": "trade.design.report.v1",
        "checker_version": "1",
        "policy_version": "v1",
        "policy_digest": POLICY.digest,
        "artifact_digest": f"sha256:{'b' * 64}",
        "change": "test-change",
        "strict": True,
        "effective_date": today,
        "approval_eligible": True,
        "governance_status": "GOVERNED",
        "status": "PASS",
        "exit_code": 0,
        "profiles": ["core"],
        "findings": [],
        "exceptions": [],
        "artifacts": [],
        "counts": {"blockers": 0, "warnings": 0, "suppressed": 0},
        "metadata": {
            "reviewed_at": today,
            "reviewed_commit": "c" * 40,
            "reviewed_commit_status": "verified",
        },
    }
    payload.update(overrides)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        payload["metadata"] = {"total_bytes": 0, **metadata}
    return payload


def _write_binding_change(repo: Path, name: str) -> None:
    change = repo / "openspec" / "changes" / name
    change.mkdir(parents=True)
    impact_rows = "\n\n".join(
        "\n".join(
            (
                "[[impacts]]",
                f'id = "{impact}"',
                f"applies = {'true' if impact == 'external_event_data' else 'false'}",
                f'reason = "The fixture explicitly declares the {impact} applicability state."',
            )
        )
        for impact in POLICY.required_impacts
    )
    (change / "design-quality.toml").write_text(
        f'schema_version = 1\npolicy_version = "v1"\n\n{impact_rows}\n',
        encoding="utf-8",
    )


def test_design_invocation_binds_sorted_planned_targets() -> None:
    invocation = _design_invocation(
        (
            sys.executable,
            "-m",
            "trade_py.devtools.design_quality.cli",
            "--strict",
            "--change",
            "zeta-change",
            "--change",
            "alpha-change",
            "--require-governance",
            "alpha-change",
            "--missing-required",
            "removed-change",
            "--immutable-policy-edit",
            "design-policy/v1.toml",
        )
    )

    assert invocation is not None
    assert invocation.live_changes == ("alpha-change", "zeta-change")
    assert invocation.required_changes == ("alpha-change",)
    assert invocation.targets == (
        "alpha-change",
        "zeta-change",
        "removed-change",
        "immutable-policy-v1",
    )


@pytest.mark.parametrize(
    "attack",
    (
        "missing-external-profile",
        "wrong-change",
        "duplicate-artifact",
        "too-many-artifacts",
        "artifact-digest",
        "total-bytes",
        "governance-downgrade",
    ),
)
def test_parent_binds_pass_to_planned_current_snapshot(tmp_path: Path, attack: str) -> None:
    change = "external-news"
    _write_binding_change(tmp_path, change)
    binding = load_report_bindings(tmp_path, (change,), POLICY)[change]
    assert binding.profiles is not None
    report = _design_report_payload(
        change=change,
        artifact_digest=binding.artifact_digest,
        profiles=list(binding.profiles),
        artifacts=[dict(item) for item in binding.artifacts],
        metadata={
            "total_bytes": binding.total_bytes,
            "reviewed_at": datetime.now(timezone.utc).date().isoformat(),
            "reviewed_commit": "c" * 40,
            "reviewed_commit_status": "verified",
        },
    )
    expected = (change,)
    if attack == "missing-external-profile":
        report["profiles"] = ["core"]
    elif attack == "wrong-change":
        report["change"] = "unplanned-change"
    elif attack == "duplicate-artifact":
        artifacts = report["artifacts"]
        assert isinstance(artifacts, list)
        artifacts.append(dict(artifacts[0]))
        metadata = report["metadata"]
        assert isinstance(metadata, dict)
        metadata["total_bytes"] = sum(int(item["size_bytes"]) for item in artifacts)
    elif attack == "too-many-artifacts":
        report["artifacts"] = [
            {
                "path": f"specs/capability-{index:03d}/spec.md",
                "size_bytes": 0,
                "digest": f"sha256:{index:064x}",
            }
            for index in range(POLICY.limits.max_files_per_change + 1)
        ]
        metadata = report["metadata"]
        assert isinstance(metadata, dict)
        metadata["total_bytes"] = 0
    elif attack == "artifact-digest":
        report["artifact_digest"] = f"sha256:{'0' * 64}"
    elif attack == "total-bytes":
        metadata = report["metadata"]
        assert isinstance(metadata, dict)
        metadata["total_bytes"] = binding.total_bytes + 1
    elif attack == "governance-downgrade":
        report.update(
            {
                "status": "NOT_GOVERNED",
                "governance_status": "NOT_GOVERNED",
                "approval_eligible": False,
                "profiles": [],
            }
        )
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 1,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }

    error = _design_envelope_error(
        payload,
        0,
        policy=POLICY,
        expected_changes=expected,
        bindings={change: binding},
    )

    assert error is not None


@pytest.mark.parametrize("required", (False, True))
def test_parent_binds_unmarked_live_governance(tmp_path: Path, required: bool) -> None:
    change = "unmarked-change"
    change_dir = tmp_path / "openspec" / "changes" / change
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text("## Why\n\nHistorical fixture.\n", encoding="utf-8")
    required_changes = frozenset({change}) if required else frozenset()
    binding = load_report_bindings(
        tmp_path,
        (change,),
        POLICY,
        require_governance=required_changes,
    )[change]
    report = _design_report_payload(
        change=change,
        artifact_digest=binding.artifact_digest,
        status="NOT_GOVERNED",
        governance_status="NOT_GOVERNED",
        approval_eligible=False,
        profiles=[],
        artifacts=[dict(item) for item in binding.artifacts],
        metadata={"total_bytes": binding.total_bytes},
    )
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 0,
            "failed": 0,
            "not_governed": 1,
            "errors": 0,
        },
    }

    error = _design_envelope_error(
        payload,
        0,
        policy=POLICY,
        expected_changes=(change,),
        expected_governance={change: binding.governance_status},
        bindings={change: binding},
    )

    if required:
        assert binding.governance_status == "REQUIRED_MISSING"
        assert error is not None
    else:
        assert binding.governance_status == "NOT_GOVERNED"
        assert error is None


def test_parent_accepts_exact_planned_current_snapshot(tmp_path: Path) -> None:
    change = "external-news"
    _write_binding_change(tmp_path, change)
    binding = load_report_bindings(tmp_path, (change,), POLICY)[change]
    assert binding.profiles is not None
    report = _design_report_payload(
        change=change,
        artifact_digest=binding.artifact_digest,
        profiles=list(binding.profiles),
        artifacts=[dict(item) for item in binding.artifacts],
        metadata={
            "total_bytes": binding.total_bytes,
            "reviewed_at": datetime.now(timezone.utc).date().isoformat(),
            "reviewed_commit": "c" * 40,
            "reviewed_commit_status": "verified",
        },
    )
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 1,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }

    assert (
        _design_envelope_error(
            payload,
            0,
            policy=POLICY,
            expected_changes=(change,),
            bindings={change: binding},
        )
        is None
    )


def test_workflow_validator_isolates_one_malformed_bound_report(tmp_path: Path) -> None:
    names = ("change-a", "change-b")
    for name in names:
        _write_binding_change(tmp_path, name)
    bindings = load_report_bindings(tmp_path, names, POLICY)
    today = datetime.now(timezone.utc).date()
    reports = []
    for name in names:
        binding = bindings[name]
        assert binding.profiles is not None
        reports.append(
            _design_report_payload(
                change=name,
                artifact_digest=binding.artifact_digest,
                profiles=list(binding.profiles),
                artifacts=[dict(item) for item in binding.artifacts],
                metadata={
                    "total_bytes": binding.total_bytes,
                    "reviewed_at": today.isoformat(),
                    "reviewed_commit": "c" * 40,
                    "reviewed_commit_status": "verified",
                },
            )
        )
    reports[1]["artifact_digest"] = f"sha256:{'0' * 64}"
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": reports,
        "summary": {
            "changes": 2,
            "passed": 2,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }

    validation = validate_design_batch_payload(
        payload,
        0,
        policy=POLICY,
        expected_changes=names,
        expected_governance={name: bindings[name].governance_status for name in names},
        bindings=bindings,
        evaluation_date=today,
    )

    assert validation.envelope_error is None
    assert set(validation.report_errors) == {"change-b"}
    assert "trusted current snapshot" in validation.report_errors["change-b"]
    assert (
        _design_envelope_error(
            payload,
            0,
            policy=POLICY,
            expected_changes=names,
            expected_governance={name: bindings[name].governance_status for name in names},
            bindings=bindings,
            current_date=today,
        )
        is not None
    )


def test_workflow_validator_rejects_summary_that_contradicts_reports(
    tmp_path: Path,
) -> None:
    change = "change-a"
    _write_binding_change(tmp_path, change)
    binding = load_report_bindings(tmp_path, (change,), POLICY)[change]
    assert binding.profiles is not None
    today = datetime.now(timezone.utc).date()
    report = _design_report_payload(
        change=change,
        artifact_digest=binding.artifact_digest,
        profiles=list(binding.profiles),
        artifacts=[dict(item) for item in binding.artifacts],
        metadata={
            "total_bytes": binding.total_bytes,
            "reviewed_at": today.isoformat(),
            "reviewed_commit": "c" * 40,
            "reviewed_commit_status": "verified",
        },
    )
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 1,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 0,
            "failed": 1,
            "not_governed": 0,
            "errors": 0,
        },
    }

    validation = validate_design_batch_payload(
        payload,
        1,
        policy=POLICY,
        expected_changes=(change,),
        expected_governance={change: binding.governance_status},
        bindings={change: binding},
        evaluation_date=today,
    )

    assert validation.envelope_error == (
        "Structured design envelope summary does not match its reports"
    )
    assert validation.report_errors == {}


def test_executor_import_keeps_design_evaluator_lazy() -> None:
    script = """
import json
import sys
import trade_py.devtools.quality.executor

names = (
    "trade_py.devtools.design_quality.evaluate",
    "trade_py.devtools.design_quality.models",
    "trade_py.devtools.design_quality.policy",
)
before = {name: name in sys.modules for name in names}
from trade_py.devtools.design_quality import DesignReport, evaluate_change
print(json.dumps({"before": before, "public_exports": bool(DesignReport and evaluate_change)}, sort_keys=True))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "before": {
            "trade_py.devtools.design_quality.evaluate": False,
            "trade_py.devtools.design_quality.models": False,
            "trade_py.devtools.design_quality.policy": False,
        },
        "public_exports": True,
    }


def test_executor_aggregates_independent_failures_and_skips_dependents() -> None:
    steps = (
        CheckStep("lint", "python", "lint", ("lint",)),
        CheckStep("build", "cpp", "build", ("build",)),
        CheckStep("test", "cpp", "test", ("test",), prerequisites=("build",)),
    )
    executor = ScriptedExecutor(
        {
            "lint": _result("lint", kind=FailureKind.QUALITY),
            "build": _result("build", kind=FailureKind.INFRASTRUCTURE),
        }
    )

    results = execute_steps(steps, executor, max_light_workers=2)
    by_id = {result.check_id: result for result in results}

    assert set(executor.called) == {"lint", "build"}
    assert by_id["test"].status is ResultStatus.SKIP
    assert by_id["test"].caused_by == "build"
    assert max(result.aggregate_exit_code for result in results) == 2


def test_missing_relevant_tool_is_infrastructure_failure(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    step = CheckStep(
        "cpp.format",
        "cpp",
        "clang-format",
        ("definitely-missing-quality-tool", "--version"),
        remediation="Install it.",
    )

    result = executor.run_step(step)

    assert result.status is ResultStatus.FAIL
    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2
    assert "Missing required tool" in result.diagnostic


def test_mutation_target_is_revalidated_before_spawn(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.cpp"
    outside.write_text("int value;\n", encoding="utf-8")
    os.symlink(outside, tmp_path / "owned.cpp")
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    step = CheckStep(
        "cpp.fix",
        "cpp",
        "fix",
        (sys.executable, "--version"),
        files=("owned.cpp",),
        mutates_source=True,
    )

    result = executor.run_step(step)

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert "symlinked source" in result.diagnostic


def test_timeout_and_signal_are_infrastructure_failures(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    timeout = executor.run_step(
        CheckStep(
            "slow",
            "test",
            "slow",
            (sys.executable, "-c", "import time; time.sleep(10)"),
            timeout_seconds=1,
        )
    )
    signalled = executor.run_step(
        CheckStep(
            "signal",
            "test",
            "signal",
            (sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"),
        )
    )

    assert timeout.failure_kind is FailureKind.INFRASTRUCTURE
    assert "Timed out" in timeout.diagnostic
    assert signalled.failure_kind is FailureKind.INFRASTRUCTURE


def test_timeout_still_applies_after_child_closes_output_pipes(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    started = time.monotonic()

    result = executor.run_step(
        CheckStep(
            "closed-pipes",
            "test",
            "closed pipes",
            (
                sys.executable,
                "-c",
                "import os,time; os.close(1); os.close(2); time.sleep(10)",
            ),
            timeout_seconds=1,
        )
    )

    assert time.monotonic() - started < 4
    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert "Timed out after 1s" in result.diagnostic


def test_dynamic_loader_version_failure_is_infrastructure(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    result = executor.run_step(
        CheckStep(
            "native",
            "web",
            "native tool",
            (
                sys.executable,
                "-c",
                "import sys; print('GLIBC_2.29 not found (required by tool)', file=sys.stderr); sys.exit(1)",
            ),
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


def test_structured_step_preserves_nested_exit_mapping_and_details(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    quality = executor.run_step(
        CheckStep(
            "design.quality",
            "design",
            "design quality",
            (
                sys.executable,
                "-c",
                "import json,sys; print(json.dumps({'schema_version':'test.v1'})); sys.exit(1)",
            ),
            exit_code_kinds=((1, FailureKind.QUALITY), (2, FailureKind.INFRASTRUCTURE)),
            structured_output_schema="test.v1",
        )
    )
    infrastructure = executor.run_step(
        CheckStep(
            "design.infrastructure",
            "design",
            "design infrastructure",
            (
                sys.executable,
                "-c",
                "import json,sys; print(json.dumps({'schema_version':'test.v1'})); sys.exit(2)",
            ),
            exit_code_kinds=((1, FailureKind.QUALITY), (2, FailureKind.INFRASTRUCTURE)),
            structured_output_schema="test.v1",
        )
    )

    assert quality.failure_kind is FailureKind.QUALITY
    assert quality.details == {"schema_version": "test.v1"}
    assert infrastructure.failure_kind is FailureKind.INFRASTRUCTURE
    assert infrastructure.aggregate_exit_code == 2


def test_invalid_structured_output_is_infrastructure_failure(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    result = executor.run_step(
        CheckStep(
            "design.invalid",
            "design",
            "invalid design output",
            (sys.executable, "-c", "print('{}')"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert "expected schema" in result.diagnostic


def test_structured_output_is_rejected_before_unbounded_json_parse(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    result = executor.run_step(
        CheckStep(
            "design.oversized",
            "design",
            "oversized design output",
            (
                sys.executable,
                "-c",
                "import json; print(json.dumps({'schema_version':'test.v1','pad':'x'*4096}))",
            ),
            output_limit_bytes=128,
            structured_output_schema="test.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert "exceeded 128 bytes" in result.diagnostic


def test_oversized_structured_output_terminates_child_immediately(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    started = time.monotonic()

    result = executor.run_step(
        CheckStep(
            "design.oversized-sleeper",
            "design",
            "oversized sleeping design output",
            (
                sys.executable,
                "-c",
                "import sys,time; sys.stdout.write('x'*4096); sys.stdout.flush(); time.sleep(10)",
            ),
            timeout_seconds=10,
            output_limit_bytes=128,
            structured_output_schema="test.v1",
        )
    )

    assert time.monotonic() - started < 4
    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert "exceeded 128 bytes" in result.diagnostic


def test_unexpected_structured_exit_defaults_to_infrastructure(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    result = executor.run_step(
        CheckStep(
            "design.unexpected",
            "design",
            "unexpected design exit",
            (
                sys.executable,
                "-c",
                "import json,sys; print(json.dumps({'schema_version':'test.v1'})); sys.exit(3)",
            ),
            exit_code_kinds=((1, FailureKind.QUALITY), (2, FailureKind.INFRASTRUCTURE)),
            nonzero_kind=FailureKind.INFRASTRUCTURE,
            structured_output_schema="test.v1",
        )
    )

    assert result.exit_code == 3
    assert result.failure_kind is FailureKind.INFRASTRUCTURE


def test_not_governed_structured_batch_is_visible_warning(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [
            _design_report_payload(
                status="NOT_GOVERNED",
                governance_status="NOT_GOVERNED",
                approval_eligible=False,
                profiles=[],
                metadata={},
            )
        ],
        "summary": {
            "changes": 1,
            "passed": 0,
            "failed": 0,
            "not_governed": 1,
            "errors": 0,
        },
    }
    result = executor.run_step(
        CheckStep(
            "design.strict",
            "design",
            "historical design",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.status is ResultStatus.WARN
    assert result.aggregate_exit_code == 0


def test_design_batch_nested_exit_must_match_child_exit(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 1,
        "reports": [],
        "summary": {},
    }

    result = executor.run_step(
        CheckStep(
            "design.inconsistent",
            "design",
            "inconsistent design batch",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert "inconsistent with the child process exit" in result.diagnostic


def test_design_batch_summary_and_report_exits_must_be_consistent(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [
            _design_report_payload(
                status="FAIL",
                exit_code=1,
                approval_eligible=False,
                findings=[
                    {
                        "rule_id": "core.review.stale",
                        "severity": "blocker",
                        "path": "design-review.toml",
                        "message": "Review evidence is stale.",
                        "remediation": "Refresh the bound review evidence.",
                        "suppressed": False,
                    }
                ],
                counts={"blockers": 1, "warnings": 0, "suppressed": 0},
                metadata={},
            )
        ],
        "summary": {
            "changes": 1,
            "passed": 0,
            "failed": 1,
            "not_governed": 0,
            "errors": 0,
        },
    }

    result = executor.run_step(
        CheckStep(
            "design.inconsistent-reports",
            "design",
            "inconsistent design reports",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert "exit code does not match its reports" in result.diagnostic


@pytest.mark.parametrize("status", ("FAIL", "UNKNOWN"))
def test_design_batch_rejects_fail_or_unknown_report_with_zero_exit(
    tmp_path: Path, status: str
) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [_design_report_payload(status=status, approval_eligible=False, metadata={})],
        "summary": {
            "changes": 1,
            "passed": 0,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }

    result = executor.run_step(
        CheckStep(
            f"design.{status.lower()}",
            "design",
            "invalid design report state",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


@pytest.mark.parametrize("attack", ("diagnostic", "pass-with-blocker"))
def test_parent_rejects_nonstrict_or_pass_with_active_findings(tmp_path: Path, attack: str) -> None:
    finding = {
        "rule_id": "core.review.stale",
        "severity": "blocker",
        "path": "design-review.toml",
        "message": "Review evidence is stale.",
        "remediation": "Refresh the bound review evidence.",
        "suppressed": False,
    }
    report = _design_report_payload(
        status="DIAGNOSTIC" if attack == "diagnostic" else "PASS",
        approval_eligible=attack == "pass-with-blocker",
        strict=attack != "diagnostic",
        findings=[] if attack == "diagnostic" else [finding],
        counts={
            "blockers": 0 if attack == "diagnostic" else 1,
            "warnings": 0,
            "suppressed": 0,
        },
        metadata=(
            {}
            if attack == "diagnostic"
            else {
                "reviewed_at": "2026-07-20",
                "reviewed_commit": "c" * 40,
                "reviewed_commit_status": "verified",
            }
        ),
    )
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 1 if attack == "pass-with-blocker" else 0,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    result = executor.run_step(
        CheckStep(
            f"design.{attack}",
            "design",
            "adversarial design report",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


def test_parent_rejects_suppressed_blocker(tmp_path: Path) -> None:
    finding = {
        "rule_id": "core.review.stale",
        "severity": "blocker",
        "path": "design-review.toml",
        "message": "Review evidence is stale.",
        "remediation": "Refresh the bound review evidence.",
        "suppressed": True,
    }
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [
            _design_report_payload(
                findings=[finding],
                counts={"blockers": 0, "warnings": 0, "suppressed": 1},
            )
        ],
        "summary": {
            "changes": 1,
            "passed": 1,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    result = executor.run_step(
        CheckStep(
            "design.suppressed-blocker",
            "design",
            "suppressed blocker attack",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert "illegally suppresses a blocker" in result.diagnostic


def test_valid_design_envelope_exit_mapping_ignores_stderr_markers(tmp_path: Path) -> None:
    finding = {
        "rule_id": "core.review.stale",
        "severity": "blocker",
        "path": "design-review.toml",
        "message": "Review evidence is stale.",
        "remediation": "Refresh review evidence.",
        "suppressed": False,
    }
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 1,
        "reports": [
            _design_report_payload(
                status="FAIL",
                exit_code=1,
                approval_eligible=False,
                findings=[finding],
                counts={"blockers": 1, "warnings": 0, "suppressed": 0},
                metadata={},
            )
        ],
        "summary": {
            "changes": 1,
            "passed": 0,
            "failed": 1,
            "not_governed": 0,
            "errors": 0,
        },
    }
    script = (
        "import json,sys; "
        f"print({json.dumps(json.dumps(payload))}); "
        "print('GLIBC_2.29 not found (required by optional formatter)', file=sys.stderr); "
        "sys.exit(1)"
    )
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    result = executor.run_step(
        CheckStep(
            "design.stderr-marker",
            "design",
            "structured failure with stderr marker",
            (sys.executable, "-c", script),
            exit_code_kinds=((1, FailureKind.QUALITY), (2, FailureKind.INFRASTRUCTURE)),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.QUALITY
    assert result.aggregate_exit_code == 1


def test_parent_rejects_empty_success_envelope(tmp_path: Path) -> None:
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [],
        "summary": {
            "changes": 0,
            "passed": 0,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    result = executor.run_step(
        CheckStep(
            "design.empty-success",
            "design",
            "empty success envelope",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


def test_parent_rejects_not_governed_with_findings(tmp_path: Path) -> None:
    finding = {
        "rule_id": "core.governance.missing",
        "severity": "blocker",
        "path": "design-quality.toml",
        "message": "Governance is missing.",
        "remediation": "Add governance evidence.",
        "suppressed": False,
    }
    report = _design_report_payload(
        status="NOT_GOVERNED",
        governance_status="NOT_GOVERNED",
        approval_eligible=False,
        profiles=[],
        findings=[finding],
        counts={"blockers": 1, "warnings": 0, "suppressed": 0},
        metadata={},
    )
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 0,
            "failed": 0,
            "not_governed": 1,
            "errors": 0,
        },
    }
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    result = executor.run_step(
        CheckStep(
            "design.not-governed-findings",
            "design",
            "not governed with findings",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


@pytest.mark.parametrize("malformation", ("missing-audit-fields", "boolean-summary"))
def test_parent_rejects_incomplete_report_or_noninteger_summary(
    tmp_path: Path, malformation: str
) -> None:
    report = _design_report_payload()
    summary: dict[str, int | bool] = {
        "changes": 1,
        "passed": 1,
        "failed": 0,
        "not_governed": 0,
        "errors": 0,
    }
    if malformation == "missing-audit-fields":
        report.pop("artifact_digest")
    else:
        summary["passed"] = True
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": summary,
    }
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    result = executor.run_step(
        CheckStep(
            f"design.{malformation}",
            "design",
            "malformed audit report",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


@pytest.mark.parametrize("malformation", ("invalid-review-status", "impossible-date"))
def test_parent_rejects_invalid_approval_provenance(tmp_path: Path, malformation: str) -> None:
    report = _design_report_payload()
    if malformation == "invalid-review-status":
        metadata = report["metadata"]
        assert isinstance(metadata, dict)
        report["metadata"] = {**metadata, "reviewed_commit_status": "invalid"}
    else:
        report["effective_date"] = "2026-99-99"
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 1,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    result = executor.run_step(
        CheckStep(
            f"design.{malformation}",
            "design",
            "invalid approval provenance",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


@pytest.mark.parametrize("attack", ("stale-review", "expired-exception"))
def test_parent_rejects_stale_review_or_expired_suppression(tmp_path: Path, attack: str) -> None:
    today = datetime.now(timezone.utc).date()
    report = _design_report_payload()
    if attack == "stale-review":
        metadata = report["metadata"]
        assert isinstance(metadata, dict)
        report["metadata"] = {
            **metadata,
            "reviewed_at": (today - timedelta(days=1)).isoformat(),
        }
    else:
        rule_id = "structure.catch_all"
        report["exceptions"] = [
            {
                "rule_id": rule_id,
                "owner": "qa",
                "reason": "Temporary exception carried by an adversarial child payload.",
                "expires": (today - timedelta(days=1)).isoformat(),
                "state": "applied",
            }
        ]
        report["findings"] = [
            {
                "rule_id": rule_id,
                "severity": "warning",
                "path": "tests/utils.py",
                "message": "Catch-all test helper remains in scope.",
                "remediation": "Move the helper into an owned fixture module.",
                "suppressed": True,
            }
        ]
        report["counts"] = {"blockers": 0, "warnings": 0, "suppressed": 1}
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 1,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    result = executor.run_step(
        CheckStep(
            f"design.{attack}",
            "design",
            "stale design approval attack",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


@pytest.mark.parametrize("attack", ("blank-owner", "placeholder-reason", "invalid-rule"))
def test_parent_rejects_malformed_exception_backing(tmp_path: Path, attack: str) -> None:
    today = datetime.now(timezone.utc).date()
    rule_id = "structure.catch_all" if attack != "invalid-rule" else "not valid"
    exception = {
        "rule_id": rule_id,
        "owner": "qa" if attack != "blank-owner" else "",
        "reason": (
            "Temporary exception while the owned fixture is extracted."
            if attack != "placeholder-reason"
            else "not applicable"
        ),
        "expires": (today + timedelta(days=30)).isoformat(),
        "state": "applied",
    }
    finding = {
        "rule_id": rule_id,
        "severity": "warning",
        "path": "tests/utils.py",
        "message": "Catch-all test helper remains in scope.",
        "remediation": "Move the helper into an owned fixture module.",
        "suppressed": True,
    }
    report = _design_report_payload(
        exceptions=[exception],
        findings=[finding],
        counts={"blockers": 0, "warnings": 0, "suppressed": 1},
    )
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 1,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    result = executor.run_step(
        CheckStep(
            f"design.{attack}",
            "design",
            "malformed exception backing attack",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


@pytest.mark.parametrize(
    ("rule_id", "severity"),
    (("unknown.suppressible", "warning"), ("core.governance.missing", "warning")),
)
def test_parent_binds_suppression_to_immutable_policy(
    tmp_path: Path, rule_id: str, severity: str
) -> None:
    today = datetime.now(timezone.utc).date()
    report = _design_report_payload(
        exceptions=[
            {
                "rule_id": rule_id,
                "owner": "qa",
                "reason": "Temporary exception while the owned fixture is corrected.",
                "expires": (today + timedelta(days=30)).isoformat(),
                "state": "applied",
            }
        ],
        findings=[
            {
                "rule_id": rule_id,
                "severity": severity,
                "path": "design-quality.toml",
                "message": "Adversarial child attempts to hide a policy finding.",
                "remediation": "Restore the immutable policy rule semantics.",
                "suppressed": True,
            }
        ],
        counts={"blockers": 0, "warnings": 0, "suppressed": 1},
    )
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 1,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }

    result = SubprocessExecutor(tmp_path, QualityConfig()).run_step(
        CheckStep(
            f"design.policy-{rule_id}",
            "design",
            "policy suppression attack",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


def test_parent_rejects_untrusted_policy_digest(tmp_path: Path) -> None:
    report = _design_report_payload(policy_digest=f"sha256:{'0' * 64}")
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 1,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }

    result = SubprocessExecutor(tmp_path, QualityConfig()).run_step(
        CheckStep(
            "design.untrusted-policy",
            "design",
            "untrusted policy digest attack",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


@pytest.mark.parametrize(
    "override",
    ({"policy_version": "v2"}, {"profiles": ["core", "unknown_profile"]}),
)
def test_parent_rejects_untrusted_policy_contract(
    tmp_path: Path, override: dict[str, object]
) -> None:
    report = _design_report_payload(**override)
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 1,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }

    result = SubprocessExecutor(tmp_path, QualityConfig()).run_step(
        CheckStep(
            "design.untrusted-policy-contract",
            "design",
            "untrusted policy contract attack",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


def test_parent_rejects_governed_report_without_core_profile(tmp_path: Path) -> None:
    report = _design_report_payload(profiles=[])
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": [report],
        "summary": {
            "changes": 1,
            "passed": 1,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }

    result = SubprocessExecutor(tmp_path, QualityConfig()).run_step(
        CheckStep(
            "design.missing-core-profile",
            "design",
            "governed profile omission attack",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


def test_parent_rejects_more_than_policy_batch_reports(tmp_path: Path) -> None:
    reports = [_design_report_payload(change=f"change-{index}") for index in range(101)]
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": reports,
        "summary": {
            "changes": 101,
            "passed": 101,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }
    executor = SubprocessExecutor(tmp_path, QualityConfig())

    result = executor.run_step(
        CheckStep(
            "design.too-many-reports",
            "design",
            "too many reports",
            (sys.executable, "-c", f"print({json.dumps(json.dumps(payload))})"),
            structured_output_schema="trade.design.batch.v1",
            output_limit_bytes=1_048_576,
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2


def test_parent_captures_one_utc_date_for_the_whole_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    today = datetime.now(timezone.utc).date()
    reports = [
        _design_report_payload(change="first-change"),
        _design_report_payload(change="second-change"),
    ]
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 0,
        "reports": reports,
        "summary": {
            "changes": 2,
            "passed": 2,
            "failed": 0,
            "not_governed": 0,
            "errors": 0,
        },
    }
    calls = 0

    def changing_date() -> object:
        nonlocal calls
        calls += 1
        return today + timedelta(days=calls - 1)

    monkeypatch.setattr("trade_py.devtools.quality.executor._current_utc_date", changing_date)

    assert _design_envelope_error(payload, 0, policy=POLICY) is None
    assert calls == 1


def test_parent_design_text_preserves_provenance_counts_and_remediation() -> None:
    lines = _design_detail_lines(
        {
            "reports": [
                {
                    "change": "typed-design",
                    "status": "PASS",
                    "governance_status": "GOVERNED",
                    "approval_eligible": True,
                    "strict": True,
                    "effective_date": "2026-07-20",
                    "policy_version": "v1",
                    "policy_digest": "sha256:policy",
                    "artifact_digest": "sha256:artifact",
                    "profiles": ["core", "external_event"],
                    "counts": {"blockers": 0, "warnings": 0, "suppressed": 0},
                    "exit_code": 0,
                    "findings": [],
                    "exceptions": [],
                    "metadata": {
                        "reviewed_at": "2026-07-20",
                        "reviewed_commit": "a" * 40,
                        "reviewed_commit_status": "verified",
                    },
                }
            ],
            "errors": [
                {
                    "code": "design.batch.invalid",
                    "message": "bad batch",
                    "remediation": "fix the invocation",
                }
            ],
            "summary": {
                "changes": 1,
                "passed": 1,
                "failed": 0,
                "not_governed": 0,
                "errors": 1,
            },
        }
    )
    text = "\n".join(lines)

    assert "policy_digest=sha256:policy" in text
    assert "profiles=core,external_event" in text
    assert "reviewed_at=2026-07-20" in text
    assert "reviewed_commit_status=verified" in text
    assert "counts blockers=0 warnings=0 suppressed=0 exit_code=0" in text
    assert "next: fix the invocation" in text
    assert "design summary changes=1 passed=1" in text


def test_parent_design_text_reports_omitted_details() -> None:
    finding = {
        "severity": "warning",
        "rule_id": "core.review.stale",
        "path": "design-review.toml",
        "message": "stale",
        "remediation": "refresh",
    }
    lines = _design_detail_lines(
        {
            "reports": [
                {
                    "change": "bounded-output",
                    "findings": [finding] * 21,
                    "exceptions": [{}] * 22,
                }
            ],
            "errors": [{}] * 23,
        }
    )
    text = "\n".join(lines)

    assert "1 finding(s) omitted" in text
    assert "2 exception(s) omitted" in text
    assert "3 design error(s) omitted" in text
