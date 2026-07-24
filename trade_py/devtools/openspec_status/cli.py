"""Public CLI adapter for read-only OpenSpec workflow status."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from trade_py.devtools.openspec_status.errors import ErrorSource, WorkflowError
from trade_py.devtools.openspec_status.models import WorkflowReport
from trade_py.devtools.openspec_status.render import render_workflow
from trade_py.devtools.openspec_status.service import collect_workflow
from trade_py.devtools.quality.scope import ScopeError, discover_repo_root


def run_openspec_cli(args: argparse.Namespace) -> int:
    try:
        repo_root = discover_repo_root(Path.cwd())
        report = collect_workflow(repo_root, requested_change=args.change)
    except KeyboardInterrupt:
        report = _error_report(
            code="workflow.command.interrupted",
            source="request",
            message="OpenSpec workflow collection was interrupted.",
            remediation="Rerun the command when you are ready to continue.",
            change=args.change,
        )
    except (OSError, ScopeError) as exc:
        report = _error_report(
            code="workflow.repository.discovery",
            source="git",
            message=str(exc),
            remediation="Run the command inside a valid trade Git repository.",
            change=args.change,
        )
    rendered = render_workflow(report, output_format=args.format)
    print(rendered.output, end="")
    return rendered.exit_code


def _error_report(
    *,
    code: str,
    source: ErrorSource,
    message: str,
    remediation: str,
    change: str | None,
) -> WorkflowReport:
    return WorkflowReport(
        evaluation_date=datetime.now(timezone.utc).date(),
        source=None,
        changes=(),
        errors=(
            WorkflowError(
                code=code,
                source=source,
                message=message,
                remediation=remediation,
                change=change,
            ),
        ),
    )
