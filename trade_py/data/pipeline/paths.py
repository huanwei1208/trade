from __future__ import annotations

from datetime import date
from pathlib import Path


def bronze_path(data_root: str | Path, source_id: str, d: date) -> Path:
    root = Path(data_root)
    return (
        root
        / "sentiment"
        / "bronze"
        / source_id
        / f"{d.year:04d}"
        / f"{d.month:02d}"
        / f"{d.isoformat()}.parquet"
    )


def bronze_root(data_root: str | Path) -> Path:
    return Path(data_root) / "sentiment" / "bronze"
