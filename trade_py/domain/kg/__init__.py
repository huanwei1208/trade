"""Knowledge-graph domain facade."""

from trade_py.intelligence.graph.builder import build_sector_graph
from trade_py.intelligence.graph.learned import LearnKGSummary, learn_kg_candidates

__all__ = [
    "build_sector_graph",
    "LearnKGSummary",
    "learn_kg_candidates",
]

