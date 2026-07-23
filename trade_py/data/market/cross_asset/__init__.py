"""DEPRECATED — ``trade_py.data.market.cross_asset`` is being split into dedicated asset modules.

- Crypto (BTC/ETH/SOL/BNB/XRP + sentiment) has moved to ``trade_py.data.market.crypto``
- FX (USD/CNH) has moved to ``trade_py.data.market.fx``
- Commodity (gold) has moved to ``trade_py.data.market.commodity``

This package remains as a backwards-compatibility shim that re-exports
everything from the new canonical locations. A DeprecationWarning is emitted
on import to nudge callers toward the new paths.
"""
import warnings

warnings.warn(
    "trade_py.data.market.cross_asset is deprecated; use "
    "trade_py.data.market.crypto, trade_py.data.market.fx, or "
    "trade_py.data.market.commodity instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Crypto symbols (new canonical location)
from trade_py.data.market.crypto.akshare import (
    fetch_btc,
    fetch_crypto,
)
from trade_py.data.market.crypto.providers import (
    CRYPTO_PROVIDER_COLUMNS as BTC_PROVIDER_COLUMNS,
    CRYPTO_PROVIDER_REQUIRED_COLUMNS as BTC_PROVIDER_REQUIRED_COLUMNS,
    DEFAULT_CRYPTO_ASSETS,
    BINANCE_BTC_SHADOW_CONTRACT,
    BINANCE_SHADOW_CONTRACT_ALIAS,
    OKX_BTC_CONTRACT,
    CryptoProviderCapture as BtcProviderCapture,
    CryptoProviderContract as BtcProviderContract,
    CryptoProviderContractError as BtcProviderContractError,
    CryptoProviderError as BtcProviderError,
    CryptoProviderResponseError as BtcProviderResponseError,
    BtcProviderCredentialError,
    BinanceDailyProvider,
    OkxDailyProvider,
    OkxBtcDailyProvider,
    normalize_okx_candles,
    normalize_binance_klines,
    okx_canonical_candidate,
)
# BTC-specific aliases (classes and function aliases) live in btc.py
from trade_py.data.market.crypto.btc import (
    BinanceBtcDailyShadowProvider,
    # Deprecated misnomer (class is backed by Binance, not CoinGecko).
    CoinGeckoBtcDailyShadowProvider,
    normalize_binance_shadow_klines,
    # Deprecated alias (binance normalizer, not coingecko).
    normalize_coingecko_market_chart,
)
from trade_py.data.market.crypto.assurance import (
    BtcAssuranceConfig,
    BtcAssuranceResult,
    DataGateResult,
    assure_btc,
)
from trade_py.data.market.cross_asset.store import (
    BtcRunStore,
    btc_operational_freshness,
    inspect_btc_status,
)
from trade_py.data.market.cross_asset.service import BtcMarketDataService

# Gold and FX re-exports come from the shim akshare.py (which delegates to fx/commodity modules)
from trade_py.data.market.cross_asset.akshare import (  # noqa: E402
    fetch_gold,
    fetch_fx_cnh,
    fetch_all,
)

# Deprecated misnomer constant: shadow is Binance; there is NO third independent
# source in D3 (two-source reconciliation only, OKX vs Binance). Retained for
# backwards compatibility with existing importers.
COINGECKO_BTC_SHADOW_CONTRACT = BINANCE_BTC_SHADOW_CONTRACT

__all__ = [
    "BTC_PROVIDER_COLUMNS",
    "BTC_PROVIDER_REQUIRED_COLUMNS",
    "DEFAULT_CRYPTO_ASSETS",
    "BINANCE_BTC_SHADOW_CONTRACT",
    "BINANCE_SHADOW_CONTRACT_ALIAS",
    # Deprecated misnomer (constant is Binance shadow contract, not CoinGecko).
    "COINGECKO_BTC_SHADOW_CONTRACT",
    "OKX_BTC_CONTRACT",
    "BtcProviderCapture",
    "BtcProviderContract",
    "BtcProviderContractError",
    "BtcProviderCredentialError",
    "BtcProviderError",
    "BtcProviderResponseError",
    "BtcAssuranceConfig",
    "BtcAssuranceResult",
    "BtcRunStore",
    "BtcMarketDataService",
    "DataGateResult",
    "BinanceDailyProvider",
    "BinanceBtcDailyShadowProvider",
    # Deprecated misnomer.
    "CoinGeckoBtcDailyShadowProvider",
    "OkxDailyProvider",
    "OkxBtcDailyProvider",
    "fetch_gold",
    "fetch_fx_cnh",
    "fetch_btc",
    "fetch_crypto",
    "fetch_all",
    "normalize_okx_candles",
    "normalize_binance_klines",
    "normalize_binance_shadow_klines",
    # Deprecated alias.
    "normalize_coingecko_market_chart",
    "okx_canonical_candidate",
    "assure_btc",
    "btc_operational_freshness",
    "inspect_btc_status",
]
