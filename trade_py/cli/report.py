from __future__ import annotations

import argparse
from pathlib import Path

from trade_py.config import default_data_root
from trade_py.intelligence.graph.builder import build_sector_graph
from trade_py.journal.morning_brief import generate
from trade_py.report import scheduler as report_scheduler


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    parser = argparse.ArgumentParser(prog="trade report")
    sub = parser.add_subparsers(dest="command", required=True)

    p_brief = sub.add_parser("brief", help="Generate morning brief")
    p_brief.add_argument("--data-root", default=str(default_data_root()))
    p_brief.add_argument("--date", default=None, help="Brief date (YYYY-MM-DD)")

    p_schedule = sub.add_parser("schedule", help="Run daily scheduler")
    p_schedule.add_argument("--data-root", default=str(default_data_root()))
    p_schedule.add_argument("--dry-run", action="store_true")

    p_graph = sub.add_parser("graph", help="Build knowledge graph")
    p_graph.add_argument("--output", default=None)

    args = parser.parse_args(argv)
    if args.command == "brief":
        path = generate(args.data_root, args.date)
        print(f"\nMorning brief saved to: {path}")
        content = Path(path).read_text(encoding="utf-8")
        print("\nPreview:")
        print("-" * 60)
        print(content[:1000])
        if len(content) > 1000:
            print(f"\n... ({len(content) - 1000} more characters)")
        return 0
    if args.command == "schedule":
        schedule_argv: list[str] = ["--data-root", args.data_root]
        if args.dry_run:
            schedule_argv.append("--dry-run")
        return report_scheduler.main(schedule_argv)
    if args.command == "graph":
        summary = build_sector_graph(args.output)
        print(f"Sector graph saved to: {summary['output']}")
        print(f"  Nodes:       {summary['nodes']}")
        print(f"  Edges:       {summary['edges']}")
        print(f"  Event types: {summary['event_types']}")
        return 0
    return 1
