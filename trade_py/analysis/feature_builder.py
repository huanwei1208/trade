"""Feature builder for the event propagation prediction model.

Assembles feature vectors for (event, asset, date) triples used in training
and inference. Six feature groups follow the plan plus Groups F and G:

  Group A – Event features:      event_type, magnitude, actor_risk_score, ...
  Group B – KG relationship:     kg_hop_distance, kg_edge_weight, ...
  Group C – Asset technical:     19 original + 6 K-line hidden signals
  Group D – Market environment:  sector rank, northbound flow, fund flow ...
  Group E – Fundamental:         ROE, profit growth, cash flow quality, ...
  Group F – Sentiment quality:   news silence signal, entropy, narrative density
  Group G – Smart money (CMF):   smart_money_flow_5d, smart_money_flow_20d

All computation is in Python (cold training path). Decision-time inference
uses the C++ FeatureExtractor + ONNX runtime instead.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Feature column definitions ────────────────────────────────────────────────

# Group A: Event features (7 fields)
GROUP_A_COLS = [
    "event_magnitude",       # [0,1] LLM event strength
    "event_breadth",         # 0=stock, 1=sector, 2=market (ordinal)
    "actor_risk_score",      # [0,1] actor unpredictability
    "news_volume_spike",     # current news / 30d avg  (>1 = spike)
    "sentiment_score",       # LLM [-1,+1]
    "event_recency_penalty", # 1 / (1 + days_since_same_event_type)
    "event_type_idx",        # integer index of EventType (one category)
]

# Group B: Knowledge graph relationship (5 fields)
GROUP_B_COLS = [
    "kg_hop_distance",         # 1=direct, 2=second-order, 0=no path
    "kg_edge_weight",          # propagation strength [0,1]
    "kg_direction",            # +1=same direction, -1=inverse
    "historical_propagation",  # historical mean excess return for this (event,sector) pair
    "propagation_lag_days",    # typical propagation lag in trading days
]

# Group C: Asset technical state (25 fields – 19 original + 6 K-line hidden)
GROUP_C_COLS = [
    # original 19
    "kdj_zone",             # 0/1/2
    "kdj_cross",            # -1/0/+1
    "kdj_divergence",       # -1/0/+1
    "macd_cross",           # -1/0/+1
    "macd_histogram_slope", # float
    "macd_zero_position",   # -1/+1
    "rsi_14",               # [0,100]
    "rsi_zone",             # 0/1/2
    "rsi_divergence",       # -1/0/+1
    "bb_position",          # approx [-1.5, 1.5]
    "bb_width_change",      # float
    "volume_price_sync",    # [0,1]
    "volume_breakout",      # ratio (>1 = high volume)
    "obv_slope",            # float (normalized by price level)
    "momentum_20d",         # [-1,+1]
    "momentum_60d",         # [-1,+1]
    "ma_trend",             # -1/0/+1
    "volatility_20d",       # annualized σ
    "liquidity_20d",        # avg turnover rate
    # Phase 6-C: 6 K-line hidden signals
    "gap_up_size",          # (open_t - close_{t-1}) / close_{t-1}
    "gap_up_volume_ratio",  # volume_t / volume_ma20
    "dist_to_52w_high",     # (high_52w - close) / close
    "dist_to_52w_low",      # (close - low_52w) / close
    "volume_poc_dist",      # (close - vwap_20d) / close  [VWAP proxy for POC]
    "auction_vol_ratio",    # placeholder 0.0 (needs L2/auction data)
]

# Group D: Market environment (6 fields, +1 from Phase 6-E)
GROUP_D_COLS = [
    "market_trend_20d",      # MA20 return of benchmark
    "sector_rank_20d",       # sector 20d return rank [0,1]
    "northbound_5d_net",     # 5-day northbound net flow (billion CNY)
    "margin_balance_change", # margin balance % change vs 30d ago
    "market_breadth",        # fraction of up-ticking stocks
    "large_order_net_ratio", # (超大单+大单 net buy) / total turnover
]

# Group E: Fundamental features (8 fields)
GROUP_E_COLS = [
    "roe_ttm",              # TTM ROE (%)
    "roe_momentum",         # ROE trend vs 4Q ago
    "profit_growth_yoy",    # YoY net profit growth ratio
    "revenue_growth_yoy",   # YoY revenue growth ratio
    "cash_flow_quality",    # OCF / Net Profit (>1 = high quality)
    "pe_percentile",        # PE rank in 3-year history [0,1]
    "pe_ttm",               # TTM P/E ratio
    "pb",                   # Price / Book ratio
]

# Group F: Sentiment quality + narrative density (4 fields, Phase 6-A/B)
GROUP_F_COLS = [
    "news_silence_signal",    # news_today / news_30d_avg - 1  (< -0.5 = danger)
    "sentiment_entropy",      # Shannon entropy of daily sentiment distribution [0,1]
    "narrative_density",      # count of active narrative threads targeting this asset
    "narrative_density_trend", # 5-day trend: +1/0/-1
]

# Group G: Smart money Chaikin Money Flow (2 fields, Phase 8)
GROUP_G_COLS = [
    "smart_money_flow_5d",   # 5-day Chaikin Money Flow [-1, +1] (positive = accumulation)
    "smart_money_flow_20d",  # 20-day Chaikin Money Flow [-1, +1]
]

ALL_FEATURE_COLS = (
    GROUP_A_COLS + GROUP_B_COLS + GROUP_C_COLS +
    GROUP_D_COLS + GROUP_E_COLS + GROUP_F_COLS + GROUP_G_COLS
)
N_FEATURES = len(ALL_FEATURE_COLS)  # 7+5+25+6+8+4+2 = 57


# ── Technical signal computation (Python mirror of C++ TechnicalSignal) ───────

def _ema(series: np.ndarray, period: int) -> np.ndarray:
    """Standard EMA with alpha = 2/(period+1)."""
    alpha = 2.0 / (period + 1)
    out = np.empty_like(series)
    out[0] = series[0]
    for i in range(1, len(series)):
        out[i] = alpha * series[i] + (1.0 - alpha) * out[i - 1]
    return out


def _wilder_ema(series: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing EMA with alpha = 1/period."""
    alpha = 1.0 / period
    out = np.empty_like(series)
    out[0] = series[0]
    for i in range(1, len(series)):
        out[i] = alpha * series[i] + (1.0 - alpha) * out[i - 1]
    return out


def _rolling_stats(arr: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Rolling mean and std for a 1-D array, returns (mean, std) arrays."""
    n = len(arr)
    means = np.full(n, np.nan)
    stds  = np.full(n, np.nan)
    for i in range(window - 1, n):
        w = arr[i - window + 1 : i + 1]
        means[i] = w.mean()
        stds[i]  = w.std(ddof=1) if len(w) > 1 else 0.0
    return means, stds


def _linear_slope(arr: np.ndarray) -> float:
    """Slope of a linear fit over a 1-D array."""
    n = len(arr)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    m = np.polyfit(x, arr, 1)[0]
    return float(m)


def compute_technical_features(bars_df: pd.DataFrame) -> dict[str, float]:
    """Compute TechnicalSignal fields from a kline DataFrame.

    Args:
        bars_df: DataFrame with columns [open, close, high, low, volume, turnover_rate],
                 sorted ascending by date. Must have at least 2 rows.

    Returns:
        Dict of feature name → float value.
        All 25 Group C fields (GROUP_C_COLS).
    """
    defaults: dict[str, float] = {col: 0.0 for col in GROUP_C_COLS}
    defaults["kdj_zone"]  = 1.0
    defaults["rsi_14"]    = 50.0
    defaults["rsi_zone"]  = 1.0

    n = len(bars_df)
    if n < 2:
        return defaults

    opens   = bars_df["open"].to_numpy(dtype=float) if "open" in bars_df.columns \
              else np.zeros(n)
    closes  = bars_df["close"].to_numpy(dtype=float)
    highs   = bars_df["high"].to_numpy(dtype=float)
    lows    = bars_df["low"].to_numpy(dtype=float)
    volumes = bars_df["volume"].to_numpy(dtype=float)
    turnover = bars_df.get("turnover_rate", pd.Series(np.zeros(n))).to_numpy(dtype=float)

    out = dict(defaults)
    last = n - 1

    # ── KDJ ───────────────────────────────────────────────────────────────
    KDJ_P = 9
    K = np.full(n, 50.0)
    D = np.full(n, 50.0)
    for i in range(n):
        s = max(0, i - KDJ_P + 1)
        ll = lows[s:i+1].min()
        hh = highs[s:i+1].max()
        rng = hh - ll
        rsv = 50.0 if rng < 1e-10 else (closes[i] - ll) / rng * 100.0
        if i == 0:
            K[i] = 50.0 + (1.0 / 3.0) * (rsv - 50.0)
            D[i] = 50.0 + (1.0 / 3.0) * (K[i] - 50.0)
        else:
            K[i] = (2.0 / 3.0) * K[i-1] + (1.0 / 3.0) * rsv
            D[i] = (2.0 / 3.0) * D[i-1] + (1.0 / 3.0) * K[i]

    kval = K[last]
    out["kdj_zone"] = float(0 if kval < 20 else 2 if kval > 80 else 1)
    if last >= 1:
        was_below = K[last-1] < D[last-1]
        now_above = K[last]   >= D[last]
        was_above = K[last-1] >= D[last-1]
        now_below = K[last]   <  D[last]
        if was_below and now_above:
            out["kdj_cross"] = 1.0
        elif was_above and now_below:
            out["kdj_cross"] = -1.0

    # KDJ divergence (look at K vs price over last 20 bars)
    if last >= 20:
        start = last - 20
        max_price_old = closes[start:last].max()
        max_k_old     = K[start:last].max()
        if closes[last] > max_price_old:
            out["kdj_divergence"] = 1.0 if K[last] > max_k_old else -1.0

    # ── MACD ──────────────────────────────────────────────────────────────
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif   = ema12 - ema26
    sig_l = _ema(dif, 9)
    hist  = dif - sig_l
    if last >= 1:
        if dif[last-1] < sig_l[last-1] and dif[last] >= sig_l[last]:
            out["macd_cross"] = 1.0
        elif dif[last-1] >= sig_l[last-1] and dif[last] < sig_l[last]:
            out["macd_cross"] = -1.0
    if n >= 5:
        out["macd_histogram_slope"] = _linear_slope(hist[last-4:last+1])
    out["macd_zero_position"] = 1.0 if dif[last] >= 0 else -1.0

    # ── RSI ───────────────────────────────────────────────────────────────
    RSI_P = 14
    chg    = np.diff(closes, prepend=closes[0])
    gains  = np.where(chg > 0, chg, 0.0)
    losses = np.where(chg < 0, -chg, 0.0)
    avg_g  = _wilder_ema(gains, RSI_P)
    avg_l  = _wilder_ema(losses, RSI_P)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_l < 1e-10,
                      np.where(avg_g < 1e-10, 1.0, 1e10),
                      avg_g / avg_l)
    rsi_series = 100.0 - 100.0 / (1.0 + rs)
    rsi_series[avg_l < 1e-10] = np.where(avg_g[avg_l < 1e-10] < 1e-10, 50.0, 100.0)
    rval = float(rsi_series[last])
    out["rsi_14"]   = rval
    out["rsi_zone"] = float(0 if rval < 30 else 2 if rval > 70 else 1)
    if last >= 20:
        start = last - 20
        max_price_old = closes[start:last].max()
        max_rsi_old   = rsi_series[start:last].max()
        if closes[last] > max_price_old:
            out["rsi_divergence"] = 1.0 if rsi_series[last] > max_rsi_old else -1.0

    # ── Bollinger Bands (20-period, 2σ) ───────────────────────────────────
    BB_P = 20
    if n >= BB_P:
        bb_means, bb_stds = _rolling_stats(closes, BB_P)
        ma   = bb_means[last]
        sd   = bb_stds[last]
        bw   = 4.0 * sd  # upper - lower = 4σ
        low_ = ma - 2 * sd
        if bw > 1e-10:
            out["bb_position"] = float((closes[last] - low_) / bw * 2.0 - 1.0)
        # Width change vs 20d avg of widths
        widths = 4.0 * bb_stds
        if last >= BB_P:
            avg_width = float(np.nanmean(widths[last-BB_P+1:last+1]))
            if avg_width > 1e-10:
                out["bb_width_change"] = float((bw - avg_width) / avg_width)

    # ── Volume-price sync (20d) ────────────────────────────────────────────
    VP_W = 20
    if n >= VP_W + 1:
        sync = 0
        for i in range(last - VP_W + 1, last + 1):
            pc = closes[i] - closes[i-1]
            vc = volumes[i] - volumes[i-1]
            if (pc > 0 and vc > 0) or (pc < 0 and vc < 0):
                sync += 1
        out["volume_price_sync"] = sync / VP_W

    # ── Volume breakout ────────────────────────────────────────────────────
    VB_W = 20
    if n >= VB_W:
        avg_vol = volumes[last-VB_W:last].mean()
        if avg_vol > 1e-10:
            out["volume_breakout"] = float(volumes[last] / avg_vol)

    # ── OBV slope (5d) ────────────────────────────────────────────────────
    obv = np.zeros(n)
    for i in range(1, n):
        if closes[i] > closes[i-1]:
            obv[i] = obv[i-1] + volumes[i]
        elif closes[i] < closes[i-1]:
            obv[i] = obv[i-1] - volumes[i]
        else:
            obv[i] = obv[i-1]
    if n >= 5:
        # Normalize OBV slope by price to make it comparable across stocks
        price_scale = max(closes[last], 1.0)
        raw_slope = _linear_slope(obv[last-4:last+1])
        out["obv_slope"] = float(raw_slope / price_scale)

    # ── Momentum ──────────────────────────────────────────────────────────
    if last >= 20 and closes[last-20] > 1e-10:
        out["momentum_20d"] = float((closes[last] - closes[last-20]) / closes[last-20])
    if last >= 60 and closes[last-60] > 1e-10:
        out["momentum_60d"] = float((closes[last] - closes[last-60]) / closes[last-60])

    # ── MA trend alignment ─────────────────────────────────────────────────
    if n >= 60:
        ma5  = closes[last-4:last+1].mean()
        ma20 = closes[last-19:last+1].mean()
        ma60 = closes[last-59:last+1].mean()
        if ma5 > ma20 > ma60:
            out["ma_trend"] = 1.0
        elif ma5 < ma20 < ma60:
            out["ma_trend"] = -1.0
        else:
            out["ma_trend"] = 0.0

    # ── Volatility (annualized 20d) ────────────────────────────────────────
    VOL_W = 20
    if n >= VOL_W + 1:
        log_rets = np.log(closes[last-VOL_W+1:last+1] /
                          closes[last-VOL_W:last])
        daily_std = float(log_rets.std(ddof=1)) if len(log_rets) > 1 else 0.0
        out["volatility_20d"] = daily_std * math.sqrt(252.0)

    # ── Liquidity (avg turnover rate 20d) ─────────────────────────────────
    LIQ_W = 20
    if n >= LIQ_W:
        out["liquidity_20d"] = float(turnover[last-LIQ_W+1:last+1].mean())

    # ── Phase 6-C: K-line hidden signals ──────────────────────────────────

    # Gap-up size: (open_today - close_yesterday) / close_yesterday
    if last >= 1 and closes[last-1] > 1e-10:
        out["gap_up_size"] = float((opens[last] - closes[last-1]) / closes[last-1])

    # Gap-up volume ratio: volume_today / volume_ma20 (prev 20 bars)
    if last >= 20:
        vol_ma20_prev = float(volumes[last-20:last].mean())
        if vol_ma20_prev > 1e-10:
            out["gap_up_volume_ratio"] = float(volumes[last] / vol_ma20_prev)

    # Distance to 52-week high/low (use up to 252 bars)
    W52 = min(252, n)
    if W52 >= 5:
        high_52w = float(highs[last - W52 + 1 : last + 1].max())
        low_52w  = float(lows[last - W52 + 1 : last + 1].min())
        close_now = closes[last]
        if close_now > 1e-10:
            out["dist_to_52w_high"] = float((high_52w - close_now) / close_now)
            out["dist_to_52w_low"]  = float((close_now - low_52w) / close_now)

    # Volume POC distance: use 20d VWAP as proxy for Point of Control
    # vwap_20d = sum(typical_price * volume) / sum(volume) over last 20 bars
    if last >= 20:
        typical_prices = (highs[last-19:last+1] + lows[last-19:last+1] +
                          closes[last-19:last+1]) / 3.0
        vol_slice = volumes[last-19:last+1]
        total_vol = vol_slice.sum()
        if total_vol > 1e-10:
            vwap_20d = float(np.dot(typical_prices, vol_slice) / total_vol)
            if closes[last] > 1e-10:
                out["volume_poc_dist"] = float(
                    (closes[last] - vwap_20d) / closes[last])

    # Auction volume ratio: placeholder 0.0 (requires pre-market auction data)
    # out["auction_vol_ratio"] remains 0.0

    return out


# ── FeatureBuilder ─────────────────────────────────────────────────────────────

@dataclass
class FeatureRow:
    """Complete feature vector for one (event, symbol, date) training sample."""
    event_id:  str
    symbol:    str
    date:      str
    features:  dict[str, float]

    def to_series(self) -> pd.Series:
        return pd.Series({
            "event_id": self.event_id,
            "symbol":   self.symbol,
            "date":     self.date,
            **self.features,
        })


class FeatureBuilder:
    """Assembles feature rows for model training.

    Args:
        data_root: Path to data directory (contains kline/, sentiment/, events/)
    """

    def __init__(self, data_root: str | Path) -> None:
        self._root = Path(data_root)
        self._kline_cache: dict[str, pd.DataFrame] = {}
        self._sector_rank_cache: Optional[pd.DataFrame] = None
        self._event_db: Optional[object] = None  # lazy EventDatabase

    # ── Kline loading ─────────────────────────────────────────────────────────

    def _load_kline(self, symbol: str,
                    end_date: date,
                    lookback_bars: int = 260) -> Optional[pd.DataFrame]:
        """Load up to lookback_bars rows of kline data ending at end_date.

        Default 260 bars covers ~1 trading year (needed for 52-week features).
        """
        import duckdb
        kline_glob = str(self._root / "kline" / "**" / "*.parquet")
        cache_key = f"{symbol}:{end_date}"
        if cache_key in self._kline_cache:
            return self._kline_cache[cache_key]
        try:
            con = duckdb.connect()
            df = con.execute(f"""
                SELECT date, open, high, low, close, volume, turnover_rate
                FROM read_parquet('{kline_glob}', union_by_name=true)
                WHERE symbol = '{symbol}'
                  AND date <= '{end_date.isoformat()}'
                ORDER BY date DESC
                LIMIT {lookback_bars}
            """).df()
            con.close()
        except Exception as exc:
            logger.warning("FeatureBuilder: kline load failed for %s: %s", symbol, exc)
            return None
        if df.empty:
            return None
        # Re-sort ascending after DESC LIMIT for proper time-series computation
        df = df.sort_values("date").reset_index(drop=True)
        self._kline_cache[cache_key] = df
        return df

    # ── Sentiment loading (legacy + Phase 6-A signals) ────────────────────────

    def _load_sentiment(self, symbol: str, target_date: date,
                        lookback_days: int = 30) -> dict[str, float]:
        """Load raw sentiment factors from Gold layer for a symbol."""
        import duckdb
        gold_glob = str(self._root / "sentiment" / "gold" / "**" / "*.parquet")
        from_date = (target_date - timedelta(days=lookback_days)).isoformat()
        defaults = {"sentiment_score": 0.0, "news_volume": 0, "event_magnitude": 0.0}
        try:
            con = duckdb.connect()
            df = con.execute(f"""
                SELECT sentiment_score, article_count, event_magnitude, net_sentiment
                FROM read_parquet('{gold_glob}', union_by_name=true)
                WHERE symbol = '{symbol}'
                  AND date >= '{from_date}'
                  AND date <= '{target_date.isoformat()}'
                ORDER BY date DESC
                LIMIT 5
            """).df()
            con.close()
        except Exception:
            return defaults
        if df.empty:
            return defaults
        latest = df.iloc[0]
        return {
            "sentiment_score":  float(latest.get("sentiment_score", 0.0)),
            "news_volume":      int(df["article_count"].sum()),
            "event_magnitude":  float(df["event_magnitude"].max()),
        }

    def _sentiment_quality_features(self, symbol: str,
                                     target_date: date) -> dict[str, float]:
        """Compute Phase 6-A Group F sentiment quality signals.

        Returns:
            news_silence_signal: news_today / 30d_avg - 1 (< -0.5 in regulated
                sectors signals suppressed information = risk flag)
            sentiment_entropy:   normalized Shannon entropy of 30-day daily
                sentiment distribution; low entropy = extreme consensus = contrarian warning
        """
        import duckdb
        gold_glob = str(self._root / "sentiment" / "gold" / "**" / "*.parquet")
        defaults = {"news_silence_signal": 0.0, "sentiment_entropy": 0.5}
        from_date = (target_date - timedelta(days=35)).isoformat()
        try:
            con = duckdb.connect()
            df = con.execute(f"""
                SELECT date, sentiment_score, article_count
                FROM read_parquet('{gold_glob}', union_by_name=true)
                WHERE symbol = '{symbol}'
                  AND date >= '{from_date}'
                  AND date <= '{target_date.isoformat()}'
                ORDER BY date ASC
            """).df()
            con.close()
        except Exception:
            return defaults

        if df.empty or len(df) < 3:
            return defaults

        # news_silence_signal
        counts = df["article_count"].to_numpy(dtype=float)
        avg_count = counts[:-1].mean() if len(counts) > 1 else counts.mean()
        today_count = float(counts[-1])
        silence = (today_count / max(avg_count, 0.1)) - 1.0
        # Clamp to [-2, 5] to avoid extreme outliers
        defaults["news_silence_signal"] = float(max(-2.0, min(5.0, silence)))

        # sentiment_entropy: Shannon entropy of daily sentiment distribution
        scores = df["sentiment_score"].dropna().to_numpy(dtype=float)
        if len(scores) >= 3:
            # Discretize [-1, +1] into 5 bins
            hist, _ = np.histogram(scores, bins=5, range=(-1.0, 1.0))
            hist = hist.astype(float) + 1e-10  # Laplace smoothing
            hist /= hist.sum()
            raw_entropy = -float(np.sum(hist * np.log(hist)))
            max_entropy = math.log(5)  # max entropy for 5 bins
            defaults["sentiment_entropy"] = float(raw_entropy / max_entropy)

        return defaults

    # ── KG features ───────────────────────────────────────────────────────────

    def _kg_features(self, event_type: str, symbol_sector: str) -> dict[str, float]:
        """Look up KG propagation features for (event_type, sector) pair."""
        try:
            from trade_py.analysis.knowledge_graph import SectorGraph, SW

            sg = SectorGraph()
            results = sg.propagate_event(event_type, max_hop=2)

            sector_name = symbol_sector.replace("SW_", "")
            target_sw = None
            for sw in SW:
                if sw.name == sector_name:
                    target_sw = sw
                    break

            if target_sw is None:
                return {"kg_hop_distance": 0.0, "kg_edge_weight": 0.0,
                        "kg_direction": 0.0, "historical_propagation": 0.0,
                        "propagation_lag_days": 0.0}

            for r in results:
                if r.sector == target_sw:
                    return {
                        "kg_hop_distance":        float(r.hop),
                        "kg_edge_weight":         abs(r.score),
                        "kg_direction":           float(1 if r.score > 0 else -1),
                        "historical_propagation": r.score,
                        "propagation_lag_days":   float(r.typical_days),
                    }
        except Exception as exc:
            logger.debug("KG lookup failed: %s", exc)

        return {"kg_hop_distance": 0.0, "kg_edge_weight": 0.0,
                "kg_direction": 0.0, "historical_propagation": 0.0,
                "propagation_lag_days": 0.0}

    # ── Market environment ────────────────────────────────────────────────────

    def _market_features(self, target_date: date) -> dict[str, float]:
        """Load market environment features (Group D).

        Best-effort: returns zeros if data is unavailable.
        """
        import duckdb
        kline_glob = str(self._root / "kline" / "**" / "*.parquet")
        defaults = {
            "market_trend_20d":      0.0,
            "sector_rank_20d":       0.5,
            "northbound_5d_net":     0.0,
            "margin_balance_change": 0.0,
            "market_breadth":        0.5,
            "large_order_net_ratio": 0.0,
        }
        benchmark = "000001.SH"
        from_d = (target_date - timedelta(days=35)).isoformat()
        try:
            con = duckdb.connect()
            bm = con.execute(f"""
                SELECT close FROM read_parquet('{kline_glob}', union_by_name=true)
                WHERE symbol = '{benchmark}'
                  AND date >= '{from_d}'
                  AND date <= '{target_date.isoformat()}'
                ORDER BY date ASC
            """).df()
            con.close()
        except Exception:
            return defaults

        if len(bm) >= 20:
            closes = bm["close"].to_numpy()
            ma20 = closes[-20:].mean()
            ma20_prev = closes[-21:-1].mean() if len(closes) > 20 else ma20
            defaults["market_trend_20d"] = float((ma20 - ma20_prev) / max(ma20_prev, 1e-10))

        return defaults

    # ── Narrative density (Phase 6-B) ─────────────────────────────────────────

    def _narrative_density(self, symbol: str, sector: str,  # noqa: ARG002
                            target_date: date) -> dict[str, float]:
        """Compute Phase 6-B narrative density signals.

        Counts how many distinct active event-type narratives are currently
        propagating to the target asset via the knowledge graph.

        Returns:
            narrative_density:       count of unique active event types reaching asset
            narrative_density_trend: +1 if rising vs 5 days ago, -1 if falling, 0 same
        """
        defaults = {"narrative_density": 0.0, "narrative_density_trend": 0.0}

        # Lazily load EventDatabase
        if self._event_db is None:
            try:
                from trade_py.db.event_db import EventDatabase
                db = EventDatabase(str(self._root))
                db.load()
                self._event_db = db
            except Exception as exc:
                logger.debug("EventDatabase unavailable: %s", exc)
                return defaults

        def count_active_narratives(from_d: date, to_d: date) -> int:
            try:
                events = self._event_db.filter(  # type: ignore[union-attr]
                    start_date=from_d, end_date=to_d)
            except Exception:
                return 0
            relevant_types: set = set()
            for ev in events:
                kg = self._kg_features(ev.event_type.value, sector)
                if kg["kg_hop_distance"] > 0:
                    relevant_types.add(ev.event_type)
            return len(relevant_types)

        # Current 30-day window
        window_start = target_date - timedelta(days=30)
        density_now = count_active_narratives(window_start, target_date)

        # Compare to 5 days ago (shift window back 5 days)
        prev_end = target_date - timedelta(days=5)
        prev_start = prev_end - timedelta(days=30)
        density_prev = count_active_narratives(prev_start, prev_end)

        trend = 0.0
        if density_now > density_prev:
            trend = 1.0
        elif density_now < density_prev:
            trend = -1.0

        return {
            "narrative_density":      float(density_now),
            "narrative_density_trend": trend,
        }

    # ── Fundamental features ──────────────────────────────────────────────────

    def _fundamental_features(self, symbol: str, target_date: date,
                               bars: "pd.DataFrame") -> dict[str, float]:
        """Load fundamental features (Group E) from local Parquet cache."""
        defaults: dict[str, float] = {col: 0.0 for col in GROUP_E_COLS}
        try:
            from trade_py.data.fundamental_fetcher import (
                FundamentalFetcher, compute_fundamental_features,
            )
            fetcher = FundamentalFetcher(str(self._root))
            df = fetcher.load(symbol)
            if df.empty:
                return defaults

            df["report_date"] = pd.to_datetime(df["report_date"])
            df = df[df["report_date"] <= pd.Timestamp(target_date)]
            if df.empty:
                return defaults

            current_price = float(bars["close"].iloc[-1]) if not bars.empty else 0.0
            total_shares = int(bars.get("total_shares", pd.Series([0])).iloc[-1]) \
                           if "total_shares" in bars.columns else 0

            result = compute_fundamental_features(
                df, current_price=current_price, total_shares=total_shares)
            return {col: float(result.get(col, 0.0)) for col in GROUP_E_COLS}
        except Exception as exc:
            logger.debug("Fundamental features unavailable for %s: %s", symbol, exc)
            return defaults

    # ── Smart money / Chaikin Money Flow (Phase 8, Group G) ──────────────────

    @staticmethod
    def _cmf(bars: pd.DataFrame, window: int) -> float:
        """Compute Chaikin Money Flow over the last `window` bars.

        CMF = sum(MFM * volume, window) / sum(volume, window)
        MFM = (2*close - high - low) / (high - low)

        Returns 0.0 when insufficient data or zero-range bars dominate.
        """
        n = len(bars)
        if n < window:
            return 0.0
        tail = bars.tail(window)
        high  = tail["high"].to_numpy(dtype=float)
        low   = tail["low"].to_numpy(dtype=float)
        close = tail["close"].to_numpy(dtype=float)
        vol   = tail["volume"].to_numpy(dtype=float)

        ranges = high - low
        mfm = np.where(ranges > 1e-8,
                       (2.0 * close - high - low) / ranges,
                       0.0)
        mfv_sum = float(np.dot(mfm, vol))
        vol_sum = float(vol.sum())
        return float(mfv_sum / vol_sum) if vol_sum > 1e-8 else 0.0

    def _smart_money_features(self, bars: pd.DataFrame) -> dict[str, float]:
        """Compute Group G smart money signals from OHLCV data."""
        defaults: dict[str, float] = {col: 0.0 for col in GROUP_G_COLS}
        if bars is None or bars.empty:
            return defaults
        defaults["smart_money_flow_5d"]  = self._cmf(bars, 5)
        defaults["smart_money_flow_20d"] = self._cmf(bars, 20)
        return defaults

    # ── Fund flow (Phase 6-E) ─────────────────────────────────────────────────

    def _fund_flow_features(self, symbol: str,
                             target_date: date) -> dict[str, float]:
        """Load large-order fund flow ratio from local Parquet cache (Group D ext)."""
        defaults = {"large_order_net_ratio": 0.0}
        try:
            from trade_py.data.fund_flow_fetcher import FundFlowFetcher
            fetcher = FundFlowFetcher(str(self._root))
            df = fetcher.load(symbol)
            if df.empty:
                return defaults
            # Find the row closest to target_date
            df["date"] = pd.to_datetime(df["date"])
            row = df[df["date"] <= pd.Timestamp(target_date)].tail(1)
            if row.empty:
                return defaults
            val = row["large_order_net_ratio"].iloc[0]
            return {"large_order_net_ratio": float(val) if val is not None else 0.0}
        except Exception as exc:
            logger.debug("Fund flow unavailable for %s: %s", symbol, exc)
            return defaults

    # ── Main build method ─────────────────────────────────────────────────────

    def build(self,
              event,          # HistoricalEvent
              symbol: str,
              sector: str,    # e.g. "SW_Electronics"
              lookback_bars: int = 260,
              ) -> Optional[FeatureRow]:
        """Build a complete feature row for (event, symbol) pair.

        Args:
            event: HistoricalEvent
            symbol: Stock code e.g. "600000.SH"
            sector: SW sector ID string e.g. "SW_Electronics"
            lookback_bars: Number of historical bars to load (default 260 = ~1yr)

        Returns:
            FeatureRow or None if insufficient data
        """
        from trade_py.db.event_db import EventType

        target_date = event.event_date
        bars = self._load_kline(symbol, target_date, lookback_bars)
        if bars is None or len(bars) < 20:
            return None

        # ── Group A: Event features ──────────────────────────────────────
        breadth_map = {"stock": 0, "sector": 1, "market": 2}
        event_type_idx = list(EventType).index(event.event_type) \
                         if event.event_type in list(EventType) else 0

        sent = self._load_sentiment(symbol, target_date)
        avg_daily_news = max(sent.get("news_volume", 0) / 30.0, 0.1)
        news_spike = sent.get("news_volume", 0) / avg_daily_news

        group_a: dict[str, float] = {
            "event_magnitude":       float(event.magnitude),
            "event_breadth":         float(breadth_map.get(event.breadth, 1)),
            "actor_risk_score":      float(event.actor_risk_score),
            "news_volume_spike":     float(min(news_spike, 10.0)),
            "sentiment_score":       float(sent.get("sentiment_score") or event.sentiment_score),
            "event_recency_penalty": 1.0,
            "event_type_idx":        float(event_type_idx),
        }

        # ── Group B: KG features ─────────────────────────────────────────
        group_b = self._kg_features(event.event_type.value, sector)

        # ── Group C: Technical features ──────────────────────────────────
        group_c = compute_technical_features(bars)

        # ── Group D: Market environment + fund flow ───────────────────────
        group_d = self._market_features(target_date)
        group_d.update(self._fund_flow_features(symbol, target_date))

        # ── Group E: Fundamental features ────────────────────────────────
        group_e = self._fundamental_features(symbol, target_date, bars)

        # ── Group F: Sentiment quality + narrative density ────────────────
        group_f_sent = self._sentiment_quality_features(symbol, target_date)
        group_f_narr = self._narrative_density(symbol, sector, target_date)
        group_f = {**group_f_sent, **group_f_narr}

        # ── Group G: Smart money (Chaikin Money Flow) ─────────────────────
        group_g = self._smart_money_features(bars)

        features = {**group_a, **group_b, **group_c, **group_d, **group_e, **group_f, **group_g}

        return FeatureRow(
            event_id=event.event_id,
            symbol=symbol,
            date=target_date.isoformat(),
            features=features,
        )

    def build_batch(self,
                    events,           # list[HistoricalEvent]
                    symbol_sector_map: dict[str, str],  # symbol → sector
                    ) -> pd.DataFrame:
        """Build feature DataFrame for all (event × symbol) pairs.

        Args:
            events: List of HistoricalEvent
            symbol_sector_map: {symbol: sector_id}

        Returns:
            DataFrame with event_id, symbol, date, and all feature columns.
        """
        rows = []
        total = len(events) * len(symbol_sector_map)
        done = 0
        for ev in events:
            for sym, sector in symbol_sector_map.items():
                row = self.build(ev, sym, sector)
                if row is not None:
                    rows.append(row.to_series())
                done += 1
                if done % 500 == 0:
                    logger.info("FeatureBuilder: %d/%d done", done, total)

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).reset_index(drop=True)
