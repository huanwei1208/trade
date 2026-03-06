"""Regulatory tone monitor for A-share market.

Scans recently cached sentiment data for regulatory/policy tone signals and
produces a composite tightening/easing score.  The monitor helps flag periods
of elevated regulatory risk that the base ML model cannot detect from price
data alone.

Algorithm:
  1. Load the last N days of Gold-layer sentiment parquets for the market
  2. Classify each article as regulatory-related using keyword matching
  3. Compute rolling tightening vs easing ratio
  4. Derive tone_score: -100 (max tightening) to +100 (max easing)

Keyword taxonomy (expandable):
  TIGHTENING: 监管、处罚、限制、停牌、整改、违规、罚款、退市、风险警示、暂停
  EASING:     利好、刺激、降准、降息、扩大开放、支持、鼓励、政策红利、减税、补贴

Usage:
    from trade_py.signals.regulatory_tone_monitor import RegulatoryToneMonitor
    mon = RegulatoryToneMonitor("data")
    result = mon.latest()
    # {'tone_score': -15.2, 'tightening_count': 8, 'easing_count': 5,
    #  'recent_articles': [...], 'date': '2026-03-01'}
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Keyword sets ──────────────────────────────────────────────────────────────
_TIGHTENING_KEYWORDS = [
    "监管", "处罚", "限制", "停牌", "整改", "违规", "罚款", "退市",
    "风险警示", "暂停", "调查", "惩处", "收紧", "去杠杆", "限贷",
    "整治", "约谈", "警告", "禁止", "核查",
]

_EASING_KEYWORDS = [
    "利好", "刺激", "降准", "降息", "扩大开放", "支持发展", "鼓励",
    "政策红利", "减税", "补贴", "宽松", "支持", "扶持", "放开",
    "促进", "激活", "优化", "改善", "便利化",
]

# Regulatory-relevant headline markers (a headline without these is probably
# not a regulatory event even if it contains generic keywords)
_REG_MARKERS = [
    "证监会", "银监会", "银保监", "国资委", "发改委", "央行", "财政部",
    "国家金融监管总局", "中国证监会", "监管层", "政策", "国务院", "部委",
    "规定", "法规", "条例", "意见", "通知", "公告",
]

_REG_PATTERN    = re.compile("|".join(_REG_MARKERS))
_TIGHT_PATTERN  = re.compile("|".join(_TIGHTENING_KEYWORDS))
_EASE_PATTERN   = re.compile("|".join(_EASING_KEYWORDS))


def _classify(text: str) -> Optional[str]:
    """Classify a text snippet as 'tightening', 'easing', or None.

    Returns None if not regulatory-relevant.
    """
    if not text or not _REG_PATTERN.search(text):
        return None
    tight = bool(_TIGHT_PATTERN.search(text))
    ease  = bool(_EASE_PATTERN.search(text))
    if tight and not ease:
        return "tightening"
    if ease and not tight:
        return "easing"
    if tight and ease:
        # Mixed signal — count both keywords and return the dominant one
        tc = sum(1 for kw in _TIGHTENING_KEYWORDS if kw in text)
        ec = sum(1 for kw in _EASING_KEYWORDS if kw in text)
        return "tightening" if tc >= ec else "easing"
    return None


class RegulatoryToneMonitor:
    """Compute regulatory tone from cached Gold-layer sentiment parquets.

    The monitor reads sentiment data from:
        {data_root}/sentiment/gold/**/*.parquet

    Each parquet is expected to have at least a ``headline`` (or ``title``)
    text column and a ``date`` column.
    """

    def __init__(self, data_root: str | Path = "data") -> None:
        self._root = Path(data_root)
        self._gold_dir = self._root / "sentiment" / "gold"

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_headlines(self, from_date: date, to_date: date) -> list[dict]:
        """Load headline rows from Gold parquets within the date range."""
        if not self._gold_dir.exists():
            return []

        frames = []
        for p in sorted(self._gold_dir.rglob("*.parquet")):
            try:
                df = pd.read_parquet(p)
                if "date" not in df.columns:
                    continue
                df["date"] = pd.to_datetime(df["date"])
                mask = (df["date"] >= pd.Timestamp(from_date)) & \
                       (df["date"] <= pd.Timestamp(to_date))
                sub = df[mask]
                if not sub.empty:
                    frames.append(sub)
            except Exception as exc:
                logger.debug("RegulatoryToneMonitor: skip %s: %s", p, exc)

        if not frames:
            return []

        combined = pd.concat(frames, ignore_index=True)

        # Normalize text column name
        text_col = None
        for candidate in ("headline", "title", "summary", "text", "content"):
            if candidate in combined.columns:
                text_col = candidate
                break
        if text_col is None:
            logger.debug("RegulatoryToneMonitor: no text column found")
            return []

        combined["_text"] = combined[text_col].fillna("").astype(str)
        return combined[["date", "_text"]].to_dict(orient="records")

    # ── Tone computation ──────────────────────────────────────────────────────

    def compute(self, lookback_days: int = 30,
                as_of: str | date | None = None) -> dict:
        """Compute the regulatory tone score for the most recent window.

        Args:
            lookback_days: Number of calendar days to analyse (default 30)
            as_of:         Reference date (defaults to today)

        Returns:
            dict with keys:
                tone_score       : float -100 to +100 (+ = easing, - = tightening)
                tightening_count : int
                easing_count     : int
                neutral_reg_count: int  (regulatory but neither tight nor easy)
                daily_scores     : dict[str, float]  date → daily tone score
                recent_articles  : list of last 5 classified snippets
                date             : str  reference date
        """
        ref_date = date.fromisoformat(str(as_of)[:10]) if as_of else date.today()
        from_date = ref_date - timedelta(days=lookback_days)

        headlines = self._load_headlines(from_date, ref_date)

        tightening_count = 0
        easing_count = 0
        neutral_reg_count = 0
        daily: defaultdict[str, dict[str, int]] = defaultdict(
            lambda: {"t": 0, "e": 0})
        recent: list[dict] = []

        for row in headlines:
            text = row["_text"]
            cls  = _classify(text)
            d    = str(row["date"])[:10]
            if cls == "tightening":
                tightening_count += 1
                daily[d]["t"] += 1
            elif cls == "easing":
                easing_count += 1
                daily[d]["e"] += 1
            elif _REG_PATTERN.search(text):
                neutral_reg_count += 1

            if cls is not None and len(recent) < 5:
                recent.append({"date": d, "tone": cls,
                               "text": text[:80] + ("…" if len(text) > 80 else "")})

        # tone_score: (+easing - tightening) / total × 100
        total = tightening_count + easing_count
        if total == 0:
            tone_score = 0.0
        else:
            tone_score = (easing_count - tightening_count) / total * 100.0

        # Daily scores
        daily_scores: dict[str, float] = {}
        for d, counts in sorted(daily.items()):
            t, e = counts["t"], counts["e"]
            tot = t + e
            daily_scores[d] = (e - t) / tot * 100.0 if tot > 0 else 0.0

        # Trend: 7-day vs full-window slope
        recent_dates = sorted(daily_scores)[-7:]
        recent_avg = (sum(daily_scores[d] for d in recent_dates) / len(recent_dates)
                      if recent_dates else 0.0)
        trend = "tightening" if recent_avg < -10 else \
                "easing"     if recent_avg >  10 else "neutral"

        return {
            "tone_score":        round(tone_score, 1),
            "tightening_count":  tightening_count,
            "easing_count":      easing_count,
            "neutral_reg_count": neutral_reg_count,
            "trend":             trend,
            "recent_7d_avg":     round(recent_avg, 1),
            "daily_scores":      daily_scores,
            "recent_articles":   recent,
            "date":              str(ref_date),
        }

    def latest(self, lookback_days: int = 30) -> dict:
        """Convenience: compute tone as of today."""
        return self.compute(lookback_days=lookback_days)

    def is_tightening(self, threshold: float = -20.0,
                      lookback_days: int = 14) -> bool:
        """Return True if recent regulatory tone is significantly tightening.

        Args:
            threshold:     tone_score below this → tightening (default -20)
            lookback_days: window size for computation (default 14 days)
        """
        result = self.compute(lookback_days=lookback_days)
        return result["tone_score"] < threshold

    def history(self, lookback_days: int = 90) -> pd.DataFrame:
        """Return a DataFrame of daily tone scores for the past N days."""
        result = self.compute(lookback_days=lookback_days)
        daily = result["daily_scores"]
        if not daily:
            return pd.DataFrame(columns=["date", "tone_score"])
        df = pd.DataFrame([
            {"date": pd.Timestamp(d), "tone_score": s}
            for d, s in sorted(daily.items())
        ])
        return df
