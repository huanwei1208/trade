from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import numpy as np
import pandas as pd

from trade_py.utils.a_share_symbols import ensure_a_share_symbol, infer_a_share_suffix
from trade_py.utils.retry import retry

logger = logging.getLogger(__name__)

_RETRY_DELAYS_SEC = (1.0, 3.0, 8.0)
_COLUMN_ORDER = [
    "symbol", "date", "open", "high", "low", "close",
    "volume", "amount", "turnover_rate", "prev_close", "vwap",
]


def _infer_suffix(code: str) -> str:
    return infer_a_share_suffix(code)


def ensure_symbol(code_or_symbol: str) -> str:
    return ensure_a_share_symbol(code_or_symbol)


def to_code(symbol: str) -> str:
    return ensure_symbol(symbol).split(".")[0]


def classify_fetch_error(exc: Exception) -> str:
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    if "timeout" in text or "timedout" in text or "timeout" in name:
        return "timeout"
    if "remote end closed connection" in text or "connection aborted" in text:
        return "upstream_disconnect"
    if "name or service not known" in text or "temporary failure in name resolution" in text:
        return "dns_failure"
    if "refused" in text:
        return "connection_refused"
    if "module not found" in text or "no module named" in text:
        return "provider_unavailable"
    return "unknown"


class KlineProvider(Protocol):
    name: str

    def fetch(self, symbol: str, start: str, end: str, adjust: str = "hfq") -> pd.DataFrame:
        ...


def _finalize_frame(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=_COLUMN_ORDER)

    out = df.copy()
    out["symbol"] = ensure_symbol(symbol)
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    for col in ["open", "close", "high", "low", "volume", "amount", "turnover_rate"]:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if "pct_chg" in out.columns:
        out["pct_chg"] = pd.to_numeric(out["pct_chg"], errors="coerce")
    if "prev_close" in out.columns:
        out["prev_close"] = pd.to_numeric(out["prev_close"], errors="coerce")

    out = out.sort_values("date").reset_index(drop=True)
    prev_close = out["prev_close"] if "prev_close" in out.columns else pd.Series(np.nan, index=out.index, dtype="float64")
    if "pct_chg" in out.columns:
        denominator = 1.0 + (out["pct_chg"] / 100.0)
        derived_prev = out["close"] / denominator.where(denominator.abs() > 1e-9)
        prev_close = prev_close.where(prev_close.notna() & (prev_close > 0), derived_prev)
    shifted_prev = out["close"].shift(1)
    prev_close = prev_close.where(prev_close.notna() & (prev_close > 0), shifted_prev)
    out["prev_close"] = pd.to_numeric(prev_close, errors="coerce").fillna(0.0)
    total_shares = out["volume"] * 100
    out["vwap"] = (out["amount"] / total_shares.where(total_shares > 0, other=float("nan"))).fillna(0.0)
    out = out.drop_duplicates(subset=["date"], keep="last")
    for col in _COLUMN_ORDER:
        if col not in out.columns:
            out[col] = 0.0
    return out[_COLUMN_ORDER]


class AkshareKlineProvider:
    name = "akshare"

    @staticmethod
    @retry(delays=_RETRY_DELAYS_SEC, on=(Exception,))
    def _fetch_raw(ak, code: str, start_ymd: str, end_ymd: str, adjust: str):
        return ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_ymd,
            end_date=end_ymd,
            adjust=adjust if adjust != "none" else "",
        )

    def fetch(self, symbol: str, start: str, end: str, adjust: str = "hfq") -> pd.DataFrame:
        import akshare as ak

        code = to_code(symbol)
        raw = self._fetch_raw(ak, code, start.replace("-", ""), end.replace("-", ""), adjust)
        if raw is None or raw.empty:
            return pd.DataFrame(columns=_COLUMN_ORDER)
        col_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "换手率": "turnover_rate",
            "涨跌幅": "pct_chg",
        }
        df = raw.rename(columns=col_map)
        keep = [c for c in col_map.values() if c in df.columns]
        return _finalize_frame(symbol, df[keep].copy())


class BaostockKlineProvider:
    name = "baostock"

    @staticmethod
    @retry(delays=_RETRY_DELAYS_SEC, on=(Exception,))
    def _query(bs, code: str, start: str, end: str, adjust: str):
        adjust_flag = {"hfq": "1", "qfq": "2", "none": "3", "": "3"}.get(adjust, "1")
        fields = "date,code,open,high,low,close,volume,amount,turn"
        return bs.query_history_k_data_plus(
            code,
            fields,
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag=adjust_flag,
        )

    def fetch(self, symbol: str, start: str, end: str, adjust: str = "hfq") -> pd.DataFrame:
        import baostock as bs

        sym = ensure_symbol(symbol)
        code = sym.split(".")[0]
        exch = "sh" if sym.endswith(".SH") else ("bj" if sym.endswith(".BJ") else "sz")
        login = bs.login()
        if getattr(login, "error_code", "0") != "0":
            raise RuntimeError(f"baostock login failed: {login.error_code} {login.error_msg}")
        try:
            rs = self._query(bs, f"{exch}.{code}", start, end, adjust)
            if getattr(rs, "error_code", "0") != "0":
                raise RuntimeError(f"baostock query failed: {rs.error_code} {rs.error_msg}")
            rows: list[list[str]] = []
            while rs.next():
                rows.append(rs.get_row_data())
        finally:
            try:
                bs.logout()
            except Exception:
                pass

        if not rows:
            return pd.DataFrame(columns=_COLUMN_ORDER)
        raw = pd.DataFrame(rows, columns=["date", "code", "open", "high", "low", "close", "volume", "amount", "turn"])
        raw = raw.rename(columns={"turn": "turnover_rate"})
        raw = raw[["date", "open", "high", "low", "close", "volume", "amount", "turnover_rate"]]
        return _finalize_frame(sym, raw)


class TencentKlineProvider:
    name = "tencent"

    def fetch(self, symbol: str, start: str, end: str, adjust: str = "hfq") -> pd.DataFrame:
        import requests

        sym = ensure_symbol(symbol)
        code = sym.split(".")[0]
        if sym.endswith(".SH"):
            prefix = "sh"
        elif sym.endswith(".SZ"):
            prefix = "sz"
        else:
            raise ValueError(f"tencent provider does not support symbol suffix: {sym}")
        adjust_key = {"qfq": "qfqday", "hfq": "hfqday", "none": "day", "": "day"}.get(adjust, "qfqday")
        param = f"{prefix}{code},day,{start},{end},640,{adjust if adjust != 'none' else ''}".rstrip(",")
        resp = requests.get(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param": param},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        data = ((payload.get("data") or {}).get(f"{prefix}{code}") or {})
        rows = data.get(adjust_key) or data.get("qfqday") or data.get("day") or []
        if not rows:
            return pd.DataFrame(columns=_COLUMN_ORDER)
        raw = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])
        for col in ("open", "close", "high", "low", "volume"):
            raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0.0)
        raw["amount"] = raw["volume"] * 100.0 * raw["close"]
        raw["turnover_rate"] = 0.0
        return _finalize_frame(sym, raw)


@dataclass
class FetchResult:
    df: pd.DataFrame
    provider: str
    error_kind: str | None = None
    error_message: str | None = None


class ProviderChain:
    def __init__(self, providers: list[KlineProvider]) -> None:
        self._providers = providers

    def fetch(self, symbol: str, start: str, end: str, adjust: str) -> FetchResult:
        last_error: Exception | None = None
        last_kind: str | None = None
        for provider in self._providers:
            try:
                df = provider.fetch(symbol=symbol, start=start, end=end, adjust=adjust)
                return FetchResult(df=df, provider=provider.name)
            except Exception as exc:
                kind = classify_fetch_error(exc)
                logger.warning(
                    "provider fetch failed provider=%s symbol=%s start=%s end=%s kind=%s error_type=%s error=%r",
                    provider.name, symbol, start, end, kind, type(exc).__name__, exc,
                )
                last_error = exc
                last_kind = kind
                continue
        return FetchResult(
            df=pd.DataFrame(columns=_COLUMN_ORDER),
            provider="none",
            error_kind=last_kind or "unknown",
            error_message=repr(last_error) if last_error is not None else "all providers failed",
        )


def build_provider_chain(provider: str, data_root: str = "data") -> ProviderChain:
    provider = (provider or "auto").lower()
    if provider == "akshare":
        return ProviderChain([AkshareKlineProvider()])
    if provider == "baostock":
        return ProviderChain([BaostockKlineProvider()])
    if provider == "tencent":
        return ProviderChain([TencentKlineProvider()])
    if provider == "tushare":
        from trade_py.data.market.kline.tushare import TushareKlineProvider
        return ProviderChain([TushareKlineProvider(data_root)])
    # auto: try Tushare first (primary), then akshare, then baostock
    try:
        from trade_py.data.market.kline.tushare import TushareKlineProvider
        return ProviderChain([
            TushareKlineProvider(data_root),
            AkshareKlineProvider(),
            TencentKlineProvider(),
            BaostockKlineProvider(),
        ])
    except Exception:
        return ProviderChain([AkshareKlineProvider(), TencentKlineProvider(), BaostockKlineProvider()])
