"""DEPRECATED — BTC market data service has moved to ``trade_py.data.market.crypto.service``.

This module is a thin backwards-compatibility shim that re-exports everything
from the new canonical location.
"""

from trade_py.data.market.crypto.service import *  # noqa: F401,F403
from trade_py.data.market.crypto.service import (  # noqa: E402
    BtcMarketDataService,
)

__all__ = ["BtcMarketDataService"]
