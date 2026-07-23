from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pytest

from trade_py.jobs import run_job


def test_kline_job_uses_explicit_range_for_recovery(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    @dataclass
    class FakeKlineSyncOptions:
        mode: str = "incremental"
        symbols: list[str] | None = None
        start: str | None = None
        end: str | None = None
        adjust: str = "none"
        provider: str = "auto"
        delay_ms: int = 300
        fail_fast: bool = False

    class FakeKlineSyncService:
        def __init__(self, data_root: str) -> None:
            captured["data_root"] = data_root

        def sync(self, opts: FakeKlineSyncOptions):
            captured["opts"] = opts
            return types.SimpleNamespace(
                sync_mode=opts.mode,
                api_calls=1,
                total_symbols=3,
                total_rows=42,
            )

    fake_module = types.ModuleType("trade_py.data.market.kline")
    fake_module.KlineSyncOptions = FakeKlineSyncOptions
    fake_module.KlineSyncService = FakeKlineSyncService
    monkeypatch.setitem(sys.modules, "trade_py.data.market.kline", fake_module)

    summary = run_job(
        "kline_update",
        str(tmp_path),
        date_from="2026-03-19",
        date_to="2026-03-20",
    )

    assert "mode=range" in summary
    opts = captured["opts"]
    assert isinstance(opts, FakeKlineSyncOptions)
    assert opts.mode == "range"
    assert opts.start == "2026-03-19"
    assert opts.end == "2026-03-20"


def test_fund_flow_job_uses_full_universe_for_recovery(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    fake_trade_db_module = types.ModuleType("trade_py.db.trade_db")

    class FakeTradeDB:
        def __init__(self, data_root: str) -> None:
            captured["db_root"] = data_root

        def watchlist_get(self):
            return ["WL1", "WL2"]

        def get_all_symbols(self):
            return ["AAA", "BBB", "CCC"]

    fake_trade_db_module.TradeDB = FakeTradeDB
    monkeypatch.setitem(sys.modules, "trade_py.db.trade_db", fake_trade_db_module)

    fake_fund_flow_module = types.ModuleType("trade_py.data.market.fund_flow")

    class FakeFundFlowFetcher:
        def __init__(self, data_root: str) -> None:
            captured["fetcher_root"] = data_root

        def fetch_batch(self, symbols, start_date=None, end_date=None):
            captured["symbols"] = list(symbols)
            captured["start_date"] = start_date
            captured["end_date"] = end_date
            return {"mode": "range", "saved_symbols": len(symbols), "api_calls": 3}

    fake_fund_flow_module.FundFlowFetcher = FakeFundFlowFetcher
    monkeypatch.setitem(sys.modules, "trade_py.data.market.fund_flow", fake_fund_flow_module)

    summary = run_job(
        "fund_flow_update",
        str(tmp_path),
        date_from="2026-03-19",
        date_to="2026-03-20",
    )

    assert "3 symbols" in summary
    assert captured["symbols"] == ["AAA", "BBB", "CCC"]
    assert captured["start_date"] == "2026-03-19"
    assert captured["end_date"] == "2026-03-20"


def test_window_score_job_refreshes_inference_artifacts(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {"score_dates": [], "materialize_dates": [], "predict_dates": []}

    fake_scorer_module = types.ModuleType("trade_py.signals.window_scorer")

    def fake_score_universe(data_root: str, date_str: str | None = None):
        captured["score_dates"].append((data_root, date_str))
        return [{"symbol": "603083.SH"}, {"symbol": "000001.SZ"}]

    fake_scorer_module.score_universe = fake_score_universe
    monkeypatch.setitem(sys.modules, "trade_py.signals.window_scorer", fake_scorer_module)

    fake_runtime_module = types.ModuleType("trade_py.analysis.propagation_runtime")

    def fake_materialize(data_root: str, day_str: str):
        captured["materialize_dates"].append((data_root, day_str))
        return (day_str, 2, ["f0", "f1"], object())

    def fake_sync_predictions(data_root: str, day_str: str):
        captured["predict_dates"].append((data_root, day_str))
        return (day_str, 2)

    fake_runtime_module.materialize_inference_factors = fake_materialize
    fake_runtime_module.sync_signal_predictions = fake_sync_predictions
    monkeypatch.setitem(sys.modules, "trade_py.analysis.propagation_runtime", fake_runtime_module)

    summary = run_job(
        "window_score",
        str(tmp_path),
        date_from="2026-03-19",
        date_to="2026-03-20",
    )

    assert "latest_symbols=2" in summary
    assert "factors=2" in summary
    assert "predictions=2" in summary
    assert captured["score_dates"] == [
        (str(tmp_path), "2026-03-19"),
        (str(tmp_path), "2026-03-20"),
    ]
    assert captured["materialize_dates"] == [
        (str(tmp_path), "2026-03-19"),
        (str(tmp_path), "2026-03-20"),
    ]
    assert captured["predict_dates"] == [
        (str(tmp_path), "2026-03-19"),
        (str(tmp_path), "2026-03-20"),
    ]


def test_kg_propagate_job_forwards_range(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    fake_event_module = types.ModuleType("trade_py.event")

    def fake_backfill_events(data_root: str, start: str | None = None, end: str | None = None) -> str:
        captured["data_root"] = data_root
        captured["start"] = start
        captured["end"] = end
        return "回填超额收益: 5d=10条, 20d=20条"

    fake_event_module.backfill_events = fake_backfill_events
    monkeypatch.setitem(sys.modules, "trade_py.event", fake_event_module)

    summary = run_job(
        "kg_propagate",
        str(tmp_path),
        date_from="2025-10-24",
        date_to="2026-02-20",
    )

    assert summary == "回填超额收益: 5d=10条, 20d=20条"
    assert captured == {
        "data_root": str(tmp_path),
        "start": "2025-10-24",
        "end": "2026-02-20",
    }


def test_macro_job_rejects_partial_dataset_failure(monkeypatch, tmp_path) -> None:
    captured: list[str] = []
    fake_macro_module = types.ModuleType("trade_py.data.market.macro")

    class FakeMacroFetcher:
        def __init__(self, data_root: str) -> None:
            self.data_root = data_root

        def fetch_and_save(self, name: str) -> None:
            captured.append(name)
            if name == "ppi":
                raise RuntimeError("provider unavailable")

    fake_macro_module.MacroFetcher = FakeMacroFetcher
    monkeypatch.setitem(sys.modules, "trade_py.data.market.macro", fake_macro_module)

    with pytest.raises(RuntimeError, match="宏观数据同步不完整.*ppi"):
        run_job("macro", str(tmp_path))

    assert captured == ["gdp", "cpi", "ppi", "pmi"]
