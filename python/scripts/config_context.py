from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent
_PYTHON_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = _PYTHON_ROOT.parent


@dataclass(frozen=True)
class ConfigContext:
    repo_root: Path
    python_root: Path
    data_root: Path

    def resolve(self, path: str | Path) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return self.repo_root / p


def get_config_context(data_root: str | Path | None = None) -> ConfigContext:
    if data_root is None:
        resolved_data_root = _REPO_ROOT / "data"
    else:
        p = Path(data_root)
        resolved_data_root = p if p.is_absolute() else (_REPO_ROOT / p)
    return ConfigContext(
        repo_root=_REPO_ROOT,
        python_root=_PYTHON_ROOT,
        data_root=resolved_data_root,
    )


def default_data_root() -> Path:
    return get_config_context().data_root


def resolve_repo_path(path: str | Path) -> Path:
    return get_config_context().resolve(path)
