"""CLI adapter for the quality planner and runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trade_py.devtools.quality.models import GateMode
from trade_py.devtools.quality.render import (
    render_plan_json,
    render_plan_text,
    render_report_json,
    render_report_text,
)
from trade_py.devtools.quality.runner import make_plan, run_gate
from trade_py.devtools.quality.scope import ScopeError, discover_repo_root


def _error(mode: str, output_format: str, message: str) -> int:
    if output_format == "json":
        print(
            json.dumps(
                {
                    "schema_version": "trade.quality.error.v1",
                    "mode": mode,
                    "exit_code": 2,
                    "error": message,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"quality {mode}: ERROR\n  {message}")
    return 2


def run_quality_cli(args: argparse.Namespace) -> int:
    mode = GateMode(args.cmd)
    try:
        repo_root = discover_repo_root(Path.cwd())
        if args.show_plan:
            plan = make_plan(
                repo_root,
                mode=mode,
                base_ref=args.base,
                all_mode=args.all_mode,
                paths=tuple(args.path),
            )
            print(render_plan_json(plan) if args.format == "json" else render_plan_text(plan))
            return 2 if plan.issues else 0
        report = run_gate(
            repo_root,
            mode=mode,
            base_ref=args.base,
            all_mode=args.all_mode,
            paths=tuple(args.path),
        )
    except (OSError, ScopeError, ValueError) as exc:
        return _error(mode.value, args.format, str(exc))
    print(render_report_json(report) if args.format == "json" else render_report_text(report))
    return report.exit_code
