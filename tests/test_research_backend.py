from __future__ import annotations

from pathlib import Path

from trade_py.data.warehouse import materialize_rss_research_loop
from trade_web.backend.research import list_research_tables, read_research_table


def _materialize_sample(root: Path) -> None:
    materialize_rss_research_loop(
        root,
        catalog_rows=[
            {"名称": "科技 / AI / 工程", "rss link": ""},
            {"名称": "OpenAI Blog", "rss link": "https://openai.com/news/rss.xml"},
        ],
        rss_entries=[
            {
                "source_id": "rss_openai_blog",
                "url": f"https://example.com/{day}/{idx}",
                "title": "OpenAI NVIDIA AI cloud capex expands",
                "summary": "GPU demand and cloud infrastructure rise",
                "published_at": f"{day}T08:00:00+00:00",
            }
            for day, total in (("2026-07-01", 1), ("2026-07-02", 1), ("2026-07-03", 4))
            for idx in range(total)
        ],
        position_rows=[{"asset_id": "NVDA", "sector": "ai", "thesis": "AI compute demand"}],
    )


def test_research_backend_lists_and_reads_allowed_warehouse_tables(tmp_path: Path) -> None:
    _materialize_sample(tmp_path)

    listing = list_research_tables(tmp_path)
    table = read_research_table(tmp_path, layer="ads", table="ads_data_signal_report", limit=5)

    assert listing["warehouse_root"].endswith("warehouse")
    layers = {item["layer"]: item["tables"] for item in listing["layers"]}
    assert any(row["table"] == "ads_data_signal_report" and row["exists"] for row in layers["ads"])
    assert next(row for row in layers["ads"] if row["table"] == "ads_data_signal_report")["row_count"] >= 1
    assert table["layer"] == "ads"
    assert table["table"] == "ads_data_signal_report"
    assert table["row_count"] >= 1
    assert "value_reason" in table["columns"]
    assert table["rows"][0]["validation_status"] == "candidate"


def test_research_backend_rejects_unsupported_tables(tmp_path: Path) -> None:
    _materialize_sample(tmp_path)

    try:
        read_research_table(tmp_path, layer="ods", table="ods_rss_entry_raw")
    except ValueError as exc:
        assert "unsupported research table" in str(exc)
    else:
        raise AssertionError("unsupported ODS table should not be exposed through research API")


def test_research_routes_are_registered() -> None:
    from trade_web import create_app

    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/api/research/warehouse/tables" in paths
    assert "/api/research/warehouse/{layer}/{table}" in paths
