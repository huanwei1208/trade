"""Deprecated alias. Use TradeDB from trade_py.db.trade_db instead."""
from __future__ import annotations

from trade_py.db.trade_db import TradeDB


class SettingsDB(TradeDB):
    """Deprecated alias for TradeDB. All methods available on TradeDB directly."""
