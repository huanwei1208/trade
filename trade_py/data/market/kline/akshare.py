"""A-share daily K-line fetcher using akshare.

Replaces the C++ EastMoney provider for OHLCV data collection.
Writes monthly-partitioned Parquet files compatible with the C++ ParquetReader.

Storage layout:  data/kline/YYYY-MM/{symbol}.parquet

Column order (must match C++ ParquetReader):
    symbol, date, open, high, low, close, volume, amount,
    turnover_rate, prev_close, vwap

Units:
    volume      : 手 (lots = 100 shares)  — akshare native unit, kept as-is
    amount      : 元 (CNY)                — akshare native unit, kept as-is
    vwap        : 元/股                    — computed as amount / (volume * 100)

Usage:
    fetcher = KlineFetcher("data")
    fetcher.fetch_instruments()
    fetcher.update("600000.SH")
    fetcher.update_all(start_fallback="2020-01-01")
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from trade_py.db.instruments_db import InstrumentsDB

logger = logging.getLogger(__name__)

# Watermark key constants (must be consistent across fetch calls)
_SOURCE = "akshare"
_DATASET = "kline"

# Parquet column order expected by C++ ParquetReader
_COLUMN_ORDER = [
    "symbol", "date", "open", "high", "low", "close",
    "volume", "amount", "turnover_rate", "prev_close", "vwap",
]


def _to_akshare_code(symbol: str) -> str:
    """Convert 'NNNNNN.SH' → '600000', stripping exchange suffix."""
    return symbol.split(".")[0]


def _infer_suffix(code: str) -> str:
    """Infer exchange suffix from 6-digit stock code.

    Rules:
        6/9 → Shanghai (.SH)
        0/2/3 → Shenzhen (.SZ)
        4/8 → Beijing (.BJ)
    """
    if code.startswith(("6", "9")):
        return ".SH"
    if code.startswith(("4", "8")):
        return ".BJ"
    return ".SZ"


def _ensure_symbol(code_or_symbol: str) -> str:
    """Return a canonical symbol with suffix (e.g. '600000.SH')."""
    if "." in code_or_symbol:
        return code_or_symbol
    return code_or_symbol + _infer_suffix(code_or_symbol)


class KlineFetcher:
    """Fetch and persist A-share daily K-line data via akshare.

    Args:
        data_root: Project data root directory (e.g. "data").
    """

    def __init__(self, data_root: str | Path = "data") -> None:
        self._data_root = Path(data_root)
        self._kline_root = self._data_root / "kline"
        self._kline_root.mkdir(parents=True, exist_ok=True)
        self._db = InstrumentsDB(data_root)

    # ── Fetch ──────────────────────────────────────────────────────────────

    def fetch(
        self,
        symbol: str,
        start: str,
        end: Optional[str] = None,
        adjust: str = "hfq",
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars for one symbol via akshare.

        Args:
            symbol:  Stock symbol with or without suffix, e.g. "600000.SH" or "600000"
            start:   Start date string "YYYY-MM-DD"
            end:     End date string "YYYY-MM-DD" (defaults to today)
            adjust:  Price adjustment type: "hfq" (back-adjusted), "qfq" (forward), "" (none)

        Returns:
            DataFrame with columns matching _COLUMN_ORDER, sorted ascending by date.
        """
        import akshare as ak  # lazy import to avoid mandatory dependency at module load

        symbol = _ensure_symbol(symbol)
        code = _to_akshare_code(symbol)
        end_str = end or date.today().isoformat()

        # akshare expects dates without hyphens for some APIs; use YYYY-MM-DD format
        try:
            raw = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start.replace("-", ""),
                end_date=end_str.replace("-", ""),
                adjust=adjust,
            )
        except Exception as exc:
            logger.warning("akshare fetch failed for %s [%s, %s]: %s", symbol, start, end_str, exc)
            return pd.DataFrame()

        if raw is None or raw.empty:
            return pd.DataFrame()

        # Rename columns from Chinese to English
        col_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",       # 手 (lots)
            "成交额": "amount",       # 元
            "换手率": "turnover_rate",
        }
        df = raw.rename(columns=col_map)

        # Keep only the columns we care about (ignore akshare extras like 振幅/涨跌幅...)
        keep = [c for c in col_map.values() if c in df.columns]
        df = df[keep].copy()

        # Ensure date is a proper date string YYYY-MM-DD
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        # Numeric coercion
        for col in ["open", "close", "high", "low", "volume", "amount", "turnover_rate"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        # prev_close: previous day's closing price (0 for first row)
        df = df.sort_values("date").reset_index(drop=True)
        df["prev_close"] = df["close"].shift(1).fillna(0.0)

        # vwap = amount / (volume * 100)  [元/股]
        total_shares = df["volume"] * 100
        df["vwap"] = (df["amount"] / total_shares.where(total_shares > 0, other=float("nan"))
                      ).fillna(0.0)

        # Add symbol column
        df["symbol"] = symbol

        # Ensure turnover_rate exists
        if "turnover_rate" not in df.columns:
            df["turnover_rate"] = 0.0

        # Reorder columns
        available = [c for c in _COLUMN_ORDER if c in df.columns]
        df = df[available]

        return df

    # ── Parquet I/O ────────────────────────────────────────────────────────

    def save_parquet(self, symbol: str, df: pd.DataFrame) -> None:
        """Persist a DataFrame to monthly-partitioned Parquet files.

        Merges new data with any existing Parquet file for the same month,
        deduplicating by date (latest value wins) and sorting ascending.

        Args:
            symbol: Full symbol e.g. "600000.SH"
            df:     DataFrame with at least "date" and "symbol" columns
        """
        if df.empty:
            return

        safe_sym = symbol.replace(".", "_")
        df = df.copy()
        df["_month"] = df["date"].str[:7]  # "YYYY-MM"

        for month, group in df.groupby("_month"):
            month_dir = self._kline_root / month
            month_dir.mkdir(parents=True, exist_ok=True)
            out_path = month_dir / f"{safe_sym}.parquet"

            group = group.drop(columns=["_month"])

            if out_path.exists():
                existing = pd.read_parquet(out_path)
                combined = pd.concat([existing, group], ignore_index=True)
                combined = combined.drop_duplicates(subset=["date"], keep="last")
            else:
                combined = group

            combined = combined.sort_values("date").reset_index(drop=True)

            # Enforce column order (add missing columns as 0)
            for col in _COLUMN_ORDER:
                if col not in combined.columns:
                    combined[col] = 0.0
            combined = combined[[c for c in _COLUMN_ORDER if c in combined.columns]]

            combined.to_parquet(out_path, index=False)

        logger.debug("Saved %d rows for %s", len(df), symbol)

    # ── Incremental update ─────────────────────────────────────────────────

    def update(
        self,
        symbol: str,
        start_fallback: str = "2020-01-01",
        adjust: str = "hfq",
    ) -> int:
        """Incrementally fetch new bars for one symbol and persist to Parquet.

        Uses the watermark table to determine the fetch start date.

        Args:
            symbol:         Stock symbol e.g. "600000.SH"
            start_fallback: Date to use when no watermark exists
            adjust:         akshare price adjustment mode

        Returns:
            Number of rows fetched and saved (0 if nothing new)
        """
        symbol = _ensure_symbol(symbol)
        wm = self._db.get_watermark(_SOURCE, _DATASET, symbol)
        if wm is not None:
            # Start from the day after the last watermark
            fetch_start = (wm + timedelta(days=1)).isoformat()
        else:
            fetch_start = start_fallback

        today = date.today().isoformat()
        if fetch_start > today:
            logger.debug("%s is already up to date (watermark=%s)", symbol, wm)
            return 0

        df = self.fetch(symbol, start=fetch_start, end=today, adjust=adjust)
        if df.empty:
            logger.info("No new data for %s since %s", symbol, fetch_start)
            return 0

        self.save_parquet(symbol, df)

        # Update watermark to the latest date in the fetched data
        latest_date = date.fromisoformat(df["date"].max())
        self._db.set_watermark(_SOURCE, _DATASET, symbol, latest_date)
        self._db.record_download(
            symbol,
            start=date.fromisoformat(df["date"].min()),
            end=latest_date,
            row_count=len(df),
        )
        logger.info("Updated %s: %d rows (%s → %s)", symbol, len(df), fetch_start, latest_date)
        return len(df)

    def update_all(
        self,
        symbols: Optional[list[str]] = None,
        start_fallback: str = "2020-01-01",
        delay_ms: int = 200,
    ) -> dict[str, int]:
        """Incrementally update all (or specified) symbols.

        Args:
            symbols:        List of symbols to update (defaults to all in DB)
            start_fallback: Fallback start date for symbols with no watermark
            delay_ms:       Delay in milliseconds between requests (rate limiting)

        Returns:
            Dict mapping symbol → rows fetched
        """
        if symbols is None:
            symbols = self._db.get_all_symbols()

        if not symbols:
            logger.warning("No symbols in database. Run fetch_instruments() first.")
            return {}

        results: dict[str, int] = {}
        for i, sym in enumerate(symbols, 1):
            try:
                n = self.update(sym, start_fallback=start_fallback)
                results[sym] = n
            except Exception as exc:
                logger.error("Failed to update %s: %s", sym, exc)
                results[sym] = -1
            if i < len(symbols) and delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

        total = sum(v for v in results.values() if v > 0)
        logger.info(
            "update_all done: %d/%d symbols, %d total new rows",
            len(results), len(symbols), total,
        )
        return results

    # ── Instrument list ────────────────────────────────────────────────────

    def fetch_instruments(self) -> list[tuple[str, str]]:
        """Fetch the full A-share instrument list from akshare and upsert to DB.

        Returns:
            List of (symbol, name) tuples for all A-share stocks
        """
        import akshare as ak

        try:
            raw = ak.stock_info_a_code_name()
        except Exception as exc:
            logger.error("akshare fetch_instruments failed: %s", exc)
            return []

        if raw is None or raw.empty:
            return []

        result: list[tuple[str, str]] = []
        for _, row in raw.iterrows():
            code = str(row.get("code", row.get("股票代码", ""))).strip()
            name = str(row.get("name", row.get("股票名称", ""))).strip()
            if not code or not name:
                continue
            symbol = code + _infer_suffix(code)
            self._db.upsert_instrument(symbol, name)
            result.append((symbol, name))

        logger.info("fetch_instruments: upserted %d instruments", len(result))
        return result
