"""Central path constants for the trade data directory.

All code should import path helpers from here rather than hardcoding
directory names, to make directory reorganization a one-file change.

Standard layout (post-migration):
  data/
  ├── market/kline/, fund_flow/, fundamental/, crypto/, fx/, commodity/,
  │   northbound/, index/, macro/
  ├── sentiment/bronze/, silver/, gold/
  ├── events/
  ├── models/
  ├── knowledge_graph/
  └── .db/
      ├── trade.db
      ├── pipeline.duckdb
      └── feed.duckdb
"""
from __future__ import annotations

import warnings
from pathlib import Path


def market_dir(data_root: str | Path, dataset: str) -> Path:
    """Return data_root/market/{dataset}/, creating the directory if needed."""
    p = Path(data_root) / "market" / dataset
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path(data_root: str | Path, name: str) -> Path:
    """Return data_root/.db/{name}, creating the .db directory if needed."""
    p = Path(data_root) / ".db"
    p.mkdir(parents=True, exist_ok=True)
    return p / name


def sentiment_dir(data_root: str | Path, tier: str) -> Path:
    """Return data_root/sentiment/{tier}/  where tier = bronze | silver | gold."""
    return Path(data_root) / "sentiment" / tier


# ── Per-asset-class market dirs (post-asset-split) ────────────────────────────
# Each returns data_root/market/<class>/ creating the directory on demand.

def _crypto_dir(root: str | Path) -> Path:
    return market_dir(root, "crypto")


def _fx_dir(root: str | Path) -> Path:
    return market_dir(root, "fx")


def _commodity_dir(root: str | Path) -> Path:
    return market_dir(root, "commodity")


# ── Deprecated cross_asset alias ──────────────────────────────────────────────
# Retained for backwards compatibility. Emits DeprecationWarning on use so that
# any remaining callers can be migrated.

def _cross_asset_dir(root: str | Path) -> Path:
    warnings.warn(
        "CROSS_ASSET_DIR is deprecated; use CRYPTO_DIR / FX_DIR / COMMODITY_DIR instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return market_dir(root, "cross_asset")


# ── Convenience lambdas / callables ───────────────────────────────────────────

KLINE_DIR        = lambda root: market_dir(root, "kline")        # noqa: E731
KLINE_MANIFEST   = lambda root: market_dir(root, "kline") / "_manifest.json"  # noqa: E731
FUND_FLOW_DIR    = lambda root: market_dir(root, "fund_flow")    # noqa: E731
CRYPTO_DIR       = _crypto_dir
FX_DIR           = _fx_dir
COMMODITY_DIR    = _commodity_dir
CROSS_ASSET_DIR  = _cross_asset_dir  # deprecated, emits DeprecationWarning
INDEX_DIR        = lambda root: market_dir(root, "index")        # noqa: E731
MACRO_DIR        = lambda root: market_dir(root, "macro")        # noqa: E731
FUNDAMENTAL_DIR  = lambda root: market_dir(root, "fundamental")  # noqa: E731
NORTHBOUND_DIR   = lambda root: market_dir(root, "northbound")   # noqa: E731

TRADE_DB    = lambda root: db_path(root, "trade.db")        # noqa: E731
PIPELINE_DB = lambda root: db_path(root, "pipeline.duckdb") # noqa: E731
FEED_DB     = lambda root: db_path(root, "feed.duckdb")     # noqa: E731
