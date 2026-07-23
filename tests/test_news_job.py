from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from trade_py.bus import Topic
from trade_py.bus.models import AdmissionOutcome
from trade_py.jobs import _job_crypto_news_sentiment


class _FakeTradeDB:
    instances: list[_FakeTradeDB] = []

    def __init__(self, data_root: str) -> None:
        self.data_root = data_root
        self.closed = False
        self.instances.append(self)

    def close(self) -> None:
        self.closed = True


class _FakeBus:
    def __init__(self, outcomes: list[AdmissionOutcome]) -> None:
        self._outcomes = iter(outcomes)
        self._bound_db: object | None = None
        self.calls: list[str] = []
        self.bound_checks: list[object] = []
        self.shutdown_calls = 0

    def is_bound_to(self, db: object) -> bool:
        self.bound_checks.append(db)
        return self._bound_db is db

    def publish_with_outcome(
        self,
        topic: str,
        payload: dict[str, Any],
        parent_event_id: int | None = None,
    ) -> Any:
        del payload, parent_event_id
        self.calls.append(topic)
        outcome = next(self._outcomes)
        return types.SimpleNamespace(
            event=types.SimpleNamespace(id=100 + len(self.calls)),
            outcome=outcome,
        )

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _install_news_fakes(
    monkeypatch: pytest.MonkeyPatch,
    bus: _FakeBus,
    *,
    local_bus: bool,
) -> None:
    _FakeTradeDB.instances.clear()
    fake_db_module: Any = types.ModuleType("trade_py.db.trade_db")
    fake_db_module.TradeDB = _FakeTradeDB
    monkeypatch.setitem(sys.modules, "trade_py.db.trade_db", fake_db_module)

    fake_source_module: Any = types.ModuleType("trade_py.data.market.cross_asset.crypto_sentiment")
    fake_source_module.fetch_fear_greed = lambda limit=90: []
    fake_source_module.fetch_all_crypto_news = lambda: {}
    fake_source_module.save_fear_greed_parquet = lambda records, path: None
    fake_source_module.save_crypto_news_parquet = lambda records, path: None
    monkeypatch.setitem(
        sys.modules,
        "trade_py.data.market.cross_asset.crypto_sentiment",
        fake_source_module,
    )

    fake_analysis_module: Any = types.ModuleType("trade_py.intelligence.crypto_base_factors")
    fake_analysis_module.analyze_crypto_news = lambda *args, **kwargs: None
    monkeypatch.setitem(
        sys.modules,
        "trade_py.intelligence.crypto_base_factors",
        fake_analysis_module,
    )

    import trade_py.bus

    def fake_get_bus(db: _FakeTradeDB) -> _FakeBus:
        bus._bound_db = db if local_bus else None
        return bus

    monkeypatch.setattr(trade_py.bus, "get_bus", fake_get_bus)


def test_news_fanout_continues_after_durable_rejection_and_closes_local_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = _FakeBus([AdmissionOutcome.SATURATED, AdmissionOutcome.ACCEPTED])
    _install_news_fakes(monkeypatch, bus, local_bus=True)

    with caplog.at_level("WARNING"):
        summary = _job_crypto_news_sentiment(str(tmp_path))

    assert bus.calls == [Topic.NEWS_FETCHED, Topic.NEWS_ANALYZED]
    assert "event_id=101" in caplog.text
    assert "outcome=saturated" in caplog.text
    assert bus.bound_checks == [_FakeTradeDB.instances[0]]
    assert bus.shutdown_calls == 1
    assert _FakeTradeDB.instances[0].closed is True
    assert "Crypto news: 0 articles" in summary


def test_news_fanout_does_not_shutdown_shared_bus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bus = _FakeBus([AdmissionOutcome.ACCEPTED, AdmissionOutcome.ACCEPTED])
    _install_news_fakes(monkeypatch, bus, local_bus=False)

    _job_crypto_news_sentiment(str(tmp_path))

    assert bus.calls == [Topic.NEWS_FETCHED, Topic.NEWS_ANALYZED]
    assert bus.bound_checks == [_FakeTradeDB.instances[0]]
    assert bus.shutdown_calls == 0
    assert _FakeTradeDB.instances[0].closed is True
