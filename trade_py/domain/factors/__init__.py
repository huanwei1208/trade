"""Factor and signal domain facade."""

from trade_py.signals.cross_asset_signal import CrossAssetSignal
from trade_py.signals.regulatory_tone_monitor import RegulatoryToneMonitor
from trade_py.signals.window_scorer import score_universe, score_watchlist

__all__ = [
    "CrossAssetSignal",
    "RegulatoryToneMonitor",
    "score_watchlist",
    "score_universe",
]

