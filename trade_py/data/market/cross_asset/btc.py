from trade_py.data.market.cross_asset.providers import *  # noqa: F401,F403
from trade_py.data.market.cross_asset.providers import (
    CRYPTO_PROVIDER_SCHEMA_VERSION as BTC_PROVIDER_SCHEMA_VERSION,
    CRYPTO_PROVIDER_REQUIRED_COLUMNS as BTC_PROVIDER_REQUIRED_COLUMNS,
    CRYPTO_PROVIDER_COLUMNS as BTC_PROVIDER_COLUMNS,
    BINANCE_KLINES_URL,
    CryptoProviderError as BtcProviderContractError,
    CryptoProviderContractError,
    CryptoProviderContract as BtcProviderContract,
    CryptoProviderCapture as BtcProviderCapture,
    OkxDailyProvider,
    BinanceDailyProvider,
    OKX_BTC_CONTRACT,
    BINANCE_BTC_SHADOW_CONTRACT as COINGECKO_BTC_SHADOW_CONTRACT,
    COINGECKO_BTC_SHADOW_CONTRACT,
    OKX_HISTORY_CANDLES_URL,
    normalize_okx_candles,
    okx_canonical_candidate,
)


class OkxBtcDailyProvider(OkxDailyProvider):
    """Backwards-compatible OKX BTC provider (http_get as first positional arg)."""
    def __init__(self, http_get=None, **kwargs):
        super().__init__(base_asset="BTC", quote_asset="USDT", http_get=http_get, **kwargs)


class CoinGeckoBtcDailyShadowProvider(BinanceDailyProvider):
    """Backwards-compatible CoinGecko shadow provider (now uses Binance, http_get as first arg)."""
    def __init__(self, http_get=None, **kwargs):
        super().__init__(base_asset="BTC", quote_asset="USDT", http_get=http_get, **kwargs)

# Backwards compatibility shims
COINGECKO_MARKET_CHART_URL = "https://api.binance.com/api/v3/klines"  # legacy alias, now Binance
BtcProviderCredentialError = CryptoProviderContractError


def normalize_coingecko_market_chart(*args, **kwargs):
    """Deprecated: use normalize_binance_klines instead. Kept for backward compat."""
    from trade_py.data.market.cross_asset.providers import normalize_binance_klines
    return normalize_binance_klines(*args, **kwargs)
