"""Gelonghui RSS feed descriptor."""

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
