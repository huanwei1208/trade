from __future__ import annotations

from pathlib import Path

import pandas as pd

from trade_py.data.warehouse import (
    WarehouseLayout,
    ControlledFetchPolicy,
    build_dim_sector,
    build_dim_topic,
    build_ads_association_result,
    build_ads_data_signal_report,
    build_ads_feature_value_report,
    build_ads_hypothesis_validation_report,
    build_ads_position_risk_signal,
    build_ads_source_value_report,
    build_dwd_articles,
    build_dws_sector_topic_daily,
    import_rss_catalog_rows,
    controlled_fetch_rss_sources,
    materialize_rss_research_loop,
    normalize_ods_rss_entries,
    normalize_position_rows,
    normalize_semantic_value,
    read_table,
    write_table,
)
from trade_py.cli import data as data_cli


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


def test_local_research_source_catalog_is_versioned_and_importable() -> None:
    catalog = Path("trade_py/infra/config/research_sources.csv")

    rows = import_rss_catalog_rows(pd.read_csv(catalog))

    assert catalog.exists()
    assert {"ai", "bank", "crypto"} <= set(",".join(rows["sector_tags"]).split(","))
    assert "https://openai.com/news/rss.xml" in set(rows["url"])


def test_controlled_fetch_rss_sources_records_attempts_and_entries() -> None:
    catalog_rows = [
        {"名称": "科技 / AI / 工程", "rss link": ""},
        {"名称": "OpenAI Blog", "rss link": "https://openai.com/news/rss.xml"},
    ]
    payload = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>Demo</title>
      <item>
        <title>OpenAI NVIDIA AI cloud capex expands</title>
        <link>https://example.com/ai/1</link>
        <description>GPU demand and cloud infrastructure rise</description>
        <pubDate>Fri, 03 Jul 2026 08:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    dim_sources, attempts, entries = controlled_fetch_rss_sources(
        catalog_rows,
        policy=ControlledFetchPolicy(min_interval_seconds=0.0, timeout_seconds=1),
        fetcher=lambda _url, _timeout: payload,
    )

    assert dim_sources.iloc[0]["source_id"] == "rss_openai_blog"
    assert attempts.iloc[0]["status"] == "ok"
    assert attempts.iloc[0]["entries"] == 1
    assert entries.iloc[0]["source_id"] == "rss_openai_blog"
    assert "OpenAI" in entries.iloc[0]["title"]


def test_controlled_fetch_rss_sources_supports_skip_and_limit_batches() -> None:
    catalog_rows = [
        {"名称": "科技 / AI / 工程", "rss link": ""},
        {"名称": "OpenAI Blog", "rss link": "https://openai.com/news/rss.xml"},
        {"名称": "Google AI Blog", "rss link": "https://blog.google/technology/ai/rss/"},
        {"名称": "财经 / 市场 / 商业", "rss link": ""},
        {"名称": "CNBC Finance", "rss link": "https://www.cnbc.com/id/10000664/device/rss/rss.html"},
    ]

    dim_sources, attempts, entries = controlled_fetch_rss_sources(
        catalog_rows,
        policy=ControlledFetchPolicy(skip_sources=1, max_sources=1, dry_run=True),
    )

    assert dim_sources["source_id"].tolist() == ["rss_google_ai_blog"]
    assert attempts.iloc[0]["status"] == "dry_run"
    assert entries.empty


def test_research_profiles_define_three_first_class_analysis_domains() -> None:
    sectors = build_dim_sector()
    topics = build_dim_topic()

    assert sectors["sector"].tolist() == ["crypto", "ai", "bank"]
    assert set(topics["sector"]) == {"crypto", "ai", "bank"}
    assert {"cloud_capex", "credit_risk", "regulation"} <= set(topics["topic"])
    assert sectors["purpose"].str.len().min() > 20


def test_position_context_links_research_signals_without_trade_actions() -> None:
    positions = normalize_position_rows(
        [
            {
                "asset_id": "NVDA",
                "asset_name": "NVIDIA",
                "sector": "ai",
                "thesis": "AI compute demand",
                "risk_notes": "capex slowdown",
            }
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "date": "2026-07-03",
                "sector": "ai",
                "signal_type": "topic_burst",
                "target_id": "ai",
                "signal_strength": "high",
                "validation_status": "candidate",
                "value_reason": "AI article volume is 3.00x baseline.",
            }
        ]
    )

    risk = build_ads_position_risk_signal(positions, signals)

    assert positions.iloc[0]["status"] == "watch"
    assert risk.iloc[0]["asset_id"] == "NVDA"
    assert risk.iloc[0]["manual_action"] == "needs_review"
    assert "Review manually" in risk.iloc[0]["reason"]


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
    feature_value = build_ads_feature_value_report(dws)
    association = build_ads_association_result(dws)
    hypothesis = build_ads_hypothesis_validation_report(ads, association)
    source_value = build_ads_source_value_report(articles, relevance)

    latest_ai = dws[(dws["date"] == "2026-07-03") & (dws["sector"] == "ai")].iloc[0]
    assert latest_ai["article_count"] == 4
    assert latest_ai["article_count_ratio"] > 1.5

    assert not ads.empty
    signal = ads[ads["sector"] == "ai"].iloc[-1]
    assert signal["signal_type"] == "topic_burst"
    assert "baseline" in signal["value_reason"]
    assert {"evidence", "reason", "validation_status"} <= set(feature_value.columns)
    assert {"evidence", "reason", "validation_status"} <= set(association.columns)
    assert {"evidence", "reason", "validation_status"} <= set(hypothesis.columns)
    assert feature_value[feature_value["sector"] == "ai"].iloc[-1]["validation_status"] in {"candidate", "monitoring"}
    assert association[association["target_id"] == "ai"].iloc[-1]["driver_type"] == "topic"
    assert hypothesis[hypothesis["sector"] == "ai"].iloc[-1]["support_score"] >= 0

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


def test_materialize_rss_research_loop_accumulates_ods_by_entry_id(tmp_path: Path) -> None:
    catalog_rows = [
        {"名称": "科技 / AI / 工程", "rss link": ""},
        {"名称": "OpenAI Blog", "rss link": "https://openai.com/news/rss.xml"},
    ]
    first = [
        {
            "source_id": "rss_openai_blog",
            "url": "https://example.com/ai/1",
            "title": "OpenAI NVIDIA AI cloud capex expands",
            "summary": "GPU demand and cloud infrastructure rise",
            "published_at": "2026-07-01T08:00:00+00:00",
        }
    ]
    second = [
        first[0],
        {
            "source_id": "rss_openai_blog",
            "url": "https://example.com/ai/2",
            "title": "Google AI cloud infrastructure spending rises",
            "summary": "AI cloud capex and chips demand improve",
            "published_at": "2026-07-02T08:00:00+00:00",
        },
    ]

    materialize_rss_research_loop(tmp_path, catalog_rows=catalog_rows, rss_entries=first)
    materialize_rss_research_loop(tmp_path, catalog_rows=catalog_rows, rss_entries=second)

    layout = WarehouseLayout.from_data_root(tmp_path)
    ods = read_table(layout, "ods", "ods_rss_entry_raw")
    dwd = read_table(layout, "dwd", "dwd_article")
    validation = read_table(layout, "ads", "ads_warehouse_validation_report")

    assert len(ods) == 2
    assert len(dwd) == 2
    assert dict(zip(validation["check_name"], validation["row_count"]))["ods.raw_rows_retained"] == 2


def test_materialize_rss_research_loop_writes_layers_and_validation_report(tmp_path: Path) -> None:
    catalog_rows = [
        {"名称": "科技 / AI / 工程", "rss link": ""},
        {"名称": "OpenAI Blog", "rss link": "https://openai.com/news/rss.xml"},
    ]
    rss_entries = []
    for day, count in [("2026-07-01", 1), ("2026-07-02", 1), ("2026-07-03", 4)]:
        for idx in range(count):
            rss_entries.append(
                {
                    "source_id": "rss_openai_blog",
                    "url": f"https://example.com/{day}/{idx}",
                    "title": "OpenAI NVIDIA AI cloud capex expands",
                    "summary": "GPU demand and cloud infrastructure rise",
                    "published_at": f"{day}T08:00:00+00:00",
                    "rating": "差评" if day == "2026-07-03" and idx == 0 else "中性",
                }
            )
    rss_entries.append(
        {
            "source_id": "rss_noise",
            "url": "",
            "title": "",
            "summary": "",
            "published_at": "not-a-date",
            "rating": "差评",
        }
    )

    position_rows = [
        {
            "asset_id": "NVDA",
            "sector": "ai",
            "thesis": "AI compute demand",
            "risk_notes": "capex slowdown",
        }
    ]

    result = materialize_rss_research_loop(
        tmp_path,
        catalog_rows=catalog_rows,
        rss_entries=rss_entries,
        position_rows=position_rows,
    )
    layout = WarehouseLayout.from_data_root(tmp_path)

    expected_tables = {
        "dim.dim_sector",
        "dim.dim_topic",
        "dim.dim_position",
        "dim.dim_data_source",
        "ods.ods_rss_entry_raw",
        "dwd.dwd_article",
        "dwd.dwd_article_quality_check",
        "dwd.dwd_article_semantic_check",
        "dwd.dwd_article_sector_relevance",
        "dws.dws_sector_topic_daily",
        "ads.ads_data_signal_report",
        "ads.ads_source_value_report",
        "ads.ads_feature_value_report",
        "ads.ads_association_result",
        "ads.ads_hypothesis_validation_report",
        "ads.ads_position_risk_signal",
        "ads.ads_warehouse_validation_report",
    }
    assert expected_tables <= set(result.table_paths)
    assert all(path.exists() for path in result.table_paths.values())

    ods = read_table(layout, "ods", "ods_rss_entry_raw")
    semantic = read_table(layout, "dwd", "dwd_article_semantic_check")
    signals = read_table(layout, "ads", "ads_data_signal_report")
    feature_value = read_table(layout, "ads", "ads_feature_value_report")
    association = read_table(layout, "ads", "ads_association_result")
    hypothesis = read_table(layout, "ads", "ads_hypothesis_validation_report")
    position_risk = read_table(layout, "ads", "ads_position_risk_signal")
    validation = read_table(layout, "ads", "ads_warehouse_validation_report")

    assert len(ods) == len(rss_entries)
    assert (semantic["null_reason"] == "invalid_type").any()
    assert not signals.empty
    assert signals["value_reason"].str.contains("baseline").any()
    assert feature_value["reason"].str.len().gt(0).all()
    assert association["evidence"].str.len().gt(0).all()
    assert hypothesis["validation_status"].isin({"candidate", "monitoring"}).all()
    assert position_risk.iloc[0]["manual_action"] == "needs_review"

    statuses = dict(zip(validation["check_name"], validation["status"]))
    assert statuses["ods.raw_rows_retained"] == "pass"
    assert statuses["dwd.semantic_nulls_recorded"] == "pass"
    assert statuses["ads.value_reasons_present"] == "pass"


def test_data_cli_materialize_rss_runs_closed_loop_from_local_csv(tmp_path: Path, capsys) -> None:
    catalog = tmp_path / "feeds.csv"
    entries = tmp_path / "entries.csv"
    catalog.write_text(
        "\n".join(
            [
                "名称,rss link",
                "科技 / AI / 工程,",
                "OpenAI Blog,https://openai.com/news/rss.xml",
            ]
        ),
        encoding="utf-8",
    )
    entry_lines = ["source_id,url,title,summary,published_at,rating"]
    for day, count in [("2026-07-01", 1), ("2026-07-02", 1), ("2026-07-03", 4)]:
        for idx in range(count):
            rating = "差评" if day == "2026-07-03" and idx == 0 else "中性"
            entry_lines.append(
                f"rss_openai_blog,https://example.com/{day}/{idx},"
                f"OpenAI NVIDIA AI cloud capex expands,"
                f"GPU demand and cloud infrastructure rise,{day}T08:00:00+00:00,{rating}"
            )
    entries.write_text("\n".join(entry_lines), encoding="utf-8")
    positions = tmp_path / "positions.csv"
    positions.write_text(
        "\n".join(
            [
                "asset_id,asset_name,sector,thesis,risk_notes",
                "NVDA,NVIDIA,ai,AI compute demand,capex slowdown",
            ]
        ),
        encoding="utf-8",
    )

    rc = data_cli.main(
        [
            "warehouse",
            "materialize-rss",
            "--data-root",
            str(tmp_path),
            "--catalog",
            str(catalog),
            "--entries",
            str(entries),
            "--positions",
            str(positions),
        ]
    )
    captured = capsys.readouterr()
    layout = WarehouseLayout.from_data_root(tmp_path)
    validation = read_table(layout, "ads", "ads_warehouse_validation_report")
    position_risk = read_table(layout, "ads", "ads_position_risk_signal")

    assert rc == 0
    assert "warehouse_root=" in captured.out
    assert "ods.raw_rows_retained" in captured.out
    assert dict(zip(validation["check_name"], validation["status"]))["ads.value_reasons_present"] == "pass"
    assert position_risk.iloc[0]["manual_action"] == "needs_review"


def test_data_cli_fetch_rss_dry_run_writes_attempts_without_network(tmp_path: Path, capsys) -> None:
    catalog = tmp_path / "feeds.csv"
    catalog.write_text(
        "\n".join(
            [
                "名称,rss link",
                "科技 / AI / 工程,",
                "OpenAI Blog,https://openai.com/news/rss.xml",
            ]
        ),
        encoding="utf-8",
    )

    rc = data_cli.main(
        [
            "warehouse",
            "fetch-rss",
            "--data-root",
            str(tmp_path),
            "--catalog",
            str(catalog),
            "--dry-run",
            "--no-materialize",
            "--min-interval-seconds",
            "0",
        ]
    )
    captured = capsys.readouterr()
    layout = WarehouseLayout.from_data_root(tmp_path)
    attempts = read_table(layout, "ods", "ods_fetch_attempt")

    assert rc == 0
    assert "dry_run=True" in captured.out
    assert attempts.iloc[0]["status"] == "dry_run"
    assert attempts.iloc[0]["entries"] == 0
