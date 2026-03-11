from __future__ import annotations

from collections import deque
import json

from trade_py.db.settings_db import SettingsDB
from trade_py.data.market.tushare_client import (
    TushareProClient,
    _classify_exception,
    _coerce_backoff,
    _load_client_config,
    _is_rate_limit_error,
    _params_hash,
    _rate_limit_delay,
)


class _FakeApi:
    def __init__(self, failures: list[Exception], result: object) -> None:
        self._failures = list(failures)
        self._result = result

    def daily(self, **kwargs):
        if self._failures:
            raise self._failures.pop(0)
        return self._result


def _make_client(fake_api: object) -> TushareProClient:
    client = object.__new__(TushareProClient)
    client._api = fake_api
    client._config = type(
        "Cfg",
        (),
        {
            "min_interval_sec": 0.6,
            "minute_budget": 80,
            "rate_limit_backoff_sec": (5, 15, 30, 45, 60),
            "audit_log_enabled": False,
            "http_url": "http://example.com",
            "data_root": ".",
        },
    )()
    client._last_call = 0.0
    client._call_timestamps = deque()
    client._global_next_allowed_at = 0.0
    client._audit_log_path = None
    return client


def test_rate_limit_errors_are_detected() -> None:
    assert _is_rate_limit_error(Exception("抱歉，您每分钟最多访问该接口1500次"))
    assert _is_rate_limit_error(Exception("Rate limit exceeded"))
    assert not _is_rate_limit_error(Exception("network timeout"))


def test_rate_limit_delays_ramp_up_to_one_minute() -> None:
    backoff = (5, 15, 30, 45, 60)
    assert [_rate_limit_delay(i, backoff) for i in range(1, 7)] == [5, 15, 30, 45, 60, 60]


def test_call_waits_longer_on_tushare_rate_limit(monkeypatch) -> None:
    sleeps: list[float] = []
    fake_api = _FakeApi(
        [Exception("抱歉，您每分钟最多访问该接口1500次，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。")],
        result={"ok": True},
    )
    client = _make_client(fake_api)

    monkeypatch.setattr("trade_py.data.market.tushare_client.time.sleep", sleeps.append)
    monkeypatch.setattr("trade_py.data.market.tushare_client.time.monotonic", lambda: 1000.0)

    result = client.call("daily", retries=3, ts_code="000001.SZ")

    assert result == {"ok": True}
    assert sleeps == [5]


def test_classify_exception_distinguishes_non_retryable_errors() -> None:
    assert _classify_exception(Exception("invalid token")) == "auth"
    assert _classify_exception(Exception("权限不足")) == "permission"
    assert _classify_exception(Exception("parameter error")) == "invalid_request"
    assert _classify_exception(Exception("connection aborted")) == "transient"


def test_minute_budget_waits_before_sending_next_request(monkeypatch) -> None:
    sleeps: list[float] = []
    fake_api = _FakeApi([], result={"ok": True})
    client = _make_client(fake_api)
    client._config.minute_budget = 1
    client._call_timestamps = deque([1000.0])
    client._last_call = 0.0

    monkeypatch.setattr("trade_py.data.market.tushare_client.time.sleep", sleeps.append)
    monkeypatch.setattr("trade_py.data.market.tushare_client.time.monotonic", lambda: 1000.0)

    client.call("daily", retries=3, ts_code="000001.SZ")

    assert sleeps == [60.0]


def test_load_client_config_reads_settings(tmp_path) -> None:
    settings = SettingsDB(str(tmp_path))
    settings.set("tushare_token", "abc")
    settings.set("tushare.http_url", "http://proxy.internal/dataapi")
    settings.set("tushare.min_interval_sec", "0.8")
    settings.set("tushare.minute_budget", "55")
    settings.set("tushare.rate_limit_backoff_sec", "3,9,27")
    settings.set("tushare.audit_log_enabled", "0")

    config = _load_client_config(tmp_path)

    assert config.token == "abc"
    assert config.http_url == "http://proxy.internal/dataapi"
    assert config.min_interval_sec == 0.8
    assert config.minute_budget == 55
    assert config.rate_limit_backoff_sec == (3, 9, 27)
    assert config.audit_log_enabled is False


def test_params_hash_is_stable() -> None:
    assert _params_hash({"b": 2, "a": 1}) == _params_hash({"a": 1, "b": 2})


def test_audit_log_writes_no_plain_params(tmp_path) -> None:
    fake_api = _FakeApi([], result={"ok": True})
    client = _make_client(fake_api)
    client._config.audit_log_enabled = True
    client._audit_log_path = tmp_path / "tushare_requests.jsonl"

    client._audit_log(
        endpoint="daily",
        kwargs={"ts_code": "000001.SZ"},
        status="success",
        duration_ms=10.0,
        wait_ms=0.0,
        retry_index=0,
    )

    payload = json.loads(client._audit_log_path.read_text(encoding="utf-8").strip())
    assert payload["endpoint"] == "daily"
    assert payload["params_hash"]
    assert "ts_code" not in client._audit_log_path.read_text(encoding="utf-8")


def test_coerce_backoff_uses_default_for_invalid_values() -> None:
    assert _coerce_backoff("bad", (5, 15)) == (5, 15)
