"""Shared low-level helpers for trade_py.db modules."""
from __future__ import annotations

import json
from typing import Any


def _json_loads_safe(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default
