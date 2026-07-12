from trade_py.data.market.crypto.providers import *  # noqa: F401,F403
from trade_py.data.market.crypto.providers import (
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
    BINANCE_BTC_SHADOW_CONTRACT,
    BINANCE_SHADOW_CONTRACT_ALIAS,
    # Deprecated misnomer retained for backwards compatibility. Shadow is
    # Binance; there is NO third independent source for D3.
    COINGECKO_BTC_SHADOW_CONTRACT,
    OKX_HISTORY_CANDLES_URL,
    normalize_okx_candles,
    normalize_binance_klines,
    okx_canonical_candidate,
)


class OkxBtcDailyProvider(OkxDailyProvider):
    """Backwards-compatible OKX BTC provider (http_get as first positional arg)."""
    def __init__(self, http_get=None, **kwargs):
        super().__init__(base_asset="BTC", quote_asset="USDT", http_get=http_get, **kwargs)


class BinanceBtcDailyShadowProvider(BinanceDailyProvider):
    """Binance-backed BTC shadow provider (http_get as first positional arg).

    NOTE: This is the SAME source as BINANCE_BTC_SHADOW_CONTRACT. There is
    NO independent third source in D3 — reconciliation is two-source only
    (OKX primary vs Binance shadow).
    """
    def __init__(self, http_get=None, **kwargs):
        super().__init__(base_asset="BTC", quote_asset="USDT", http_get=http_get, **kwargs)


# Deprecated class name: the shadow provider is Binance, NOT CoinGecko. Kept
# only so old call sites keep importing; new code should use
# BinanceBtcDailyShadowProvider.
class CoinGeckoBtcDailyShadowProvider(BinanceBtcDailyShadowProvider):
    """Deprecated alias for BinanceBtcDailyShadowProvider. Shadow is Binance."""
    pass


# Legacy shim constants: historically pointed at a CoinGecko endpoint. They
# now point at Binance; the misnomer is preserved only for import
# compatibility. D3 is two-source (OKX vs Binance), no independent third
# source is wired.
COINGECKO_MARKET_CHART_URL = BINANCE_KLINES_URL  # legacy alias, now Binance
BINANCE_SHADOW_MARKET_CHART_URL = BINANCE_KLINES_URL
BtcProviderCredentialError = CryptoProviderContractError


def normalize_coingecko_market_chart(*args, **kwargs):
    """Deprecated alias: use normalize_binance_klines instead.

    The historical "coingecko" shadow normalizer is actually the Binance
    normalizer. Kept for backward compatibility only.
    """
    from trade_py.data.market.crypto.providers import normalize_binance_klines
    return normalize_binance_klines(*args, **kwargs)


# Canonical-name alias
normalize_binance_shadow_klines = normalize_binance_klines
