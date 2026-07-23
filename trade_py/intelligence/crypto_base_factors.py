"""English-language base sentiment and event extraction for crypto news.

Provides keyword-based sentiment scoring and event type detection for English
crypto/financial news text. Used as the always-on fallback when ML models are
not loaded, and as a fast pre-filter.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ── Crypto-specific sentiment terms ─────────────────────────────────────────

CRYPTO_POSITIVE = (
    "bullish", "rally", "surge", "soar", "breakout", "all-time high", "ath",
    "adoption", "partnership", "integration", "upgrade", "launch", "listing",
    "approved", "approval", "greenlight", "etf approved", "inflows",
    "buy the dip", "accumulate", "support", "bounce", "recovery",
    "record high", "beat", "exceed expectations", "growth", "outperform",
    "halving rally", "institutional", "mainstream",
)

CRYPTO_NEGATIVE = (
    "bearish", "crash", "plunge", "dump", "selloff", "sell-off", "collapse",
    "hack", "exploit", "stolen", "rugpull", "rug pull", "bankrupt", "bankruptcy",
    "rejected", "rejection", "delay", "ban", "crackdown", "lawsuit", "sue",
    "charged", "enforcement", "subpoena", "fraud", "scam", "ponzi",
    "delist", "delisting", "halt withdrawals", "suspend withdrawals",
    "ftx", "terra collapse", "liquidation cascade", "capitulation",
    "outflows", "fear", "panic", "fud", "breach", "vulnerability",
    "rate hike", "hawkish", "tightening",
)

CRYPTO_POSITIVE_MODIFIERS = ("strong", "massive", "huge", "significant", "major", "record")
CRYPTO_NEGATIVE_MODIFIERS = ("severe", "major", "massive", "critical", "emergency")

# ── Crypto event patterns (keyword groups) ──────────────────────────────────

CRYPTO_EVENT_RULES: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("etf_approval", ("etf approved", "spot etf approved", "sec approves", "greenlight etf", "blackrock etf", "fidelity etf"), 2),
    ("etf_rejection", ("etf reject", "etf denied", "etf delayed", "reject etf", "sec rejects", "delay etf"), 1),
    ("fed_rate_hike", ("rate hike", "raise rates", "hike rates", "hawkish fed", "fed hike"), 1),
    ("fed_rate_cut", ("rate cut", "cut rates", "lower rates", "dovish fed", "fed cut", "fed pause"), 1),
    ("hack_exploit", ("hack", "exploit", "stolen funds", "drained", "breach", "vulnerability exploited", "$m stolen", "$m exploit", "$m hack", "flash loan attack"), 1),
    ("exchange_bankruptcy", ("bankrupt", "bankruptcy", "chapter 11", "insolvent", "halts withdrawals", "suspend withdrawals", "ftx collapse"), 1),
    ("exchange_listing", ("will list", "new listing", "listing on", "binance listing", "coinbase listing", "lists on"), 2),
    ("exchange_delisting", ("delist", "delisting", "remove from", "suspend trading"), 1),
    ("regulatory_action", ("sec charge", "cftc charge", "sec sues", "lawsuit filed", "enforcement action", "subpoena", "doj investigation"), 1),
    ("regulation_ban", ("china ban", "ban crypto", "crypto illegal", "prohibit crypto", "criminalize crypto"), 1),
    ("protocol_upgrade", ("network upgrade", "hard fork", "mainnet launch", "v2 upgrade", "merge", "shapella", "dencun"), 1),
    ("halving", ("halving", "block reward halving", "mining reward cut"), 1),
    ("defi_exploit", ("defi exploit", "protocol exploit", "bridge exploit", "flash loan exploit", "drained from"), 2),
    ("stablecoin_depeg", ("depeg", "ust collapse", "usdc depeg", "stablecoin depeg", "de-pegs"), 1),
    ("macro_cpi", ("cpi print", "inflation data", "pce report", "jobs report", "nfp", "nonfarm payrolls"), 2),
    ("institutional_adoption", ("institutional adoption", "blackrock buys", "fidelity crypto", "microstrategy buys", "etf inflows", "corporate treasury"), 2),
)

# ── Crypto sectors ──────────────────────────────────────────────────────────

CRYPTO_SECTOR_RULES: dict[str, tuple[str, ...]] = {
    "CRYPTO_L1": ("bitcoin", "btc", "ethereum", "eth", "solana", "sol", "bnb", "layer 1", "l1", "blockchain"),
    "CRYPTO_L2": ("layer 2", "l2", "arbitrum", "optimism", "base chain", "polygon", "matic", "zk", "rollup"),
    "CRYPTO_DEFI": ("defi", "dex", "decentralized exchange", "yield", "lending", "amm", "liquidity pool", "aave", "uniswap", "compound"),
    "CRYPTO_NFT": ("nft", "non-fungible", "opensea", "collection", "mint"),
    "CRYPTO_STABLECOIN": ("stablecoin", "usdt", "usdc", "tether", "ust", "depeg"),
    "CRYPTO_MINING": ("mining", "hashrate", "miner", "hash rate", "bitcoin miner"),
    "CRYPTO_EXCHANGE": ("binance", "coinbase", "kraken", "ftx", "okx", "exchange", "cex"),
    "CRYPTO_REGULATION": ("sec", "cftc", "regulation", "regulatory", "ban", "enforcement", "compliance"),
    "CRYPTO_MEME": ("dogecoin", "doge", "shiba", "meme coin", "pepe", "meme"),
    "CRYPTO_AI": ("ai token", "artificial intelligence", "render", "fetch", "worldcoin", "ai crypto"),
}

# ── Known crypto symbols and aliases ────────────────────────────────────────

CRYPTO_SYMBOL_MAP: dict[str, str] = {
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH", "ether": "ETH",
    "solana": "SOL", "sol": "SOL",
    "binance coin": "BNB", "bnb": "BNB",
    "xrp": "XRP", "ripple": "XRP",
    "cardano": "ADA", "ada": "ADA",
    "dogecoin": "DOGE", "doge": "DOGE",
    "avalanche": "AVAX", "avax": "AVAX",
    "polkadot": "DOT", "dot": "DOT",
    "polygon": "MATIC", "matic": "MATIC",
    "chainlink": "LINK", "link": "LINK",
    "litecoin": "LTC", "ltc": "LTC",
    "uniswap": "UNI", "uni": "UNI",
    "arbitrum": "ARB", "arb": "ARB",
    "optimism": "OP", "op": "OP",
    "tether": "USDT", "usdt": "USDT",
    "usd coin": "USDC", "usdc": "USDC",
}

# Regex for patterns like "$BTC", "BTC/USDT", "BTC-USD", "BTCUSDT"
_CRYPTO_TICKER_RE = re.compile(r'\$?([A-Z]{2,10})(?:/USDT|/USD|-USD|USDT)?\b')
_DOLLAR_TICKER_RE = re.compile(r'\$([A-Z]{2,10})\b')


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _count_hits(text: str, terms: tuple[str, ...]) -> int:
    if not text:
        return 0
    lower = text.lower()
    return sum(lower.count(t) for t in terms)


def extract_crypto_symbols(text: str) -> list[str]:
    """Extract crypto symbols from English text."""
    symbols: set[str] = set()
    lower = text.lower()
    for alias, symbol in CRYPTO_SYMBOL_MAP.items():
        if alias in lower:
            symbols.add(symbol)
    # $TICKER patterns
    for match in _DOLLAR_TICKER_RE.finditer(text):
        ticker = match.group(1)
        if ticker in CRYPTO_SYMBOL_MAP.values() or ticker in {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "MATIC", "LINK", "LTC", "UNI", "ARB", "OP"}:
            symbols.add(ticker)
    return sorted(symbols)


def extract_crypto_sectors(text: str) -> list[str]:
    """Extract crypto sectors from English text."""
    lower = text.lower()
    sectors = [
        sector for sector, terms in CRYPTO_SECTOR_RULES.items()
        if any(t in lower for t in terms)
    ]
    return sorted(set(sectors))


@dataclass
class CryptoNewsAnalysis:
    """Analysis result for a crypto news article."""
    sentiment_score: float = 0.0
    sentiment_label: str = "neutral"
    event_type: str = "other"
    event_magnitude: float = 0.0
    event_confidence: float = 0.0
    affected_sectors: list[str] = field(default_factory=list)
    affected_symbols: list[str] = field(default_factory=list)
    urgency: str = "normal"
    is_urgent: bool = False
    market_scope: str = "individual"
    noise_score: float = 0.0
    novelty_score: float = 1.0
    source_credibility_weight: float = 0.7

    def to_dict(self) -> dict:
        return {
            "sentiment_score": round(self.sentiment_score, 4),
            "sentiment_label": self.sentiment_label,
            "event_type": self.event_type,
            "event_magnitude": round(self.event_magnitude, 4),
            "event_confidence": round(self.event_confidence, 4),
            "affected_sectors": self.affected_sectors,
            "affected_symbols": self.affected_symbols,
            "urgency": self.urgency,
            "is_urgent": self.is_urgent,
            "market_scope": self.market_scope,
            "noise_score": round(self.noise_score, 4),
        }


def analyze_crypto_news(
    title: str,
    text: str = "",
    *,
    source_credibility: float = 0.7,
) -> CryptoNewsAnalysis:
    """Analyze a crypto news article using keyword-based heuristics.

    This is the fast, always-on base layer. For production-grade sentiment,
    layer CryptoBERT/FinBERT results on top when available.
    """
    combined = f"{title} {text}".strip()
    lower = combined.lower()

    pos_hits = _count_hits(combined, CRYPTO_POSITIVE)
    neg_hits = _count_hits(combined, CRYPTO_NEGATIVE)
    pos_mod = _count_hits(combined, CRYPTO_POSITIVE_MODIFIERS)
    neg_mod = _count_hits(combined, CRYPTO_NEGATIVE_MODIFIERS)

    raw_sent = (pos_hits - neg_hits) + 0.3 * (pos_mod - neg_mod)
    sentiment_score = math.tanh(raw_sent / 2.5)

    if "ban" in lower or "hack" in lower or "exploit" in lower:
        sentiment_score = min(sentiment_score, -0.3)
    if "etf approved" in lower or "approval" in lower and "etf" in lower:
        sentiment_score = max(sentiment_score, 0.4)

    if sentiment_score >= 0.2:
        label = "positive"
    elif sentiment_score <= -0.2:
        label = "negative"
    else:
        label = "neutral"

    event_type = "other"
    event_confidence = 0.0
    best_evt_hits = 0
    for evt, terms, min_hits in CRYPTO_EVENT_RULES:
        hits = sum(1 for t in terms if t in lower)
        if hits >= min_hits and hits > best_evt_hits:
            event_type = evt
            event_confidence = _clip(hits / max(2, len(terms)), 0.3, 0.95)
            best_evt_hits = hits

    urgent_terms = ("breaking", "just in", "urgent", "emergency", "now live")
    urgent_hits = _count_hits(combined, urgent_terms)
    high_impact_events = {"etf_approval", "etf_rejection", "hack_exploit", "exchange_bankruptcy", "exchange_delisting", "regulation_ban", "stablecoin_depeg", "defi_exploit"}
    is_urgent = urgent_hits > 0 or (event_type in high_impact_events and event_confidence >= 0.5)
    urgency = "immediate" if is_urgent else ("short_term" if event_confidence > 0.5 else "normal")

    symbols = extract_crypto_symbols(combined)
    sectors = extract_crypto_sectors(combined)

    if "crypto market" in lower or "total market" in lower or len(sectors) >= 3 or "macro" in event_type:
        scope = "market"
    elif sectors or symbols:
        scope = "sector"
    else:
        scope = "individual"

    clickbait = _count_hits(combined, ("shocking", "you won't believe", "massive", "epic", "bombshell"))
    noise_score = _clip(0.3 * min(clickbait, 3) / 3.0 + 0.2 * (1.0 if len(title) < 15 else 0.0), 0.0, 1.0)

    magnitude = _clip(
        0.15
        + 0.25 * abs(sentiment_score)
        + 0.25 * event_confidence
        + 0.15 * source_credibility
        + 0.1 * (1.0 if scope == "market" else 0.6 if scope == "sector" else 0.3)
        + 0.1 * (1.0 if is_urgent else 0.0)
        - 0.15 * noise_score,
        0.0,
        1.0,
    )

    return CryptoNewsAnalysis(
        sentiment_score=round(float(sentiment_score), 4),
        sentiment_label=label,
        event_type=event_type,
        event_magnitude=round(float(magnitude), 4),
        event_confidence=round(float(event_confidence), 4),
        affected_sectors=sectors or ["CRYPTO_GENERAL"],
        affected_symbols=symbols,
        urgency=urgency,
        is_urgent=is_urgent,
        market_scope=scope,
        noise_score=round(float(noise_score), 4),
        novelty_score=1.0,
        source_credibility_weight=source_credibility,
    )


def compute_fear_greed_category(value: int) -> str:
    """Convert Fear & Greed Index value (0-100) to category."""
    if value <= 25:
        return "extreme_fear"
    if value <= 45:
        return "fear"
    if value <= 55:
        return "neutral"
    if value <= 75:
        return "greed"
    return "extreme_greed"
