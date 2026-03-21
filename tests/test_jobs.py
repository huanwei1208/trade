from __future__ import annotations

import sys
import types
from dataclasses import dataclass

from trade_py.jobs import run_job


def test_kline_job_uses_explicit_range_for_recovery(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    @dataclass
    class FakeKlineSyncOptions:
        mode: str = "incremental"
        symbols: list[str] | None = None
        start: str | None = None
        end: str | None = None
        adjust: str = "hfq"
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
