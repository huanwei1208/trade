"""Market data handlers: kline, cross_asset, market_index, fund_flow, northbound,
fundamental, macro, sector_refresh."""
from __future__ import annotations

import logging

from trade_py.bus import EventBus, Topic, Event
from trade_py.jobs import run_job

logger = logging.getLogger(__name__)


def register(bus: EventBus, data_root: str) -> None:
    """Subscribe all market data handlers to the bus."""

    def _h(job_name: str, downstream_topic: str | None = None):
        """Build a handler that runs job_name and optionally publishes a downstream event."""
        def handler(event: Event) -> None:
            logger.info("market handler: job=%s via topic=%s", job_name, event.topic)
            result = run_job(job_name, data_root)
            logger.info("market handler done: job=%s result=%s", job_name, result)
            if downstream_topic:
                event.bus.publish(downstream_topic, {"result": result})
        handler.__name__ = job_name
        handler.__qualname__ = f"market.{job_name}"
        return handler

    # Gate subscriptions (time-triggered)
    bus.subscribe(Topic.GATE_MORNING,       _h("kline_update",    Topic.KLINE_SYNCED))
    bus.subscribe(Topic.GATE_MORNING,       _h("cross_asset_fetch"))
    bus.subscribe(Topic.GATE_PRE_MARKET,    _h("market_index",    Topic.INDEX_SYNCED))
    bus.subscribe(Topic.GATE_SIGNAL_AM,     _h("fund_flow_update"))
    bus.subscribe(Topic.GATE_MARKET_CLOSE,  _h("fund_flow_update"))
    bus.subscribe(Topic.GATE_MARKET_CLOSE,  _h("northbound"))
    bus.subscribe(Topic.GATE_FUND_WEEKLY,   _h("fundamental"))
    bus.subscribe(Topic.GATE_MACRO_WEEKLY,  _h("macro"))
    bus.subscribe(Topic.GATE_SECTOR_WEEKLY, _h("sector_refresh"))

    # Job subscriptions (manual precise trigger)
    bus.subscribe(Topic.JOB_KLINE,          _h("kline_update",    Topic.KLINE_SYNCED))
    bus.subscribe(Topic.JOB_CROSS_ASSET,    _h("cross_asset_fetch"))
    bus.subscribe(Topic.JOB_MARKET_INDEX,   _h("market_index",    Topic.INDEX_SYNCED))
    bus.subscribe(Topic.JOB_FUND_FLOW,      _h("fund_flow_update"))
    bus.subscribe(Topic.JOB_NORTHBOUND,     _h("northbound"))
    bus.subscribe(Topic.JOB_FUNDAMENTAL,    _h("fundamental"))
    bus.subscribe(Topic.JOB_MACRO,          _h("macro"))
    bus.subscribe(Topic.JOB_SECTOR_REFRESH, _h("sector_refresh"))
