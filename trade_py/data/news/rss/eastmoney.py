"""EastMoney RSS feed descriptor and provider-specific source class."""

from __future__ import annotations

import re

from trade_py.data.news.rss.base import RssSource
from trade_py.intelligence.raw_record import RawRecord

FEED_NAME = "EastMoney"
FEED_PATH = "/eastmoney/report/macresearch"
FEED_DEFAULTS: dict = {
    "name": FEED_NAME,
    "path": FEED_PATH,
    "category": "portal",
    "region": "CN",
    "officialness": 3.0,
    "authority": 3.0,
    "quality": 3.0,
    "coverage": 3.5,
    "value": 3.0,
    "status": "trial",
    "enabled_default": True,
}

_EM_TAG_RE = re.compile(r"<em>(.*?)</em>", re.IGNORECASE | re.DOTALL)


class EastMoneyRssSource(RssSource):
    """EastMoney RSS with keyword extraction from <em> highlighted terms."""

    source_id = "rss_eastmoney"

    def _post_process_record(self, record: RawRecord) -> RawRecord:
        # Extract <em>-highlighted keywords from the raw text before HTML cleanup
        keywords = _EM_TAG_RE.findall(record.text)
        if keywords:
            record.meta["keywords"] = [k.strip() for k in keywords if k.strip()]
        record.meta["provider"] = "eastmoney"
        return record
