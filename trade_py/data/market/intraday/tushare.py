"""Tushare intraday minute quote fetcher.

Uses rt_min, which supports comma-separated ts_code values, so the real-time
lane can fetch watchlists in batches instead of one symbol per request.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class IntradaySyncSummary:
    requested_symbols: int
    api_calls: int
    rows_fetched: int
    symbols_saved: int
    start_time: str
    end_time: str
    freq: str
    provider: str = "tushare"
    degraded_reason: str = ""


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


def _symbol_code(symbol: str) -> str:
    return str(symbol or "").strip().upper().split(".", 1)[0]


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

    def _persist_grouped(self, grouped: dict[str, list[pd.DataFrame]], freq: str) -> int:
        saved = 0
        for symbol, frames in grouped.items():
            merged = pd.concat(frames, ignore_index=True)
            self._merge_and_save(symbol, merged, freq)
            saved += 1
        return saved

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

    @staticmethod
    def _parse_akshare_spot(raw: pd.DataFrame, symbols: list[str], freq: str, timestamp: str) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        work = raw.copy()
        work["代码"] = work["代码"].astype(str).str.zfill(6)
        ts = pd.to_datetime(timestamp, errors="coerce")
        if pd.isna(ts):
            ts = pd.Timestamp.now().floor("min")
        rows: list[dict[str, object]] = []
        mapping = {str(row["代码"]): row for _, row in work.iterrows()}
        for symbol in symbols:
            code = _symbol_code(symbol)
            row = mapping.get(code)
            if row is None:
                continue
            close = float(pd.to_numeric(row.get("最新价"), errors="coerce") or 0.0)
            prev_close = float(pd.to_numeric(row.get("昨收"), errors="coerce") or 0.0)
            open_px = float(pd.to_numeric(row.get("今开"), errors="coerce") or close or prev_close)
            high_px = float(pd.to_numeric(row.get("最高"), errors="coerce") or close or open_px)
            low_px = float(pd.to_numeric(row.get("最低"), errors="coerce") or close or open_px)
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": ts,
                    "date": ts.strftime("%Y-%m-%d"),
                    "freq": str(freq).upper(),
                    "open": open_px,
                    "high": high_px,
                    "low": low_px,
                    "close": close or open_px,
                    "volume": float(pd.to_numeric(row.get("成交量"), errors="coerce") or 0.0),
                    "amount": float(pd.to_numeric(row.get("成交额"), errors="coerce") or 0.0),
                }
            )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    def _fetch_akshare_spot_fallback(
        self,
        symbols: list[str],
        *,
        freq: str,
        end_time: str,
    ) -> tuple[dict[str, list[pd.DataFrame]], int]:
        import akshare as ak

        raw = ak.stock_zh_a_spot_em()
        parsed = self._parse_akshare_spot(raw, symbols, freq, end_time)
        grouped: dict[str, list[pd.DataFrame]] = defaultdict(list)
        if parsed.empty:
            return grouped, 0
        for symbol, frame in parsed.groupby("symbol", sort=False):
            grouped[symbol].append(frame.copy())
        return grouped, len(parsed)

    def _build_local_cache_fallback(
        self,
        symbols: list[str],
        *,
        freq: str,
        end_time: str,
    ) -> tuple[dict[str, list[pd.DataFrame]], int]:
        ts = pd.to_datetime(end_time, errors="coerce")
        if pd.isna(ts):
            ts = pd.Timestamp.now().floor("min")
        grouped: dict[str, list[pd.DataFrame]] = defaultdict(list)
        count = 0
        for symbol in symbols:
            frame = self.load(symbol, freq=freq)
            if frame.empty:
                continue
            latest = frame.sort_values("timestamp").iloc[-1].to_dict()
            latest["timestamp"] = ts
            latest["date"] = ts.strftime("%Y-%m-%d")
            latest["freq"] = str(freq).upper()
            latest["volume"] = 0.0
            latest["amount"] = 0.0
            grouped[symbol].append(pd.DataFrame([latest]))
            count += 1
        return grouped, count

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
        from trade_py.data.market.tushare_client import (
            TushareAuthError,
            TushareError,
            TusharePermissionError,
            TushareRateLimitError,
            TushareTransientError,
            get_pro_api,
        )

        ts_codes = _normalize_ts_codes(symbols)
        if not ts_codes:
            start_s, end_s = _default_window(lookback_minutes)
            return IntradaySyncSummary(0, 0, 0, 0, start_s, end_s, str(freq).upper())

        start_s = start_time or _default_window(lookback_minutes)[0]
        end_s = end_time or _default_window(lookback_minutes)[1]
        grouped: dict[str, list[pd.DataFrame]] = defaultdict(list)
        api_calls = 0
        rows_fetched = 0
        provider = "tushare"
        degraded_reason = ""

        try:
            pro = get_pro_api(self.data_root)
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
        except (TushareAuthError, TushareRateLimitError, TusharePermissionError, TushareTransientError, TushareError) as exc:
            provider = "akshare_spot"
            degraded_reason = f"tushare fallback: {exc}"
            logger.warning("intraday sync fallback to akshare spot: %s", exc)
            try:
                grouped, rows_fetched = self._fetch_akshare_spot_fallback(
                    ts_codes,
                    freq=freq,
                    end_time=end_s,
                )
                api_calls = 1 if rows_fetched else 0
            except Exception as fallback_exc:
                logger.warning("intraday sync fallback to local cache: %s", fallback_exc)
                provider = "local_cache"
                degraded_reason = f"{degraded_reason}; akshare fallback failed: {fallback_exc}"
                grouped, rows_fetched = self._build_local_cache_fallback(
                    ts_codes,
                    freq=freq,
                    end_time=end_s,
                )
                api_calls = 0

        saved = self._persist_grouped(grouped, freq)

        return IntradaySyncSummary(
            requested_symbols=len(ts_codes),
            api_calls=api_calls,
            rows_fetched=rows_fetched,
            symbols_saved=saved,
            start_time=start_s,
            end_time=end_s,
            freq=str(freq).upper(),
            provider=provider,
            degraded_reason=degraded_reason,
        )
