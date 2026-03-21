from __future__ import annotations

import datetime

import pandas as pd

from trade_py.signals.window_scorer import _score_large_order


class _GatewayProbe:
    def __init__(self) -> None:
        self._root = "/tmp/unused"
        self.called = False

    def get_fund_flow(self, symbol: str, as_of=None):
        self.called = True
        raise AssertionError("network-backed fund_flow read should not run")

    def format_report(self, report) -> str:
        return str(report)


def test_score_large_order_skips_gateway_when_no_local_fund_flow(monkeypatch) -> None:
    gateway = _GatewayProbe()

    class _Fetcher:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def load(self, _symbol: str) -> pd.DataFrame:
            return pd.DataFrame()

    monkeypatch.setattr("trade_py.signals.window_scorer.FundFlowFetcher", _Fetcher)

    score = _score_large_order("920000.BJ", gateway, datetime.date(2026, 3, 20))

    assert score == 50.0
    assert gateway.called is False
