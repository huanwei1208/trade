"""CLI adapters for direct and aggregate design-quality evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from trade_py.devtools.design_quality.errors import DesignQualityError
from trade_py.devtools.design_quality.evaluate import evaluate_change, evaluate_changes
from trade_py.devtools.design_quality.models import Policy
from trade_py.devtools.design_quality.policy import load_policy
from trade_py.devtools.design_quality.render import (
    batch_payload,
    render_report_json,
    render_report_text,
)
from trade_py.devtools.design_quality.snapshot import validate_change_name
from trade_py.devtools.quality.scope import ScopeError, discover_repo_root

_EMPTY_ARTIFACT_DIGEST = f"sha256:{hashlib.sha256().hexdigest()}"


def _effective_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise DesignQualityError(f"Invalid --as-of date: {raw!r}; expected YYYY-MM-DD") from exc


def _error(output_format: str, message: str) -> int:
    code = "design.request.invalid"
    remediation = (
        "Fix the change name, options, repository policy, or governed artifacts and rerun."
    )
    if output_format == "json":
        print(
            json.dumps(
                {
                    "schema_version": "trade.design.error.v1",
                    "status": "ERROR",
                    "exit_code": 2,
                    "code": code,
                    "error": message,
                    "remediation": remediation,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"design-check: ERROR {code}\n  {message}\n  next: {remediation}")
    return 2


def run_design_cli(args: argparse.Namespace) -> int:
    try:
        repo_root = discover_repo_root(Path.cwd())
        report = evaluate_change(
            repo_root,
            args.change,
            strict=args.strict,
            effective_date=_effective_date(args.as_of),
            require_governance=args.strict,
        )
    except (DesignQualityError, OSError, ScopeError, ValueError) as exc:
        return _error(args.format, str(exc))
    print(render_report_json(report) if args.format == "json" else render_report_text(report))
    return report.exit_code


def _batch_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m trade_py.devtools.design_quality.cli")
    parser.add_argument("--change", action="append", default=[])
    parser.add_argument("--require-governance", action="append", default=[])
    parser.add_argument("--missing-required", action="append", default=[])
    parser.add_argument("--immutable-policy-edit", action="append", default=[])
    parser.add_argument("--strict", action="store_true")
    return parser


def _synthetic_report(
    name: str,
    policy: Policy,
    *,
    strict: bool,
    governance_status: str,
    rule_id: str,
    path: str,
    message: str,
    remediation: str,
    metadata: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "trade.design.report.v1",
        "checker_version": "1",
        "policy_version": policy.policy_version,
        "policy_digest": policy.digest,
        "artifact_digest": _EMPTY_ARTIFACT_DIGEST,
        "change": name,
        "strict": strict,
        "effective_date": datetime.now(timezone.utc).date().isoformat(),
        "approval_eligible": False,
        "governance_status": governance_status,
        "status": "FAIL",
        "exit_code": 1,
        "profiles": [],
        "findings": [
            {
                "rule_id": rule_id,
                "severity": "blocker",
                "path": path,
                "message": message,
                "remediation": remediation,
                "suppressed": False,
            }
        ],
        "exceptions": [],
        "artifacts": [],
        "counts": {"blockers": 1, "warnings": 0, "suppressed": 0},
        "metadata": {"total_bytes": 0, **metadata},
    }


def _missing_report(name: str, policy: Policy, *, strict: bool) -> dict[str, object]:
    return _synthetic_report(
        name,
        policy,
        strict=strict,
        governance_status="REQUIRED_MISSING",
        rule_id="core.governance.missing",
        path="design-quality.toml",
        message="The governed change or marker was deleted from changed scope.",
        remediation="Restore governance or use the supported archive workflow.",
        metadata={"missing_from_changed_scope": True},
    )


def _policy_edit_report(path: str, policy: Policy, *, strict: bool) -> dict[str, object]:
    return _synthetic_report(
        f"immutable-policy-{Path(path).stem}",
        policy,
        strict=strict,
        governance_status="POLICY_IMMUTABILITY_VIOLATION",
        rule_id="core.policy.immutable",
        path=path,
        message="An existing immutable design policy version was modified or deleted.",
        remediation="Restore the policy and introduce a newly reviewed version instead.",
        metadata={"immutable_policy_path": path},
    )


def _batch_error(message: str) -> int:
    print(
        json.dumps(
            {
                "schema_version": "trade.design.batch.v1",
                "exit_code": 2,
                "reports": [],
                "errors": [
                    {
                        "code": "design.batch.invalid",
                        "message": message,
                        "remediation": "Fix the invocation or repository policy and rerun.",
                    }
                ],
                "summary": {
                    "changes": 0,
                    "passed": 0,
                    "failed": 0,
                    "not_governed": 0,
                    "errors": 1,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = _batch_parser()
    args = parser.parse_args(argv)
    try:
        repo_root = discover_repo_root(Path.cwd())
        policy = load_policy(repo_root)
        changes = tuple(sorted(set(args.change)))
        required_names = tuple(sorted(set(args.require_governance)))
        missing_names = tuple(sorted(set(args.missing_required) - set(changes)))
        policy_edits = tuple(sorted(set(args.immutable_policy_edit)))
        for name in (*changes, *missing_names, *required_names):
            validate_change_name(name)
        orphaned_required = sorted(set(required_names) - set(changes))
        if orphaned_required:
            raise DesignQualityError(
                "--require-governance must reference a supplied --change: "
                + ", ".join(orphaned_required)
            )
        if any(
            not re.fullmatch(r"design-policy/v[1-9][0-9]*\.toml", path) for path in policy_edits
        ):
            raise DesignQualityError("Invalid immutable policy edit path")
        target_count = len(changes) + len(missing_names) + len(policy_edits)
        if target_count > policy.limits.max_changes_per_batch:
            raise DesignQualityError(
                f"Batch has {target_count} targets; limit is {policy.limits.max_changes_per_batch}"
            )
        reports = (
            evaluate_changes(
                repo_root,
                changes,
                strict=args.strict,
                require_governance=frozenset(required_names),
                policy=policy,
            )
            if changes
            else ()
        )
        if not reports and not missing_names and not policy_edits:
            raise DesignQualityError(
                "At least one --change, --missing-required, or --immutable-policy-edit is required"
            )
    except (DesignQualityError, OSError, ScopeError, ValueError) as exc:
        return _batch_error(str(exc))
    payload = batch_payload(reports)
    synthetic = [
        *(_missing_report(item, policy, strict=args.strict) for item in missing_names),
        *(_policy_edit_report(item, policy, strict=args.strict) for item in policy_edits),
    ]
    payload_reports = payload["reports"]
    if not isinstance(payload_reports, list):
        return _batch_error("Internal batch payload has invalid reports")
    payload_reports.extend(synthetic)
    payload["exit_code"] = max((int(item["exit_code"]) for item in payload_reports), default=0)
    payload["summary"] = {
        "changes": len(payload_reports),
        "passed": sum(item.get("status") == "PASS" for item in payload_reports),
        "failed": sum(int(item.get("exit_code", 0)) != 0 for item in payload_reports),
        "not_governed": sum(
            item.get("governance_status") == "NOT_GOVERNED" for item in payload_reports
        ),
        "errors": 0,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return int(payload["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
