"""Knowledge-graph domain facade."""

from trade_py.analysis.knowledge_graph import SW, SectorGraph
from trade_py.intelligence.graph.builder import build_sector_graph
from trade_py.intelligence.graph.learned import LearnKGSummary, learn_kg_candidates

__all__ = [
    "SW",
    "SectorGraph",
    "build_sector_graph",
    "LearnKGSummary",
    "learn_kg_candidates",
]
