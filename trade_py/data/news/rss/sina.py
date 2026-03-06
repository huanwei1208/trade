"""Sina Finance RSS feed descriptor and provider-specific source class."""

from __future__ import annotations

from trade_py.data.news.rss.base import RssSource
from trade_py.meta.records.raw import RawRecord

FEED_NAME = "Sina"
FEED_PATH = "/sina/finance/rollnews"
FEED_DEFAULTS: dict = {
    "name": FEED_NAME,
    "path": FEED_PATH,
    "category": "portal",
    "region": "CN",
    "officialness": 3.0,
    "authority": 3.0,
    "quality": 3.0,
    "coverage": 3.5,
    "value": 2.5,
    "status": "trial",
    "enabled_default": True,
}


class SinaRssSource(RssSource):
    """Sina Finance RSS with provider-specific title cleanup.

    Strips the 【快讯】 prefix common in Sina flash-news titles
    and tags records with provider/category metadata.
    """

    source_id = "rss_sina"

    def _post_process_record(self, record: RawRecord) -> RawRecord:
        record.title = record.title.removeprefix("【快讯】").strip()
        record.meta["provider"] = "sina"
        record.meta["category"] = "portal"
        return record
