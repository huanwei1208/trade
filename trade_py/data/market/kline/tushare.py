"""Tushare K-line provider for the ProviderChain.

Fetches daily OHLCV via tushare pro.daily() with back-adjustment.
Output schema matches the project standard (11 columns).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from trade_py.data.market.kline.providers import _COLUMN_ORDER, _finalize_frame, ensure_symbol

logger = logging.getLogger(__name__)


def _to_ts_code(symbol: str) -> str:
    """'600000.SH' → '600000.SH'  (Tushare uses the same dotted format)."""
    return ensure_symbol(symbol)


def _adj_value(adjust: str) -> str | None:
    return {"hfq": "hfq", "qfq": "qfq", "none": None}.get(adjust, "hfq")


def _fetch_raw_trade_date(trade_date: str, data_root: str, adjust: str = "hfq") -> pd.DataFrame:
    from trade_py.data.market.tushare_client import get_pro_api

    pro = get_pro_api(data_root)
    df = pro.call(
        "daily",
        trade_date=trade_date.replace("-", ""),
        adj=_adj_value(adjust),
    )
    return df if df is not None else pd.DataFrame()


def _fetch_raw_daily_basic_trade_date(trade_date: str, data_root: str) -> pd.DataFrame:
    from trade_py.data.market.tushare_client import get_pro_api

    pro = get_pro_api(data_root)
    df = pro.call(
        "daily_basic",
        trade_date=trade_date.replace("-", ""),
        fields="ts_code,trade_date,turnover_rate",
    )
    return df if df is not None else pd.DataFrame()


def _fetch_raw_daily_basic_range(ts_code: str, start: str, end: str, data_root: str) -> pd.DataFrame:
    from trade_py.data.market.tushare_client import get_pro_api

    pro = get_pro_api(data_root)
    df = pro.call(
        "daily_basic",
        ts_code=ts_code,
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
        fields="ts_code,trade_date,turnover_rate",
    )
    return df if df is not None else pd.DataFrame()


def _trade_dates(start: str, end: str) -> list[str]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts > end_ts:
        return []
    return [ts.strftime("%Y-%m-%d") for ts in pd.bdate_range(start_ts, end_ts)]


def _merge_daily_basic(raw: pd.DataFrame, basics: pd.DataFrame | None) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    merged = raw.copy()
    if "turnover_rate" in merged.columns:
        merged = merged.drop(columns=["turnover_rate"])
    if basics is not None and not basics.empty and {"ts_code", "trade_date"}.issubset(basics.columns):
        basis = basics.copy()
        basis["trade_date"] = basis["trade_date"].astype(str)
        merged["trade_date"] = merged["trade_date"].astype(str)
        merged = merged.merge(
            basis[["ts_code", "trade_date", "turnover_rate"]],
            on=["ts_code", "trade_date"],
            how="left",
            suffixes=("", "_basic"),
        )
    return merged


def _parse_raw(raw: pd.DataFrame, symbol: str, basics: pd.DataFrame | None = None) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=_COLUMN_ORDER)
    df = _merge_daily_basic(raw, basics)
    col_map = {
        "trade_date": "date",
        "vol": "volume",
        "amount": "amount",
        "pre_close": "prev_close",
        "pct_chg": "pct_chg",
    }
    df = df.rename(columns=col_map)
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0) * 1000.0
    if "turnover_rate" not in df.columns:
        df["turnover_rate"] = 0.0
    keep = [
        "date", "open", "high", "low", "close", "volume", "amount", "turnover_rate", "prev_close", "pct_chg",
    ]
    keep = [c for c in keep if c in df.columns]
    return _finalize_frame(symbol, df[keep].copy())


@dataclass
class TradeDateBatchResult:
    frames: dict[str, pd.DataFrame]
    api_calls: int
    trade_dates: int
    days_with_hits: int


class TushareKlineProvider:
    name = "tushare"

    def __init__(self, data_root: str = "data") -> None:
        self._data_root = data_root

    def fetch(self, symbol: str, start: str, end: str, adjust: str = "hfq") -> pd.DataFrame:
        from trade_py.data.market.tushare_client import get_pro_api

        pro = get_pro_api(self._data_root)
        ts_code = _to_ts_code(symbol)
        start_d = start.replace("-", "")
        end_d = end.replace("-", "")

        raw = pro.call(
            "daily",
            ts_code=ts_code,
            start_date=start_d,
            end_date=end_d,
            adj=_adj_value(adjust),
        )
        try:
            basics = _fetch_raw_daily_basic_range(ts_code, start, end, self._data_root)
        except Exception as exc:
            logger.warning("tushare daily_basic fallback disabled for %s %s..%s: %s", ts_code, start, end, exc)
            basics = None
        return _parse_raw(raw, symbol, basics=basics)

    def fetch_batch_by_trade_date(
        self,
        symbols: list[str],
        *,
        start: str | None = None,
        end: str | None = None,
        trade_dates: list[str] | None = None,
        adjust: str = "hfq",
    ) -> TradeDateBatchResult:
        normalized = [ensure_symbol(sym) for sym in symbols if str(sym).strip()]
        if not normalized:
            return TradeDateBatchResult(frames={}, api_calls=0, trade_dates=0, days_with_hits=0)
        dates = sorted(set(trade_dates or _trade_dates(start or "", end or "")))
        if not dates:
            return TradeDateBatchResult(frames={}, api_calls=0, trade_dates=0, days_with_hits=0)

        symbol_set = set(normalized)
        grouped: dict[str, list[pd.DataFrame]] = {}
        api_calls = 0
        day_hits = 0
        for trade_date in dates:
            raw = _fetch_raw_trade_date(trade_date, self._data_root, adjust=adjust)
            api_calls += 1
            if raw.empty or "ts_code" not in raw.columns:
                continue
            try:
                basics = _fetch_raw_daily_basic_trade_date(trade_date, self._data_root)
                api_calls += 1
            except Exception as exc:
                logger.warning("tushare daily_basic trade_date fallback disabled for %s: %s", trade_date, exc)
                basics = None
            filtered = raw[raw["ts_code"].astype(str).str.upper().isin(symbol_set)].copy()
            if filtered.empty:
                continue
            day_hits += 1
            for symbol, frame in filtered.groupby(filtered["ts_code"].astype(str).str.upper(), sort=False):
                if basics is not None and not basics.empty:
                    basic_frame = basics[basics["ts_code"].astype(str).str.upper() == symbol].copy()
                else:
                    basic_frame = None
                grouped.setdefault(symbol, []).append(_merge_daily_basic(frame.copy(), basic_frame))

        frames: dict[str, pd.DataFrame] = {}
        for symbol, frame_list in grouped.items():
            frames[symbol] = _parse_raw(pd.concat(frame_list, ignore_index=True), symbol)
        return TradeDateBatchResult(
            frames=frames,
            api_calls=api_calls,
            trade_dates=len(dates),
            days_with_hits=day_hits,
        )
