"""Deterministic terminal and JSON rendering for design-quality reports."""

from __future__ import annotations

import json

from trade_py.devtools.design_quality.models import DesignReport


def render_report_text(report: DesignReport) -> str:
    payload = report.to_dict()
    counts = payload["counts"]
    lines = [
        f"design-check {report.change}: {report.status} "
        f"({len(report.findings)} findings, strict={str(report.strict).lower()})",
        f"policy={report.policy_version} policy_digest={report.policy_digest}",
        f"artifact_digest={report.artifact_digest} effective_date={report.effective_date.isoformat()}",
        f"governance={report.governance_status} approval_eligible={str(report.approval_eligible).lower()}",
    ]
    if report.profiles:
        lines.append(f"profiles={','.join(report.profiles)}")
    if report.metadata.get("reviewed_at") or report.metadata.get("reviewed_commit"):
        lines.append(
            f"reviewed_at={report.metadata.get('reviewed_at', '')} "
            f"reviewed_commit={report.metadata.get('reviewed_commit', '')} "
            f"reviewed_commit_status={report.metadata.get('reviewed_commit_status', '')}"
        )
    for finding in report.findings:
        state = "SUPPRESSED" if finding.suppressed else finding.severity.value.upper()
        lines.append(f"{state} {finding.rule_id} {finding.path}: {finding.message}")
        lines.append(f"  next: {finding.remediation}")
    for exception in report.exceptions:
        lines.append(
            f"EXCEPTION {exception.state} {exception.rule_id} "
            f"owner={exception.owner} expires={exception.expires.isoformat()}"
        )
    if not report.findings and report.governance_status == "GOVERNED":
        lines.append(
            "PASS no design findings" if report.strict else "DIAGNOSTIC no design findings"
        )
    if isinstance(counts, dict):
        lines.append(
            "counts "
            f"blockers={counts.get('blockers', 0)} "
            f"warnings={counts.get('warnings', 0)} "
            f"suppressed={counts.get('suppressed', 0)} exit_code={report.exit_code}"
        )
    return "\n".join(lines)


def render_report_json(report: DesignReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def batch_payload(reports: tuple[DesignReport, ...]) -> dict[str, object]:
    return {
        "schema_version": "trade.design.batch.v1",
        "exit_code": max((item.exit_code for item in reports), default=0),
        "reports": [item.to_dict() for item in reports],
        "summary": {
            "changes": len(reports),
            "passed": sum(item.status == "PASS" for item in reports),
            "failed": sum(item.exit_code != 0 for item in reports),
            "not_governed": sum(item.governance_status == "NOT_GOVERNED" for item in reports),
            "errors": 0,
        },
    }


def render_batch_json(reports: tuple[DesignReport, ...]) -> str:
    return json.dumps(batch_payload(reports), ensure_ascii=False, indent=2, sort_keys=True)
