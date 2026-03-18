from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from trade_py.db.trade_db import TradeDB
from trade_py.infra.settings.context import default_data_root, resolve_repo_path


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _load_yaml_override() -> dict[str, Any]:
    configured = os.environ.get("TRADE_CONFIG_FILE", "").strip()
    if configured:
        target = Path(configured).expanduser()
    else:
        target = resolve_repo_path("config/trade.yaml")
    if not target.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _load_defaults_from_db() -> dict[str, Any]:
    data_root = os.environ.get("TRADE_DATA_ROOT", "").strip()
    resolved_root = Path(data_root).expanduser() if data_root else default_data_root()
    try:
        payload = TradeDB(resolved_root).get_json("config.defaults", None)
    except Exception:
        payload = None
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def load_defaults(path: str | Path | None = None) -> dict[str, Any]:
    defaults = _load_defaults_from_db()
    override = _load_yaml_override()
    return _deep_merge(defaults, override)
