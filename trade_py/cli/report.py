from __future__ import annotations

import argparse
from pathlib import Path

from trade_py.config import default_data_root
from trade_py.intelligence.graph.builder import build_sector_graph
from trade_py.report.morning_brief import generate


def make_parser() -> argparse.ArgumentParser:
    from trade_py.cli import epilog_from_subparsers

    parser = argparse.ArgumentParser(
        prog="trade report",
        description="报告生成 — 晨报/知识图谱",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_brief = sub.add_parser(
        "brief",
        description="生成晨报",
        epilog=(
            "trade report brief\n"
            "trade report brief --date 2026-03-05"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_brief.add_argument("--data-root", default=str(default_data_root()))
    p_brief.add_argument("--date", default=None, help="Brief date (YYYY-MM-DD)")

    p_graph = sub.add_parser(
        "graph",
        description="构建行业知识图谱",
        epilog=(
            "trade report graph\n"
            "trade report graph --output /tmp/graph.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_graph.add_argument("--output", default=None)

    parser.epilog = epilog_from_subparsers(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    args = make_parser().parse_args(argv)

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
    if args.command == "graph":
        summary = build_sector_graph(args.output)
        print(f"Sector graph saved to: {summary['output']}")
        print(f"  Nodes:       {summary['nodes']}")
        print(f"  Edges:       {summary['edges']}")
        print(f"  Event types: {summary['event_types']}")
        return 0
    return 1
