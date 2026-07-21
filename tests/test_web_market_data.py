from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from fastapi.routing import APIRoute

from trade_web.backend.market_data import read_symbol_sparkline


def _write_kline(path: Path, rows: list[tuple[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["date", "close"]).to_parquet(path, index=False)


def test_sparkline_prefers_flat_kline_and_filters_invalid_rows(tmp_path: Path) -> None:
    kline_root = tmp_path / "market" / "kline"
    _write_kline(
        kline_root / "000001_SZ.parquet",
        [
            ("2026-07-01", 9.0),
            ("2026-07-18", 10.0),
            ("invalid", 11.0),
            ("2026-07-20", 12.0),
            ("2026-07-22", 13.0),
        ],
    )
    _write_kline(
        kline_root / "2026-07" / "000001_SZ.parquet",
        [("2026-07-19", 99.0)],
    )

    assert read_symbol_sparkline(
        tmp_path,
        "000001.SZ",
        days=2,
        end_date=date(2026, 7, 21),
    ) == [
        {"date": "2026-07-18", "close": 10.0},
        {"date": "2026-07-20", "close": 12.0},
    ]


def test_sparkline_falls_back_to_sorted_monthly_kline_shards(tmp_path: Path) -> None:
    kline_root = tmp_path / "market" / "kline"
    _write_kline(
        kline_root / "2026-06" / "000001_SZ.parquet",
        [("2026-06-30", 9.0)],
    )
    _write_kline(
        kline_root / "2026-07" / "000001_SZ.parquet",
        [
            ("2026-07-18", 10.0),
            ("2026-07-20", 12.0),
        ],
    )

    assert read_symbol_sparkline(
        tmp_path,
        "000001.SZ",
        days=2,
        end_date=date(2026, 7, 21),
    ) == [
        {"date": "2026-07-18", "close": 10.0},
        {"date": "2026-07-20", "close": 12.0},
    ]


def test_sparkline_returns_empty_for_missing_or_incomplete_data(tmp_path: Path) -> None:
    assert read_symbol_sparkline(tmp_path, "000001.SZ") == []

    _write_kline(
        tmp_path / "market" / "kline" / "000001_SZ.parquet",
        [("2026-07-20", 12.0)],
    )
    incomplete = pd.DataFrame({"date": ["2026-07-20"]})
    incomplete.to_parquet(
        tmp_path / "market" / "kline" / "000002_SZ.parquet",
        index=False,
    )

    assert (
        read_symbol_sparkline(
            tmp_path,
            "000002.SZ",
            end_date=date(2026, 7, 21),
        )
        == []
    )


def test_symbol_data_ops_routes_keep_request_injection(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    app = create_app()
    wanted = {
        "/api/symbol-data-ops/repull",
        "/api/symbol-data-ops/replay",
        "/api/symbol-data-ops/mark-verified",
    }
    routes = {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path in wanted
    }

    assert set(routes) == wanted
    for route in routes.values():
        assert route.dependant.query_params == []
        assert route.dependant.request_param_name == "request"


def test_json_object_routes_keep_required_request_bodies(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    from trade_web import create_app

    app = create_app()
    wanted = {
        "/api/dag/{dag_id}/config",
        "/api/dag/{dag_id}/run",
        "/api/trigger",
        "/api/run",
        "/api/workflows/{root_event_id}/rerun-node",
        "/api/readiness/detect-changes",
        "/api/readiness/backfill",
        "/api/readiness/replay",
        "/api/ops/replay/preview",
        "/api/ops/replay/execute",
    }
    routes = {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path in wanted
    }

    assert set(routes) == wanted
    for route in routes.values():
        assert route.dependant.query_params == []
        assert [field.name for field in route.dependant.body_params] == ["req"]
        assert route.dependant.body_params[0].field_info.is_required() is True
