"""Tushare news source — historical Bronze-layer backfill.

Uses pro.news() to fetch article headlines + content for historical periods.
Unlike RSS (real-time only), Tushare news can backfill past dates.

Output records are compatible with the existing NewsRecord schema.

Supported sources (Tushare src parameter):
    sina        — 新浪财经
    eastmoney   — 东方财富
    wallstreetcn — 华尔街见闻

Usage:
    from trade_py.data.news.tushare import TushareNewsSource
    src = TushareNewsSource(data_root="data", src="sina")
    records = src.fetch(since=datetime(2025,1,1), until=datetime(2025,3,1))
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterator

import pandas as pd

logger = logging.getLogger(__name__)

_VALID_SRCS = {"sina", "eastmoney", "wallstreetcn"}


class TushareNewsSource:
    """Fetch historical news from Tushare pro.news()."""

    source_id = "tushare_news"

    def __init__(self, data_root: str = "data", src: str = "sina") -> None:
        if src not in _VALID_SRCS:
            raise ValueError(f"Invalid src {src!r}. Choose from {_VALID_SRCS}")
        self.data_root = data_root
        self.src = src

    def fetch(self, since: datetime, until: datetime) -> list[dict]:
        """Fetch news records in [since, until].

        Tushare pro.news() returns max ~1000 records per call, so we split by day
        for dense periods.

        Returns list of dicts with keys:
            datetime, title, content, source, url
        """
        from trade_py.data.market.tushare_client import get_pro_api
        pro = get_pro_api(self.data_root)

        records: list[dict] = []
        current = since.date()
        end_date = until.date()

        # Walk day by day (Tushare news API is date-ranged)
        chunk_days = 7  # fetch 1 week at a time
        while current <= end_date:
            chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
            start_str = current.strftime("%Y%m%d") + "000000"
            end_str   = chunk_end.strftime("%Y%m%d") + "235959"
            try:
                raw = pro.call(
                    "news",
                    src=self.src,
                    start_date=start_str,
                    end_date=end_str,
                )
                if raw is not None and not raw.empty:
                    records.extend(_parse_raw(raw, self.src))
            except Exception as exc:
                logger.warning("TushareNewsSource fetch failed %s-%s: %s", current, chunk_end, exc)
            current = chunk_end + timedelta(days=1)

        logger.info("TushareNewsSource: fetched %d records from %s to %s (src=%s)",
                    len(records), since.date(), until.date(), self.src)
        return records


def _parse_raw(raw: pd.DataFrame, source: str) -> list[dict]:
    records = []
    for _, row in raw.iterrows():
        pub_str = str(row.get("datetime", "")).strip()
        try:
            dt = pd.to_datetime(pub_str)
        except Exception:
            continue
        title   = str(row.get("title",   "")).strip()
        content = str(row.get("content", "")).strip()
        url     = str(row.get("url",     "")).strip()
        if not title:
            continue
        records.append({
            "datetime": dt.to_pydatetime(),
            "title":    title,
            "content":  content,
            "source":   source,
            "url":      url,
        })
    return records
