"""Crypto market data module: BTC/ETH/SOL/BNB/XRP OHLC, D0-D4 assurance gates, sentiment.

Storage layout (under data_root/market/crypto/):
    btc.parquet              — canonical BTC daily OHLC (published by assurance service)
    btc_current.json         — current BTC run pointer
    runs/btc/<run_id>/       — immutable run artifacts (primary/shadow/canonical/reconciliation/revisions + raw/)
    audit/publish/, audit/rollback/  — audit event logs
    <asset>.parquet          — simple fetch_crypto() output for non-BTC assets (e.g. eth.parquet)
    fear_greed.parquet       — Crypto Fear & Greed Index history

All crypto data sources are 100% free public exchange/API endpoints:
- OKX public market-data API (primary OHLCV)
- Binance public kline API (shadow OHLCV for cross-validation)
- alternative.me Fear & Greed Index (sentiment)
"""

from trade_py.data.market.crypto.akshare import (
    fetch_btc,
    fetch_crypto,
)
from trade_py.data.market.crypto.providers import (
    CRYPTO_PROVIDER_COLUMNS,
    CRYPTO_PROVIDER_REQUIRED_COLUMNS,
    CRYPTO_PROVIDER_SCHEMA_VERSION,
    DEFAULT_CRYPTO_ASSETS,
    BINANCE_BTC_SHADOW_CONTRACT,
    OKX_BTC_CONTRACT,
    BINANCE_KLINES_URL,
    OKX_HISTORY_CANDLES_URL,
    CryptoProviderCapture,
    CryptoProviderContract,
    CryptoProviderContractError,
    CryptoProviderError,
    CryptoProviderResponseError,
    BinanceDailyProvider,
    OkxDailyProvider,
    normalize_binance_klines,
    normalize_okx_candles,
    okx_canonical_candidate,
    make_binance_contract,
    make_okx_contract,
)
from trade_py.data.market.crypto.btc import (
    OkxBtcDailyProvider,
    CoinGeckoBtcDailyShadowProvider,
    COINGECKO_BTC_SHADOW_CONTRACT,
    COINGECKO_MARKET_CHART_URL,
    BtcProviderCapture,
    BtcProviderContract,
    BtcProviderContractError,
    BtcProviderCredentialError,
    BtcProviderError,
    BtcProviderResponseError,
    BTC_PROVIDER_COLUMNS,
    BTC_PROVIDER_REQUIRED_COLUMNS,
    BTC_PROVIDER_SCHEMA_VERSION,
    normalize_coingecko_market_chart,
)
from trade_py.data.market.crypto.assurance import (
    BtcAssuranceConfig,
    BtcAssuranceResult,
    DataGateResult,
    assure_btc,
    reconcile_btc,
    compare_revisions,
    summarize_btc_health,
)
from trade_py.data.market.crypto.store import (
    BtcRunStore,
    btc_operational_freshness,
    inspect_btc_status,
    btc_live_pilot_checklist,
    file_sha256,
)
from trade_py.data.market.crypto.service import BtcMarketDataService
from trade_py.data.market.crypto.crypto_sentiment import (
    FearGreedRecord,
    CryptoNewsItem,
    fetch_fear_greed,
    fetch_crypto_rss_news,
    fetch_binance_announcements,
    fetch_reddit_crypto,
    fetch_all_crypto_news,
    save_fear_greed_parquet,
    save_crypto_news_parquet,
    FEAR_GREED_URL,
    CRYPTO_RSS_FEEDS,
)

__all__ = [
    # Akshare fetchers
    "fetch_btc",
    "fetch_crypto",
    # Generic provider contracts and adapters
    "CRYPTO_PROVIDER_COLUMNS",
    "CRYPTO_PROVIDER_REQUIRED_COLUMNS",
    "CRYPTO_PROVIDER_SCHEMA_VERSION",
    "DEFAULT_CRYPTO_ASSETS",
    "BINANCE_BTC_SHADOW_CONTRACT",
    "OKX_BTC_CONTRACT",
    "BINANCE_KLINES_URL",
    "OKX_HISTORY_CANDLES_URL",
    "CryptoProviderCapture",
    "CryptoProviderContract",
    "CryptoProviderContractError",
    "CryptoProviderError",
    "CryptoProviderResponseError",
    "BinanceDailyProvider",
    "OkxDailyProvider",
    "normalize_binance_klines",
    "normalize_okx_candles",
    "okx_canonical_candidate",
    "make_binance_contract",
    "make_okx_contract",
    # BTC-specific aliases/classes (backwards compat)
    "BTC_PROVIDER_COLUMNS",
    "BTC_PROVIDER_REQUIRED_COLUMNS",
    "BTC_PROVIDER_SCHEMA_VERSION",
    "OkxBtcDailyProvider",
    "CoinGeckoBtcDailyShadowProvider",
    "COINGECKO_BTC_SHADOW_CONTRACT",
    "COINGECKO_MARKET_CHART_URL",
    "BtcProviderCapture",
    "BtcProviderContract",
    "BtcProviderContractError",
    "BtcProviderCredentialError",
    "BtcProviderError",
    "BtcProviderResponseError",
    "normalize_coingecko_market_chart",
    # Assurance gates (D0-D4)
    "BtcAssuranceConfig",
    "BtcAssuranceResult",
    "DataGateResult",
    "assure_btc",
    "reconcile_btc",
    "compare_revisions",
    "summarize_btc_health",
    # Store / persistence
    "BtcRunStore",
    "btc_operational_freshness",
    "inspect_btc_status",
    "btc_live_pilot_checklist",
    "file_sha256",
    # Service orchestration
    "BtcMarketDataService",
    # Sentiment
    "FearGreedRecord",
    "CryptoNewsItem",
    "fetch_fear_greed",
    "fetch_crypto_rss_news",
    "fetch_binance_announcements",
    "fetch_reddit_crypto",
    "fetch_all_crypto_news",
    "save_fear_greed_parquet",
    "save_crypto_news_parquet",
    "FEAR_GREED_URL",
    "CRYPTO_RSS_FEEDS",
]
