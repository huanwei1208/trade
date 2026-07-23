"""DEPRECATED — Crypto provider contracts have moved to ``trade_py.data.market.crypto.providers``.

This module is a thin backwards-compatibility shim that re-exports everything
from the new canonical location.
"""

from trade_py.data.market.crypto.providers import *  # noqa: F401,F403
from trade_py.data.market.crypto.providers import (
    CRYPTO_PROVIDER_SCHEMA_VERSION,
    CRYPTO_PROVIDER_REQUIRED_COLUMNS,
    CRYPTO_PROVIDER_COLUMNS,
    DEFAULT_CRYPTO_ASSETS,
    DEFAULT_QUOTE_ASSET,
    CryptoProviderError,
    CryptoProviderContractError,
    CryptoProviderResponseError,
    CryptoProviderContract,
    CryptoProviderCapture,
    make_okx_contract,
    make_binance_contract,
    OKX_BTC_CONTRACT,
    BINANCE_BTC_SHADOW_CONTRACT,
    BINANCE_SHADOW_CONTRACT_ALIAS,
    # Deprecated misnomer (shadow is Binance, no third independent source).
    COINGECKO_BTC_SHADOW_CONTRACT,
    OKX_HISTORY_CANDLES_URL,
    BINANCE_KLINES_URL,
    normalize_okx_candles,
    normalize_binance_klines,
    # Deprecated alias (backed by Binance normalizer).
    normalize_coingecko_market_chart,
    okx_canonical_candidate,
    OkxDailyProvider,
    OkxBtcDailyProvider,
    BinanceDailyProvider,
    # Deprecated misnomer (class actually wraps Binance).
    CoinGeckoBtcDailyShadowProvider,
    BtcProviderCapture,
    BtcProviderError,
    BtcProviderContractError,
    BtcProviderCredentialError,
    BtcProviderResponseError,
    BTC_PROVIDER_COLUMNS,
    BTC_PROVIDER_REQUIRED_COLUMNS,
)
