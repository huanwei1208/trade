from __future__ import annotations

import ast
import re
import sqlite3
import threading
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from trade_py.db.trade_db import TradeDB
from trade_web.backend.inference import InferenceService
from trade_web.backend.runtime.commands import RuntimeCommandRunner


class _ObservedRLock:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._owner: int | None = None
        self._depth = 0
        self.contended = threading.Event()

    def __enter__(self) -> _ObservedRLock:
        thread_id = threading.get_ident()
        with self._state_lock:
            if self._owner is not None and self._owner != thread_id:
                self.contended.set()
        self._lock.acquire()
        with self._state_lock:
            self._owner = thread_id
            self._depth += 1
        return self

    def __exit__(self, *_args: object) -> None:
        with self._state_lock:
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
        self._lock.release()


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


def test_shared_pipeline_facade_cannot_commit_another_threads_transaction(
    tmp_path: Path,
) -> None:
    db = TradeDB(tmp_path)
    observed_lock = _ObservedRLock()
    db._conn_lock = cast(Any, observed_lock)
    row = db.pipeline_dag_all(enabled_only=False)[0]
    dag_id = int(row["id"])
    original_config = row["config_json"]
    target_enabled = not bool(row["enabled"])
    worker_done = threading.Event()
    worker_errors: list[BaseException] = []

    def update_enabled() -> None:
        try:
            db.pipeline_dag_set_enabled(dag_id, target_enabled)
        except BaseException as exc:
            worker_errors.append(exc)
        finally:
            worker_done.set()

    try:
        with observed_lock:
            db._conn.execute("BEGIN IMMEDIATE")
            db._conn.execute(
                "UPDATE pipeline_dag SET config_json=? WHERE id=?",
                ('{"owner":"uncommitted"}', dag_id),
            )
            worker = threading.Thread(target=update_enabled)
            worker.start()

            assert observed_lock.contended.wait(timeout=1.0)
            assert not worker_done.is_set()
            with sqlite3.connect(tmp_path / ".db" / "trade.db") as observer:
                visible_config = observer.execute(
                    "SELECT config_json FROM pipeline_dag WHERE id=?",
                    (dag_id,),
                ).fetchone()
            assert visible_config == (original_config,)
            db._conn.rollback()

        assert worker_done.wait(timeout=1.0)
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        assert worker_errors == []
        current = db.pipeline_dag_get(dag_id)
        assert current is not None
        assert current["config_json"] == original_config
        assert bool(current["enabled"]) is target_enabled
    finally:
        db.close()


def test_policy_stale_cleanup_preserves_owner_managed_web_command_rows(
    tmp_path: Path,
) -> None:
    with TradeDB(tmp_path) as db:
        generic_run_id = db.job_run_start("kline_update", stage="fetch")
        command_run_id = db.job_run_start("kline_update", stage="web_command")
        with db._conn_lock:
            db._conn.execute(
                """
                UPDATE job_runs
                SET started_at=datetime('now', 'localtime', '-24 hours')
                WHERE id IN (?, ?)
                """,
                (generic_run_id, command_run_id),
            )
            db._conn.commit()

        assert db.job_runs_mark_stale_by_policy() == 1
        rows = {
            int(row["id"]): row
            for row in db.job_runs_recent(limit=10)
            if int(row["id"]) in {generic_run_id, command_run_id}
        }

    assert rows[generic_run_id]["status"] == "error"
    assert rows[command_run_id]["status"] == "running"
    assert rows[command_run_id]["completed_at"] is None
