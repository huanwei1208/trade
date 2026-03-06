"""Label builder for the event propagation prediction model.

Computes multi-horizon labels for (event, symbol) training pairs:
  - return_5d, return_20d, return_60d  : excess return vs benchmark
  - p_loss_5pct_20d                    : did price drop >5% within 20 days?
  - p_drawdown_20pct                   : did price drawdown >20% within 60 days?
  - max_drawdown_20d                   : maximum drawdown over 20 trading days

Labels are aligned to the event date (T=0) and look forward.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Default benchmark symbol (Shanghai Composite proxy)
DEFAULT_BENCHMARK = "000001.SH"


@dataclass
class Labels:
    """Multi-horizon return and risk labels for one (event, symbol) pair."""
    event_id:   str
    symbol:     str
    date:       str

    # Return labels (excess return vs benchmark)
    return_5d:  Optional[float] = None  # (P_5 - P_0) / P_0 - benchmark_5d
    return_20d: Optional[float] = None
    return_60d: Optional[float] = None

    # Risk labels (binary classifiers)
    loss_5pct_20d:   Optional[int] = None   # 1 if price dropped >5% within 20d
    drawdown_20pct:  Optional[int] = None   # 1 if drawdown >20% within 60d

    # Auxiliary
    max_drawdown_20d: Optional[float] = None
    max_drawdown_60d: Optional[float] = None

    def is_complete(self, horizon: int = 20) -> bool:
        """True if essential labels for the given horizon are available."""
        if horizon <= 5:
            return self.return_5d is not None
        if horizon <= 20:
            return self.return_20d is not None
        return self.return_60d is not None

    def to_dict(self) -> dict:
        return {
            "event_id":       self.event_id,
            "symbol":         self.symbol,
            "date":           self.date,
            "return_5d":      self.return_5d,
            "return_20d":     self.return_20d,
            "return_60d":     self.return_60d,
            "loss_5pct_20d":  self.loss_5pct_20d,
            "drawdown_20pct": self.drawdown_20pct,
            "max_drawdown_20d": self.max_drawdown_20d,
            "max_drawdown_60d": self.max_drawdown_60d,
        }


class LabelBuilder:
    """Builds multi-horizon return and risk labels.

    Args:
        data_root: Path to data directory (contains kline/ parquet files).
        benchmark_symbol: Symbol used as market benchmark.
    """

    def __init__(self, data_root: str | Path,
                 benchmark_symbol: str = DEFAULT_BENCHMARK) -> None:
        self._root = Path(data_root)
        self._benchmark = benchmark_symbol
        self._price_cache: dict[str, pd.Series] = {}  # symbol → date-indexed close series

    # ── Private helpers ────────────────────────────────────────────────────────

    def _load_price_series(self, symbol: str,
                           start: date, end: date) -> Optional[pd.Series]:
        """Load daily close prices as a date-indexed Series."""
        cache_key = f"{symbol}:{start}:{end}"
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]

        import duckdb
        kline_glob = str(self._root / "kline" / "**" / "*.parquet")
        try:
            con = duckdb.connect()
            df = con.execute(f"""
                SELECT date, close
                FROM read_parquet('{kline_glob}', union_by_name=true)
                WHERE symbol = '{symbol}'
                  AND date >= '{start.isoformat()}'
                  AND date <= '{end.isoformat()}'
                ORDER BY date ASC
            """).df()
            con.close()
        except Exception as exc:
            logger.warning("LabelBuilder: price load failed for %s: %s", symbol, exc)
            return None

        if df.empty:
            return None

        df["date"] = pd.to_datetime(df["date"])
        series = df.set_index("date")["close"]
        self._price_cache[cache_key] = series
        return series

    @staticmethod
    def _forward_return(prices: pd.Series, t0: date, horizon_days: int) -> Optional[float]:
        """Compute return from t0 to t0+horizon_days (in calendar days, approx).

        Finds the next available trading day on or after the target date.
        """
        ts_t0 = pd.Timestamp(t0)
        after = prices[prices.index >= ts_t0]
        if after.empty:
            return None
        p0 = float(after.iloc[0])
        if p0 <= 0:
            return None

        # Find price ~horizon_days calendar days later
        ts_target = ts_t0 + pd.Timedelta(days=horizon_days)
        future = prices[prices.index >= ts_target]
        if future.empty:
            return None
        pn = float(future.iloc[0])
        return (pn - p0) / p0

    @staticmethod
    def _max_drawdown(prices: pd.Series, t0: date, horizon_days: int) -> Optional[float]:
        """Compute maximum drawdown from t0 over the next horizon_days calendar days."""
        ts_t0 = pd.Timestamp(t0)
        ts_end = ts_t0 + pd.Timedelta(days=horizon_days)
        window = prices[(prices.index >= ts_t0) & (prices.index <= ts_end)]
        if len(window) < 2:
            return None
        peak = float(window.iloc[0])
        max_dd = 0.0
        for p in window.values:
            if p > peak:
                peak = float(p)
            dd = (peak - float(p)) / peak
            max_dd = max(max_dd, dd)
        return max_dd

    # ── Public API ─────────────────────────────────────────────────────────────

    def compute(self, event, symbol: str) -> Optional[Labels]:
        """Compute labels for one (event, symbol) pair.

        Args:
            event: HistoricalEvent
            symbol: Stock code

        Returns:
            Labels or None if price data is unavailable.
        """
        t0 = event.event_date
        # Load prices for both stock and benchmark with enough forward buffer
        load_end = date(t0.year + 1, t0.month, t0.day) if t0.month < 12 \
                   else date(t0.year + 1, 12, 31)
        load_end = min(load_end, date.today())

        stock_prices = self._load_price_series(symbol, t0, load_end)
        bench_prices = self._load_price_series(self._benchmark, t0, load_end)

        if stock_prices is None or len(stock_prices) < 2:
            return None

        lbl = Labels(
            event_id=event.event_id,
            symbol=symbol,
            date=t0.isoformat(),
        )

        # ── Return labels ──────────────────────────────────────────────────
        for horizon, attr in [(5 * 2, "return_5d"),   # 5 trading days ≈ 7 cal days
                               (20 * 2, "return_20d"), # 20 trading days ≈ 28 cal days
                               (60 * 2, "return_60d")]:
            stock_ret = self._forward_return(stock_prices, t0, horizon)
            if stock_ret is None:
                continue
            bench_ret = 0.0
            if bench_prices is not None:
                br = self._forward_return(bench_prices, t0, horizon)
                if br is not None:
                    bench_ret = br
            setattr(lbl, attr, round(stock_ret - bench_ret, 6))

        # ── Risk labels ────────────────────────────────────────────────────
        # 20-day max drawdown
        dd20 = self._max_drawdown(stock_prices, t0, 40)  # 20 trading days ≈ 40 cal
        if dd20 is not None:
            lbl.max_drawdown_20d = round(dd20, 6)
            lbl.loss_5pct_20d = int(dd20 > 0.05)

        # 60-day max drawdown
        dd60 = self._max_drawdown(stock_prices, t0, 120)  # 60 trading days ≈ 120 cal
        if dd60 is not None:
            lbl.max_drawdown_60d = round(dd60, 6)
            lbl.drawdown_20pct = int(dd60 > 0.20)

        return lbl

    def build_batch(self,
                    events,         # list[HistoricalEvent]
                    symbols: list[str],
                    ) -> pd.DataFrame:
        """Build label DataFrame for all (event × symbol) pairs.

        Args:
            events: List of HistoricalEvent
            symbols: List of stock codes to compute labels for

        Returns:
            DataFrame with one row per (event, symbol) pair.
        """
        rows = []
        total = len(events) * len(symbols)
        done = 0
        for ev in events:
            for sym in symbols:
                lbl = self.compute(ev, sym)
                if lbl is not None:
                    rows.append(lbl.to_dict())
                done += 1
                if done % 500 == 0:
                    logger.info("LabelBuilder: %d/%d done", done, total)

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).reset_index(drop=True)

    def save(self, df: pd.DataFrame, output_path: Optional[str | Path] = None) -> Path:
        """Save label DataFrame to Parquet.

        Default path: {data_root}/events/propagation_labels.parquet
        """
        if output_path is None:
            output_path = self._root / "events" / "propagation_labels.parquet"
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        logger.info("LabelBuilder: saved %d rows to %s", len(df), path)
        return path
