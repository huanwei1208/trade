"""Sentiment and event pipeline handlers."""
from __future__ import annotations

import logging

from trade_py.bus import EventBus, Topic, Event
from trade_py.jobs import run_job

logger = logging.getLogger(__name__)


def register(bus: EventBus, data_root: str) -> None:
    """Subscribe sentiment and event handlers to the bus."""

    def _h(job_name: str, downstream_topic: str | None = None):
        def handler(event: Event) -> None:
            logger.info("sentiment handler: job=%s via topic=%s", job_name, event.topic)
            result = run_job(job_name, data_root)
            logger.info("sentiment handler done: job=%s result=%s", job_name, result)
            if downstream_topic:
                event.bus.publish(downstream_topic, {"result": result})
        handler.__name__ = job_name
        handler.__qualname__ = f"sentiment.{job_name}"
        return handler

    # Gate subscriptions
    bus.subscribe(Topic.GATE_EVENING,        _h("sentiment_pipeline", Topic.SILVER_CREATED))
    bus.subscribe(Topic.GATE_EVENT_EXTRACT,  _h("event_pipeline"))
    bus.subscribe(Topic.GATE_MARKET_CLOSE,   _h("event_backfill"))

    # Cascade: new silver data → run event_pipeline immediately
    bus.subscribe(Topic.SILVER_CREATED,      _h("event_pipeline"))

    # Job subscriptions
    bus.subscribe(Topic.JOB_SENTIMENT,       _h("sentiment_pipeline", Topic.SILVER_CREATED))
    bus.subscribe(Topic.JOB_EVENT_PIPELINE,  _h("event_pipeline"))
    bus.subscribe(Topic.JOB_EVENT_BACKFILL,  _h("event_backfill"))
