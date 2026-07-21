from __future__ import annotations

from datetime import timezone

import pytest

from trade_py.bus.admission import (
    MAX_CHANNEL_CAPACITY,
    ChannelAdmission,
    validate_channel_config,
)
from trade_py.bus.models import AdmissionOutcome, BusLifecycle


@pytest.mark.parametrize(
    ("workers", "capacity", "message"),
    [
        (0, 1, "workers must be positive"),
        (-1, 1, "workers must be positive"),
        (True, 1, "workers must be positive"),
        (2, 1, "capacity must be at least"),
        (1, MAX_CHANNEL_CAPACITY + 1, "reviewed bound"),
    ],
)
def test_channel_config_rejects_invalid_values(
    workers: int,
    capacity: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_channel_config("nlp", workers=workers, capacity=capacity)


def test_channel_config_rejects_boolean_capacity() -> None:
    with pytest.raises(ValueError, match="capacity must be an integer"):
        validate_channel_config("nlp", workers=1, capacity=True)


def test_channel_config_accepts_capacity_equal_to_workers() -> None:
    config = validate_channel_config("signal", workers=3, capacity=3)

    assert config.workers == 3
    assert config.capacity == 3


def test_channel_admission_saturates_without_consuming_an_extra_permit() -> None:
    owner = ChannelAdmission(
        "io",
        validate_channel_config("io", workers=1, capacity=2),
    )

    first_outcome, first = owner.acquire()
    second_outcome, second = owner.acquire()
    saturated_outcome, saturated = owner.acquire()

    assert first_outcome is AdmissionOutcome.ACCEPTED
    assert second_outcome is AdmissionOutcome.ACCEPTED
    assert saturated_outcome is AdmissionOutcome.SATURATED
    assert saturated is None
    snapshot = owner.snapshot()
    assert snapshot.admitted == 2
    assert snapshot.active == 0
    assert snapshot.available == 0
    assert snapshot.accepted_count == 0
    assert snapshot.saturated_count == 1
    assert snapshot.last_saturation_at is not None
    assert snapshot.last_saturation_at.tzinfo is timezone.utc

    assert first is not None
    assert second is not None
    owner.record_submission_success()
    owner.record_submission_success()
    first.release()
    second.release()

    assert owner.snapshot().admitted == 0
    assert owner.snapshot().available == 2
    assert owner.snapshot().accepted_count == 2


def test_permit_tracks_active_work_and_releases_exactly_once() -> None:
    owner = ChannelAdmission(
        "decision",
        validate_channel_config("decision", workers=1, capacity=1),
    )
    outcome, permit = owner.acquire()

    assert outcome is AdmissionOutcome.ACCEPTED
    assert permit is not None
    permit.mark_active()
    permit.mark_active()
    assert owner.snapshot().active == 1

    permit.release()
    permit.release()

    snapshot = owner.snapshot()
    assert snapshot.admitted == 0
    assert snapshot.active == 0
    assert snapshot.available == 1


def test_release_before_activation_does_not_change_other_active_work() -> None:
    owner = ChannelAdmission(
        "ingest",
        validate_channel_config("ingest", workers=1, capacity=2),
    )
    _, active = owner.acquire()
    _, queued = owner.acquire()
    assert active is not None
    assert queued is not None
    active.mark_active()

    queued.release()

    snapshot = owner.snapshot()
    assert snapshot.admitted == 1
    assert snapshot.active == 1
    active.release()
    assert owner.snapshot().active == 0


def test_shutdown_rejects_new_work_and_preserves_admitted_permits() -> None:
    owner = ChannelAdmission(
        "nlp",
        validate_channel_config("nlp", workers=1, capacity=1),
    )
    accepted, permit = owner.acquire()
    assert accepted is AdmissionOutcome.ACCEPTED
    assert permit is not None

    owner.begin_shutdown()
    rejected, rejected_permit = owner.acquire()

    assert owner.lifecycle is BusLifecycle.STOPPING
    assert rejected is AdmissionOutcome.SHUTTING_DOWN
    assert rejected_permit is None
    assert owner.snapshot().admitted == 1
    assert owner.snapshot().shutting_down_count == 1

    permit.release()
    owner.finish_shutdown()
    assert owner.lifecycle is BusLifecycle.STOPPED
    assert owner.snapshot().admitted == 0


def test_submission_failure_counter_is_distinct_from_saturation() -> None:
    owner = ChannelAdmission(
        "signal",
        validate_channel_config("signal", workers=1, capacity=1),
    )

    owner.record_submission_failure()

    snapshot = owner.snapshot()
    assert snapshot.submission_failed_count == 1
    assert snapshot.saturated_count == 0
