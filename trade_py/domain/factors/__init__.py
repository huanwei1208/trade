"""Factor and signal domain facade."""

from trade_py.analysis.factor_evaluation import factor_metrics, factor_status
from trade_py.analysis.intraday_runtime import compute_intraday_snapshot
from trade_py.signals.cross_asset_signal import CrossAssetSignal
from trade_py.signals.regulatory_tone_monitor import RegulatoryToneMonitor
from trade_py.signals.window_scorer import score_universe, score_watchlist

__all__ = [
    "CrossAssetSignal",
    "RegulatoryToneMonitor",
    "score_watchlist",
    "score_universe",
    "factor_metrics",
    "factor_status",
    "compute_intraday_snapshot",
]
