from __future__ import annotations

from pathlib import Path

import pandas as pd

from trade_py.data.warehouse import (
    WarehouseLayout,
    build_ads_data_signal_report,
    build_ads_source_value_report,
    build_dwd_articles,
    build_dws_sector_topic_daily,
    import_rss_catalog_rows,
    normalize_ods_rss_entries,
    normalize_semantic_value,
    read_table,
    write_table,
)


def test_import_rss_catalog_rows_keeps_first_category_and_dedupes_repeated_sources() -> None:
    rows = [
        {"名称": "科技 / AI / 工程", "rss link": ""},
        {"名称": "OpenAI Blog", "rss link": "https://openai.com/news/rss.xml"},
        {"名称": "财经 / 市场 / 商业", "rss link": ""},
        {"名称": "CNBC Finance:", "rss link": "https://www.cnbc.com/id/10000664/device/rss/rss.html"},
        {"名称": "其他", "rss link": ""},
        {"名称": "OpenAI Blog", "rss link": "https://openai.com/news/rss.xml"},
    ]

    catalog = import_rss_catalog_rows(rows)

    assert catalog["url"].tolist() == [
        "https://openai.com/news/rss.xml",
        "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    ]
    openai = catalog[catalog["source_id"] == "rss_openai_blog"].iloc[0]
    assert openai["category"] == "科技 / AI / 工程"
    assert openai["sector_tags"] == "ai"
    assert openai["language"] == "en"
    assert "AI" in openai["value_hypothesis"]


def test_ods_normalization_preserves_dirty_rows_instead_of_filtering() -> None:
    rows = [
        {
            "source_id": "rss_openai_blog",
            "url": "https://example.com/ai",
            "title": "OpenAI announces new GPU infrastructure",
            "summary": "AI capex rises",
            "published_at": "2026-07-06T08:00:00+00:00",
        },
        {
            "source_id": "rss_bad",
            "url": "",
            "title": "",
            "summary": "",
            "published_at": "not-a-date",
        },
    ]

    ods = normalize_ods_rss_entries(rows)

    assert len(ods) == 2
    assert ods.iloc[1]["source_id"] == "rss_bad"
    assert ods.iloc[1]["url"] is None
    assert ods.iloc[1]["title_raw"] == ""


def test_semantic_normalization_maps_labels_but_nulls_invalid_numeric_values() -> None:
    assert normalize_semantic_value("差评", "sentiment_label") == ("negative", None)
    assert normalize_semantic_value("差评", "rating_score") == (None, "invalid_type")
    assert normalize_semantic_value("1.25", "ratio_value") == (1.25, None)
    assert normalize_semantic_value("--", "metric_value") == (None, "empty_string")


def test_build_dwd_articles_records_quality_semantic_nulls_and_sector_relevance() -> None:
    ods = normalize_ods_rss_entries(
        [
            {
                "source_id": "rss_openai_blog",
                "url": "https://example.com/ai",
                "title": "OpenAI and NVIDIA expand AI cloud capex",
                "summary": "GPU demand and cloud infrastructure rise.",
                "published_at": "2026-07-06T08:00:00+00:00",
                "rating": "差评",
            },
            {
                "source_id": "rss_noise",
                "url": "https://example.com/login",
                "title": "Sign in",
                "summary": "Enable cookies to continue",
                "published_at": "2026-07-06T08:00:00+00:00",
            },
        ]
    )

    articles, quality, semantic, relevance = build_dwd_articles(ods)

    assert len(articles) == 2
    ai_row = articles[articles["source_id"] == "rss_openai_blog"].iloc[0]
    assert ai_row["quality_status"] == "accepted"
    assert bool(ai_row["is_usable"]) is True

    noise_row = articles[articles["source_id"] == "rss_noise"].iloc[0]
    assert noise_row["quality_status"] == "quarantined"
    assert "boilerplate_or_error_page" in quality[quality["article_id"] == noise_row["article_id"]]["check_name"].tolist()

    semantic_by_field = {
        row["field_name"]: row
        for row in semantic[semantic["article_id"] == ai_row["article_id"]].to_dict(orient="records")
    }
    assert semantic_by_field["sentiment_label"]["normalized_value"] == "negative"
    assert semantic_by_field["rating_score"]["normalized_value"] is None
    assert semantic_by_field["rating_score"]["null_reason"] == "invalid_type"

    ai_relevance = relevance[(relevance["article_id"] == ai_row["article_id"]) & (relevance["sector"] == "ai")]
    assert not ai_relevance.empty
    assert bool(ai_relevance.iloc[0]["is_relevant"]) is True


def test_dws_and_ads_surface_ratio_based_value_signals() -> None:
    raw_rows = []
    for day, count in [("2026-07-01", 1), ("2026-07-02", 1), ("2026-07-03", 4)]:
        for idx in range(count):
            raw_rows.append(
                {
                    "source_id": "rss_openai_blog",
                    "url": f"https://example.com/{day}/{idx}",
                    "title": "AI GPU cloud capex expands",
                    "summary": "OpenAI NVIDIA AI infrastructure",
                    "published_at": f"{day}T08:00:00+00:00",
                }
            )
    ods = normalize_ods_rss_entries(raw_rows)
    articles, _, _, relevance = build_dwd_articles(ods)

    dws = build_dws_sector_topic_daily(articles, relevance, lookback_days=20)
    ads = build_ads_data_signal_report(dws)
    source_value = build_ads_source_value_report(articles, relevance)

    latest_ai = dws[(dws["date"] == "2026-07-03") & (dws["sector"] == "ai")].iloc[0]
    assert latest_ai["article_count"] == 4
    assert latest_ai["article_count_ratio"] > 1.5

    assert not ads.empty
    signal = ads[ads["sector"] == "ai"].iloc[-1]
    assert signal["signal_type"] == "topic_burst"
    assert "baseline" in signal["value_reason"]

    value_row = source_value[source_value["source_id"] == "rss_openai_blog"].iloc[0]
    assert value_row["sector"] == "ai"
    assert value_row["verdict"] in {"promote", "monitor"}
    assert "produced" in value_row["value_reason"]


def test_warehouse_io_uses_layered_paths_inside_project_data_root(tmp_path: Path) -> None:
    layout = WarehouseLayout.from_data_root(tmp_path)
    frame = pd.DataFrame([{"sector": "ai", "name": "AI"}])

    path = write_table(layout, "dim", "dim_sector", frame)
    loaded = read_table(layout, "dim", "dim_sector")

    assert path == tmp_path / "warehouse" / "dim" / "dim_sector.parquet"
    assert loaded.to_dict(orient="records") == [{"sector": "ai", "name": "AI"}]
