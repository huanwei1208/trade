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


def _validate_ohlc_frame(symbol: str, df: pd.DataFrame) -> None:
    """Reject frames with NaN/non-positive/inconsistent OHLC prices.

    Mirrors the pattern used in trade_py/data/market/crypto/akshare.py.
    Rows that fail these checks indicate corrupted upstream data and must
    not be silently written to parquet.
    """
    if df is None or df.empty:
        return
    required = {"date", "open", "high", "low", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{symbol} kline OHLC data missing columns: {missing}")
    work = df.copy()
    for column in ("open", "high", "low", "close"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    invalid = work[
        work[["open", "high", "low", "close"]].isna().any(axis=1)
        | work[["open", "high", "low", "close"]].le(0).any(axis=1)
        | (work["high"] < work["low"])
        | (work["high"] < work["open"])
        | (work["high"] < work["close"])
        | (work["low"] > work["open"])
        | (work["low"] > work["close"])
    ].copy()
    if invalid.empty:
        return
    invalid["date"] = pd.to_datetime(invalid["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    sample = invalid[["date", "open", "high", "low", "close"]].head(5).to_dict(orient="records")
    start = str(invalid["date"].min())[:10]
    end = str(invalid["date"].max())[:10]
    raise ValueError(
        f"{symbol} kline OHLC data failed validation rows={len(invalid)} "
        f"dates={start}..{end} sample={sample}"
    )


def _finalize_frame(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=_COLUMN_ORDER)

    out = df.copy()
    out["symbol"] = ensure_symbol(symbol)
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    # Price columns: coerce but DO NOT fillna(0.0) — NaN means "bad/missing",
    # not "zero". Zero-prices poison downstream training.
    for col in ["open", "close", "high", "low"]:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")
    # Volume/amount/turnover_rate are volume-like; fillna(0) is acceptable for
    # non-trading days after coercion.
    for col in ["volume", "amount", "turnover_rate"]:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").to_numpy(dtype=float, na_value=0.0)
    if "pct_chg" in out.columns:
        out["pct_chg"] = pd.to_numeric(out["pct_chg"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    if "prev_close" in out.columns:
        out["prev_close"] = pd.to_numeric(out["prev_close"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)

    out = out.sort_values("date").reset_index(drop=True)
    prev_close = out["prev_close"] if "prev_close" in out.columns else pd.Series(np.nan, index=out.index, dtype="float64")
    if "pct_chg" in out.columns:
        out["pct_chg"] = pd.to_numeric(out["pct_chg"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        denominator = 1.0 + (out["pct_chg"] / 100.0)
        derived_prev = out["close"] / denominator.where(denominator.abs() > 1e-9)
        prev_close = prev_close.where(prev_close.notna() & (prev_close > 0), derived_prev)
    shifted_prev = out["close"].shift(1)
    prev_close = prev_close.where(prev_close.notna() & (prev_close > 0), shifted_prev)
    # prev_close is a price — leave NaN, do not zero-fill.
    out["prev_close"] = pd.to_numeric(prev_close, errors="coerce")
    total_shares = out["volume"] * 100
    # vwap = amount / total_shares; when volume==0, vwap must be NaN, not 0.
    out["vwap"] = out["amount"] / total_shares.where(total_shares > 0, other=float("nan"))

    # Drop rows that claim to be real trading days (volume > 0) but have NaN
    # prices in any OHLC column — these are parse/upstream failures that would
    # otherwise silently poison parquet.
    ohlc_cols = ["open", "high", "low", "close"]
    bad_mask = (out["volume"] > 0) & out[ohlc_cols].isna().any(axis=1)
    if bad_mask.any():
        bad_count = int(bad_mask.sum())
        bad_dates = out.loc[bad_mask, "date"].head(5).tolist()
        logger.warning(
            "Dropping %d corrupted kline rows for %s (volume>0 but NaN OHLC); sample dates=%s",
            bad_count, symbol, bad_dates,
        )
        out = out.loc[~bad_mask].reset_index(drop=True)

    out = out.drop_duplicates(subset=["date"], keep="last")
    # Strict OHLC validation: rejects any remaining NaN/non-positive/inconsistent
    # price rows so we never write poisoned data to parquet.
    _validate_ohlc_frame(symbol, out)
    for col in _COLUMN_ORDER:
        if col not in out.columns:
            # Non-price columns default to 0.0 on absence; price columns were
            # already validated above, so we only fill columns like
            # turnover_rate/prev_close/vwap that may be legitimately absent.
            if col in ("open", "high", "low", "close"):
                out[col] = np.nan
            else:
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


class SinaKlineProvider:
    name = "sina"

    @staticmethod
    @retry(delays=_RETRY_DELAYS_SEC, on=(Exception,))
    def _fetch_raw(ak, sina_code: str, start_ymd: str, end_ymd: str, adjust: str):
        return ak.stock_zh_a_daily(
            symbol=sina_code,
            start_date=start_ymd,
            end_date=end_ymd,
            adjust=adjust if adjust != "none" else "",
        )

    def fetch(self, symbol: str, start: str, end: str, adjust: str = "hfq") -> pd.DataFrame:
        import akshare as ak

        sym = ensure_symbol(symbol)
        sina_code = sym.split(".")[1].lower() + sym.split(".")[0]
        raw = self._fetch_raw(ak, sina_code, start.replace("-", ""), end.replace("-", ""), adjust)
        if raw is None or raw.empty:
            return pd.DataFrame(columns=_COLUMN_ORDER)
        df = raw.reset_index() if "date" not in raw.columns else raw.copy()
        # Sina volume is in shares; project convention (Eastmoney) is lots (手).
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce") / 100.0
        # Sina turnover is a fraction; project convention is percent.
        if "turnover" in df.columns:
            df["turnover_rate"] = pd.to_numeric(df["turnover"], errors="coerce") * 100.0
        keep = [c for c in ["date", "open", "high", "low", "close", "volume", "amount", "turnover_rate"] if c in df.columns]
        return _finalize_frame(sym, df[keep].copy())


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
        param = f"{prefix}{code},day,{start},{end},640,{adjust if adjust != 'none' else ''}"
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
        normalized_rows = []
        for row in rows:
            values = list(row)
            if len(values) < 6:
                continue
            normalized_rows.append(values[:7] if len(values) >= 7 else values[:6] + [None])
        raw = pd.DataFrame(normalized_rows, columns=["date", "open", "close", "high", "low", "volume", "amount"])
        # Do NOT zero-fill prices: NaN signals parse failure and will be caught
        # by _finalize_frame's NaN-OHLC + volume>0 guard.
        for col in ("open", "close", "high", "low"):
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
        raw["volume"] = pd.to_numeric(raw["volume"], errors="coerce").fillna(0.0)
        raw["amount"] = pd.to_numeric(raw["amount"], errors="coerce")
        raw["amount"] = raw["amount"].where(raw["amount"].notna() & (raw["amount"] > 0), raw["volume"] * 100.0 * raw["close"])
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
    if provider == "sina":
        return ProviderChain([SinaKlineProvider()])
    if provider == "baostock":
        return ProviderChain([BaostockKlineProvider()])
    if provider == "tencent":
        return ProviderChain([TencentKlineProvider()])
    if provider == "tushare":
        from trade_py.data.market.kline.tushare import TushareKlineProvider
        return ProviderChain([TushareKlineProvider(data_root)])
    # auto: try Tushare first (primary), then akshare, then sina, then baostock
    try:
        from trade_py.data.market.kline.tushare import TushareKlineProvider
        return ProviderChain([
            TushareKlineProvider(data_root),
            AkshareKlineProvider(),
            SinaKlineProvider(),
            TencentKlineProvider(),
            BaostockKlineProvider(),
        ])
    except Exception:
        return ProviderChain([AkshareKlineProvider(), SinaKlineProvider(), TencentKlineProvider(), BaostockKlineProvider()])
