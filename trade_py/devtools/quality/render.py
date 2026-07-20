"""Concise terminal and deterministic JSON rendering."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from trade_py.devtools.quality.executor import resolve_executable
from trade_py.devtools.quality.models import GatePlan, GateReport


def render_plan_text(plan: GatePlan) -> str:
    lines = [
        f"quality {plan.mode.value} plan: {len(plan.eligible_files)} eligible file(s), {len(plan.steps)} step(s)",
        f"base={plan.selection.base_ref} merge_base={plan.selection.base_sha[:12]} head={plan.selection.head_sha[:12]}",
    ]
    for issue in plan.issues:
        lines.append(f"ERROR {issue.code}: {issue.message}")
    for exclusion in plan.exclusions:
        lines.append(f"EXCLUDE {exclusion.path} ({exclusion.reason})")
    root = Path(plan.selection.repo_root)
    for step in plan.steps:
        cwd = (root / step.cwd).resolve()
        tool = resolve_executable(step.argv[0], cwd) or "<missing>"
        mutation = "source-write" if step.mutates_source else "read-only"
        lines.append(
            f"PLAN {step.check_id} [{step.resource_class.value},{mutation},{step.network_policy}] "
            f"cwd={step.cwd} tool={tool} files={len(step.files)} timeout={step.timeout_seconds}s"
        )
        lines.append(f"  {shlex.join(step.argv)}")
        if step.prerequisites:
            lines.append(f"  after={','.join(step.prerequisites)}")
        if step.permitted_outputs:
            lines.append(f"  outputs={','.join(step.permitted_outputs)}")
    if not plan.eligible_files and not plan.issues:
        lines.append("PASS no applicable files")
    return "\n".join(lines)


def render_plan_json(plan: GatePlan) -> str:
    payload = plan.to_dict()
    root = Path(plan.selection.repo_root)
    for step, item in zip(plan.steps, payload["steps"], strict=True):
        item["tool_path"] = resolve_executable(step.argv[0], (root / step.cwd).resolve())
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def render_report_text(report: GateReport) -> str:
    outcome = {0: "PASS", 1: "FAIL", 2: "ERROR"}[report.exit_code]
    lines = [
        f"quality {report.mode.value}: {outcome} ({len(report.eligible_files)} files, {len(report.results)} results, {report.duration_ms}ms)",
        f"base={report.selection.base_ref} merge_base={report.selection.base_sha[:12]} head={report.selection.head_sha[:12]}",
    ]
    for exclusion in report.exclusions:
        lines.append(f"EXCLUDE {exclusion.path} ({exclusion.reason})")
    for result in report.results:
        kind = f"/{result.failure_kind.value}" if result.failure_kind else ""
        lines.append(f"{result.status.value}{kind} {result.check_id} {result.duration_ms}ms")
        if result.diagnostic and result.status.value != "PASS":
            for line in result.diagnostic.splitlines()[:20]:
                lines.append(f"  {line}")
        if result.status.value in {"FAIL", "SKIP"} and result.remediation:
            lines.append(f"  next: {result.remediation}")
    if not report.eligible_files and not report.results:
        lines.append("PASS no applicable files")
    return "\n".join(lines)


def render_report_json(report: GateReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
