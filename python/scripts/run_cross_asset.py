#!/usr/bin/env python3
from __future__ import annotations

"""CLI for cross-asset data collection.

Usage:
    uv run python python/scripts/run_cross_asset.py [all|gold|fx|btc] [--data-root DATA]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_context import default_data_root
from trade_py.data.cross_asset_fetcher import fetch_all, fetch_btc, fetch_fx_cnh, fetch_gold

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-asset data fetcher")
    parser.add_argument("asset", nargs="?", default="all",
                        choices=["all", "gold", "fx", "btc"],
                        help="Which asset to fetch (default: all)")
    parser.add_argument("--data-root", default=str(default_data_root()), help="Data root directory")
    args = parser.parse_args()

    fn_map = {
        "gold": lambda: fetch_gold(args.data_root),
        "fx":   lambda: fetch_fx_cnh(args.data_root),
        "btc":  lambda: fetch_btc(args.data_root),
        "all":  lambda: fetch_all(args.data_root),
    }
    fn_map[args.asset]()


if __name__ == "__main__":
    main()
