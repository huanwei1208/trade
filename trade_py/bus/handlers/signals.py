"""Signal computation handlers: window_score and model_inference."""
from __future__ import annotations

import logging

from trade_py.bus import EventBus, Topic, Event
from trade_py.jobs import run_job

logger = logging.getLogger(__name__)


def register(bus: EventBus, data_root: str) -> None:
    """Subscribe signal computation handlers to the bus."""

    def _h(job_name: str, downstream_topic: str | None = None):
        def handler(event: Event) -> None:
            logger.info("signals handler: job=%s via topic=%s", job_name, event.topic)
            result = run_job(job_name, data_root)
            logger.info("signals handler done: job=%s result=%s", job_name, result)
            if downstream_topic:
                event.bus.publish(downstream_topic, {"result": result})
        handler.__name__ = job_name
        handler.__qualname__ = f"signals.{job_name}"
        return handler

    # window_score: runs after kline sync, at pre-market signal slot, and at close
    bus.subscribe(Topic.GATE_SIGNAL_AM,      _h("window_score",     Topic.WINDOW_SCORE_UPDATED))
    bus.subscribe(Topic.GATE_MARKET_CLOSE,   _h("window_score",     Topic.WINDOW_SCORE_UPDATED))
    bus.subscribe(Topic.KLINE_SYNCED,        _h("window_score",     Topic.WINDOW_SCORE_UPDATED))

    # model_inference: runs at pre-market gate
    bus.subscribe(Topic.GATE_PRE_MARKET,     _h("model_inference",  Topic.MODEL_INFERRED))

    # Job subscriptions
    bus.subscribe(Topic.JOB_WINDOW_SCORE,    _h("window_score",     Topic.WINDOW_SCORE_UPDATED))
    bus.subscribe(Topic.JOB_MODEL_INFERENCE, _h("model_inference",  Topic.MODEL_INFERRED))
