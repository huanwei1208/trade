"""Strict design-quality batch adaptation for workflow status."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import NoReturn

from trade_py.devtools.design_quality.governance import GovernanceResolution
from trade_py.devtools.design_quality.models import Policy
from trade_py.devtools.design_quality.report_binding import load_report_bindings
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
    bindings = load_report_bindings(
        repo_root,
        names,
        policy,
        require_governance=required,
    )
    expected_governance = {name: bindings[name].governance_status for name in names}
    argv: list[str] = [
        sys.executable,
        "-m",
        "trade_py.devtools.design_quality.cli",
        "--strict",
        "--evaluation-date",
        evaluation_date.isoformat(),
        "--parent-managed-process-group",
    ]
    for name in names:
        argv.extend(("--change", name))
    for name in sorted(required):
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
        expected_changes=names,
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
    errors: dict[str, WorkflowError] = {}
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
