"""WSJ Chinese (wallstreetcn) RSS feed descriptor."""

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
