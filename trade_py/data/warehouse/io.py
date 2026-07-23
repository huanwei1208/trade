from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class WarehouseLayout:
    root: Path

    @classmethod
    def from_data_root(cls, data_root: str | Path) -> "WarehouseLayout":
        return cls(Path(data_root) / "warehouse")

    def layer_dir(self, layer: str) -> Path:
        return self.root / layer

    def table_path(self, layer: str, table: str) -> Path:
        return self.layer_dir(layer) / f"{table}.parquet"


def write_table(layout: WarehouseLayout, layer: str, table: str, frame: pd.DataFrame) -> Path:
    path = layout.table_path(layer, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def upsert_table(
    layout: WarehouseLayout,
    layer: str,
    table: str,
    frame: pd.DataFrame,
    *,
    key_cols: list[str],
) -> Path:
    path = layout.table_path(layer, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, frame], ignore_index=True)
    else:
        combined = frame.copy()
    if key_cols and not combined.empty:
        combined = combined.drop_duplicates(subset=key_cols, keep="last")
    combined.to_parquet(path, index=False)
    return path


def read_table(layout: WarehouseLayout, layer: str, table: str) -> pd.DataFrame:
    path = layout.table_path(layer, table)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)
