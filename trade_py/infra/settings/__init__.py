"""Runtime configuration context and defaults for TradeDB."""

from trade_py.infra.settings.context import (
    ConfigContext,
    default_data_root,
    get_config_context,
    resolve_repo_path,
)


def load_defaults(path=None):
    """Load persisted defaults without importing the database on package import."""
    from trade_py.infra.settings.defaults import load_defaults as _load_defaults

    return _load_defaults(path)

__all__ = [
    "ConfigContext",
    "get_config_context",
    "default_data_root",
    "resolve_repo_path",
    "load_defaults",
]
