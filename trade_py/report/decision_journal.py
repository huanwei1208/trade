"""Decision journal for recording and analysing trading decisions.

Implements the "Captain-First-Mate Protocol" from the plan (Section 13.1):
the user (captain) records each trade decision with its narrative thesis,
emotional state, and technical indicators. The journal then computes win-rate
statistics per decision type to build a personalised decision fingerprint.

Storage layout:
    {data_root}/journal/decisions.parquet
    {data_root}/journal/outcomes.parquet   (filled retrospectively)

Usage:
    journal = DecisionJournal("data")
    journal.log(
        symbol="600111.SH",
        action="buy",
        narrative="稀土叙事: 美国限制稀土出口，国内定价权提升",
        emotion="fearful_but_confident",
        indicators=["kdj_oversold", "narrative_density_rising"],
        amount=1000,
    )
    journal.record_outcome("600111.SH", entry_date, exit_price=35.2)
    report = journal.performance_report()
    fp     = journal.fingerprint()
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Emotion vocabulary (can be extended)
EMOTIONS = {
    "confident",
    "fearful_but_confident",
    "fearful",
    "greedy",
    "contrarian",
    "uncertain",
    "neutral",
}


class DecisionJournal:
    """Records trading decisions and tracks their performance outcomes.

    Each entry captures the full cognitive state at decision time:
    narrative thesis, emotional label, indicator signals, and position size.
    Retrospective outcomes are linked by symbol + entry_date for win-rate analysis.
    """

    _DECISIONS_FILE = "decisions.parquet"
    _OUTCOMES_FILE  = "outcomes.parquet"

    def __init__(self, data_root: str | Path) -> None:
        self._dir = Path(data_root) / "journal"
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── I/O helpers ───────────────────────────────────────────────────────────

    def _decisions_path(self) -> Path:
        return self._dir / self._DECISIONS_FILE

    def _outcomes_path(self) -> Path:
        return self._dir / self._OUTCOMES_FILE

    def _load_decisions(self) -> pd.DataFrame:
        p = self._decisions_path()
        if not p.exists():
            return pd.DataFrame(columns=[
                "decision_id", "symbol", "action", "entry_date", "narrative",
                "emotion", "indicators", "amount", "recorded_at",
            ])
        return pd.read_parquet(p)

    def _load_outcomes(self) -> pd.DataFrame:
        p = self._outcomes_path()
        if not p.exists():
            return pd.DataFrame(columns=[
                "decision_id", "exit_date", "exit_price",
                "entry_price", "pnl_pct", "recorded_at",
            ])
        return pd.read_parquet(p)

    # ── Core methods ──────────────────────────────────────────────────────────

    def log(
        self,
        symbol: str,
        action: str,
        narrative: str,
        emotion: str,
        indicators: list[str],
        amount: float,
        entry_date: Optional[date] = None,
        entry_price: Optional[float] = None,
    ) -> str:
        """Record a trading decision.

        Args:
            symbol:     Stock code (e.g. "600111.SH")
            action:     "buy", "sell", or "hold"
            narrative:  Natural-language description of the trade thesis
            emotion:    Emotional state label (see EMOTIONS vocabulary)
            indicators: Technical/signal indicators that drove the decision
            amount:     Position size (shares or CNY)
            entry_date: Trade date (defaults to today)
            entry_price: Entry price (optional, filled from kline if omitted)

        Returns:
            decision_id: Unique identifier for this decision
        """
        if action not in ("buy", "sell", "hold"):
            raise ValueError(f"action must be buy/sell/hold, got {action!r}")

        target_date = entry_date or date.today()
        key = f"{symbol}|{action}|{target_date.isoformat()}|{narrative[:40]}"
        decision_id = hashlib.sha1(key.encode()).hexdigest()[:12]

        new_row = pd.DataFrame([{
            "decision_id": decision_id,
            "symbol":      symbol,
            "action":      action,
            "entry_date":  target_date.isoformat(),
            "narrative":   narrative,
            "emotion":     emotion,
            "indicators":  "|".join(indicators),   # pipe-separated for Parquet compat
            "amount":      float(amount),
            "entry_price": float(entry_price) if entry_price is not None else None,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }])

        existing = self._load_decisions()
        # Replace if same decision_id exists (idempotent)
        existing = existing[existing["decision_id"] != decision_id]
        combined = pd.concat([existing, new_row], ignore_index=True)
        combined.to_parquet(self._decisions_path(), index=False)

        logger.info("DecisionJournal: logged %s %s %s (id=%s)",
                    action, symbol, target_date, decision_id)
        return decision_id

    def record_outcome(
        self,
        decision_id: str,
        exit_date: date,
        exit_price: float,
        entry_price: Optional[float] = None,
    ) -> None:
        """Link an outcome (exit price) to a previously logged decision.

        Args:
            decision_id: ID returned by log()
            exit_date:   Date position was closed
            exit_price:  Closing price
            entry_price: Override entry price (if not stored in decision)
        """
        decisions = self._load_decisions()
        match = decisions[decisions["decision_id"] == decision_id]
        if match.empty:
            raise KeyError(f"decision_id {decision_id!r} not found in journal")

        row = match.iloc[0]
        ep = entry_price or row.get("entry_price")
        pnl_pct: Optional[float] = None
        if ep is not None and float(ep) > 1e-10:
            direction = 1.0 if row["action"] == "buy" else -1.0
            pnl_pct = float((exit_price - float(ep)) / float(ep) * direction * 100.0)

        outcomes = self._load_outcomes()
        outcomes = outcomes[outcomes["decision_id"] != decision_id]
        new_row = pd.DataFrame([{
            "decision_id": decision_id,
            "exit_date":   exit_date.isoformat(),
            "exit_price":  float(exit_price),
            "entry_price": float(ep) if ep is not None else None,
            "pnl_pct":     pnl_pct,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }])
        combined = pd.concat([outcomes, new_row], ignore_index=True)
        combined.to_parquet(self._outcomes_path(), index=False)
        logger.info("DecisionJournal: outcome recorded for %s: PnL=%.2f%%",
                    decision_id, pnl_pct or 0.0)

    # ── Analytics ─────────────────────────────────────────────────────────────

    def performance_report(self) -> pd.DataFrame:
        """Compute win-rate statistics grouped by decision attributes.

        Returns a DataFrame with columns:
            group_key, group_value, n_trades, win_rate, avg_pnl_pct,
            median_pnl_pct, best_pnl_pct, worst_pnl_pct

        Grouped by: emotion, action, each indicator, narrative_prefix
        """
        decisions = self._load_decisions()
        outcomes  = self._load_outcomes()

        if decisions.empty or outcomes.empty:
            return pd.DataFrame()

        merged = decisions.merge(outcomes, on="decision_id", how="inner")
        if merged.empty or "pnl_pct" not in merged.columns:
            return pd.DataFrame()

        merged = merged.dropna(subset=["pnl_pct"])
        if merged.empty:
            return pd.DataFrame()

        def win_rate(series: pd.Series) -> float:
            return float((series > 0).mean())

        rows: list[dict] = []

        def add_group(key: str, col: "pd.Series[str]") -> None:
            for val, grp in merged.groupby(col):
                pnl = grp["pnl_pct"]
                rows.append({
                    "group_key":      key,
                    "group_value":    str(val),
                    "n_trades":       int(len(pnl)),
                    "win_rate":       round(win_rate(pnl), 4),
                    "avg_pnl_pct":    round(float(pnl.mean()), 2),
                    "median_pnl_pct": round(float(pnl.median()), 2),
                    "best_pnl_pct":   round(float(pnl.max()), 2),
                    "worst_pnl_pct":  round(float(pnl.min()), 2),
                })

        add_group("emotion", merged["emotion"])
        add_group("action",  merged["action"])

        # Per-indicator breakdown
        all_indicators: list[str] = []
        for row in merged["indicators"]:
            all_indicators.extend(str(row).split("|"))
        unique_indicators = sorted(set(all_indicators) - {""})
        for ind in unique_indicators:
            mask = merged["indicators"].str.contains(ind, regex=False, na=False)
            pnl = merged.loc[mask, "pnl_pct"]
            if len(pnl) > 0:
                rows.append({
                    "group_key":      "indicator",
                    "group_value":    ind,
                    "n_trades":       int(len(pnl)),
                    "win_rate":       round(win_rate(pnl), 4),
                    "avg_pnl_pct":    round(float(pnl.mean()), 2),
                    "median_pnl_pct": round(float(pnl.median()), 2),
                    "best_pnl_pct":   round(float(pnl.max()), 2),
                    "worst_pnl_pct":  round(float(pnl.min()), 2),
                })

        return pd.DataFrame(rows).sort_values(
            ["group_key", "win_rate"], ascending=[True, False]
        ).reset_index(drop=True)

    def fingerprint(self) -> dict:
        """Return the optimal decision-state fingerprint.

        Identifies the combination of emotion + indicators that historically
        produces the highest win-rate (min 2 trades, positive avg PnL).

        Returns a dict with:
            best_emotion: emotion label with highest win rate
            best_indicators: list of indicators with win_rate > 60%
            worst_emotions: emotion labels that consistently lose money
            total_trades: total number of recorded decisions with outcomes
            overall_win_rate: overall win rate across all decisions
        """
        report = self.performance_report()
        if report.empty:
            return {"message": "No outcomes recorded yet."}

        outcomes = self._load_outcomes().dropna(subset=["pnl_pct"])
        total = len(outcomes)
        overall_wr = float((outcomes["pnl_pct"] > 0).mean()) if total > 0 else 0.0

        emotions_df = report[report["group_key"] == "emotion"]
        indic_df    = report[report["group_key"] == "indicator"]

        best_emotion = ""
        if not emotions_df.empty:
            qualified = emotions_df[emotions_df["n_trades"] >= 2]
            if not qualified.empty:
                best_emotion = str(
                    qualified.sort_values("win_rate", ascending=False).iloc[0]["group_value"]
                )

        worst_emotions: list[str] = []
        if not emotions_df.empty:
            bad = emotions_df[
                (emotions_df["n_trades"] >= 2) & (emotions_df["avg_pnl_pct"] < 0)
            ]
            worst_emotions = bad["group_value"].tolist()

        best_indicators: list[str] = []
        if not indic_df.empty:
            good = indic_df[
                (indic_df["n_trades"] >= 2) & (indic_df["win_rate"] > 0.6)
            ]
            best_indicators = good.sort_values(
                "win_rate", ascending=False
            )["group_value"].tolist()

        return {
            "best_emotion":    best_emotion,
            "best_indicators": best_indicators,
            "worst_emotions":  worst_emotions,
            "total_trades":    total,
            "overall_win_rate": round(overall_wr, 4),
        }

    def recent(self, n: int = 10) -> pd.DataFrame:
        """Return the n most recent decisions with outcomes if available."""
        decisions = self._load_decisions()
        if decisions.empty:
            return pd.DataFrame()
        outcomes = self._load_outcomes()
        if not outcomes.empty:
            merged = decisions.merge(outcomes, on="decision_id", how="left")
        else:
            merged = decisions.copy()
        merged["entry_date"] = pd.to_datetime(merged["entry_date"])
        return merged.sort_values("entry_date", ascending=False).head(n).reset_index(drop=True)

    def __len__(self) -> int:
        return len(self._load_decisions())

    def __repr__(self) -> str:
        return f"DecisionJournal(n={len(self)}, dir={self._dir})"
