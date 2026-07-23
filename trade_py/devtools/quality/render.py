"""Concise terminal and deterministic JSON rendering."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from trade_py.devtools.quality.executor import resolve_executable
from trade_py.devtools.quality.models import GatePlan, GateReport


def _design_detail_lines(details: dict[str, object]) -> list[str]:
    lines: list[str] = []
    reports = details.get("reports")
    if isinstance(reports, list):
        for item in reports[:100]:
            if not isinstance(item, dict):
                continue
            lines.append(
                "  design "
                f"{item.get('change', '<unknown>')}: {item.get('status', '<unknown>')} "
                f"governance={item.get('governance_status', '<unknown>')} "
                f"approval={item.get('approval_eligible', False)} "
                f"strict={item.get('strict', '<unknown>')} "
                f"effective_date={item.get('effective_date', '<unknown>')}"
            )
            lines.append(
                "    "
                f"policy={item.get('policy_version', '<unknown>')} "
                f"policy_digest={item.get('policy_digest', '')} "
                f"artifact_digest={item.get('artifact_digest', '')}"
            )
            profiles = item.get("profiles")
            if isinstance(profiles, list):
                lines.append(f"    profiles={','.join(str(value) for value in profiles)}")
            counts = item.get("counts")
            if isinstance(counts, dict):
                lines.append(
                    "    counts "
                    f"blockers={counts.get('blockers', 0)} "
                    f"warnings={counts.get('warnings', 0)} "
                    f"suppressed={counts.get('suppressed', 0)} "
                    f"exit_code={item.get('exit_code', '<unknown>')}"
                )
            metadata = item.get("metadata")
            if isinstance(metadata, dict) and (
                metadata.get("reviewed_at") or metadata.get("reviewed_commit")
            ):
                lines.append(
                    "    "
                    f"reviewed_at={metadata.get('reviewed_at', '')} "
                    f"reviewed_commit={metadata.get('reviewed_commit', '')} "
                    f"reviewed_commit_status={metadata.get('reviewed_commit_status', '')}"
                )
            findings = item.get("findings")
            if isinstance(findings, list):
                for finding in findings[:20]:
                    if not isinstance(finding, dict):
                        continue
                    lines.append(
                        "    "
                        f"{finding.get('severity', 'unknown').upper()} "
                        f"{finding.get('rule_id', '<unknown>')} "
                        f"{finding.get('path', '<unknown>')}: {finding.get('message', '')}"
                    )
                    if finding.get("remediation"):
                        lines.append(f"      next: {finding['remediation']}")
                if len(findings) > 20:
                    lines.append(
                        f"    ... {len(findings) - 20} finding(s) omitted; "
                        "use --format json for full details"
                    )
            exceptions = item.get("exceptions")
            if isinstance(exceptions, list):
                for exception in exceptions[:20]:
                    if isinstance(exception, dict):
                        lines.append(
                            "    exception "
                            f"{exception.get('state', '<unknown>')} "
                            f"{exception.get('rule_id', '<unknown>')} "
                            f"owner={exception.get('owner', '<unknown>')} "
                            f"expires={exception.get('expires', '<unknown>')}"
                        )
                if len(exceptions) > 20:
                    lines.append(
                        f"    ... {len(exceptions) - 20} exception(s) omitted; "
                        "use --format json for full details"
                    )
        if len(reports) > 100:
            lines.append(
                f"  ... {len(reports) - 100} design report(s) omitted; "
                "use --format json for full details"
            )
    errors = details.get("errors")
    if isinstance(errors, list):
        for error in errors[:20]:
            if isinstance(error, dict):
                lines.append(
                    f"  design error {error.get('code', '<unknown>')}: {error.get('message', '')}"
                )
                if error.get("remediation"):
                    lines.append(f"    next: {error['remediation']}")
        if len(errors) > 20:
            lines.append(
                f"  ... {len(errors) - 20} design error(s) omitted; "
                "use --format json for full details"
            )
    summary = details.get("summary")
    if isinstance(summary, dict):
        lines.append(
            "  design summary "
            f"changes={summary.get('changes', 0)} passed={summary.get('passed', 0)} "
            f"failed={summary.get('failed', 0)} "
            f"not_governed={summary.get('not_governed', 0)} errors={summary.get('errors', 0)}"
        )
    return lines


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
        if result.check_id == "design.strict" and result.details:
            lines.extend(_design_detail_lines(result.details))
        if result.status.value in {"FAIL", "SKIP"} and result.remediation:
            lines.append(f"  next: {result.remediation}")
    if not report.eligible_files and not report.results:
        lines.append("PASS no applicable files")
    return "\n".join(lines)


def render_report_json(report: GateReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
