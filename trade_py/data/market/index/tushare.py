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
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)
_INDUSTRY_UNKNOWN = 255

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

# SW enum integer → (Tushare index code, 中文名)（用于 stock_basic baseline 回填）
_SW_IDX_TO_INFO: dict[int, tuple[str, str]] = {
    sw_idx: (code, name) for code, (name, sw_idx) in SW_SECTOR_INDICES.items()
}

# Tushare stock_basic industry 字段的别名（非精确匹配时使用）
_INDUSTRY_ALIAS: dict[str, str] = {
    "采矿业":     "采掘",
    "化工":       "基础化工",
    "化学工业":   "基础化工",
    "煤炭开采":   "煤炭",
    "石油天然气": "石油石化",
    "石油化工":   "石油石化",
    "钢铁行业":   "钢铁",
    "汽车制造":   "汽车",
    "饮料制造":   "食品饮料",
    "食品加工":   "食品饮料",
    "医药制造":   "医药生物",
    "生物制品":   "医药生物",
    "公共设施":   "公用事业",
    "电力":       "公用事业",
    "运输业":     "交通运输",
    "房地产业":   "房地产",
    "零售业":     "商业贸易",
    "商贸零售":   "商业贸易",
    "休闲服务":   "社会服务",
    "消费者服务": "社会服务",
    "保险":       "非银金融",
    "证券":       "非银金融",
    "多元金融":   "非银金融",
    "综合金融":   "非银金融",
    "互联网":     "计算机",
    "软件服务":   "计算机",
    "电子信息":   "电子",
    "半导体":     "电子",
    "电力设备及新能源": "电力设备",
    "农业":       "农林牧渔",
    "林业":       "农林牧渔",
    "牧业":       "农林牧渔",
    "渔业":       "农林牧渔",
}


def _map_industry_to_sw(industry: str) -> int:
    """Map Tushare stock_basic industry string to SW enum integer.

    Priority: exact match → alias → fuzzy substring match → unknown.
    """
    if not industry:
        return _INDUSTRY_UNKNOWN
    # Exact match
    if industry in _ZH_TO_SW_IDX:
        return _ZH_TO_SW_IDX[industry]
    # Alias map
    mapped = _INDUSTRY_ALIAS.get(industry)
    if mapped and mapped in _ZH_TO_SW_IDX:
        return _ZH_TO_SW_IDX[mapped]
    # Fuzzy: SW name is substring of industry or vice versa
    for sw_name, sw_idx in _ZH_TO_SW_IDX.items():
        if sw_name in industry or industry in sw_name:
            return sw_idx
    return _INDUSTRY_UNKNOWN


def _ensure_symbol(value: str) -> str:
    value = str(value).strip().upper()
    if "." in value:
        return value
    if value.startswith(("6", "9")):
        return value + ".SH"
    if value.startswith(("4", "8")):
        return value + ".BJ"
    return value + ".SZ"


def _default_start_date(data_root: str) -> str:
    try:
        from trade_py.db.settings_db import SettingsDB
        return str(SettingsDB(data_root).get("index.start_date", "2015-01-01"))
    except Exception:
        return "2015-01-01"


def _fetch_raw(ts_code: str, data_root: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    from trade_py.data.market.tushare_client import get_pro_api
    pro = get_pro_api(data_root)
    end = (end_date or date.today().strftime("%Y%m%d")).replace("-", "")
    start = (start_date or _default_start_date(data_root)).replace("-", "")
    endpoint = "sw_daily" if str(ts_code).upper().endswith(".SI") else "index_daily"
    df = pro.call(endpoint, ts_code=ts_code, start_date=start, end_date=end)
    return df if df is not None else pd.DataFrame()


def _numeric_series(raw: pd.DataFrame, column: str) -> pd.Series:
    if column in raw.columns:
        source = raw[column]
    else:
        source = pd.Series([0.0] * len(raw))
    return pd.to_numeric(source, errors="coerce").fillna(0.0)


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
        existing = self.load(ts_code)
        # incremental: only fetch from day after the last stored date when no explicit start given
        if start_date is None and not existing.empty:
            last_dt = pd.to_datetime(existing["date"]).max()
            start_date = (last_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        raw = _fetch_raw(ts_code, self.data_root, start_date=start_date, end_date=end_date)
        if raw is None or raw.empty:
            logger.warning("IndexFetcher: no data for %s", ts_code)
            return existing

        df = pd.DataFrame({
            "date":    pd.to_datetime(raw["trade_date"].astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d"),
            "open":    _numeric_series(raw, "open"),
            "high":    _numeric_series(raw, "high"),
            "low":     _numeric_series(raw, "low"),
            "close":   _numeric_series(raw, "close"),
            "volume":  _numeric_series(raw, "vol"),
            "amount":  _numeric_series(raw, "amount") * 1000.0,
            "pct_chg": _numeric_series(raw, "pct_chg"),
        })
        df = df.sort_values("date").reset_index(drop=True)

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
        from trade_py.utils.progress import iter_progress
        for code in iter_progress(indices or DEFAULT_INDICES, desc="index", unit="idx"):
            try:
                self.fetch_and_save(code, start_date=start_date)
            except Exception as exc:
                logger.error("IndexFetcher: %s failed: %s", code, exc)

    def fetch_sector_all(self, start_date: str | None = None) -> None:
        """批量拉取 31 个申万一级行业指数，存储到 data/index/sector_{code}.parquet。"""
        from trade_py.utils.progress import iter_progress
        for code, (zh_name, _sw_idx) in iter_progress(SW_SECTOR_INDICES.items(), desc="sector-index", unit="idx"):
            safe_code = "sector_" + code.replace(".", "_")
            out_path = self._dir / (safe_code + ".parquet")
            try:
                existing = pd.read_parquet(out_path) if out_path.exists() else pd.DataFrame()
                # incremental: only fetch from day after last stored date when no explicit start given
                effective_start = start_date
                if effective_start is None and not existing.empty:
                    last_dt = pd.to_datetime(existing["date"]).max()
                    effective_start = (last_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                raw = _fetch_raw(code, self.data_root, start_date=effective_start)
                if raw is None or raw.empty:
                    logger.warning("fetch_sector_all: no data for %s (%s)", code, zh_name)
                    continue
                df = pd.DataFrame({
                    "date":    pd.to_datetime(raw["trade_date"].astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d"),
                    "open":    _numeric_series(raw, "open"),
                    "high":    _numeric_series(raw, "high"),
                    "low":     _numeric_series(raw, "low"),
                    "close":   _numeric_series(raw, "close"),
                    "volume":  _numeric_series(raw, "vol"),
                    "amount":  _numeric_series(raw, "amount") * 1000.0,
                    "pct_chg": _numeric_series(raw, "pct_chg"),
                })
                df = df.sort_values("date").reset_index(drop=True)
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
        """两层刷新板块映射和 instruments.industry 字段。

        Layer 1 (baseline): stock_basic() industry 字段 → 覆盖全量 5489 只股票
        Layer 2 (precise):  index_member × 31 SW 指数 → 精确成分股（优先级更高）

        Returns:
            symbol → sw_idx 映射（已写入 DB 的条目）
        """
        from trade_py.data.market.tushare_client import get_pro_api
        from trade_py.db.instruments_db import InstrumentsDB

        pro = get_pro_api(self.data_root)
        db = InstrumentsDB(self.data_root)
        existing_symbols = set(db.get_all_symbols())

        # ── Layer 1: stock_basic baseline ─────────────────────────────────────
        baseline: dict[str, int] = {}
        try:
            sb_df = pro.call("stock_basic", list_status="L", fields="ts_code,industry")
            if sb_df is not None and not sb_df.empty:
                for _, row in sb_df.iterrows():
                    symbol = _ensure_symbol(str(row.get("ts_code", "")))
                    if symbol not in existing_symbols:
                        continue
                    sw_idx = _map_industry_to_sw(str(row.get("industry", "") or ""))
                    if sw_idx != _INDUSTRY_UNKNOWN:
                        baseline[symbol] = sw_idx
                logger.info(
                    "refresh_sector_members: stock_basic baseline → %d / %d symbols mapped",
                    len(baseline), len(existing_symbols),
                )
        except Exception as exc:
            logger.warning("refresh_sector_members: stock_basic call failed: %s", exc)

        # ── Layer 2: index_member precise override ─────────────────────────────
        # memberships maps symbol → list of (index_code, zh_name, sw_idx, in_date_str)
        today_str = date.today().strftime("%Y%m%d")
        memberships: dict[str, list[tuple[str, str, int, str]]] = {}
        for index_code, (zh_name, sw_idx) in SW_SECTOR_INDICES.items():
            try:
                df = pro.call("index_member", index_code=index_code)
                if df is None or df.empty:
                    logger.warning("refresh_sector_members: no members for %s (%s)", index_code, zh_name)
                    continue

                # Keep only CURRENT members: out_date is empty/null, or in the future
                if "out_date" in df.columns:
                    out = df["out_date"].fillna("").astype(str)
                    df = df[(out == "") | (out == "None") | (out >= today_str)]

                ts_col = "ts_code" if "ts_code" in df.columns else "con_code"
                in_date_col = "in_date" if "in_date" in df.columns else None

                current_count = 0
                for _, row in df.iterrows():
                    symbol = _ensure_symbol(str(row[ts_col]))
                    if symbol not in existing_symbols:
                        continue
                    in_date = str(row[in_date_col]) if in_date_col else ""
                    memberships.setdefault(symbol, []).append((index_code, zh_name, sw_idx, in_date))
                    current_count += 1

                logger.info(
                    "refresh_sector_members: %s (%s) → %d current members",
                    index_code, zh_name, current_count,
                )
            except Exception as exc:
                logger.error("refresh_sector_members: %s failed: %s", index_code, exc)

        # Resolve conflicts: for stocks still in 2+ current indices, pick most recently added
        precise: dict[str, tuple[str, str, int]] = {}
        conflicted: list[str] = []
        for symbol, entries in memberships.items():
            unique_sectors = {(code, name, idx) for code, name, idx, _ in entries}
            if len(unique_sectors) == 1:
                sector_code, sector_name, sw_idx = next(iter(unique_sectors))
                precise[symbol] = (sector_code, sector_name, sw_idx)
            else:
                # True conflict: pick the entry with the latest in_date
                best = max(entries, key=lambda e: e[3] or "")
                precise[symbol] = (best[0], best[1], best[2])
                conflicted.append(symbol)
                logger.debug(
                    "refresh_sector_members: %s in %d current indices → chose %s (%s)",
                    symbol, len(unique_sectors), best[1], best[3] or "no date",
                )

        # ── Merge: baseline + precise (precise takes priority) ─────────────────
        sector_rows: list[tuple[str, str, str, int]] = []
        updated: dict[str, int] = {}

        # Baseline entries (symbols not covered by precise)
        for symbol, sw_idx in baseline.items():
            if symbol in precise:
                continue
            info = _SW_IDX_TO_INFO.get(sw_idx)
            if info:
                sector_code, sector_name = info
                sector_rows.append((symbol, sector_code, sector_name, sw_idx))
                updated[symbol] = sw_idx

        # Precise entries override
        for symbol, (sector_code, sector_name, sw_idx) in precise.items():
            sector_rows.append((symbol, sector_code, sector_name, sw_idx))
            updated[symbol] = sw_idx

        with db._conn:
            db._conn.execute("UPDATE instruments SET industry=?", (_INDUSTRY_UNKNOWN,))
            db._conn.execute("DELETE FROM instrument_sector_members")
            db._conn.executemany(
                """
                INSERT INTO instrument_sector_members
                    (symbol, sector_code, sector_name, industry_code, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                sector_rows,
            )
            db._conn.executemany(
                "UPDATE instruments SET industry=? WHERE symbol=?",
                [(sw_idx, symbol) for symbol, sw_idx in updated.items()],
            )

        if conflicted:
            # 申万2021调整时大量旧记录 out_date 未填，导致同一股票在两个当前指数里同时存在。
            # 已全部按 in_date 最新的那条解决，不是未映射，降为 DEBUG 避免刷屏。
            logger.debug(
                "refresh_sector_members: %d symbols in 2+ current indices, resolved by latest in_date",
                len(conflicted),
            )

        logger.info(
            "refresh_sector_members: baseline=%d precise=%d total=%d (multi-index=%d)",
            len(baseline), len(precise), len(updated), len(conflicted),
        )
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
