from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.data.warehouse import WarehouseLayout, read_table


_ALLOWED_TABLES: dict[str, set[str]] = {
    "dim": {"dim_sector", "dim_topic", "dim_data_source", "dim_position"},
    "dws": {"dws_sector_topic_daily"},
    "ads": {
        "ads_data_signal_report",
        "ads_source_value_report",
        "ads_feature_value_report",
        "ads_association_result",
        "ads_hypothesis_validation_report",
        "ads_position_risk_signal",
        "ads_warehouse_validation_report",
    },
}


def list_research_tables(data_root: str | Path) -> dict[str, Any]:
    layout = WarehouseLayout.from_data_root(data_root)
    layers: list[dict[str, Any]] = []
    for layer, tables in _ALLOWED_TABLES.items():
        items: list[dict[str, Any]] = []
        for table in sorted(tables):
            path = layout.table_path(layer, table)
            row_count = 0
            if path.exists():
                row_count = int(len(pd.read_parquet(path)))
            items.append(
                {
                    "layer": layer,
                    "table": table,
                    "exists": path.exists(),
                    "row_count": row_count,
                    "path": str(path),
                }
            )
        layers.append({"layer": layer, "tables": items})
    return {"warehouse_root": str(layout.root), "layers": layers}


def read_research_table(
    data_root: str | Path,
    *,
    layer: str,
    table: str,
    limit: int = 100,
) -> dict[str, Any]:
    if layer not in _ALLOWED_TABLES or table not in _ALLOWED_TABLES[layer]:
        raise ValueError(f"unsupported research table: {layer}.{table}")
    layout = WarehouseLayout.from_data_root(data_root)
    frame = read_table(layout, layer, table)
    resolved_limit = max(1, min(int(limit or 100), 1000))
    return {
        "warehouse_root": str(layout.root),
        "layer": layer,
        "table": table,
        "row_count": int(len(frame)),
        "columns": list(frame.columns),
        "rows": frame.head(resolved_limit).to_dict(orient="records"),
    }
