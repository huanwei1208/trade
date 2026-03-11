"""Deprecated alias. Use TradeDB from trade_py.db.trade_db instead."""
from __future__ import annotations

from trade_py.db.trade_db import (
    TradeDB,
    _INDUSTRY_NAMES,
    _INDUSTRY_UNKNOWN,
    _MARKET_SH, _MARKET_SZ, _MARKET_BJ,
    _BOARD_MAIN, _BOARD_ST, _BOARD_STAR, _BOARD_CHINEXT, _BOARD_BSE,
    _STATUS_NORMAL, _STATUS_SUSPENDED, _STATUS_ST, _STATUS_STAR_ST,
    _infer_market, _market_name, _infer_board, _infer_status,
)


class InstrumentsDB(TradeDB):
    """Deprecated alias for TradeDB. All methods available on TradeDB directly."""
