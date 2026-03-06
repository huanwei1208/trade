from __future__ import annotations

from pathlib import Path

from trade_py.analysis.knowledge_graph import SectorGraph
from trade_py.config import default_data_root


def build_sector_graph(output: str | None = None) -> dict:
    target = Path(output) if output else (default_data_root() / "knowledge_graph" / "sector_graph.json")
    graph = SectorGraph()
    graph.save(str(target))
    data = graph.to_dict()
    return {
        "output": str(target),
        "nodes": len(data.get("nodes", [])),
        "edges": len(data.get("edges", [])),
        "event_types": len(data.get("event_mappings", {})),
        "event_mappings": data.get("event_mappings", {}),
    }
