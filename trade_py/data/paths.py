"""Central path constants for the trade data directory.

All code should import path helpers from here rather than hardcoding
directory names, to make directory reorganization a one-file change.

Standard layout (post-migration):
  data/
  ├── market/kline/, fund_flow/, fundamental/, cross_asset/, northbound/, index/, macro/
  ├── sentiment/bronze/, silver/, gold/
  ├── events/
  ├── models/
  ├── knowledge_graph/
  ├── briefs/
  └── .db/
      ├── trade.db
      ├── pipeline.duckdb
      └── feed.duckdb
"""
from __future__ import annotations

from pathlib import Path


def market_dir(data_root: str | Path, dataset: str) -> Path:
    """Return data_root/market/{dataset}/."""
    return Path(data_root) / "market" / dataset


def db_path(data_root: str | Path, name: str) -> Path:
    """Return data_root/.db/{name}, creating the .db directory if needed."""
    p = Path(data_root) / ".db"
    p.mkdir(parents=True, exist_ok=True)
    return p / name


def sentiment_dir(data_root: str | Path, tier: str) -> Path:
    """Return data_root/sentiment/{tier}/  where tier = bronze | silver | gold."""
    return Path(data_root) / "sentiment" / tier


# ── Convenience lambdas ────────────────────────────────────────────────────────

KLINE_DIR       = lambda root: market_dir(root, "kline")        # noqa: E731
FUND_FLOW_DIR   = lambda root: market_dir(root, "fund_flow")    # noqa: E731
CROSS_ASSET_DIR = lambda root: market_dir(root, "cross_asset")  # noqa: E731
INDEX_DIR       = lambda root: market_dir(root, "index")        # noqa: E731
MACRO_DIR       = lambda root: market_dir(root, "macro")        # noqa: E731
FUNDAMENTAL_DIR = lambda root: market_dir(root, "fundamental")  # noqa: E731
NORTHBOUND_DIR  = lambda root: market_dir(root, "northbound")   # noqa: E731

TRADE_DB    = lambda root: db_path(root, "trade.db")        # noqa: E731
PIPELINE_DB = lambda root: db_path(root, "pipeline.duckdb") # noqa: E731
FEED_DB     = lambda root: db_path(root, "feed.duckdb")     # noqa: E731
