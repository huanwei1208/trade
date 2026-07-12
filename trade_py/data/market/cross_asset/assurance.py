"""DEPRECATED — BTC D0-D4 assurance gates have moved to ``trade_py.data.market.crypto.assurance``.

This module is a thin backwards-compatibility shim that re-exports everything
from the new canonical location.
"""

from trade_py.data.market.crypto.assurance import *  # noqa: F401,F403
from trade_py.data.market.crypto.assurance import (
    CONTRACT_VERSION,
    SCHEMA_VERSION,
    PRIMARY_REQUIRED,
    SHADOW_REQUIRED,
    PRIMARY_CONTRACT,
    SHADOW_CONTRACT,
    BtcAssuranceConfig,
    DataGateResult,
    BtcAssuranceResult,
    summarize_btc_health,
    reconcile_btc,
    compare_revisions,
    assure_btc,
)
