"""AkShare-based historical news sources for Bronze-layer backfill.

Provides DataSource-compatible wrappers around akshare news APIs.
Unlike RSS/CLS (real-time only), these support arbitrary historical dates.

Available sources:
    CctvNewsSource      — 央视新闻（宏观政策/国内财经）
    EastMoneyNewsSource — 东方财富个股新闻（需要 symbol 列表）

Usage:
    src = CctvNewsSource()
    records = src.fetch(since=datetime(2026,2,18), until=datetime(2026,2,18,23,59))
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from trade_py.intelligence.raw_record import RawRecord

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


class CctvNewsSource:
    """央视新闻历史抓取（通过 akshare.news_cctv）。

    Coverage: arbitrary historical dates.
    Content:  宏观政策、国内财经、产业政策等，适合宏观事件情绪分析。
    Volume:   ~10-20 条/天。
    """

    source_id: str = "cctv"
    data_type: Literal["news"] = "news"

    def fetch(self, since: datetime, until: datetime,
              known_hashes: set[str] | None = None,
              progress_cb=None) -> list[RawRecord]:
        """Fetch CCTV news for each calendar day in [since, until]."""
        import akshare as ak

        since_cst = since.astimezone(CST) if since.tzinfo else since.replace(tzinfo=CST)
        until_cst = until.astimezone(CST) if until.tzinfo else until.replace(tzinfo=CST)

        known = known_hashes or set()
        records: list[RawRecord] = []

        cur = since_cst.date()
        end = until_cst.date()
        while cur <= end:
            date_str = cur.strftime("%Y%m%d")
            try:
                df = ak.news_cctv(date=date_str)
                if progress_cb:
                    progress_cb(f"[cctv] {cur}: {len(df)} articles")
                for _, row in df.iterrows():
                    title   = str(row.get("title",   "")).strip()
                    content = str(row.get("content", "")).strip()
                    if not title:
                        continue
                    # CCTV API only gives date; set published_at to noon CST
                    pub = datetime(cur.year, cur.month, cur.day, 12, 0, 0, tzinfo=CST)
                    rec = RawRecord(
                        source_id="cctv",
                        data_type="news",
                        published_at=pub,
                        title=title,
                        text=content,
                        url="",
                    )
                    if rec.content_hash not in known:
                        records.append(rec)
            except Exception as exc:
                logger.warning("CctvNewsSource fetch failed %s: %s", cur, exc)

            cur += timedelta(days=1)

        logger.info("CctvNewsSource: %d records from %s to %s",
                    len(records), since_cst.date(), until_cst.date())
        return records

    def health_check(self) -> dict:
        try:
            import akshare as ak
            from datetime import date
            yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
            df = ak.news_cctv(date=yesterday)
            return {"source_id": self.source_id, "healthy": True,
                    "latest_articles": len(df)}
        except Exception as e:
            return {"source_id": self.source_id, "healthy": False, "error": str(e)}


class EastMoneyStockNewsSource:
    """东方财富个股新闻（通过 akshare.stock_news_em）。

    Coverage: historical per-symbol news.
    Usage:    需提供 symbols 列表，适合补充特定股票的新闻。
    """

    source_id: str = "eastmoney_stock"
    data_type: Literal["news"] = "news"

    def __init__(self, symbols: list[str] | None = None) -> None:
        self.symbols = symbols or []

    def fetch(self, since: datetime, until: datetime,
              known_hashes: set[str] | None = None,
              progress_cb=None) -> list[RawRecord]:
        import akshare as ak
        import pandas as pd

        since_cst = since.astimezone(CST) if since.tzinfo else since.replace(tzinfo=CST)
        until_cst = until.astimezone(CST) if until.tzinfo else until.replace(tzinfo=CST)
        known = known_hashes or set()
        records: list[RawRecord] = []

        for symbol in self.symbols:
            code = symbol.split(".")[0]
            try:
                df = ak.stock_news_em(symbol=code)
                if df.empty:
                    continue
                # Filter by date range
                time_col = "发布时间" if "发布时间" in df.columns else df.columns[0]
                df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
                df = df.dropna(subset=[time_col])
                df = df[
                    (df[time_col] >= since_cst.replace(tzinfo=None)) &
                    (df[time_col] <= until_cst.replace(tzinfo=None))
                ]
                for _, row in df.iterrows():
                    title = str(row.get("新闻标题", row.get("title", ""))).strip()
                    content = str(row.get("新闻内容", row.get("content", ""))).strip()
                    url = str(row.get("新闻链接", row.get("url", ""))).strip()
                    if not title:
                        continue
                    pub_raw = row[time_col]
                    pub = pub_raw.to_pydatetime().replace(tzinfo=CST)
                    rec = RawRecord(
                        source_id="eastmoney_stock",
                        data_type="news",
                        published_at=pub,
                        title=title,
                        text=content,
                        url=url,
                    )
                    if rec.content_hash not in known:
                        records.append(rec)
                if progress_cb:
                    progress_cb(f"[eastmoney_stock] {symbol}: {len(df)} articles in range")
            except Exception as exc:
                logger.warning("EastMoneyStockNewsSource %s failed: %s", symbol, exc)

        return records

    def health_check(self) -> dict:
        try:
            import akshare as ak
            df = ak.stock_news_em(symbol="000001")
            return {"source_id": self.source_id, "healthy": True,
                    "latest_articles": len(df)}
        except Exception as e:
            return {"source_id": self.source_id, "healthy": False, "error": str(e)}
