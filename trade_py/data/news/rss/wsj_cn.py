"""WSJ Chinese (wallstreetcn) RSS feed descriptor and provider-specific source class."""

from __future__ import annotations

from trade_py.data.news.rss.base import RssSource
from trade_py.intelligence.raw_record import RawRecord

FEED_NAME = "WSJ"
FEED_PATH = "/wallstreetcn/news/articles"
FEED_DEFAULTS: dict = {
    "name": FEED_NAME,
    "path": FEED_PATH,
    "category": "macro",
    "region": "CN",
    "officialness": 3.5,
    "authority": 4.0,
    "quality": 4.0,
    "coverage": 3.5,
    "value": 4.0,
    "status": "trial",
    "enabled_default": True,
}

# Elevated authority weight for scoring/aggregation downstream
_AUTHORITY_WEIGHT = 1.5


class WsjCnRssSource(RssSource):
    """WSJ Chinese RSS with Global region tag and elevated authority weight."""

    source_id = "rss_wsj_cn"

    def _post_process_record(self, record: RawRecord) -> RawRecord:
        record.meta["region"] = "Global"
        record.meta["provider"] = "wsj_cn"
        record.meta["authority_weight"] = _AUTHORITY_WEIGHT
        return record
