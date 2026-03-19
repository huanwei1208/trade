"""Factor group builders — modular factor assembly with provenance contracts."""
from __future__ import annotations

from trade_py.factors.groups._base import FactorGroupResult
from trade_py.factors.groups.event_features import (
    build_event_group,
    build_event_group_training,
    EVENT_FEATURE_COLS,
)
from trade_py.factors.groups.sentiment_features import (
    build_sentiment_group,
    SENTIMENT_FEATURE_COLS,
)
from trade_py.factors.groups.technical_features import (
    build_technical_group,
    TECHNICAL_FEATURE_COLS,
)
from trade_py.factors.groups.instrument_features import (
    build_instrument_group,
    build_instrument_group_training,
    INSTRUMENT_FEATURE_COLS,
)

__all__ = [
    "FactorGroupResult",
    "build_event_group",
    "build_event_group_training",
    "build_sentiment_group",
    "build_technical_group",
    "build_instrument_group",
    "build_instrument_group_training",
    "EVENT_FEATURE_COLS",
    "SENTIMENT_FEATURE_COLS",
    "TECHNICAL_FEATURE_COLS",
    "INSTRUMENT_FEATURE_COLS",
]
