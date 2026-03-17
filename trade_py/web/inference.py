"""Compatibility shim for legacy imports.

The web-facing inference runtime now lives in ``trade_web.inference``.
"""
from __future__ import annotations

from trade_web.inference import *  # noqa: F401,F403
