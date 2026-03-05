#!/usr/bin/env python3
from __future__ import annotations

"""CLI for window quality scoring.

Usage:
    uv run python python/scripts/run_window_score.py [--data-root DATA] [--date YYYY-MM-DD]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_context import default_data_root
from trade_py.signals.window_scorer import score_watchlist

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Window quality scorer")
    parser.add_argument("--data-root", default=str(default_data_root()), help="Data root directory")
    parser.add_argument("--date", default=None, help="Score date (YYYY-MM-DD, default: today)")
    args = parser.parse_args()

    scores = score_watchlist(args.data_root, args.date)
    if not scores:
        print("No scores computed (watchlist empty or no data)")
        return

    print(f"\nWindow Scores — {args.date or 'today'}")
    print("-" * 30)
    for sym, score in sorted(scores.items(), key=lambda x: -x[1]):
        bar = "█" * (score // 10) + "░" * (10 - score // 10)
        label = "⭐ 建仓窗口" if score >= 75 else ("👀 观察" if score >= 60 else "⏸ 等待")
        print(f"  {sym:<15} {bar} {score:3d}  {label}")


if __name__ == "__main__":
    main()
