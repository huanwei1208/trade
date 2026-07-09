from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.data.warehouse.articles import build_dwd_articles, normalize_ods_rss_entries
from trade_py.data.warehouse.catalog import import_rss_catalog_rows
from trade_py.data.warehouse.io import WarehouseLayout, read_table, write_table
from trade_py.data.warehouse.profiles import build_dim_sector, build_dim_topic
from trade_py.data.warehouse.signals import (
    build_ads_association_result,
    build_ads_data_signal_report,
    build_ads_feature_value_report,
    build_ads_hypothesis_validation_report,
    build_ads_source_value_report,
    build_dws_sector_topic_daily,
)


_REQUIRED_TABLES: tuple[tuple[str, str], ...] = (
    ("dim", "dim_sector"),
    ("dim", "dim_topic"),
    ("dim", "dim_data_source"),
    ("ods", "ods_rss_entry_raw"),
    ("dwd", "dwd_article"),
    ("dwd", "dwd_article_quality_check"),
    ("dwd", "dwd_article_semantic_check"),
    ("dwd", "dwd_article_sector_relevance"),
    ("dws", "dws_sector_topic_daily"),
    ("ads", "ads_data_signal_report"),
    ("ads", "ads_source_value_report"),
    ("ads", "ads_feature_value_report"),
    ("ads", "ads_association_result"),
    ("ads", "ads_hypothesis_validation_report"),
)


@dataclass(frozen=True)
class WarehouseMaterializationResult:
    layout_root: Path
    table_paths: dict[str, Path]
    validation_report: pd.DataFrame

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout_root": str(self.layout_root),
            "table_paths": {key: str(value) for key, value in self.table_paths.items()},
            "validation_report": self.validation_report.to_dict(orient="records"),
        }


def _table_key(layer: str, table: str) -> str:
    return f"{layer}.{table}"


def _row_count(layout: WarehouseLayout, layer: str, table: str) -> int:
    frame = read_table(layout, layer, table)
    return int(len(frame))


def build_warehouse_validation_report(
    layout: WarehouseLayout,
    *,
    expected_ods_rows: int | None = None,
) -> pd.DataFrame:
    """Build a persisted validation report for the research warehouse loop.

    This validates concrete artifacts, not only function return values. It is
    intentionally table-oriented so users can query the result from DuckDB.
    """
    rows: list[dict[str, Any]] = []
    for layer, table in _REQUIRED_TABLES:
        path = layout.table_path(layer, table)
        exists = path.exists()
        count = _row_count(layout, layer, table) if exists else 0
        rows.append(
            {
                "check_name": f"{layer}.{table}.exists",
                "layer": layer,
                "table_name": table,
                "status": "pass" if exists else "fail",
                "row_count": count,
                "detail": str(path),
            }
        )

    if expected_ods_rows is not None:
        actual = _row_count(layout, "ods", "ods_rss_entry_raw")
        rows.append(
            {
                "check_name": "ods.raw_rows_retained",
                "layer": "ods",
                "table_name": "ods_rss_entry_raw",
                "status": "pass" if actual == expected_ods_rows else "fail",
                "row_count": actual,
                "detail": f"expected_ods_rows={expected_ods_rows}",
            }
        )

    semantic = read_table(layout, "dwd", "dwd_article_semantic_check")
    semantic_null_rows = 0
    if not semantic.empty and "null_reason" in semantic.columns:
        semantic_null_rows = int(semantic["null_reason"].notna().sum())
    rows.append(
        {
            "check_name": "dwd.semantic_nulls_recorded",
            "layer": "dwd",
            "table_name": "dwd_article_semantic_check",
            "status": "pass" if semantic_null_rows > 0 else "warn",
            "row_count": semantic_null_rows,
            "detail": "semantic NULL rows should exist when source fields contain invalid values",
        }
    )

    ads_signals = read_table(layout, "ads", "ads_data_signal_report")
    value_reason_rows = 0
    if not ads_signals.empty and "value_reason" in ads_signals.columns:
        value_reason_rows = int(ads_signals["value_reason"].fillna("").astype(str).str.len().gt(0).sum())
    rows.append(
        {
            "check_name": "ads.value_reasons_present",
            "layer": "ads",
            "table_name": "ads_data_signal_report",
            "status": "pass" if value_reason_rows > 0 else "warn",
            "row_count": value_reason_rows,
            "detail": "ADS signals should explain why the statistical structure may matter",
        }
    )
    return pd.DataFrame(rows)


def materialize_rss_research_loop(
    data_root: str | Path,
    *,
    catalog_rows: list[dict[str, Any]] | pd.DataFrame,
    rss_entries: list[dict[str, Any]] | pd.DataFrame,
) -> WarehouseMaterializationResult:
    """Materialize the first RSS research warehouse loop.

    Layers written:
    - DIM: normalized RSS source catalog
    - ODS: raw RSS entries, including malformed rows
    - DWD: article detail, quality, semantic, and sector relevance checks
    - DWS: sector/topic daily statistics
    - ADS: data signal and source value reports, plus validation report
    """
    layout = WarehouseLayout.from_data_root(data_root)
    table_paths: dict[str, Path] = {}

    table_paths[_table_key("dim", "dim_sector")] = write_table(
        layout, "dim", "dim_sector", build_dim_sector()
    )
    table_paths[_table_key("dim", "dim_topic")] = write_table(
        layout, "dim", "dim_topic", build_dim_topic()
    )

    dim_data_source = import_rss_catalog_rows(catalog_rows)
    table_paths[_table_key("dim", "dim_data_source")] = write_table(
        layout, "dim", "dim_data_source", dim_data_source
    )

    ods_rss = normalize_ods_rss_entries(rss_entries)
    table_paths[_table_key("ods", "ods_rss_entry_raw")] = write_table(
        layout, "ods", "ods_rss_entry_raw", ods_rss
    )

    dwd_article, quality, semantic, relevance = build_dwd_articles(ods_rss)
    table_paths[_table_key("dwd", "dwd_article")] = write_table(layout, "dwd", "dwd_article", dwd_article)
    table_paths[_table_key("dwd", "dwd_article_quality_check")] = write_table(
        layout, "dwd", "dwd_article_quality_check", quality
    )
    table_paths[_table_key("dwd", "dwd_article_semantic_check")] = write_table(
        layout, "dwd", "dwd_article_semantic_check", semantic
    )
    table_paths[_table_key("dwd", "dwd_article_sector_relevance")] = write_table(
        layout, "dwd", "dwd_article_sector_relevance", relevance
    )

    dws_sector_topic_daily = build_dws_sector_topic_daily(dwd_article, relevance)
    table_paths[_table_key("dws", "dws_sector_topic_daily")] = write_table(
        layout, "dws", "dws_sector_topic_daily", dws_sector_topic_daily
    )

    ads_data_signal = build_ads_data_signal_report(dws_sector_topic_daily)
    table_paths[_table_key("ads", "ads_data_signal_report")] = write_table(
        layout, "ads", "ads_data_signal_report", ads_data_signal
    )

    ads_source_value = build_ads_source_value_report(dwd_article, relevance)
    table_paths[_table_key("ads", "ads_source_value_report")] = write_table(
        layout, "ads", "ads_source_value_report", ads_source_value
    )

    ads_feature_value = build_ads_feature_value_report(dws_sector_topic_daily)
    table_paths[_table_key("ads", "ads_feature_value_report")] = write_table(
        layout, "ads", "ads_feature_value_report", ads_feature_value
    )

    ads_association = build_ads_association_result(dws_sector_topic_daily)
    table_paths[_table_key("ads", "ads_association_result")] = write_table(
        layout, "ads", "ads_association_result", ads_association
    )

    ads_hypothesis = build_ads_hypothesis_validation_report(ads_data_signal, ads_association)
    table_paths[_table_key("ads", "ads_hypothesis_validation_report")] = write_table(
        layout, "ads", "ads_hypothesis_validation_report", ads_hypothesis
    )

    validation = build_warehouse_validation_report(layout, expected_ods_rows=len(ods_rss))
    table_paths[_table_key("ads", "ads_warehouse_validation_report")] = write_table(
        layout, "ads", "ads_warehouse_validation_report", validation
    )
    return WarehouseMaterializationResult(
        layout_root=layout.root,
        table_paths=table_paths,
        validation_report=validation,
    )
