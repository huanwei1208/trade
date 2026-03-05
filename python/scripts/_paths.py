from __future__ import annotations

from pathlib import Path

from config_context import default_data_root, get_config_context, resolve_repo_path


def repo_root() -> Path:
    return get_config_context().repo_root
