"""EastMoney RSS feed descriptor."""

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
