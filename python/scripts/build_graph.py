#!/usr/bin/env python3
"""Build and save the A-share sector knowledge graph to JSON.

Usage:
    python python/scripts/build_graph.py
    python python/scripts/build_graph.py --output data/knowledge_graph/sector_graph.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_context import default_data_root
from trade_py.analysis.knowledge_graph import SectorGraph, SW, SW_NAMES_ZH


def main():
    parser = argparse.ArgumentParser(description="Build sector knowledge graph")
    parser.add_argument(
        "--output",
        default=str(default_data_root() / "knowledge_graph" / "sector_graph.json"),
    )
    args = parser.parse_args()

    graph = SectorGraph()
    graph.save(args.output)
    d = graph.to_dict()

    print(f"Sector graph saved to: {args.output}")
    print(f"  Nodes:          {len(d['nodes'])}")
    print(f"  Edges:          {len(d['edges'])}")
    print(f"  Event types:    {len(d['event_mappings'])}")
    print()
    print("Event types available:")
    for evt in sorted(d['event_mappings'].keys()):
        primaries = d['event_mappings'][evt]
        top = sorted(primaries, key=lambda x: abs(x['score']), reverse=True)[:3]
        top_str = ", ".join(f"{x['sector'].replace('SW_','')}({x['score']:+.1f})" for x in top)
        print(f"  {evt:35s} -> {top_str}")


if __name__ == "__main__":
    main()
