"""Report handlers: morning_brief."""
from __future__ import annotations

import logging

from trade_py.bus import EventBus, Topic, Event
from trade_py.jobs import run_job

logger = logging.getLogger(__name__)


def register(bus: EventBus, data_root: str) -> None:
    """Subscribe report handlers to the bus."""

    def _h(job_name: str, downstream_topic: str | None = None):
        def handler(event: Event) -> None:
            logger.info("report handler: job=%s via topic=%s", job_name, event.topic)
            result = run_job(job_name, data_root)
            logger.info("report handler done: job=%s result=%s", job_name, result)
            if downstream_topic:
                event.bus.publish(downstream_topic, {"result": result})
        handler.__name__ = job_name
        handler.__qualname__ = f"report.{job_name}"
        return handler

    # morning_brief at scheduled time
    bus.subscribe(Topic.GATE_REPORT,       _h("morning_brief", Topic.MORNING_BRIEF_READY))

    # Job subscription
    bus.subscribe(Topic.JOB_MORNING_BRIEF, _h("morning_brief", Topic.MORNING_BRIEF_READY))
