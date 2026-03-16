"""Fund flow fetcher via Tushare Pro moneyflow API.

Replaces akshare-based FundFlowFetcher; same output schema so feature_builder
Group D (large_order_net_ratio) works without changes.

Storage: data/fund_flow/{symbol}.parquet
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Default look-back window when no start_date given
_DEFAULT_DAYS = 120


def _fetch_raw(symbol: str, data_root: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    from trade_py.data.market.tushare_client import get_pro_api
    pro = get_pro_api(data_root)
    end = (end_date or date.today().strftime("%Y%m%d")).replace("-", "")
    if start_date:
        start = start_date.replace("-", "")
    else:
        start = (date.today() - timedelta(days=_DEFAULT_DAYS)).strftime("%Y%m%d")
    df = pro.call("moneyflow", ts_code=symbol, start_date=start, end_date=end)
    return df if df is not None else pd.DataFrame()


def _fetch_raw_trade_date(trade_date: str, data_root: str) -> pd.DataFrame:
    from trade_py.data.market.tushare_client import get_pro_api

    pro = get_pro_api(data_root)
    df = pro.call("moneyflow", trade_date=trade_date.replace("-", ""))
    return df if df is not None else pd.DataFrame()


def _resolve_window(start_date: str | None = None, end_date: str | None = None) -> tuple[date, date]:
    end = date.fromisoformat(end_date) if end_date else date.today()
    if start_date:
        start = date.fromisoformat(start_date)
    else:
        start = end - timedelta(days=_DEFAULT_DAYS)
    return start, end


def _date_span(start: date, end: date) -> list[str]:
    current = start
    values: list[str] = []
    while current <= end:
        values.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return values


def _parse_rows(symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
    """Convert Tushare moneyflow DataFrame to project fund-flow schema."""
    if raw is None or raw.empty:
        return pd.DataFrame()

    def _f(col: str) -> pd.Series:
        return pd.to_numeric(raw.get(col, pd.Series([0.0] * len(raw))), errors="coerce").fillna(0.0)

    # Tushare moneyflow columns (万元):
    # buy_elg_amount, sell_elg_amount  — 超大单
    # buy_lg_amount,  sell_lg_amount   — 大单
    # buy_md_amount,  sell_md_amount   — 中单
    # buy_sm_amount,  sell_sm_amount   — 小单
    # buy_elg_vol/sell_elg_vol etc.    — 手
    # trade_count (手), trade_date

    date_series = pd.to_datetime(raw["trade_date"].astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d")

    # Amounts in 万元 → 元
    xl_net = (_f("buy_elg_amount") - _f("sell_elg_amount")) * 1e4
    l_net  = (_f("buy_lg_amount")  - _f("sell_lg_amount"))  * 1e4
    m_net  = (_f("buy_md_amount")  - _f("sell_md_amount"))  * 1e4
    s_net  = (_f("buy_sm_amount")  - _f("sell_sm_amount"))  * 1e4

    total_inflow  = (_f("buy_elg_amount") + _f("buy_lg_amount") + _f("buy_md_amount") + _f("buy_sm_amount")) * 1e4
    total_outflow = (_f("sell_elg_amount") + _f("sell_lg_amount") + _f("sell_md_amount") + _f("sell_sm_amount")) * 1e4
    total_turnover = total_inflow + total_outflow

    large_net = xl_net + l_net
    denom = total_turnover.where(total_turnover > 1e-6, other=float("nan"))
    ratio = (large_net / denom).fillna(0.0)
    sbd   = ((large_net - s_net) / denom).fillna(0.0)

    small_ratio = (s_net.abs() / denom).fillna(0.0)
    retail_heat = (small_ratio.rolling(60, min_periods=5).rank(pct=True) * 100.0).fillna(50.0).round(1)
    dist_flag = ((ratio < -0.05) & (s_net > 0) & (sbd < -0.05)).astype(int)

    df = pd.DataFrame({
        "symbol":                        symbol,
        "date":                          date_series.values,
        "xl_net":                        xl_net.values,
        "large_net":                     l_net.values,
        "medium_net":                    m_net.values,
        "small_net":                     s_net.values,
        "total_turnover":                total_turnover.values,
        "large_order_net_ratio":         ratio.round(6).values,
        "sentiment_behavior_divergence": sbd.round(6).values,
        "retail_heat_score":             retail_heat.values,
        "distribution_zone_flag":        dist_flag.values,
    })
    return df.sort_values("date").reset_index(drop=True)


class FundFlowFetcher:
    """Tushare-backed fund flow fetcher (drop-in replacement for akshare version)."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self.data_root = str(data_root)
        self._root = Path(data_root) / "market" / "fund_flow"
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self._root / (symbol.replace(".", "_") + ".parquet")

    def load(self, symbol: str) -> pd.DataFrame:
        p = self._path(symbol)
        if not p.exists():
            return pd.DataFrame()
        return pd.read_parquet(p)

    def _merge_and_save(self, symbol: str, new_df: pd.DataFrame) -> pd.DataFrame:
        existing = self.load(symbol)
        if new_df.empty:
            return existing
        if not existing.empty:
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["symbol", "date"], keep="last")
            combined = combined.sort_values("date").reset_index(drop=True)
        else:
            combined = new_df
        combined.to_parquet(self._path(symbol), index=False)
        logger.info("FundFlowFetcher: saved %d rows for %s", len(combined), symbol)
        return combined

    def fetch_and_save(self, symbol: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        existing = self.load(symbol)
        # incremental: only fetch from day after the last stored date when no explicit start given
        if start_date is None and not existing.empty:
            last_dt = pd.to_datetime(existing["date"]).max()
            start_date = (last_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        raw = _fetch_raw(symbol, self.data_root, start_date=start_date, end_date=end_date)
        new_df = _parse_rows(symbol, raw)
        if new_df.empty:
            logger.warning("FundFlowFetcher: no data for %s", symbol)
            return existing
        return self._merge_and_save(symbol, new_df)

    def _fetch_batch_by_trade_date(
        self,
        symbols: list[str],
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        symbol_set = {str(sym).strip().upper() for sym in symbols if str(sym).strip()}
        start, end = _resolve_window(start_date, end_date)
        grouped: dict[str, list[pd.DataFrame]] = {}
        api_calls = 0
        day_hits = 0
        for trade_date in _date_span(start, end):
            raw = _fetch_raw_trade_date(trade_date, self.data_root)
            api_calls += 1
            if raw.empty or "ts_code" not in raw.columns:
                continue
            filtered = raw[raw["ts_code"].astype(str).str.upper().isin(symbol_set)].copy()
            if filtered.empty:
                continue
            day_hits += 1
            for symbol, frame in filtered.groupby(filtered["ts_code"].astype(str).str.upper(), sort=False):
                grouped.setdefault(symbol, []).append(frame.copy())

        saved = 0
        for symbol, frames in grouped.items():
            parsed = _parse_rows(symbol, pd.concat(frames, ignore_index=True))
            self._merge_and_save(symbol, parsed)
            saved += 1
        return {
            "mode": "trade_date_batch",
            "symbols": len(symbols),
            "saved_symbols": saved,
            "api_calls": api_calls,
            "days_with_hits": day_hits,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }

    def fetch_batch(
        self,
        symbols: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        from trade_py.utils.progress import iter_progress
        normalized = [str(sym).strip().upper() for sym in symbols if str(sym).strip()]
        start, end = _resolve_window(start_date, end_date)
        range_days = max(1, (end - start).days + 1)
        if len(normalized) > 1 and range_days < len(normalized):
            logger.info(
                "FundFlowFetcher: using batch trade_date mode for %d symbols across %d days",
                len(normalized),
                range_days,
            )
            return self._fetch_batch_by_trade_date(
                normalized,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
            )

        ok = 0
        for sym in iter_progress(normalized, desc="fund-flow", unit="sym"):
            try:
                self.fetch_and_save(sym, start_date=start.isoformat(), end_date=end.isoformat())
                ok += 1
            except Exception as exc:
                logger.error("FundFlowFetcher: %s failed: %s", sym, exc)
        return {
            "mode": "symbol_loop",
            "symbols": len(normalized),
            "saved_symbols": ok,
            "api_calls": len(normalized),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }

    def latest_ratio(self, symbol: str, as_of: date | None = None) -> float:
        df = self.load(symbol)
        if df.empty:
            return 0.0
        df["date"] = pd.to_datetime(df["date"])
        if as_of is not None:
            df = df[df["date"] <= pd.Timestamp(as_of)]
        return float(df.sort_values("date").iloc[-1]["large_order_net_ratio"]) if not df.empty else 0.0
