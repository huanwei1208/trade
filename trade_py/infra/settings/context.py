from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ConfigContext:
    repo_root: Path
    data_root: Path

    def resolve(self, path: str | Path) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return self.repo_root / p


@lru_cache(maxsize=8)
def get_config_context(data_root: str | Path | None = None) -> ConfigContext:
    if data_root is None:
        resolved_data_root = _REPO_ROOT / "data"
    else:
        p = Path(data_root)
        resolved_data_root = p if p.is_absolute() else (_REPO_ROOT / p)

    return ConfigContext(
        repo_root=_REPO_ROOT,
        data_root=resolved_data_root,
    )


def default_data_root() -> Path:
    return get_config_context().data_root


def resolve_repo_path(path: str | Path) -> Path:
    return get_config_context().resolve(path)
