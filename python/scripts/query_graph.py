#!/usr/bin/env python3
"""Query the A-share sector knowledge graph for event propagation.

Usage:
    python python/scripts/query_graph.py --event semiconductor_policy
    python python/scripts/query_graph.py --event new_energy_policy --hop 3
    python python/scripts/query_graph.py --list-events
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_context import default_data_root
from trade_py.analysis.knowledge_graph import SectorGraph


def print_propagation(results, event_type: str, max_rows: int = 15):
    print(f"\n{'='*65}")
    print(f"Event: {event_type}")
    print(f"{'='*65}")
    print(f"{'Sector':<18} {'Score':>7} {'Hop':>4} {'Days':>5}  Path")
    print("-" * 65)
    for r in results[:max_rows]:
        score_str = f"{r.score:+.3f}"
        path_short = " -> ".join(p.replace("SW_", "").replace(f"event:{event_type}", "EVT")
                                  for p in r.path)
        if len(path_short) > 35:
            path_short = path_short[:32] + "..."
        print(f"  {r.sector_name:<16} {score_str:>7} {r.hop:>4} {r.typical_days:>5}  {path_short}")
    if len(results) > max_rows:
        print(f"  ... ({len(results) - max_rows} more sectors)")
    print()
    pos = [r for r in results if r.score > 0]
    neg = [r for r in results if r.score < 0]
    print(f"  Positive impact: {len(pos)} sectors  |  Negative impact: {len(neg)} sectors")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", help="Event type to propagate")
    parser.add_argument("--hop", type=int, default=2)
    parser.add_argument(
        "--graph",
        default=str(default_data_root() / "knowledge_graph" / "sector_graph.json"),
    )
    parser.add_argument("--list-events", action="store_true")
    parser.add_argument("--build", action="store_true", help="Build and save graph first")
    args = parser.parse_args()

    graph_path = Path(args.graph)

    if args.build or not graph_path.exists():
        print(f"Building graph -> {graph_path}")
        graph = SectorGraph()
        graph.save(graph_path)
    else:
        graph = SectorGraph.load(graph_path)

    if args.list_events:
        print("\nAvailable event types:")
        for evt in sorted(graph.available_events()):
            print(f"  {evt}")
        return

    if not args.event:
        parser.print_help()
        return

    results = graph.propagate_event(args.event, max_hop=args.hop)
    print_propagation(results, args.event)


if __name__ == "__main__":
    main()
