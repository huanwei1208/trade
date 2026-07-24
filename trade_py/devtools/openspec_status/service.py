"""Read-only OpenSpec workflow collection and lifecycle derivation."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

from trade_py.devtools.design_quality.errors import DesignQualityError
from trade_py.devtools.design_quality.policy import load_policy
from trade_py.devtools.design_quality.snapshot import validate_change_name
from trade_py.devtools.openspec_status.design import collect_design_evidence
from trade_py.devtools.openspec_status.errors import (
    WorkflowCollectionError,
    WorkflowError,
)
from trade_py.devtools.openspec_status.executor import BoundedProcessExecutor
from trade_py.devtools.openspec_status.models import (
    ChangeWorkflow,
    GovernanceEvidence,
    Lifecycle,
    NativeEvidence,
    NextAction,
    TaskProgress,
    WorkflowLimits,
    WorkflowReport,
)
from trade_py.devtools.openspec_status.native import (
    NativeChange,
    collect_native_evidence,
)
from trade_py.devtools.openspec_status.snapshot import capture_source_generation

_REVIEW_FINDINGS = frozenset(
    {
        "core.review.missing",
        "core.review.stale",
        "core.review.incomplete",
    }
)


def collect_workflow(
    repo_root: Path,
    requested_change: str | None = None,
    *,
    limits: WorkflowLimits | None = None,
    evaluation_date: date | None = None,
    executor: BoundedProcessExecutor | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> WorkflowReport:
    active_limits = limits or WorkflowLimits()
    captured_date = evaluation_date or datetime.now(timezone.utc).date()
    active_executor = executor or BoundedProcessExecutor()
    deadline = monotonic() + active_limits.command_deadline_seconds
    source = None
    try:
        if requested_change is not None:
            validate_change_name(requested_change)
        policy = load_policy(repo_root)
        generation = capture_source_generation(
            repo_root,
            executor=active_executor,
            deadline=deadline,
            policy=policy,
            limits=active_limits,
        )
        source = generation.source
        with generation.materialize() as snapshot_root:
            native = collect_native_evidence(
                snapshot_root,
                expected_names=generation.names,
                requested_change=requested_change,
                executor=active_executor,
                deadline=deadline,
                limits=active_limits,
            )
        selected = (requested_change,) if requested_change else native.names
        requirements = {
            item.change: item
            for item in generation.governance.requirements
            if item.change in selected
        }
        selected_governance = type(generation.governance)(
            tuple(requirements[name] for name in selected)
        )
        designs = collect_design_evidence(
            generation.repo_root,
            selected,
            selected_governance,
            evaluation_date=captured_date,
            executor=active_executor,
            deadline=deadline,
            policy=policy,
            limits=active_limits,
        )
        drift_errors = generation.verify(policy)
        errors = {**native.errors, **designs.errors, **drift_errors}
        changes = tuple(
            ChangeWorkflow.unavailable(name, errors[name])
            if name in errors
            else _derive_change(native.changes[name], designs.evidence[name])
            for name in selected
        )
        return WorkflowReport(
            evaluation_date=captured_date,
            source=generation.source,
            changes=changes,
            limits=active_limits,
        )
    except (DesignQualityError, ValueError) as exc:
        error = WorkflowError(
            code="workflow.request.invalid",
            source="request",
            change=requested_change,
            message=str(exc),
            remediation="Use a valid active change slug and rerun ./trade dev openspec.",
        )
    except WorkflowCollectionError as exc:
        error = exc.error
    except KeyboardInterrupt:
        active_executor.cancel_all()
        raise
    return WorkflowReport(
        evaluation_date=captured_date,
        source=source,
        changes=(),
        errors=(error,),
        limits=active_limits,
    )


def _derive_change(native_change: NativeChange, governance: GovernanceEvidence) -> ChangeWorkflow:
    name = native_change.name
    native = native_change.evidence
    tasks = native_change.tasks
    report = governance.report
    active_rules = _active_finding_rules(report)
    if report.get("governance_status") == "REQUIRED_MISSING" or (active_rules - _REVIEW_FINDINGS):
        return _complete(
            name,
            tasks,
            native,
            governance,
            lifecycle="blocked",
            action=NextAction(
                kind="repair",
                command=f"./trade dev design-check {name} --strict",
                reason="Required design-governance evidence is missing or invalid.",
            ),
        )

    first_incomplete = next(
        (item for item in native.artifacts if item.status != "done"),
        None,
    )
    if first_incomplete is not None:
        ready = next(
            (item for item in native.artifacts if item.status == "ready"),
            None,
        )
        if ready is None:
            error = WorkflowError(
                code="workflow.openspec.artifact_deadlock",
                source="openspec",
                change=name,
                message="Native artifact graph has no ready incomplete artifact.",
                remediation="Repair the OpenSpec schema dependency graph and rerun.",
            )
            return ChangeWorkflow.unavailable(name, error)
        return _complete(
            name,
            tasks,
            native,
            governance,
            lifecycle="authoring",
            action=NextAction(
                kind="author",
                command=f"openspec instructions {ready.id} --change {name}",
                reason=f"Authoring artifact {ready.id} is ready and incomplete.",
            ),
        )

    if not native.validation.valid:
        return _complete(
            name,
            tasks,
            native,
            governance,
            lifecycle="blocked",
            action=NextAction(
                kind="repair",
                command=f"openspec validate {name} --strict",
                reason="Native OpenSpec validation reports change-owned issues.",
            ),
        )

    if (
        report.get("governance_status") == "GOVERNED"
        and report.get("approval_eligible") is False
        and active_rules
        and active_rules <= _REVIEW_FINDINGS
    ):
        return _complete(
            name,
            tasks,
            native,
            governance,
            lifecycle="review",
            action=NextAction(
                kind="review",
                command=f"./trade dev review --slug {name} --scope openspec/changes/{name}",
                reason="The governed design awaits current six-role approval.",
            ),
        )

    if tasks.total == 0 or tasks.completed != tasks.total:
        return _complete(
            name,
            tasks,
            native,
            governance,
            lifecycle="implementation",
            action=NextAction(
                kind="apply",
                command=f"openspec instructions apply --change {name}",
                reason=(
                    "Implementation has no tracked tasks."
                    if tasks.total == 0
                    else f"{tasks.total - tasks.completed} implementation task(s) remain."
                ),
            ),
        )

    approved = (
        report.get("governance_status") == "GOVERNED"
        and report.get("approval_eligible") is True
        and report.get("status") == "PASS"
    )
    historical = (
        not governance.required
        and governance.requirement_source == "historical_exempt"
        and report.get("governance_status") == "NOT_GOVERNED"
    )
    if approved or historical:
        return _complete(
            name,
            tasks,
            native,
            governance,
            lifecycle="archive-ready",
            action=NextAction(
                kind="archive",
                command=f"openspec archive {name}",
                reason="Authoring, validation, implementation, and governance are complete.",
            ),
        )

    error = WorkflowError(
        code="workflow.design_quality.state",
        source="design_quality",
        change=name,
        message="Design report is valid but cannot authorize a reviewed lifecycle state.",
        remediation=f"Run ./trade dev design-check {name} --strict and repair the evidence.",
    )
    return ChangeWorkflow.unavailable(name, error)


def _active_finding_rules(report: dict[str, object]) -> frozenset[str]:
    findings = report.get("findings")
    if not isinstance(findings, list):
        return frozenset()
    return frozenset(
        rule
        for item in findings
        if isinstance(item, dict)
        and item.get("suppressed") is False
        and isinstance((rule := item.get("rule_id")), str)
    )


def _complete(
    name: str,
    tasks: TaskProgress,
    native: NativeEvidence,
    governance: GovernanceEvidence,
    *,
    lifecycle: Lifecycle,
    action: NextAction,
) -> ChangeWorkflow:
    return ChangeWorkflow(
        name=name,
        collection_status="complete",
        lifecycle=lifecycle,
        tasks=tasks,
        native=native,
        governance=governance,
        next_action=action,
    )
