"""CLI adapter for bounded read-only layout diagnostics."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from trade_py.devtools.layout_status.deadline import InvocationDeadline
from trade_py.devtools.layout_status.errors import (
    LayoutStatusError,
    LayoutStatusInvalid,
)
from trade_py.devtools.layout_status.records import ExplicitRecordReader
from trade_py.devtools.layout_status.report import render_status
from trade_py.devtools.layout_status.validation import validate_graph

MANIFEST_ENV = "TRADE_LAYOUT_STATUS_MANIFEST"


def run_layout_status_cli(args: argparse.Namespace) -> int:
    selected = os.environ.get(MANIFEST_ENV)
    if not selected:
        rendered = render_status(
            None,
            error=LayoutStatusError(
                code="layout.status.manifest_unset",
                message=f"{MANIFEST_ENV} must select one explicit immutable manifest.",
            ),
            as_json=args.as_json,
        )
        print(rendered.output, end="")
        return rendered.exit_code

    try:
        deadline = InvocationDeadline()
        with deadline.interrupt_blocking_calls():
            graph = ExplicitRecordReader(Path(selected), deadline=deadline).read()
            status = validate_graph(graph, deadline=deadline)
            rendered = render_status(status, as_json=args.as_json, deadline=deadline)
    except KeyboardInterrupt:
        rendered = render_status(
            None,
            error=LayoutStatusError(
                code="layout.status.interrupted",
                message="Layout status validation was interrupted.",
            ),
            as_json=args.as_json,
        )
    except LayoutStatusInvalid as exc:
        rendered = render_status(None, error=exc.error, as_json=args.as_json)
    print(rendered.output, end="")
    return rendered.exit_code


__all__ = ["MANIFEST_ENV", "run_layout_status_cli"]
