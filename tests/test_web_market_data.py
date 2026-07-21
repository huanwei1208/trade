from __future__ import annotations

import json
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


def test_data_assets_uses_kline_manifest_without_deep_parquet_scan(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADE_OBSERVATORY_ENABLED", "0")

    kline_root = tmp_path / "market" / "kline"
    kline_root.mkdir(parents=True)
    (kline_root / "_manifest.json").write_text(
        json.dumps(
            {
                "entries": {
                    "000001_SZ": {
                        "rows": 123,
                        "date_min": "2026-07-01",
                        "date_max": date.today().isoformat(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (kline_root / "000001_SZ.parquet").write_bytes(b"not a real parquet file")

    from trade_web import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/data/assets")

    assert response.status_code == 200
    payload = response.json()
    stock_asset = next(
        asset for asset in payload["assets"] if asset["asset_id"] == "stock.000001.SZ"
    )
    assert stock_asset == {
        "asset_id": "stock.000001.SZ",
        "asset_class": "stock",
        "symbol": "000001.SZ",
        "venue": "akshare/tushare",
        "data_types": ["kline"],
        "total_rows": 123,
        "first_date": "2026-07-01",
        "last_date": date.today().isoformat(),
        "lag_days": 0,
        "health": "ok",
    }


def test_data_assets_resolves_registered_crypto_lowercase_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADE_OBSERVATORY_ENABLED", "0")

    _write_kline(
        tmp_path / "market" / "crypto" / "btc.parquet",
        [("2026-07-21", 100.0)],
    )

    from trade_web import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/data/assets")

    assert response.status_code == 200
    payload = response.json()
    btc_asset = next(asset for asset in payload["assets"] if asset["asset_id"] == "crypto.BTC")
    assert btc_asset["data_types"] == ["kline"]
    assert btc_asset["total_rows"] == 1
    assert btc_asset["first_date"] == "2026-07-21"
    assert btc_asset["last_date"] == "2026-07-21"
    assert btc_asset["health"] in {"ok", "stale", "error"}
