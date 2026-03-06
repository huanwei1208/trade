from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from trade_py.config.context import resolve_repo_path


@lru_cache(maxsize=1)
def load_defaults(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else resolve_repo_path("config/defaults.json")
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload
