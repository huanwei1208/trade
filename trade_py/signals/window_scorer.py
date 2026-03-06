from __future__ import annotations

"""Window quality scorer for the watchlist.

Computes a 0-100 score for each symbol indicating how "clean" the current
price action window is for making a decision.

Score components (all 0-100 then weighted sum):
    A. Turnover/volume: is volume drying up (potential breakout setup)?  20 pts
    B. Large-order net flow: institutional accumulation signal?           20 pts
    C. Technical position: RSI, MA position, MACD momentum?              20 pts
    D. Price behaviour: gap_up, distance from 52-week high/low?          20 pts
    E. Sentiment: net_sentiment / neg_shock / sent_velocity from Gold?   20 pts

The score is stored in signal_cache via SettingsDB.
"""

import logging
import sys
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_DATA_ROOT = "data"


# ── Individual score components ────────────────────────────────────────────────

def _score_volume(df: pd.DataFrame) -> float:
    """Volume drying up in recent 5 days vs 20-day MA → higher score = quieter."""
    if len(df) < 20:
        return 50.0
    vol_5d  = df["volume"].iloc[-5:].mean()
    vol_20d = df["volume"].iloc[-20:].mean()
    if vol_20d == 0:
        return 50.0
    ratio = vol_5d / vol_20d  # < 1 means drying, > 1 means expansion
    # Ideal for accumulation: 0.5–0.8 (quiet but not dead)
    if   ratio < 0.3:  return 30.0  # too quiet, may be delisted/suspended
    elif ratio < 0.5:  return 75.0
    elif ratio < 0.8:  return 95.0
    elif ratio < 1.0:  return 70.0
    elif ratio < 1.5:  return 50.0
    else:              return 20.0  # volume expansion, chasing not ideal


def _score_large_order(symbol: str, data_root: str) -> float:
    """Read fund_flow parquet and score based on large-order net flow trend."""
    ff_path = Path(data_root) / "fund_flow" / f"{symbol.replace('.', '_')}.parquet"
    if not ff_path.exists():
        return 50.0  # neutral when no data
    try:
        df = pd.read_parquet(ff_path)
        if df.empty or "large_order_net_ratio" not in df.columns:
            return 50.0
        df = df.sort_values("date").tail(5)
        recent = df["large_order_net_ratio"].dropna()
        if recent.empty:
            return 50.0
        latest = recent.iloc[-1]
        trend_3d = recent.diff().dropna().mean() if len(recent) >= 3 else 0
        # Score: positive and rising is best
        base = 50.0 + latest * 200  # ±25 range for ±12.5% net ratio
        base = max(0.0, min(100.0, base))
        if trend_3d > 0:
            base = min(100.0, base + 10)
        elif trend_3d < 0:
            base = max(0.0, base - 10)
        return base
    except Exception:
        return 50.0


def _score_technical(df: pd.DataFrame) -> float:
    """Score RSI position and MACD momentum (simple inline computation)."""
    if len(df) < 26:
        return 50.0
    close = df["close"]

    # RSI-14
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, float("nan"))
    rsi   = 100 - 100 / (1 + rs)
    rsi_val = rsi.iloc[-1]

    # MACD: 12-26-9
    ema12  = close.ewm(span=12, adjust=False).mean()
    ema26  = close.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    # Bullish: histogram positive and rising
    hist_val  = hist.iloc[-1]
    hist_prev = hist.iloc[-2] if len(hist) >= 2 else hist_val

    # RSI score: 30-50 is "oversold recovery" (ideal for entry) = 80+
    if   rsi_val < 20:  rsi_score = 40.0   # extremely oversold / possible trap
    elif rsi_val < 35:  rsi_score = 80.0   # oversold recovery zone
    elif rsi_val < 55:  rsi_score = 70.0   # neutral/mild bull
    elif rsi_val < 70:  rsi_score = 50.0   # overbought watch zone
    else:               rsi_score = 20.0   # overbought, avoid chasing

    # MACD score
    if hist_val > 0 and hist_val > hist_prev:
        macd_score = 80.0   # bullish and strengthening
    elif hist_val > 0:
        macd_score = 60.0   # bullish but weakening
    elif hist_val < 0 and hist_val < hist_prev:
        macd_score = 20.0   # bearish and weakening
    else:
        macd_score = 40.0   # transitional

    return (rsi_score + macd_score) / 2


def _score_price_behaviour(df: pd.DataFrame) -> float:
    """Score based on distance from 52-week high/low and gap-up pattern."""
    if len(df) < 5:
        return 50.0
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    high_52w = high.tail(252).max()
    low_52w  = low.tail(252).min()
    current  = close.iloc[-1]

    # Distance to 52-week high (0=at high, 1=at low)
    if high_52w > low_52w:
        dist = (high_52w - current) / (high_52w - low_52w)
    else:
        dist = 0.5

    # Consolidation near lows with recent recovery is ideal
    # dist ~0.6-0.8: recovering from low = good setup
    if   dist < 0.1:  dist_score = 30.0   # at 52w high, chasing
    elif dist < 0.3:  dist_score = 55.0
    elif dist < 0.5:  dist_score = 70.0
    elif dist < 0.7:  dist_score = 80.0   # sweet spot
    elif dist < 0.9:  dist_score = 65.0
    else:             dist_score = 40.0   # near 52w low, possible value trap

    # Gap-up signal in recent 3 days
    prev = df["prev_close"]
    opens = df["open"]
    gap_pcts = ((opens - prev) / prev.replace(0, float("nan"))).tail(3)
    has_gap_up = (gap_pcts > 0.02).any()
    if has_gap_up:
        dist_score = min(100.0, dist_score + 10)

    return dist_score


# ── Sentiment component (Gold tier) ────────────────────────────────────────────

def _score_sentiment(symbol: str, data_root: str,
                     date_str: str | None = None) -> float:
    """Score [0-100] from Gold sentiment tier for a symbol.

    Uses net_sentiment, neg_shock, sent_velocity from the most recent
    Gold Parquet file available.

    Returns 50 (neutral) when no Gold data exists.
    """
    import datetime
    gold_dir = Path(data_root) / "sentiment" / "gold"
    if not gold_dir.exists():
        return 50.0

    # Find the most recent gold parquet on or before date_str
    target_date = (
        datetime.date.fromisoformat(date_str) if date_str
        else datetime.date.today()
    )
    # Scan last 5 calendar days for a file
    gold_path = None
    for delta in range(5):
        d = target_date - datetime.timedelta(days=delta)
        p = gold_dir / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.isoformat()}.parquet"
        if p.exists():
            gold_path = p
            break
    if gold_path is None:
        return 50.0

    try:
        df = pd.read_parquet(gold_path)
        # Try symbol-level row first, fall back to _MARKET_
        row = df[df["symbol"] == symbol]
        if row.empty:
            row = df[df["symbol"] == "_MARKET_"]
        if row.empty:
            return 50.0
        row = row.iloc[0]

        net_sent   = float(row.get("net_sentiment",  0.0))  # [-1, 1]
        neg_shock  = float(row.get("neg_shock",      0.0))  # negative = bad
        sent_vel   = float(row.get("sent_velocity",  0.0))  # positive = improving

        # net_sentiment: scale [-1,1] → [0,100]
        base = 50.0 + net_sent * 40.0

        # Negative shock penalty: each 0.1 of neg_shock subtracts ~10 pts
        base -= neg_shock * 100.0

        # Velocity bonus/penalty: rising sentiment is a positive signal
        base += sent_vel * 20.0

        return max(0.0, min(100.0, base))
    except Exception:
        return 50.0


# ── Master scorer ──────────────────────────────────────────────────────────────

def compute_window_score(
    symbol: str,
    kline_df: pd.DataFrame,
    data_root: str = _DEFAULT_DATA_ROOT,
    date_str: str | None = None,
) -> int:
    """Compute composite window score [0-100] for a symbol.

    Args:
        symbol:    Stock code (e.g., "600000.SH")
        kline_df:  DataFrame with columns: date, open, high, low, close, volume,
                   amount, turnover_rate, prev_close, vwap. Sorted by date.
        data_root: Path to the data root directory.
        date_str:  Date for sentiment lookup (default: today).

    Returns:
        Integer score 0-100.
    """
    if kline_df is None or kline_df.empty or len(kline_df) < 5:
        return 0

    w = 0.20  # equal weight across 5 components

    s_vol   = _score_volume(kline_df)
    s_flow  = _score_large_order(symbol, data_root)
    s_tech  = _score_technical(kline_df)
    s_price = _score_price_behaviour(kline_df)
    s_sent  = _score_sentiment(symbol, data_root, date_str)

    composite = w * (s_vol + s_flow + s_tech + s_price + s_sent)
    return max(0, min(100, round(composite)))


def score_watchlist(
    data_root: str = _DEFAULT_DATA_ROOT,
    date_str: str | None = None,
) -> dict[str, int]:
    """Score all symbols in the watchlist and cache results.

    Returns a dict mapping symbol → score.
    """
    import datetime

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from trade_py.db.settings_db import SettingsDB

    db = SettingsDB(data_root)
    symbols = db.watchlist_get()
    if not symbols:
        logger.info("Watchlist is empty, nothing to score")
        return {}

    date_str = date_str or datetime.date.today().isoformat()
    kline_dir = Path(data_root) / "kline"

    scores: dict[str, int] = {}
    for symbol in symbols:
        sym_file = symbol.replace(".", "_") + ".parquet"
        frames = []
        if kline_dir.exists():
            for month_dir in sorted(kline_dir.iterdir()):
                p = month_dir / sym_file
                if p.exists():
                    frames.append(pd.read_parquet(p))

        if frames:
            df = pd.concat(frames, ignore_index=True)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").tail(260)
        else:
            df = pd.DataFrame()

        score = compute_window_score(symbol, df, data_root, date_str)
        scores[symbol] = score

        # Also pull net_sentiment from Gold for caching alongside the score
        gold_dir = Path(data_root) / "sentiment" / "gold"
        net_sentiment_val = None
        if gold_dir.exists():
            import datetime as _dt
            target_d = _dt.date.fromisoformat(date_str) if date_str else _dt.date.today()
            for delta in range(5):
                gp = (gold_dir / f"{(target_d - _dt.timedelta(days=delta)).year:04d}"
                      / f"{(target_d - _dt.timedelta(days=delta)).month:02d}"
                      / f"{(target_d - _dt.timedelta(days=delta)).isoformat()}.parquet")
                if gp.exists():
                    try:
                        gdf = pd.read_parquet(gp)
                        row_sym = gdf[gdf["symbol"] == symbol]
                        if not row_sym.empty and "net_sentiment" in gdf.columns:
                            net_sentiment_val = float(row_sym.iloc[0]["net_sentiment"])
                    except Exception:
                        pass
                    break

        logger.info("%s  window_score=%d  net_sentiment=%s",
                    symbol, score, net_sentiment_val)

        cache_fields: dict = {"window_score": score}
        if net_sentiment_val is not None:
            cache_fields["net_sentiment"] = net_sentiment_val
        db.signal_cache_upsert(date_str, symbol, **cache_fields)

    return scores
