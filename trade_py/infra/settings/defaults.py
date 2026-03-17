from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from trade_py.infra.settings.context import resolve_repo_path


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


@lru_cache(maxsize=1)
def load_defaults(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else resolve_repo_path("config/defaults.json")
    defaults: dict[str, Any] = {}
    if not target.exists():
        defaults = {}
    else:
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            defaults = payload
    override = _load_yaml_override()
    return _deep_merge(defaults, override)
