"""Deterministic text and JSON rendering for workflow status reports."""

from __future__ import annotations

import json
from dataclasses import dataclass

from trade_py.devtools.openspec_status.errors import WorkflowError
from trade_py.devtools.openspec_status.models import (
    ChangeWorkflow,
    WorkflowReport,
)


@dataclass(frozen=True)
class RenderedWorkflow:
    output: str
    exit_code: int


def render_workflow(
    report: WorkflowReport,
    *,
    output_format: str,
) -> RenderedWorkflow:
    bounded_report, json_output = _bounded_report(report)
    if output_format == "json":
        return RenderedWorkflow(json_output, bounded_report.exit_code)
    if output_format != "text":
        raise ValueError(f"Unsupported workflow output format: {output_format}")
    return RenderedWorkflow(_render_text(bounded_report), bounded_report.exit_code)


def _bounded_report(report: WorkflowReport) -> tuple[WorkflowReport, str]:
    output = _encode_json(report)
    if len(output.encode("utf-8")) <= report.limits.report_output_bytes:
        return report, output

    error = WorkflowError(
        code="workflow.report.too_large",
        source="openspec",
        message="The complete OpenSpec workflow report exceeds its output limit.",
        remediation="Inspect one active change at a time or reduce active OpenSpec work.",
    )
    bounded = WorkflowReport(
        evaluation_date=report.evaluation_date,
        source=report.source,
        changes=(),
        errors=(error,),
        limits=report.limits,
    )
    return bounded, _encode_json(bounded)


def _encode_json(report: WorkflowReport) -> str:
    return (
        json.dumps(
            report.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _render_text(report: WorkflowReport) -> str:
    payload = report.to_dict()
    summary = payload["summary"]
    assert isinstance(summary, dict)
    lines = [
        (
            f"OpenSpec workflow: {report.status} "
            f"({summary['changes']} changes, {summary['unavailable']} unavailable, "
            f"{summary['errors']} errors)"
        ),
        f"Evaluation date: {report.evaluation_date.isoformat()} UTC",
    ]
    if report.source is None:
        lines.append("Source: unavailable")
    else:
        lines.append(
            f"Source: {report.source.git_head[:12]} "
            f"(base {report.source.base_ref} @ {report.source.base_sha[:12]}, "
            f"snapshot {report.source.snapshot_digest[:19]})"
        )

    for change in sorted(report.changes, key=lambda item: item.name):
        lines.extend(("", *_render_change(change)))

    if report.errors:
        lines.extend(("", "Errors:"))
        for error in sorted(
            report.errors,
            key=lambda item: (item.change or "", item.source, item.code, item.message),
        ):
            lines.extend(_render_error(error, indent="  "))
    return "\n".join(lines) + "\n"


def _render_change(change: ChangeWorkflow) -> list[str]:
    lifecycle = change.lifecycle or "unavailable"
    if change.tasks is None:
        tasks = "unavailable"
    else:
        tasks = f"{change.tasks.completed}/{change.tasks.total} ({change.tasks.status})"

    if change.native is None:
        validation = "unavailable"
        artifacts = "unavailable"
    else:
        validation = "pass" if change.native.validation.valid else "fail"
        validation += (
            f" ({len(change.native.validation.issues)} issues, "
            f"{change.native.validation.omitted_count} omitted)"
        )
        done = sum(item.status == "done" for item in change.native.artifacts)
        artifacts = f"{done}/{len(change.native.artifacts)} done"

    if change.governance is None:
        governance = "unavailable"
    else:
        design = change.governance.report
        governance = (
            f"{design.get('governance_status', 'unknown')} "
            f"(status={design.get('status', 'unknown')}, "
            f"approval={design.get('approval_eligible', 'unknown')}, "
            f"source={change.governance.requirement_source})"
        )

    lines = [
        f"{change.name}: {lifecycle} [{change.collection_status}]",
        f"  tasks: {tasks}",
        f"  artifacts: {artifacts}",
        f"  validation: {validation}",
        f"  governance: {governance}",
    ]
    if change.next_action.command is None:
        lines.append(f"  next: unavailable ({change.next_action.reason})")
    else:
        lines.append(f"  next: {change.next_action.command}")
        lines.append(f"    reason: {change.next_action.reason}")
    for error in change.errors:
        lines.extend(_render_error(error, indent="  "))
    return lines


def _render_error(error: WorkflowError, *, indent: str) -> list[str]:
    target = f" [{error.change}]" if error.change else ""
    return [
        f"{indent}! {error.code}{target}: {error.message}",
        f"{indent}  recovery: {error.remediation}",
    ]
