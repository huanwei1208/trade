"""Fundamental data fetcher for A-share stocks (akshare).

Fetches quarterly financial statements via akshare and stores them in Parquet.
Each symbol gets one Parquet file with all historical quarterly data.

Storage: data/fundamental/{symbol}.parquet

Usage:
    fetcher = FundamentalFetcher("data")
    fetcher.fetch_and_save("600703.SH", limit=20)
    df = fetcher.load("600703.SH")
"""
from __future__ import annotations
import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)


def _to_code(symbol: str) -> str:
    """Strip exchange suffix: '600000.SH' → '600000'."""
    return symbol.split('.')[0]


def _infer_period(report_date_str: str) -> str:
    """Determine quarter from report date string YYYY-MM-DD."""
    try:
        month_day = report_date_str[5:10]
        return {
            "03-31": "Q1",
            "06-30": "Q2",
            "09-30": "Q3",
            "12-31": "Annual",
        }.get(month_day, "Q1")
    except Exception:
        return "Q1"


def _fetch_raw(code: str, limit: int = 20) -> pd.DataFrame:
    """Fetch quarterly financial summary from akshare.

    Uses ak.stock_financial_abstract_ths (THS financial abstract)
    which returns all historical quarterly/annual data for the symbol.

    Returns a raw DataFrame (Chinese column names) or empty DataFrame on error.
    """
    import akshare as ak
    try:
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
    except Exception as exc:
        logger.warning("akshare financial fetch failed for %s: %s", code, exc)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    # Most recent `limit` rows (API returns descending; we reverse later)
    return df.head(limit)


def _parse_rows(symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
    """Map akshare financial abstract columns to the project schema.

    akshare stock_financial_abstract_ths columns (representative subset):
        报告期 / 截止日期        → report_date
        每股收益                 → eps
        每股净资产               → bps
        每股经营现金流量(元)     → op_cash_flow_per_share (converted to total via shares)
        归属净利润 / 净利润(元)  → net_profit
        营业总收入(元)           → revenue
        加权净资产收益率(%)      → roe (convert to decimal)
        经营活动现金流量净额      → op_cash_flow (prefer this over per-share)
        总资产                   → total_assets
        营业利润                 → op_profit
    """
    if raw is None or raw.empty:
        return pd.DataFrame()

    # Build a flexible column finder
    cols = {c: c for c in raw.columns}

    def _find(candidates: list[str]) -> str | None:
        for c in candidates:
            for col in cols:
                if c in col:
                    return col
        return None

    date_col       = _find(["报告期", "截止日期", "报告日期"])
    eps_col        = _find(["每股收益"])
    bps_col        = _find(["每股净资产"])
    np_col         = _find(["归属净利润", "净利润"])
    revenue_col    = _find(["营业总收入", "营业收入"])
    roe_col        = _find(["加权净资产收益率", "净资产收益率"])
    op_profit_col  = _find(["营业利润"])
    op_cf_col      = _find(["经营活动现金流量净额", "经营性现金流"])
    assets_col     = _find(["总资产"])

    if date_col is None:
        logger.warning("Could not find date column in akshare financial data for %s", symbol)
        return pd.DataFrame()

    def _float(series: pd.Series | None, idx: int) -> float:
        if series is None:
            return 0.0
        try:
            val = series.iloc[idx]
            return float(val) if val is not None and str(val) not in ("", "nan", "--") else 0.0
        except (ValueError, TypeError, IndexError):
            return 0.0

    records = []
    for i in range(len(raw)):
        date_raw = str(raw[date_col].iloc[i]).strip()
        if not date_raw or date_raw in ("nan", "--", ""):
            continue
        report_date = date_raw[:10].replace("/", "-")

        roe_val = _float(raw[roe_col] if roe_col else None, i)
        # akshare may return ROE as percentage (e.g. 12.5) → convert to decimal
        if abs(roe_val) > 1.5:
            roe_val = roe_val / 100.0

        records.append({
            "symbol":       symbol,
            "report_date":  pd.to_datetime(report_date),
            "publish_date": pd.to_datetime(report_date),
            "period":       _infer_period(report_date),
            "revenue":      _float(raw[revenue_col] if revenue_col else None, i),
            "net_profit":   _float(raw[np_col] if np_col else None, i),
            "op_profit":    _float(raw[op_profit_col] if op_profit_col else None, i),
            "op_cash_flow": _float(raw[op_cf_col] if op_cf_col else None, i),
            "total_assets": _float(raw[assets_col] if assets_col else None, i),
            "eps":          _float(raw[eps_col] if eps_col else None, i),
            "bps":          _float(raw[bps_col] if bps_col else None, i),
            "roe":          roe_val,
        })

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df = df.sort_values("report_date").reset_index(drop=True)
    return df


class FundamentalFetcher:
    """Fetch and persist quarterly financial reports via akshare."""

    def __init__(self, data_root: str = 'data') -> None:
        self.data_root = Path(data_root)
        self._fundamental_dir = self.data_root / 'fundamental'
        self._fundamental_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        safe = symbol.replace('.', '_')
        return self._fundamental_dir / (safe + '.parquet')

    def load(self, symbol: str) -> pd.DataFrame:
        path = self._path(symbol)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def fetch_and_save(self, symbol: str, limit: int = 20) -> pd.DataFrame:
        code = _to_code(symbol)
        raw = _fetch_raw(code, limit=limit)
        new_df = _parse_rows(symbol, raw)
        if new_df.empty:
            logger.warning('No data fetched for %s', symbol)
            return self.load(symbol)
        existing = self.load(symbol)
        if not existing.empty:
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(
                subset=['symbol', 'report_date'], keep='last'
            )
            combined = combined.sort_values('report_date').reset_index(drop=True)
        else:
            combined = new_df
        combined.to_parquet(self._path(symbol), index=False)
        logger.info('Saved %d rows for %s', len(combined), symbol)
        return combined


def compute_fundamental_features(
    df: pd.DataFrame,
    current_price: float = 0.0,
    total_shares: int = 0,
) -> dict[str, float]:
    """Compute FundamentalSignal fields from DataFrame of historical reports.

    Columns required: roe, net_profit, revenue, op_cash_flow, bps.
    Sorted ascending by report_date. Returns a dict matching C++ FundamentalSignal.
    """
    result: dict[str, float] = {
        'roe_ttm': 0.0, 'roe_momentum': 0.0,
        'profit_growth_yoy': 0.0, 'revenue_growth_yoy': 0.0,
        'cash_flow_quality': 0.0, 'pe_percentile': 0.0,
        'pe_ttm': 0.0, 'pb': 0.0, 'quarters_available': 0,
    }
    if df.empty:
        return result
    n = len(df)
    q_avail = min(n, 12)
    result['quarters_available'] = q_avail
    last4_start = max(0, n - 4)
    last4 = df.iloc[last4_start:]
    result['roe_ttm'] = float(last4['roe'].mean())
    if n >= 5:
        prev4_end = n - 4
        prev4_start = max(0, n - 8)
        prev4 = df.iloc[prev4_start:prev4_end]
        if not prev4.empty:
            result['roe_momentum'] = result['roe_ttm'] - float(prev4['roe'].mean())
    if n >= 5:
        latest = df.iloc[n - 1]
        year_ago = df.iloc[n - 5]
        prior_profit = float(year_ago['net_profit'])
        prior_revenue = float(year_ago['revenue'])
        if abs(prior_profit) > 1.0:
            result['profit_growth_yoy'] = (
                float(latest['net_profit']) - prior_profit
            ) / abs(prior_profit)
        if prior_revenue > 1.0:
            result['revenue_growth_yoy'] = (
                float(latest['revenue']) - prior_revenue
            ) / prior_revenue
    cf_sum = float(last4['op_cash_flow'].sum())
    np_sum = float(last4['net_profit'].sum())
    if abs(np_sum) > 1.0:
        result['cash_flow_quality'] = max(-3.0, min(5.0, cf_sum / np_sum))
    ttm_np = float(last4['net_profit'].sum())
    if abs(ttm_np) > 1.0 and total_shares > 0 and current_price > 0.0:
        pe = (current_price * total_shares) / ttm_np
        result['pe_ttm'] = max(1.0, min(300.0, pe))
    bps = float(df.iloc[n - 1]['bps'])
    if bps > 1e-6 and current_price > 0.0:
        result['pb'] = max(0.1, min(50.0, current_price / bps))
    if result['pe_ttm'] > 0.0 and total_shares > 0 and current_price > 0.0:
        hist_start = n - q_avail
        pe_history: list[float] = []
        for i in range(hist_start, n):
            np_slice = float(df.iloc[max(0, i - 3): i + 1]['net_profit'].sum())
            if abs(np_slice) > 1.0:
                pe_i = (current_price * total_shares) / np_slice
                if pe_i > 0.0:
                    pe_history.append(max(1.0, min(300.0, pe_i)))
        if len(pe_history) > 1:
            rank = sum(1 for p in pe_history if p < result['pe_ttm'])
            result['pe_percentile'] = rank / len(pe_history)
    return result
