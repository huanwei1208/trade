from __future__ import annotations

import ast
import re
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from trade_py.db.trade_db import TradeDB
from trade_web.backend.inference import InferenceService
from trade_web.backend.runtime.commands import RuntimeCommandRunner


def test_web_app_source_uses_semantic_db_facades_only() -> None:
    app_module = import_module("trade_web.backend.app")
    assert app_module.__file__ is not None
    source = Path(app_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    private_or_generic_access = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in {"_conn", "_conn_lock", "execute", "runtime_read_one", "runtime_read_all"}
    }
    sql_literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.search(r"\b(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b", node.value)
    ]

    assert private_or_generic_access == set()
    assert sql_literals == []


def test_mark_verified_route_uses_locked_trade_db_facade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    runtime_trade_db = import_module("trade_py.db.trade_db").TradeDB
    calls: list[tuple[str, str, str]] = []

    def mark_verified(
        _db: Any,
        source: str,
        dataset: str,
        symbol: str,
    ) -> bool:
        calls.append((source, dataset, symbol))
        return dataset != "fund_flow"

    monkeypatch.setattr(
        runtime_trade_db,
        "sync_state_mark_verified",
        mark_verified,
    )
    monkeypatch.setattr(
        RuntimeCommandRunner,
        "shutdown",
        lambda _runner, *, wait=True: None,
    )
    from trade_web import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/symbol-data-ops/mark-verified",
            json={
                "symbol": " btc ",
                "domains": ["kline", "fund_flow", "unknown"],
            },
        )

    assert response.status_code == 200
    assert response.json()["updated"] == ["kline"]
    assert calls == [
        ("tushare_kline", "daily", "BTC"),
        ("akshare", "fund_flow", "BTC"),
    ]


def test_inference_freshness_uses_trade_db_facade_without_connection_access() -> None:
    latest = (date.today() - timedelta(days=3)).isoformat()

    class FacadeOnlyDB:
        def __init__(self) -> None:
            self.datasets: list[str] = []

        def sync_state_latest_date(self, dataset: str) -> str | None:
            self.datasets.append(dataset)
            return latest

        def __getattr__(self, name: str) -> Any:
            if name == "_conn":
                raise AssertionError("InferenceService must not access TradeDB._conn")
            raise AttributeError(name)

    db = FacadeOnlyDB()
    service = object.__new__(InferenceService)
    service._db = cast(TradeDB, db)
    service._data_root = "unused"

    assert service._data_lag_days() == 3
    assert db.datasets == ["kline"]
