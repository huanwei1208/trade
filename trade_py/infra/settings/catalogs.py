"""DB-first access helpers for legacy catalog payloads."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from trade_py.db.trade_db import TradeDB
from trade_py.infra.settings import default_data_root


def _active_data_root() -> Path:
    override = os.environ.get("TRADE_DATA_ROOT", "").strip()
    if override:
        return Path(override).expanduser()
    return default_data_root()


def load_catalog_payload(setting_key: str, fallback_path: str) -> Any:
    """Load a structured catalog payload from DB settings."""
    _ = fallback_path
    db = TradeDB(_active_data_root())
    try:
        payload = db.get_json(setting_key, None)
        if payload is not None:
            return payload
    except Exception:
        pass
    return None
