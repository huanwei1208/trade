"""Backward-compatible utilities for intelligence modules.

Deprecated: prefer imports from trade_py.utils.*
"""

from __future__ import annotations

from trade_py.utils.html import clean_html
from trade_py.utils.scoring import META_SCORE_WEIGHTS, meta_score

__all__ = ["META_SCORE_WEIGHTS", "meta_score", "clean_html"]
