"""GDELT channel loading helpers."""

from trade_py.data.news.gdelt.source import _Channel as Channel  # backward-compatible alias
from trade_py.data.news.gdelt.source import _load_channels as load_channels

__all__ = ["Channel", "load_channels"]
