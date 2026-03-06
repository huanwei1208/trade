"""Gelonghui RSS feed descriptor and provider-specific source class."""

from __future__ import annotations

from trade_py.data.news.rss.base import RssSource
from trade_py.meta.records.raw import RawRecord

FEED_NAME = "Gelonghui"
FEED_PATH = "/gelonghui/live"
FEED_DEFAULTS: dict = {
    "name": FEED_NAME,
    "path": FEED_PATH,
    "category": "market",
    "region": "CN/HK",
    "officialness": 3.0,
    "authority": 3.5,
    "quality": 3.5,
    "coverage": 4.0,
    "value": 3.5,
    "status": "trial",
    "enabled_default": True,
}

_HK_KEYWORDS = frozenset(["港股", "恒指", "恒生", "港元", "联交所", "香港"])
_US_KEYWORDS = frozenset(["美股", "纳指", "纳斯达克", "道琼斯", "标普", "美联储", "NYSE", "NASDAQ"])


class GelonghuiRssSource(RssSource):
    """Gelonghui RSS with HK/US region tagging for offshore content filtering."""

    source_id = "rss_gelonghui"

    def _post_process_record(self, record: RawRecord) -> RawRecord:
        combined = record.title + " " + record.text
        has_hk = any(kw in combined for kw in _HK_KEYWORDS)
        has_us = any(kw in combined for kw in _US_KEYWORDS)
        if has_hk and has_us:
            region = "HK/US"
        elif has_hk:
            region = "HK"
        elif has_us:
            region = "US"
        else:
            region = "CN"
        record.meta["region"] = region
        record.meta["provider"] = "gelonghui"
        return record
