"""Tushare intraday minute quote fetcher.

Uses rt_min, which supports comma-separated ts_code values, so the real-time
lane can fetch watchlists in batches instead of one symbol per request.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


@dataclass
class IntradaySyncSummary:
    requested_symbols: int
    api_calls: int
    rows_fetched: int
    symbols_saved: int
    start_time: str
    end_time: str
    freq: str


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _normalize_ts_codes(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for symbol in symbols:
        code = str(symbol or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result


def _default_window(lookback_minutes: int = 30) -> tuple[str, str]:
    end = datetime.now().replace(second=0, microsecond=0)
    start = end - timedelta(minutes=max(1, lookback_minutes))
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


class TushareIntradayFetcher:
    def __init__(self, data_root: str | Path = "data") -> None:
        self.data_root = str(data_root)
        self._root = Path(data_root) / "market" / "intraday"
        self._root.mkdir(parents=True, exist_ok=True)

    def _freq_dir(self, freq: str) -> Path:
        safe = str(freq or "1MIN").strip().lower()
        path = self._root / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(self, symbol: str, freq: str) -> Path:
        return self._freq_dir(freq) / f"{symbol.replace('.', '_')}.parquet"

    def load(self, symbol: str, freq: str = "1MIN") -> pd.DataFrame:
        path = self._path(symbol, freq)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def _merge_and_save(self, symbol: str, frame: pd.DataFrame, freq: str) -> pd.DataFrame:
        path = self._path(symbol, freq)
        if path.exists():
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, frame], ignore_index=True)
            combined = combined.drop_duplicates(subset=["symbol", "timestamp"], keep="last")
        else:
            combined = frame.copy()
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        combined.to_parquet(path, index=False)
        return combined

    @staticmethod
    def _parse_frame(raw: pd.DataFrame, freq: str) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        work = raw.copy()
        if "ts_code" not in work.columns or "time" not in work.columns:
            return pd.DataFrame()
        work["symbol"] = work["ts_code"].astype(str).str.upper()
        work["timestamp"] = pd.to_datetime(work["time"], errors="coerce")
        work = work.dropna(subset=["timestamp"])
        work["date"] = work["timestamp"].dt.strftime("%Y-%m-%d")
        work["freq"] = str(freq).upper()
        for col in ("open", "close", "high", "low", "vol", "amount"):
            work[col] = pd.to_numeric(work.get(col), errors="coerce").fillna(0.0)
        work = work.rename(columns={"vol": "volume"})
        keep = ["symbol", "timestamp", "date", "freq", "open", "high", "low", "close", "volume", "amount"]
        return work[keep].sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    def fetch_batch(
        self,
        symbols: list[str],
        *,
        freq: str = "1MIN",
        start_time: str | None = None,
        end_time: str | None = None,
        lookback_minutes: int = 30,
        chunk_size: int = 50,
        asset: str = "E",
    ) -> IntradaySyncSummary:
        from trade_py.data.market.tushare_client import get_pro_api

        ts_codes = _normalize_ts_codes(symbols)
        if not ts_codes:
            start_s, end_s = _default_window(lookback_minutes)
            return IntradaySyncSummary(0, 0, 0, 0, start_s, end_s, str(freq).upper())

        start_s = start_time or _default_window(lookback_minutes)[0]
        end_s = end_time or _default_window(lookback_minutes)[1]
        pro = get_pro_api(self.data_root)
        grouped: dict[str, list[pd.DataFrame]] = defaultdict(list)
        api_calls = 0
        rows_fetched = 0

        for chunk in _chunked(ts_codes, max(1, int(chunk_size))):
            raw = pro.call(
                "rt_min",
                ts_code=",".join(chunk),
                asset=asset,
                freq=str(freq).upper(),
                start_time=start_s,
                end_time=end_s,
            )
            api_calls += 1
            if raw is None or raw.empty:
                continue
            rows_fetched += len(raw)
            parsed = self._parse_frame(raw, freq)
            if parsed.empty:
                continue
            for symbol, frame in parsed.groupby("symbol", sort=False):
                grouped[symbol].append(frame.copy())

        saved = 0
        for symbol, frames in grouped.items():
            merged = pd.concat(frames, ignore_index=True)
            self._merge_and_save(symbol, merged, freq)
            saved += 1

        return IntradaySyncSummary(
            requested_symbols=len(ts_codes),
            api_calls=api_calls,
            rows_fetched=rows_fetched,
            symbols_saved=saved,
            start_time=start_s,
            end_time=end_s,
            freq=str(freq).upper(),
        )
