#!/usr/bin/env python3
from __future__ import annotations

"""CLI for morning brief generation.

Usage:
    uv run python python/scripts/morning_brief.py [--data-root DATA] [--date YYYY-MM-DD]

Typically scheduled at 09:10 each trading day.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_context import default_data_root
from trade_py.journal.morning_brief import generate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Morning brief generator")
    parser.add_argument("--data-root", default=str(default_data_root()), help="Data root directory")
    parser.add_argument("--date", default=None, help="Brief date (YYYY-MM-DD, default: today)")
    args = parser.parse_args()

    path = generate(args.data_root, args.date)
    print(f"\nMorning brief saved to: {path}")
    print("\nPreview:")
    print("-" * 60)
    content = Path(path).read_text(encoding="utf-8")
    print(content[:1000])
    if len(content) > 1000:
        print(f"\n... ({len(content) - 1000} more characters)")


if __name__ == "__main__":
    main()
