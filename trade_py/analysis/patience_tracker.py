"""Patience tracker — waiting cost calculator.

Tracks the opportunity cost of *waiting* for a trading setup.  When a trader
spots a potential opportunity but does not act yet (e.g. waiting for a
confirmation candle or a better entry), this module answers:

  1. How long has the position been in the watchlist?
  2. What is the price drift since the initial watch date?
  3. What is the estimated opportunity cost vs a benchmark (CSI 300 proxy)?
  4. Is the wait still justified given decaying signal purity?

Usage:
    from trade_py.analysis.patience_tracker import PatienceTracker
    tracker = PatienceTracker("data")
    tracker.record("600036.SH", watch_date="2026-02-01", entry_target=12.50,
                   trigger="breakout above 12.5")
    cost = tracker.cost("600036.SH")
    # {'days_waited': 28, 'price_drift_pct': -3.2, 'opp_cost_vs_bench': -1.1, ...}
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_WATCHLIST_FILE = ".metadata/patience_watchlist.json"
_BENCHMARK = "000300.SH"   # CSI 300 proxy for opportunity cost


class PatienceTracker:
    """Track opportunity cost of waiting for confirmed entries.

    Persistence:
        Records are stored in ``{data_root}/.metadata/patience_watchlist.json``
        as a JSON dict keyed by symbol.
    """

    def __init__(self, data_root: str | Path = "data") -> None:
        self._root = Path(data_root)
        self._file = self._root / _WATCHLIST_FILE
        self._file.parent.mkdir(parents=True, exist_ok=True)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self._file.exists():
            return {}
        try:
            return json.loads(self._file.read_text())
        except Exception as exc:
            logger.warning("PatienceTracker: failed to load watchlist: %s", exc)
            return {}

    def _save(self, data: dict) -> None:
        self._file.write_text(json.dumps(data, indent=2, default=str))

    # ── Record management ─────────────────────────────────────────────────────

    def record(self,
               symbol: str,
               watch_date: str | date,
               entry_target: float,
               trigger: str = "",
               signal_score: float = 0.0) -> None:
        """Add or update a patience watch record.

        Args:
            symbol:       Stock code e.g. "600036.SH"
            watch_date:   Date the opportunity was first identified (ISO str or date)
            entry_target: Target entry price
            trigger:      Human-readable entry trigger condition
            signal_score: Signal quality score at watch time (0-100)
        """
        data = self._load()
        data[symbol] = {
            "symbol":        symbol,
            "watch_date":    str(watch_date)[:10],
            "entry_target":  entry_target,
            "trigger":       trigger,
            "signal_score":  signal_score,
            "recorded_at":   datetime.now().isoformat()[:19],
        }
        self._save(data)
        logger.info("PatienceTracker: recorded watch for %s at %.2f (target=%.2f)",
                    symbol, entry_target, entry_target)

    def remove(self, symbol: str) -> None:
        """Remove a watch record (e.g. after entry or abort)."""
        data = self._load()
        if symbol in data:
            del data[symbol]
            self._save(data)

    def all_records(self) -> dict[str, dict]:
        """Return all current watch records."""
        return self._load()

    # ── Kline helpers ─────────────────────────────────────────────────────────

    def _latest_close(self, symbol: str,
                      as_of: date | None = None) -> Optional[float]:
        """Return the latest close price for a symbol from local parquets."""
        kline_dir = self._root / "kline"
        if not kline_dir.exists():
            return None
        frames = []
        safe = symbol.replace(".", "_") + ".parquet"
        for month_dir in sorted(kline_dir.iterdir()):
            p = month_dir / safe
            if p.exists():
                frames.append(pd.read_parquet(p, columns=["date", "close"]))
        if not frames:
            return None
        df = pd.concat(frames, ignore_index=True)
        df["date"] = pd.to_datetime(df["date"])
        if as_of:
            df = df[df["date"] <= pd.Timestamp(as_of)]
        if df.empty:
            return None
        return float(df.sort_values("date").iloc[-1]["close"])

    def _close_on(self, symbol: str, on_date: date) -> Optional[float]:
        """Return close on or just before a specific date."""
        return self._latest_close(symbol, as_of=on_date)

    # ── Opportunity cost ──────────────────────────────────────────────────────

    def _benchmark_return(self, from_date: date, to_date: date) -> float:
        """Return benchmark return (fraction) from from_date to to_date.

        Uses CSI 300 proxy (000300.SH) kline data.  Falls back to 0.0 if data
        unavailable.
        """
        c0 = self._close_on(_BENCHMARK, from_date)
        c1 = self._latest_close(_BENCHMARK, as_of=to_date)
        if c0 and c1 and c0 > 1e-6:
            return (c1 - c0) / c0
        return 0.0

    # ── Cost computation ──────────────────────────────────────────────────────

    def cost(self, symbol: str,
             as_of: str | date | None = None) -> dict:
        """Compute the current waiting cost for a symbol.

        Args:
            symbol: Stock code
            as_of:  Reference date (defaults to today)

        Returns:
            dict with keys:
                days_waited          : int, calendar days since watch_date
                price_drift_pct      : float, price change since watch date (%)
                opp_cost_vs_bench    : float, price_drift - benchmark return (%)
                signal_decay         : float in [0,1], decayed signal score
                    (exponential decay: half-life = 15 trading days ≈ 21 cal days)
                entry_gap_pct        : float, (current_price - entry_target) / entry_target (%)
                verdict              : str, "WAIT" / "ABORT" / "ENTER"
        """
        records = self._load()
        if symbol not in records:
            return {"error": f"No watch record for {symbol}"}

        rec = records[symbol]
        watch_date = date.fromisoformat(rec["watch_date"])
        ref_date = date.fromisoformat(str(as_of)[:10]) if as_of else date.today()
        days_waited = (ref_date - watch_date).days

        entry_target = float(rec["entry_target"])
        signal_score_0 = float(rec.get("signal_score", 50.0))

        # Price drift since watch
        price_watch = self._close_on(symbol, watch_date)
        price_now   = self._latest_close(symbol, as_of=ref_date)
        price_drift = 0.0
        if price_watch and price_now and price_watch > 1e-6:
            price_drift = (price_now - price_watch) / price_watch * 100.0

        # Opportunity cost vs benchmark
        bench_ret = self._benchmark_return(watch_date, ref_date) * 100.0
        opp_cost  = price_drift - bench_ret

        # Signal decay: half-life = 21 calendar days
        HALF_LIFE_DAYS = 21.0
        decay_factor = 0.5 ** (days_waited / HALF_LIFE_DAYS)
        decayed_score = signal_score_0 * decay_factor

        # Entry gap
        entry_gap = 0.0
        if price_now and entry_target > 1e-6:
            entry_gap = (price_now - entry_target) / entry_target * 100.0

        # Simple verdict heuristic
        if decayed_score < 25 or days_waited > 60:
            verdict = "ABORT"
        elif abs(entry_gap) < 1.0:   # within 1% of target → enter
            verdict = "ENTER"
        else:
            verdict = "WAIT"

        return {
            "symbol":             symbol,
            "watch_date":         rec["watch_date"],
            "days_waited":        days_waited,
            "price_drift_pct":    round(price_drift, 2),
            "opp_cost_vs_bench":  round(opp_cost, 2),
            "signal_decay":       round(decay_factor, 3),
            "decayed_score":      round(decayed_score, 1),
            "entry_gap_pct":      round(entry_gap, 2),
            "entry_target":       entry_target,
            "current_price":      round(price_now, 2) if price_now else None,
            "trigger":            rec.get("trigger", ""),
            "verdict":            verdict,
        }

    def cost_all(self, as_of: str | date | None = None) -> list[dict]:
        """Return cost analysis for all watched symbols, sorted by days_waited."""
        results = []
        for sym in self._load():
            c = self.cost(sym, as_of=as_of)
            if "error" not in c:
                results.append(c)
        return sorted(results, key=lambda x: x["days_waited"], reverse=True)

    def report(self, as_of: str | date | None = None) -> str:
        """Return a human-readable patience report as a Markdown string."""
        costs = self.cost_all(as_of=as_of)
        if not costs:
            return "## 等待成本报告\n\n暂无自选标的。\n"

        lines = ["## 等待成本报告\n"]
        lines.append(f"| 代码 | 等待天数 | 价格漂移% | 相对基准% | 信号衰减 | 条目差距% | 判决 |")
        lines.append("|------|---------|----------|----------|---------|---------|------|")
        for c in costs:
            lines.append(
                f"| {c['symbol']} | {c['days_waited']} "
                f"| {c['price_drift_pct']:+.1f}% "
                f"| {c['opp_cost_vs_bench']:+.1f}% "
                f"| {c['signal_decay']:.2f} "
                f"| {c['entry_gap_pct']:+.1f}% "
                f"| **{c['verdict']}** |"
            )
        return "\n".join(lines)
