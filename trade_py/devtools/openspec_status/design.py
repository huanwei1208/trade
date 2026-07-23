"""Strict design-quality batch adaptation for workflow status."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import NoReturn

from trade_py.devtools.design_quality.errors import DesignQualityError
from trade_py.devtools.design_quality.governance import GovernanceResolution
from trade_py.devtools.design_quality.models import Policy
from trade_py.devtools.design_quality.report_binding import (
    ReportBinding,
    load_report_bindings_isolated,
)
from trade_py.devtools.openspec_status.errors import (
    WorkflowCollectionError,
    WorkflowError,
)
from trade_py.devtools.openspec_status.executor import BoundedProcessExecutor
from trade_py.devtools.openspec_status.models import GovernanceEvidence, WorkflowLimits
from trade_py.devtools.quality.executor import validate_design_batch_payload


@dataclass(frozen=True)
class DesignCollection:
    evidence: dict[str, GovernanceEvidence]
    errors: dict[str, WorkflowError]


def collect_design_evidence(
    repo_root: Path,
    names: tuple[str, ...],
    governance: GovernanceResolution,
    *,
    evaluation_date: date,
    executor: BoundedProcessExecutor,
    deadline: float,
    policy: Policy,
    limits: WorkflowLimits,
) -> DesignCollection:
    if not names:
        return DesignCollection(evidence={}, errors={})
    requirements = {item.change: item for item in governance.requirements}
    if set(requirements) != set(names):
        _raise("Governance provenance does not match the selected active changes.")
    required = frozenset(item.change for item in governance.requirements if item.required)
    bindings, binding_errors = _collect_report_bindings(
        repo_root,
        names,
        policy,
        required=required,
        deadline=deadline,
    )
    healthy_names = tuple(name for name in names if name in bindings)
    if not healthy_names:
        return DesignCollection(evidence={}, errors=binding_errors)
    healthy_required = required.intersection(healthy_names)
    expected_governance = {name: bindings[name].governance_status for name in healthy_names}
    argv: list[str] = [
        sys.executable,
        "-m",
        "trade_py.devtools.design_quality.cli",
        "--strict",
        "--evaluation-date",
        evaluation_date.isoformat(),
        "--parent-managed-process-group",
    ]
    for name in healthy_names:
        argv.extend(("--change", name))
    for name in sorted(healthy_required):
        argv.extend(("--require-governance", name))
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _raise("Command-wide deadline expired before design-quality collection.")
    result = executor.run(
        tuple(argv),
        cwd=repo_root,
        deadline=deadline,
        timeout_seconds=remaining,
        output_limit_bytes=limits.report_output_bytes,
        source="design_quality",
        allowed_returncodes=frozenset({0, 1}),
    )
    try:
        payload = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _raise("Design-quality batch did not emit valid JSON.")
        raise AssertionError("unreachable") from exc
    if not isinstance(payload, dict):
        _raise("Design-quality batch did not emit a JSON object.")
    validation = validate_design_batch_payload(
        payload,
        result.returncode,
        policy=policy,
        expected_changes=healthy_names,
        expected_governance=expected_governance,
        bindings=bindings,
        evaluation_date=evaluation_date,
    )
    if validation.envelope_error:
        _raise(validation.envelope_error)
    reports = payload.get("reports")
    if not isinstance(reports, list):
        _raise("Design-quality batch omitted its report list.")
    evidence: dict[str, GovernanceEvidence] = {}
    errors = dict(binding_errors)
    for raw in reports:
        if not isinstance(raw, dict) or not isinstance(raw.get("change"), str):
            _raise("Design-quality batch contains a malformed report.")
        name = raw["change"]
        requirement = requirements.get(name)
        if requirement is None:
            _raise("Design-quality batch contains duplicate or unexpected reports.")
        report_error = validation.report_errors.get(name)
        if report_error:
            errors.setdefault(name, _report_error(name, report_error))
            continue
        if name in evidence:
            _raise("Design-quality batch contains duplicate or unexpected reports.")
        evidence[name] = GovernanceEvidence(
            required=requirement.required,
            requirement_source=requirement.source.value,
            report=raw,
        )
    for name, report_error in validation.report_errors.items():
        errors.setdefault(name, _report_error(name, report_error))
    if set(evidence) | set(errors) != set(names):
        _raise("Design-quality batch did not return every selected active change.")
    return DesignCollection(evidence=evidence, errors=errors)


def _collect_report_bindings(
    repo_root: Path,
    names: tuple[str, ...],
    policy: Policy,
    *,
    required: frozenset[str],
    deadline: float,
) -> tuple[dict[str, ReportBinding], dict[str, WorkflowError]]:
    def check_deadline() -> None:
        if time.monotonic() >= deadline:
            raise WorkflowCollectionError(
                WorkflowError(
                    code="workflow.process.timeout",
                    source="design_quality",
                    message="Command-wide deadline expired during design binding collection.",
                    remediation=(
                        "Reduce active OpenSpec work or repair slow design artifacts, then rerun."
                    ),
                )
            )

    check_deadline()
    try:
        batch = load_report_bindings_isolated(
            repo_root,
            names,
            policy,
            require_governance=required,
            checkpoint=check_deadline,
        )
    except DesignQualityError as exc:
        _raise(str(exc))
    check_deadline()
    errors = {
        name: WorkflowError(
            code="workflow.snapshot.changed",
            source="snapshot",
            change=name,
            message=str(error),
            remediation=(
                f"Stop concurrent edits, repair the OpenSpec artifacts for {name}, and rerun."
            ),
        )
        for name, error in batch.errors.items()
    }
    return batch.bindings, errors


def _report_error(name: str, message: str) -> WorkflowError:
    return WorkflowError(
        code="workflow.design_quality.invalid",
        source="design_quality",
        change=name,
        message=message,
        remediation=(
            f"Run ./trade dev design-check {name} --strict, repair the "
            "structured evidence, and rerun."
        ),
    )


def _raise(message: str) -> NoReturn:
    raise WorkflowCollectionError(
        WorkflowError(
            code="workflow.design_quality.invalid",
            source="design_quality",
            message=message,
            remediation=(
                "Run ./trade dev design-check for the affected change, repair the "
                "structured evidence, and rerun."
            ),
        )
    )
