"""Cross-asset macro environment signals.

Reads gold, BTC, and USD/CNH parquets written by cross_asset_fetcher and
computes three composite macro scores:

  risk_off_score   0–100   high = safe-haven demand (gold up, CNH weak, BTC down)
  risk_on_score    0–100   high = risk appetite (BTC up, CNH strong, gold flat)
  macro_env_score  -100–100 composite (positive = risk-on, negative = risk-off)

Usage:
    from trade_py.signals.cross_asset_signal import CrossAssetSignal
    sig = CrossAssetSignal("data")
    env = sig.latest()
    # {'risk_off_score': 62.3, 'risk_on_score': 38.1, 'macro_env_score': -24.2, 'date': '2026-03-01'}
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_CROSS_ASSET_DIR = "cross_asset"


def _momentum(df: pd.DataFrame, window: int) -> float:
    """Return (last_close / close_N_periods_ago - 1) in percent.

    Returns 0.0 when there are insufficient rows or data is missing.
    """
    if df is None or df.empty or len(df) < window + 1:
        return 0.0
    closes = df["close"].dropna()
    if len(closes) < window + 1:
        return 0.0
    pct = (closes.iloc[-1] / closes.iloc[-(window + 1)] - 1.0) * 100.0
    return float(pct)


def _percentile_rank(series: pd.Series, window: int = 252) -> float:
    """Rolling percentile rank of the last value over the past `window` rows.

    Returns a value in [0, 100]; 50 when data is insufficient.
    """
    if series is None or len(series) < 2:
        return 50.0
    tail = series.dropna().tail(window)
    if tail.empty:
        return 50.0
    last_val = tail.iloc[-1]
    rank = (tail < last_val).sum() / len(tail) * 100.0
    return float(rank)


class CrossAssetSignal:
    """Compute macro environment scores from cross-asset parquets."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self._dir = Path(data_root) / _CROSS_ASSET_DIR

    def _load(self, name: str) -> pd.DataFrame:
        """Load a parquet file; return empty DataFrame on failure."""
        p = self._dir / f"{name}.parquet"
        if not p.exists():
            logger.debug("cross_asset parquet not found: %s", p)
            return pd.DataFrame()
        try:
            df = pd.read_parquet(p)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", p, exc)
            return pd.DataFrame()

    def compute(self, as_of: str | None = None) -> dict:
        """Compute the three macro scores up to `as_of` date (inclusive).

        Args:
            as_of: ISO date string 'YYYY-MM-DD'.  Defaults to latest available.

        Returns:
            dict with keys: risk_off_score, risk_on_score, macro_env_score, date.
        """
        gold = self._load("gold")
        btc  = self._load("btc")
        fx   = self._load("fx_cnh")

        if as_of:
            cutoff = pd.Timestamp(as_of)
            gold = gold[gold["date"] <= cutoff] if not gold.empty else gold
            btc  = btc[btc["date"]  <= cutoff] if not btc.empty  else btc
            fx   = fx[fx["date"]   <= cutoff] if not fx.empty   else fx

        # --- Date of latest available data ---
        dates = []
        for df in (gold, btc, fx):
            if not df.empty:
                dates.append(str(df["date"].iloc[-1])[:10])
        latest_date = max(dates) if dates else (as_of or "N/A")

        # --- Gold momentum (5d) --- positive → risk-off
        gold_5d = _momentum(gold, 5)

        # --- BTC momentum (5d) --- positive → risk-on
        btc_5d = _momentum(btc, 5)

        # --- USD/CNH rate momentum (5d) ---
        # Rising = USD strengthening = risk-off; falling = CNH strength = risk-on
        fx_5d = _momentum(fx, 5)

        # --- Percentile ranks (rolling 252-day) ---
        gold_rank_pct = _percentile_rank(gold["close"]) if not gold.empty else 50.0
        btc_rank_pct  = _percentile_rank(btc["close"])  if not btc.empty  else 50.0

        # ─── risk_off_score (0–100) ─────────────────────────────────────────
        # Higher when:
        #   gold momentum is positive (flight to safety)
        #   USD/CNH is rising (capital outflow pressure)
        #   BTC is falling (risk aversion)
        #
        # Components:
        #   gold_momentum_contrib  : tanh(gold_5d / 3) mapped to [0,100]
        #   fx_momentum_contrib    : tanh(fx_5d / 1)  mapped to [0,100]
        #   btc_momentum_contrib   : tanh(-btc_5d / 5) mapped to [0,100]  (inverted)
        import math
        def _to_score(x: float, scale: float) -> float:
            return (math.tanh(x / scale) + 1.0) * 50.0  # → [0, 100]

        gold_contrib = _to_score(gold_5d, 3.0)  # ±3% daily swing is ±1 tanh unit
        fx_contrib   = _to_score(fx_5d,   1.0)  # ±1% CNH move is significant
        btc_contrib  = _to_score(-btc_5d, 5.0)  # BTC inverted

        # Level-based boost: gold near 252-day high = structural safe-haven demand
        level_boost = (gold_rank_pct - 50.0) * 0.2  # ±10 pts max

        risk_off = (gold_contrib * 0.45 + fx_contrib * 0.35 + btc_contrib * 0.20 + level_boost)
        risk_off = max(0.0, min(100.0, risk_off))

        # ─── risk_on_score (0–100) ──────────────────────────────────────────
        # Higher when:
        #   BTC is rising (risk appetite)
        #   CNH is strengthening (USD/CNH falling = capital inflow)
        #   gold is falling
        btc_contrib_on  = _to_score(btc_5d,   5.0)
        fx_contrib_on   = _to_score(-fx_5d,   1.0)  # inverted
        gold_contrib_on = _to_score(-gold_5d, 3.0)  # inverted

        # Level-based boost: BTC near 252-day high = structural risk-on
        btc_level_boost = (btc_rank_pct - 50.0) * 0.2

        risk_on = (btc_contrib_on * 0.50 + fx_contrib_on * 0.30 + gold_contrib_on * 0.20
                   + btc_level_boost)
        risk_on = max(0.0, min(100.0, risk_on))

        # ─── macro_env_score (-100 to +100) ─────────────────────────────────
        # Simple: risk_on_score - risk_off_score, scaled to [-100, +100]
        # Positive = net risk-on environment; negative = net risk-off
        macro = risk_on - risk_off

        return {
            "risk_off_score":  round(risk_off, 1),
            "risk_on_score":   round(risk_on, 1),
            "macro_env_score": round(macro, 1),
            "date":            latest_date,
            # Raw inputs for transparency
            "gold_5d_pct":     round(gold_5d, 3),
            "btc_5d_pct":      round(btc_5d, 3),
            "fx_cnh_5d_pct":   round(fx_5d, 3),
            "gold_level_pct":  round(gold_rank_pct, 1),
            "btc_level_pct":   round(btc_rank_pct, 1),
        }

    def latest(self) -> dict:
        """Convenience: compute scores as of the latest available data."""
        return self.compute()

    def history(self, lookback_days: int = 90) -> pd.DataFrame:
        """Compute rolling macro scores for each trading day.

        Returns a DataFrame with columns:
            date, risk_off_score, risk_on_score, macro_env_score
        """
        gold = self._load("gold")
        if gold.empty:
            return pd.DataFrame()

        rows = []
        dates = gold["date"].tail(lookback_days).tolist()
        for d in dates:
            date_str = str(d)[:10]
            try:
                row = self.compute(as_of=date_str)
                rows.append(row)
            except Exception as exc:
                logger.debug("history compute failed at %s: %s", date_str, exc)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
