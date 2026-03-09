"""Index daily OHLCV fetcher via Tushare Pro.

Default indices synced:
    000001.SH  上证综指 (benchmark)
    000300.SH  沪深300
    399001.SZ  深证成指
    399006.SZ  创业板指

Storage: data/index/{index_code}.parquet
Columns: date, open, high, low, close, volume, amount, pct_chg
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_INDICES = ["000001.SH", "000300.SH", "399001.SZ", "399006.SZ"]

# 申万一级行业指数（2021年修订版，31个行业）
# Key: Tushare index code, Value: (中文名, SW enum integer)
SW_SECTOR_INDICES: dict[str, tuple[str, int]] = {
    "801010.SI": ("农林牧渔", 0),
    "801020.SI": ("基础化工", 2),
    "801030.SI": ("钢铁",    3),
    "801040.SI": ("有色金属", 4),
    "801050.SI": ("电子",    5),
    "801060.SI": ("汽车",    6),
    "801070.SI": ("家用电器", 7),
    "801080.SI": ("食品饮料", 8),
    "801090.SI": ("纺织服装", 9),
    "801100.SI": ("轻工制造", 10),
    "801110.SI": ("医药生物", 11),
    "801120.SI": ("公用事业", 12),
    "801130.SI": ("交通运输", 13),
    "801140.SI": ("房地产",  14),
    "801150.SI": ("商业贸易", 15),
    "801160.SI": ("社会服务", 16),
    "801170.SI": ("银行",    17),
    "801180.SI": ("非银金融", 18),
    "801190.SI": ("建筑装饰", 19),
    "801200.SI": ("建筑材料", 20),
    "801210.SI": ("机械设备", 21),
    "801220.SI": ("国防军工", 22),
    "801230.SI": ("计算机",  23),
    "801240.SI": ("传媒",    24),
    "801250.SI": ("通信",    25),
    "801260.SI": ("煤炭",    29),
    "801270.SI": ("石油石化", 30),
    "801280.SI": ("环保",    26),
    "801290.SI": ("电力设备", 27),
    "801300.SI": ("美容护理", 28),
    "801310.SI": ("采掘",    1),
}

# 中文名 → SW enum integer（用于 refresh_sector_members 反查）
_ZH_TO_SW_IDX: dict[str, int] = {zh: idx for zh, idx in SW_SECTOR_INDICES.values()}


def _fetch_raw(ts_code: str, data_root: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    from trade_py.data.market.tushare_client import get_pro_api
    pro = get_pro_api(data_root)
    end = (end_date or date.today().strftime("%Y%m%d")).replace("-", "")
    start = (start_date or (date.today() - timedelta(days=365 * 3)).strftime("%Y%m%d")).replace("-", "")
    df = pro.call("index_daily", ts_code=ts_code, start_date=start, end_date=end)
    return df if df is not None else pd.DataFrame()


class IndexFetcher:
    """Fetch and persist daily index data."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self.data_root = str(data_root)
        self._dir = Path(data_root) / "index"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ts_code: str) -> Path:
        return self._dir / (ts_code.replace(".", "_") + ".parquet")

    def load(self, ts_code: str) -> pd.DataFrame:
        p = self._path(ts_code)
        if not p.exists():
            return pd.DataFrame()
        return pd.read_parquet(p)

    def fetch_and_save(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = _fetch_raw(ts_code, self.data_root, start_date=start_date, end_date=end_date)
        if raw is None or raw.empty:
            logger.warning("IndexFetcher: no data for %s", ts_code)
            return self.load(ts_code)

        df = pd.DataFrame({
            "date":    pd.to_datetime(raw["trade_date"].astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d"),
            "open":    pd.to_numeric(raw.get("open",   0), errors="coerce").fillna(0.0),
            "high":    pd.to_numeric(raw.get("high",   0), errors="coerce").fillna(0.0),
            "low":     pd.to_numeric(raw.get("low",    0), errors="coerce").fillna(0.0),
            "close":   pd.to_numeric(raw.get("close",  0), errors="coerce").fillna(0.0),
            "volume":  pd.to_numeric(raw.get("vol",    0), errors="coerce").fillna(0.0),
            "amount":  pd.to_numeric(raw.get("amount", 0), errors="coerce").fillna(0.0) * 1000.0,
            "pct_chg": pd.to_numeric(raw.get("pct_chg", 0), errors="coerce").fillna(0.0),
        })
        df = df.sort_values("date").reset_index(drop=True)

        existing = self.load(ts_code)
        if not existing.empty:
            combined = pd.concat([existing, df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date"], keep="last")
            combined = combined.sort_values("date").reset_index(drop=True)
        else:
            combined = df

        combined.to_parquet(self._path(ts_code), index=False)
        logger.info("IndexFetcher: saved %d rows for %s", len(combined), ts_code)
        return combined

    def fetch_all(self, indices: list[str] | None = None, start_date: str | None = None) -> None:
        for code in (indices or DEFAULT_INDICES):
            try:
                self.fetch_and_save(code, start_date=start_date)
            except Exception as exc:
                logger.error("IndexFetcher: %s failed: %s", code, exc)

    def fetch_sector_all(self, start_date: str | None = None) -> None:
        """批量拉取 31 个申万一级行业指数，存储到 data/index/sector_{code}.parquet。"""
        for code, (zh_name, _sw_idx) in SW_SECTOR_INDICES.items():
            safe_code = "sector_" + code.replace(".", "_")
            try:
                raw = _fetch_raw(code, self.data_root, start_date=start_date)
                if raw is None or raw.empty:
                    logger.warning("fetch_sector_all: no data for %s (%s)", code, zh_name)
                    continue
                df = pd.DataFrame({
                    "date":    pd.to_datetime(raw["trade_date"].astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d"),
                    "open":    pd.to_numeric(raw.get("open",   0), errors="coerce").fillna(0.0),
                    "high":    pd.to_numeric(raw.get("high",   0), errors="coerce").fillna(0.0),
                    "low":     pd.to_numeric(raw.get("low",    0), errors="coerce").fillna(0.0),
                    "close":   pd.to_numeric(raw.get("close",  0), errors="coerce").fillna(0.0),
                    "volume":  pd.to_numeric(raw.get("vol",    0), errors="coerce").fillna(0.0),
                    "amount":  pd.to_numeric(raw.get("amount", 0), errors="coerce").fillna(0.0) * 1000.0,
                    "pct_chg": pd.to_numeric(raw.get("pct_chg", 0), errors="coerce").fillna(0.0),
                })
                df = df.sort_values("date").reset_index(drop=True)
                out_path = self._dir / (safe_code + ".parquet")
                existing_path = self._dir / (code.replace(".", "_") + ".parquet")
                existing = pd.read_parquet(existing_path) if existing_path.exists() else pd.DataFrame()
                if not existing.empty:
                    df = pd.concat([existing, df], ignore_index=True)
                    df = df.drop_duplicates(subset=["date"], keep="last")
                    df = df.sort_values("date").reset_index(drop=True)
                df.to_parquet(out_path, index=False)
                logger.info("fetch_sector_all: saved %d rows for %s (%s)", len(df), code, zh_name)
            except Exception as exc:
                logger.error("fetch_sector_all: %s (%s) failed: %s", code, zh_name, exc)

    def load_sector(self, ts_code: str) -> pd.DataFrame:
        """Load sector index parquet by Tushare code (e.g. '801010.SI')."""
        safe_code = "sector_" + ts_code.replace(".", "_")
        p = self._dir / (safe_code + ".parquet")
        if not p.exists():
            return pd.DataFrame()
        return pd.read_parquet(p)

    def refresh_sector_members(self) -> dict[str, int]:
        """通过 Tushare index_member API 刷新 instruments.industry 字段。

        Returns:
            symbol → sw_idx 映射（已写入 DB 的条目）
        """
        from trade_py.data.market.tushare_client import get_pro_api
        from trade_py.db.instruments_db import InstrumentsDB

        pro = get_pro_api(self.data_root)
        db = InstrumentsDB(self.data_root)
        existing_symbols = set(db.get_all_symbols())

        updated: dict[str, int] = {}
        for index_code, (zh_name, sw_idx) in SW_SECTOR_INDICES.items():
            try:
                df = pro.call("index_member", index_code=index_code)
                if df is None or df.empty:
                    logger.warning("refresh_sector_members: no members for %s (%s)", index_code, zh_name)
                    continue
                # Tushare returns con_code (6-digit) and ts_code (full)
                ts_col = "ts_code" if "ts_code" in df.columns else "con_code"
                for symbol in df[ts_col].dropna():
                    symbol = str(symbol).strip()
                    if symbol in existing_symbols:
                        db._conn.execute(
                            "UPDATE instruments SET industry=? WHERE symbol=?",
                            (sw_idx, symbol),
                        )
                        updated[symbol] = sw_idx
                db._conn.commit()
                logger.info("refresh_sector_members: %s (%s) → %d members", index_code, zh_name, len(df))
            except Exception as exc:
                logger.error("refresh_sector_members: %s failed: %s", index_code, exc)

        return updated

    def get_return(self, ts_code: str, window: int = 20, as_of: date | None = None) -> float:
        """Return N-day price return for an index (used by feature_builder Group D)."""
        df = self.load(ts_code)
        if df.empty or "close" not in df.columns:
            return 0.0
        df["date"] = pd.to_datetime(df["date"])
        if as_of is not None:
            df = df[df["date"] <= pd.Timestamp(as_of)]
        df = df.sort_values("date").tail(window + 1)
        if len(df) < 2:
            return 0.0
        start_price = float(df.iloc[0]["close"])
        end_price = float(df.iloc[-1]["close"])
        if start_price <= 0:
            return 0.0
        return (end_price - start_price) / start_price
