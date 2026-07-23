"""HTTP translation for durable EventBus admission outcomes."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from trade_py.bus import Event, EventAdmissionError
from trade_py.bus.models import AdmissionOutcome, PublishResult

_OUTCOME_MESSAGES = {
    AdmissionOutcome.SATURATED: (
        "Event persisted but channel capacity is saturated; replay the existing event "
        "when capacity is available."
    ),
    AdmissionOutcome.SHUTTING_DOWN: (
        "Event persisted while the runtime is stopping; replay the existing event after restart."
    ),
    AdmissionOutcome.SUBMISSION_FAILED: "Event persisted but executor submission failed; "
    "inspect runtime capacity and replay the existing event.",
}


def event_admission_failure_response(
    failure: PublishResult[Event] | EventAdmissionError,
) -> JSONResponse:
    """Return a stable, actionable response for a non-accepted durable event."""
    result = failure.result if isinstance(failure, EventAdmissionError) else failure
    if result.accepted:
        raise ValueError("accepted PublishResult cannot be rendered as an admission failure")

    channels = sorted(
        {handler.channel for handler in result.handlers if handler.outcome is result.outcome}
    )
    channel = channels[0] if len(channels) == 1 else ",".join(channels) or "unknown"
    payload: dict[str, Any] = {
        "accepted": False,
        "durable": True,
        "dispatch_status": "deferred",
        "event_id": result.event.id,
        "outcome": result.outcome.value,
        "channel": channel,
        "message": _OUTCOME_MESSAGES[result.outcome],
        "action": "replay_existing",
    }
    return JSONResponse(status_code=503, content=payload)
