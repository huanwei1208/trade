"""DEPRECATED — BTC assurance store has moved to ``trade_py.data.market.crypto.store``.

This module is a thin backwards-compatibility shim. The new store writes to
``data/market/crypto/`` instead of ``data/market/cross_asset/``. A compatibility
property ``cross_asset_root`` is provided for code that still reads the old
attribute name.
"""

from trade_py.data.market.crypto.store import (  # noqa: F401
    file_sha256,
    btc_operational_freshness,
    btc_live_pilot_checklist,
    inspect_btc_status,
)

# Re-export BtcRunStore with a backwards-compatible cross_asset_root property alias
from trade_py.data.market.crypto.store import BtcRunStore as _CryptoBtcRunStore


class BtcRunStore(_CryptoBtcRunStore):
    """Backwards-compatible BtcRunStore shim.

    Writes to ``data/market/crypto/`` (new canonical location) but exposes
    ``cross_asset_root`` as an alias for ``crypto_root`` so existing code that
    reads the attribute continues to work during the migration.
    """

    @property
    def cross_asset_root(self):
        """Deprecated alias for ``crypto_root``."""
        return self.crypto_root


__all__ = [
    "BtcRunStore",
    "btc_operational_freshness",
    "btc_live_pilot_checklist",
    "inspect_btc_status",
    "file_sha256",
]
