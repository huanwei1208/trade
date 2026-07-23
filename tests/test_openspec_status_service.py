from __future__ import annotations

from datetime import date

import pytest

from trade_py.devtools.openspec_status.errors import WorkflowError
from trade_py.devtools.openspec_status.models import (
    ArtifactEvidence,
    ChangeWorkflow,
    GovernanceEvidence,
    NativeEvidence,
    NextAction,
    TaskProgress,
    ValidationEvidence,
    ValidationIssue,
    WorkflowReport,
    WorkflowSource,
)
from trade_py.devtools.openspec_status.native import NativeChange
from trade_py.devtools.openspec_status.service import _derive_change


def _native(
    *,
    artifacts: tuple[ArtifactEvidence, ...] | None = None,
    validation_valid: bool = True,
    completed: int = 1,
    total: int = 2,
) -> NativeChange:
    active_artifacts = artifacts or (
        ArtifactEvidence("proposal", "proposal.md", "done"),
        ArtifactEvidence("tasks", "tasks.md", "done"),
    )
    issues = (
        ()
        if validation_valid
        else (ValidationIssue("error", "specs/test/spec.md", "Requirement is invalid."),)
    )
    return NativeChange(
        name="change-a",
        tasks=TaskProgress.from_counts(completed, total),
        evidence=NativeEvidence(
            schema_name="spec-driven",
            is_complete=all(item.status == "done" for item in active_artifacts),
            apply_requires=("tasks",),
            artifacts=active_artifacts,
            validation=ValidationEvidence(
                valid=validation_valid,
                issues=issues,
                omitted_count=0,
            ),
            payload_digests={
                "list": f"sha256:{'1' * 64}",
                "status": f"sha256:{'2' * 64}",
                "validation": f"sha256:{'3' * 64}",
            },
        ),
    )


def _governance(
    *,
    status: str = "PASS",
    governance_status: str = "GOVERNED",
    approval: bool = True,
    rules: tuple[str, ...] = (),
    required: bool = True,
    source: str = "existing_governed",
) -> GovernanceEvidence:
    return GovernanceEvidence(
        required=required,
        requirement_source=source,
        report={
            "status": status,
            "governance_status": governance_status,
            "approval_eligible": approval,
            "findings": [{"rule_id": rule, "suppressed": False} for rule in rules],
        },
    )


@pytest.mark.parametrize(
    ("native", "governance", "lifecycle", "kind", "command_fragment"),
    (
        (
            _native(
                artifacts=(
                    ArtifactEvidence("proposal", "proposal.md", "ready"),
                    ArtifactEvidence(
                        "tasks",
                        "tasks.md",
                        "blocked",
                        ("proposal",),
                    ),
                )
            ),
            _governance(),
            "authoring",
            "author",
            "instructions proposal",
        ),
        (
            _native(validation_valid=False),
            _governance(),
            "blocked",
            "repair",
            "openspec validate",
        ),
        (
            _native(),
            _governance(
                status="FAIL",
                approval=False,
                rules=("core.review.stale",),
            ),
            "review",
            "review",
            "review --slug",
        ),
        (
            _native(completed=1, total=2),
            _governance(),
            "implementation",
            "apply",
            "instructions apply",
        ),
        (
            _native(completed=0, total=0),
            _governance(),
            "implementation",
            "apply",
            "instructions apply",
        ),
        (
            _native(completed=2, total=2),
            _governance(),
            "archive-ready",
            "archive",
            "openspec archive",
        ),
        (
            _native(completed=2, total=2),
            _governance(
                status="NOT_GOVERNED",
                governance_status="NOT_GOVERNED",
                approval=False,
                required=False,
                source="historical_exempt",
            ),
            "archive-ready",
            "archive",
            "openspec archive",
        ),
    ),
)
def test_lifecycle_matrix(
    native: NativeChange,
    governance: GovernanceEvidence,
    lifecycle: str,
    kind: str,
    command_fragment: str,
) -> None:
    result = _derive_change(native, governance)

    assert result.collection_status == "complete"
    assert result.lifecycle == lifecycle
    assert result.next_action.kind == kind
    assert result.next_action.command is not None
    assert command_fragment in result.next_action.command


@pytest.mark.parametrize(
    "governance",
    (
        _governance(
            status="FAIL",
            governance_status="REQUIRED_MISSING",
            approval=False,
            rules=("core.governance.missing",),
            source="new_change",
        ),
        _governance(
            status="FAIL",
            approval=False,
            rules=("core.review.stale", "core.governance.invalid"),
        ),
    ),
)
def test_governance_blocker_precedes_authoring(
    governance: GovernanceEvidence,
) -> None:
    native = _native(
        artifacts=(
            ArtifactEvidence("proposal", "proposal.md", "ready"),
            ArtifactEvidence("tasks", "tasks.md", "blocked", ("proposal",)),
        )
    )

    result = _derive_change(native, governance)

    assert result.lifecycle == "blocked"
    assert result.next_action.command == "./trade dev design-check change-a --strict"


def test_incomplete_artifact_graph_without_ready_node_is_unavailable() -> None:
    native = _native(
        artifacts=(
            ArtifactEvidence("proposal", "proposal.md", "blocked", ("design",)),
            ArtifactEvidence("tasks", "tasks.md", "blocked", ("proposal",)),
        )
    )

    result = _derive_change(native, _governance())

    assert result.collection_status == "unavailable"
    assert result.lifecycle is None
    assert result.errors[0].code == "workflow.openspec.artifact_deadlock"


def test_valid_but_unapproved_empty_governance_state_is_unavailable() -> None:
    result = _derive_change(
        _native(completed=2, total=2),
        _governance(status="FAIL", approval=False),
    )

    assert result.collection_status == "unavailable"
    assert result.errors[0].code == "workflow.design_quality.state"


def test_workflow_report_error_precedence_and_summary_are_consistent() -> None:
    error = WorkflowError(
        code="workflow.openspec.shape",
        source="openspec",
        change="change-b",
        message="Malformed status.",
        remediation="Repair OpenSpec.",
    )
    unavailable = ChangeWorkflow.unavailable("change-b", error)
    blocked = ChangeWorkflow(
        name="change-a",
        collection_status="complete",
        lifecycle="blocked",
        tasks=TaskProgress.from_counts(1, 1),
        native=_native(completed=1, total=1).evidence,
        governance=_governance(),
        next_action=NextAction("repair", "openspec validate change-a --strict", "Fix validation."),
    )
    report = WorkflowReport(
        evaluation_date=date(2026, 7, 23),
        source=WorkflowSource(
            git_head="a" * 40,
            base_ref="origin/master",
            base_sha="b" * 40,
            snapshot_digest=f"sha256:{'c' * 64}",
        ),
        changes=(unavailable, blocked),
    )

    payload = report.to_dict()

    assert report.exit_code == 2
    assert report.status == "ERROR"
    assert payload["summary"] == {
        "changes": 2,
        "authoring": 0,
        "review": 0,
        "implementation": 0,
        "archive_ready": 0,
        "blocked": 1,
        "unavailable": 1,
        "errors": 1,
    }
    assert payload["errors"] == [error.to_dict()]
