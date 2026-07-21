from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from trade_py.bus import Event, EventAdmissionError
from trade_py.bus.models import AdmissionOutcome, HandlerAdmissionResult, PublishResult
from trade_py.cli import event
from trade_py.db.trade_db import TradeDB


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{", "Invalid --payload JSON"),
        ("[]", "expected a JSON object, got list"),
        ("0", "expected a JSON object, got int"),
        ("null", "expected a JSON object, got NoneType"),
        ("NaN", "non-finite JSON constant is not allowed: NaN"),
        ('{"value": Infinity}', "non-finite JSON constant is not allowed: Infinity"),
        ('{"value": -Infinity}', "non-finite JSON constant is not allowed: -Infinity"),
        ('{"value": 1e400}', "non-finite JSON number is not allowed: 1e400"),
    ],
)
def test_trigger_rejects_invalid_or_non_object_payload_before_database_creation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    payload: str,
    message: str,
) -> None:
    exit_code = event.main(
        [
            "trigger",
            "ops.fixture",
            "--data-root",
            str(tmp_path),
            "--payload",
            payload,
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert message in captured.err
    assert captured.out == ""
    assert not (tmp_path / ".db" / "trade.db").exists()


def test_trigger_persists_accepted_event_and_releases_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = event.main(
        [
            "trigger",
            "ops.fixture",
            "--data-root",
            str(tmp_path),
            "--payload",
            '{"fixture": true}',
            "--timeout-sec",
            "0.2",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Published event_id=1  topic=ops.fixture durable=true outcome=accepted" in captured.out
    assert "dispatch_status=accepted action=none handlers_accepted=0/0" in captured.out
    assert captured.err == ""
    with TradeDB(tmp_path) as db:
        rows = db.event_log_recent(limit=1, topic="ops.fixture")
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert rows[0]["payload"] == '{"fixture": true}'


class _FakeDB:
    instances: list[_FakeDB] = []

    def __init__(self, _data_root: str) -> None:
        self.closed = False
        self.stale_calls: list[str] = []
        self.__class__.instances.append(self)

    def job_runs_mark_stale_by_policy(self) -> None:
        self.stale_calls.append("job_runs")

    def event_log_mark_stale(self) -> None:
        self.stale_calls.append("event_log")

    def close(self) -> None:
        self.closed = True


class _FakeBus:
    def __init__(
        self,
        outcome: AdmissionOutcome,
        handler_outcomes: tuple[AdmissionOutcome, ...],
        *,
        publish_error: Exception | None = None,
    ) -> None:
        self._outcome = outcome
        self._handler_outcomes = handler_outcomes
        self._publish_error = publish_error
        self.shutdown_calls: list[bool] = []
        self.wait_calls: list[tuple[int | None, float]] = []

    def publish_with_outcome(self, topic: str, payload: dict[str, Any]) -> PublishResult[Event]:
        if self._publish_error is not None:
            raise self._publish_error
        event_row = Event(
            id=41,
            topic=topic,
            payload=payload,
            parent_event_id=None,
            created_at=datetime.now(timezone.utc),
            bus=self,  # type: ignore[arg-type]
        )
        handlers = tuple(
            HandlerAdmissionResult(
                event_id=event_row.id,
                handler_name=f"handler-{index}",
                channel="io",
                outcome=handler_outcome,
            )
            for index, handler_outcome in enumerate(self._handler_outcomes)
        )
        return PublishResult(event=event_row, outcome=self._outcome, handlers=handlers)

    def wait_for_idle(self, *, min_event_id: int | None, timeout_sec: float) -> bool:
        self.wait_calls.append((min_event_id, timeout_sec))
        return True

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)


def _trigger_args(tmp_path: Path) -> Namespace:
    return Namespace(
        topic="ops.fixture",
        data_root=str(tmp_path),
        payload='{"fixture": true}',
        timeout_sec=1.5,
    )


def _install_trigger_fakes(
    monkeypatch: pytest.MonkeyPatch,
    bus: _FakeBus,
) -> None:
    import trade_py.bus
    import trade_py.db.trade_db

    _FakeDB.instances.clear()
    monkeypatch.setattr(trade_py.db.trade_db, "TradeDB", _FakeDB)
    monkeypatch.setattr(trade_py.bus, "get_bus", lambda _db: bus)
    monkeypatch.setattr(
        trade_py.bus,
        "bootstrap_from_dag",
        lambda _db, _data_root, *, bus: bus,
    )


def test_trigger_prints_accepted_identity_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bus = _FakeBus(
        AdmissionOutcome.ACCEPTED,
        (AdmissionOutcome.ACCEPTED,),
    )
    _install_trigger_fakes(monkeypatch, bus)

    exit_code = event._cmd_trigger(_trigger_args(tmp_path))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (
        captured.out == "Published event_id=41  topic=ops.fixture durable=true outcome=accepted "
        "dispatch_status=accepted action=none handlers_accepted=1/1\n"
    )
    assert captured.err == ""
    assert bus.wait_calls == [(41, 1.5)]
    assert bus.shutdown_calls == [True]
    assert _FakeDB.instances[0].closed
    assert _FakeDB.instances[0].stale_calls == ["job_runs", "event_log"]


@pytest.mark.parametrize(
    ("outcome", "handler_outcomes"),
    [
        (
            AdmissionOutcome.SATURATED,
            (AdmissionOutcome.SATURATED,),
        ),
        (
            AdmissionOutcome.SATURATED,
            (AdmissionOutcome.ACCEPTED, AdmissionOutcome.SATURATED),
        ),
        (
            AdmissionOutcome.SUBMISSION_FAILED,
            (AdmissionOutcome.SUBMISSION_FAILED,),
        ),
    ],
)
def test_trigger_reports_durable_deferred_admission_and_returns_tempfail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    outcome: AdmissionOutcome,
    handler_outcomes: tuple[AdmissionOutcome, ...],
) -> None:
    bus = _FakeBus(outcome, handler_outcomes)
    _install_trigger_fakes(monkeypatch, bus)

    exit_code = event._cmd_trigger(_trigger_args(tmp_path))

    captured = capsys.readouterr()
    accepted_count = sum(
        1 for handler_outcome in handler_outcomes if handler_outcome is AdmissionOutcome.ACCEPTED
    )
    assert exit_code == 75
    assert "Deferred event_id=41  topic=ops.fixture durable=true" in captured.out
    assert f"outcome={outcome.value}" in captured.out
    assert "dispatch_status=deferred action=replay_existing" in captured.out
    assert f"handlers_accepted={accepted_count}/{len(handler_outcomes)}" in captured.out
    assert captured.err == ""
    assert bus.wait_calls == []
    assert bus.shutdown_calls == [True]
    assert _FakeDB.instances[0].closed


def test_trigger_cleans_up_after_typed_admission_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bus = _FakeBus(
        AdmissionOutcome.SATURATED,
        (AdmissionOutcome.SATURATED,),
    )
    result = bus.publish_with_outcome("ops.fixture", {})
    bus._publish_error = EventAdmissionError(result)
    _install_trigger_fakes(monkeypatch, bus)

    exit_code = event._cmd_trigger(_trigger_args(tmp_path))

    captured = capsys.readouterr()
    assert exit_code == 75
    assert "action=replay_existing" in captured.out
    assert captured.err == ""
    assert bus.shutdown_calls == [True]
    assert _FakeDB.instances[0].closed


def test_trigger_closes_resources_after_publish_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bus = _FakeBus(
        AdmissionOutcome.ACCEPTED,
        (),
        publish_error=RuntimeError("executor unavailable"),
    )
    _install_trigger_fakes(monkeypatch, bus)

    exit_code = event._cmd_trigger(_trigger_args(tmp_path))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Event trigger failed: RuntimeError: executor unavailable" in captured.err
    assert bus.shutdown_calls == [True]
    assert _FakeDB.instances[0].closed
