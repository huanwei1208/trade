"""DEPRECATED — BTC provider aliases have moved to ``trade_py.data.market.crypto.btc``.

This module is a thin backwards-compatibility shim that re-exports everything
from the new canonical location.
"""

from trade_py.data.market.crypto.btc import *  # noqa: F401,F403
from trade_py.data.market.crypto.btc import (
    BTC_PROVIDER_SCHEMA_VERSION,
    BTC_PROVIDER_REQUIRED_COLUMNS,
    BTC_PROVIDER_COLUMNS,
    BINANCE_KLINES_URL,
    BINANCE_SHADOW_MARKET_CHART_URL,
    BtcProviderContractError,
    CryptoProviderContractError,
    BtcProviderContract,
    BtcProviderCapture,
    OkxDailyProvider,
    BinanceDailyProvider,
    BinanceBtcDailyShadowProvider,
    OKX_BTC_CONTRACT,
    BINANCE_BTC_SHADOW_CONTRACT,
    BINANCE_SHADOW_CONTRACT_ALIAS,
    # Deprecated misnomer (shadow is Binance, no third independent source).
    COINGECKO_BTC_SHADOW_CONTRACT,
    COINGECKO_MARKET_CHART_URL,
    BtcProviderCredentialError,
    OkxBtcDailyProvider,
    # Deprecated misnomer — class actually wraps Binance.
    CoinGeckoBtcDailyShadowProvider,
    OKX_HISTORY_CANDLES_URL,
    normalize_okx_candles,
    normalize_binance_klines,
    normalize_binance_shadow_klines,
    okx_canonical_candidate,
    # Deprecated alias.
    normalize_coingecko_market_chart,
)
