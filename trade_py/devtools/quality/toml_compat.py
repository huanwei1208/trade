"""TOML reader compatible with every supported Python version."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

__all__ = ["tomllib"]
