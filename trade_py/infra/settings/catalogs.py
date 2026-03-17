"""DB-first access helpers for legacy catalog payloads.

Runtime should read catalogs from DB settings.
File fallbacks only exist as migration baselines and are opportunistically
imported back into DB on first use if missing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from trade_py.db.trade_db import TradeDB
from trade_py.infra.settings import default_data_root, resolve_repo_path


def _active_data_root() -> Path:
    override = os.environ.get("TRADE_DATA_ROOT", "").strip()
    if override:
        return Path(override).expanduser()
    return default_data_root()


def load_catalog_payload(setting_key: str, fallback_path: str) -> Any:
    """Load a structured catalog payload from DB settings.

    If the DB setting is absent, a repository file can be used once as a
    migration baseline; the loaded payload is then persisted back into DB.
    """
    db = TradeDB(_active_data_root())
    try:
        payload = db.get_json(setting_key, None)
        if payload is not None:
            return payload
    except Exception:
        pass
    target = resolve_repo_path(fallback_path)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        db.set(setting_key, payload, value_type="json", category="catalog")
    except Exception:
        pass
    return payload
