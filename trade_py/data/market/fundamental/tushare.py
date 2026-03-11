"""Fundamental data fetcher via Tushare Pro.

Uses tushare pro.fina_indicator() for quarterly financial metrics.
Output schema is identical to the original akshare-based FundamentalFetcher,
so feature_builder.py Group E requires no changes.

Storage: data/fundamental/{symbol}.parquet
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _infer_period(report_date_str: str) -> str:
    try:
        md = report_date_str[5:10]
        return {"03-31": "Q1", "06-30": "Q2", "09-30": "Q3", "12-31": "Annual"}.get(md, "Q1")
    except Exception:
        return "Q1"


def _fetch_raw(ts_code: str, data_root: str, start_date: str | None = None) -> pd.DataFrame:
    """Fetch fina_indicator from Tushare Pro."""
    from trade_py.data.market.tushare_client import get_pro_api
    pro = get_pro_api(data_root)
    kwargs: dict = {"ts_code": ts_code, "fields": (
        "ts_code,ann_date,end_date,roe,eps,bps,netprofit_yoy,"
        "or_yoy,ocfps,total_revenue,n_income_attr_p,oper_profit,"
        "total_assets,q_opincome"
    )}
    if start_date:
        kwargs["start_date"] = start_date.replace("-", "")
    df = pro.call("fina_indicator", **kwargs)
    return df if df is not None else pd.DataFrame()


def _parse_rows(symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    def _f(series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors="coerce").fillna(0.0)

    records = []
    for _, row in raw.iterrows():
        end_date = str(row.get("end_date", "")).strip()
        if not end_date or end_date in ("nan", "--", ""):
            continue
        report_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

        roe = float(_f(pd.Series([row.get("roe", 0)])).iloc[0])
        # Tushare returns ROE as percentage → convert to decimal
        if abs(roe) > 1.5:
            roe /= 100.0

        records.append({
            "symbol":       symbol,
            "report_date":  pd.to_datetime(report_date),
            "publish_date": pd.to_datetime(
                str(row.get("ann_date", end_date)).strip()[:8]
                    .replace("-", "")
                    [:8]
            ) if row.get("ann_date") else pd.to_datetime(report_date),
            "period":       _infer_period(report_date),
            "revenue":      float(_f(pd.Series([row.get("total_revenue", 0)])).iloc[0]),
            "net_profit":   float(_f(pd.Series([row.get("n_income_attr_p", 0)])).iloc[0]),
            "op_profit":    float(_f(pd.Series([row.get("oper_profit", 0)])).iloc[0]),
            "op_cash_flow": float(_f(pd.Series([row.get("ocfps", 0)])).iloc[0]),  # 每股经营现金流
            "total_assets": float(_f(pd.Series([row.get("total_assets", 0)])).iloc[0]),
            "eps":          float(_f(pd.Series([row.get("eps", 0)])).iloc[0]),
            "bps":          float(_f(pd.Series([row.get("bps", 0)])).iloc[0]),
            "roe":          roe,
        })

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df = df.sort_values("report_date").reset_index(drop=True)
    return df


class FundamentalFetcher:
    """Fetch and persist quarterly financial reports via Tushare Pro."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self.data_root = str(data_root)
        self._dir = Path(data_root) / "market" / "fundamental"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self._dir / (symbol.replace(".", "_") + ".parquet")

    def load(self, symbol: str) -> pd.DataFrame:
        p = self._path(symbol)
        if not p.exists():
            return pd.DataFrame()
        return pd.read_parquet(p)

    def fetch_and_save(self, symbol: str, start_date: str | None = None) -> pd.DataFrame:
        existing = self.load(symbol)
        # incremental: only fetch quarters after the last stored report_date when no explicit start given
        if start_date is None and not existing.empty:
            last_dt = pd.to_datetime(existing["report_date"]).max()
            start_date = last_dt.strftime("%Y-%m-%d")
        raw = _fetch_raw(symbol, self.data_root, start_date=start_date)
        new_df = _parse_rows(symbol, raw)
        if new_df.empty:
            logger.warning("No fundamental data fetched for %s", symbol)
            return existing
        if not existing.empty:
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["symbol", "report_date"], keep="last")
            combined = combined.sort_values("report_date").reset_index(drop=True)
        else:
            combined = new_df
        combined.to_parquet(self._path(symbol), index=False)
        logger.info("FundamentalFetcher: saved %d rows for %s", len(combined), symbol)
        return combined

    def fetch_batch(self, symbols: list[str], start_date: str | None = None) -> None:
        try:
            from tqdm import tqdm
            from tqdm.contrib.logging import logging_redirect_tqdm
        except ImportError:
            tqdm = None

        ok = err = 0

        def _run(bar=None):
            nonlocal ok, err
            for sym in symbols:
                if bar is not None:
                    bar.set_description(f"fundamental [{ok}ok {err}err]")
                    bar.set_postfix_str(sym, refresh=False)
                try:
                    df = self.fetch_and_save(sym, start_date=start_date)
                    ok += 1
                    if bar is not None:
                        bar.set_description(f"fundamental [{ok}ok {err}err]")
                except Exception as exc:
                    err += 1
                    logger.error("FundamentalFetcher: %s failed: %s", sym, exc)
                finally:
                    if bar is not None:
                        bar.update(1)

        if tqdm is None:
            _run()
        else:
            with logging_redirect_tqdm():
                with tqdm(total=len(symbols), unit="sym", dynamic_ncols=True,
                          desc=f"fundamental [0ok 0err]") as bar:
                    _run(bar)


def compute_fundamental_features(
    df: pd.DataFrame,
    current_price: float = 0.0,
    total_shares: int = 0,
) -> dict[str, float]:
    """Compute Group E features from quarterly report DataFrame.

    Input df columns: roe, net_profit, revenue, op_cash_flow, bps (sorted asc by report_date).
    """
    result: dict[str, float] = {
        "roe_ttm": 0.0, "roe_momentum": 0.0,
        "profit_growth_yoy": 0.0, "revenue_growth_yoy": 0.0,
        "cash_flow_quality": 0.0, "pe_percentile": 0.0,
        "pe_ttm": 0.0, "pb": 0.0, "quarters_available": 0,
    }
    if df.empty:
        return result
    n = len(df)
    q_avail = min(n, 12)
    result["quarters_available"] = q_avail
    last4 = df.iloc[max(0, n - 4):]
    result["roe_ttm"] = float(last4["roe"].mean())
    if n >= 5:
        prev4 = df.iloc[max(0, n - 8): n - 4]
        if not prev4.empty:
            result["roe_momentum"] = result["roe_ttm"] - float(prev4["roe"].mean())
        latest = df.iloc[n - 1]
        year_ago = df.iloc[n - 5]
        prior_profit = float(year_ago["net_profit"])
        prior_revenue = float(year_ago["revenue"])
        if abs(prior_profit) > 1.0:
            result["profit_growth_yoy"] = (float(latest["net_profit"]) - prior_profit) / abs(prior_profit)
        if prior_revenue > 1.0:
            result["revenue_growth_yoy"] = (float(latest["revenue"]) - prior_revenue) / prior_revenue
    cf_sum = float(last4["op_cash_flow"].sum())
    np_sum = float(last4["net_profit"].sum())
    if abs(np_sum) > 1.0:
        result["cash_flow_quality"] = max(-3.0, min(5.0, cf_sum / np_sum))
    ttm_np = float(last4["net_profit"].sum())
    if abs(ttm_np) > 1.0 and total_shares > 0 and current_price > 0.0:
        pe = (current_price * total_shares) / ttm_np
        result["pe_ttm"] = max(1.0, min(300.0, pe))
    bps = float(df.iloc[n - 1]["bps"])
    if bps > 1e-6 and current_price > 0.0:
        result["pb"] = max(0.1, min(50.0, current_price / bps))
    if result["pe_ttm"] > 0.0 and total_shares > 0 and current_price > 0.0:
        pe_history: list[float] = []
        for i in range(n - q_avail, n):
            np_sl = float(df.iloc[max(0, i - 3): i + 1]["net_profit"].sum())
            if abs(np_sl) > 1.0:
                pe_i = (current_price * total_shares) / np_sl
                if pe_i > 0.0:
                    pe_history.append(max(1.0, min(300.0, pe_i)))
        if len(pe_history) > 1:
            result["pe_percentile"] = sum(1 for p in pe_history if p < result["pe_ttm"]) / len(pe_history)
    return result
