"""Startup data repair events for Web-owned runtime resources."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trade_py.bus import Event, EventBus, Topic
from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

BTC_STARTUP_CHECK_TOPIC = "gate.btc_startup_gap_check"
BTC_AUTOFILL_TOPIC = "gate.btc_autofill"
BTC_AUTOFILL_JOB_NAME = "crypto_btc_fetch"


@dataclass(frozen=True)
class BtcStartupGapDecision:
    """A read-only startup decision for BTC assurance repair."""

    should_autofill: bool
    payload: dict[str, Any]
    idempotency_key: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    return text


def _btc_current_path(data_root: str | Path) -> Path:
    return Path(data_root) / "market" / "crypto" / "btc_current.json"


def _compact_reason_codes(status: dict[str, Any], reason_code: str | None) -> list[str]:
    values = [str(item) for item in status.get("reason_codes") or [] if str(item or "").strip()]
    if reason_code and reason_code not in values:
        values.insert(0, reason_code)
    return values[:8]


def _requires_existing_current(data_root: str | Path) -> bool:
    """Return whether startup automation may repair this root.

    A fresh empty root should not start provider I/O merely because Web started.
    The automation is for maintaining an already bootstrapped BTC assurance
    dataset whose current pointer makes the authoritative writer and lineage
    explicit.
    """

    return _btc_current_path(data_root).exists()


def build_btc_startup_gap_decision(
    data_root: str | Path,
    *,
    now: Any | None = None,
) -> BtcStartupGapDecision:
    """Inspect BTC readiness and decide whether Web startup should enqueue repair."""

    checked_at = now if now is not None else _utc_now()
    checked_at_text = (
        checked_at.isoformat() if hasattr(checked_at, "isoformat") else str(checked_at)
    )
    check_date = checked_at_text[:10]
    from trade_py.data.market.crypto.store import inspect_btc_status

    current_exists = _requires_existing_current(data_root)
    try:
        status = inspect_btc_status(data_root, as_of=checked_at)
    except (OSError, ValueError) as exc:
        status = {
            "data_readiness": "invalid",
            "reason_code": "BTC_STATUS_UNAVAILABLE",
            "reason_codes": ["BTC_STATUS_UNAVAILABLE"],
            "error": f"{type(exc).__name__}: {exc}",
        }

    readiness = str(status.get("data_readiness") or "invalid")
    freshness = _json_payload(status.get("operational_freshness"))
    health = _json_payload(status.get("health"))
    observed = _json_payload(health.get("observed"))
    reason_code = _clean_text(status.get("reason_code")) or _clean_text(
        health.get("blocking_reason_code")
    )
    reason_codes = _compact_reason_codes(status, reason_code)
    watermark = (
        _clean_text(freshness.get("watermark"))
        or _clean_text(status.get("watermark"))
        or _clean_text(observed.get("watermark"))
    )
    expected_latest_open = _clean_text(freshness.get("expected_latest_open"))
    staleness_days = freshness.get("staleness_days")
    maximum_staleness_days = freshness.get("maximum_staleness_days")
    fresh = freshness.get("fresh")

    if not current_exists:
        should_autofill = False
        decision_reason = "BTC_CURRENT_POINTER_MISSING"
        title = "BTC startup data check"
        phase = "not_bootstrapped"
        status_text = "BTC current pointer is absent; startup auto-fill is skipped."
    elif readiness != "ready":
        should_autofill = True
        decision_reason = reason_code or "BTC_NOT_READY"
        title = "BTC data auto-fill requested"
        phase = "repair_requested"
        status_text = "BTC data is not ready; startup queued an assurance sync job."
    elif fresh is False:
        should_autofill = True
        decision_reason = "CANONICAL_STALE"
        if "CANONICAL_STALE" not in reason_codes:
            reason_codes.insert(0, "CANONICAL_STALE")
        title = "BTC data auto-fill requested"
        phase = "repair_requested"
        status_text = "BTC data is stale; startup queued an assurance sync job."
    else:
        should_autofill = False
        decision_reason = "BTC_CURRENT_READY"
        title = "BTC startup data check"
        phase = "healthy"
        status_text = "BTC data is ready; startup auto-fill is not needed."

    payload = {
        "title": title,
        "action": "btc_startup_gap_check",
        "phase": phase,
        "status_text": status_text,
        "dataset": "crypto.btc",
        "asset_id": "crypto.BTC",
        "check_date": check_date,
        "decision": "enqueue_autofill" if should_autofill else "no_autofill",
        "reason_code": decision_reason,
        "reason_codes": reason_codes,
        "data_readiness": readiness,
        "current_pointer": str(_btc_current_path(data_root)),
        "current_exists": current_exists,
        "watermark": watermark,
        "expected_latest_open": expected_latest_open,
        "staleness_days": staleness_days,
        "maximum_staleness_days": maximum_staleness_days,
        "fresh": fresh,
        "visibility": {
            "events_api": "/api/events?topic=gate.btc_startup_gap_check",
            "autofill_events_api": "/api/events?topic=gate.btc_autofill",
            "runs_api": "/api/runs?stage=fetch",
        },
    }
    key_parts = [
        "btc-startup-gap-check",
        check_date,
        str(watermark or "none"),
        str(expected_latest_open or "none"),
        decision_reason,
    ]
    return BtcStartupGapDecision(
        should_autofill=should_autofill,
        payload=payload,
        idempotency_key=":".join(key_parts),
    )


def _autofill_payload(check_event: Event, decision: BtcStartupGapDecision) -> dict[str, Any]:
    source = decision.payload
    return {
        "title": "BTC data auto-fill job",
        "action": "btc_auto_fill",
        "phase": "repair_job",
        "status_text": "BTC assurance sync job was queued from startup gap detection.",
        "dataset": "crypto.btc",
        "asset_id": "crypto.BTC",
        "source_event_id": check_event.id,
        "reason_code": source.get("reason_code"),
        "reason_codes": source.get("reason_codes") or [],
        "data_readiness": source.get("data_readiness"),
        "watermark": source.get("watermark"),
        "expected_latest_open": source.get("expected_latest_open"),
        "staleness_days": source.get("staleness_days"),
        "maximum_staleness_days": source.get("maximum_staleness_days"),
        "job_name": BTC_AUTOFILL_JOB_NAME,
        "job_mode": "assurance_sync",
        "visibility": {
            "events_api": "/api/events?topic=gate.btc_autofill",
            "runs_api": "/api/runs?stage=fetch",
        },
    }


def _btc_startup_gap_handler() -> Callable[[Event], None]:
    def handler(event: Event) -> None:
        payload = dict(event.payload or {})
        if payload.get("decision") != "enqueue_autofill":
            logger.info(
                "BTC startup gap check skipped autofill: event_id=%s reason=%s",
                event.id,
                payload.get("reason_code"),
            )
            return

        decision = BtcStartupGapDecision(
            should_autofill=True,
            payload=payload,
            idempotency_key=str(payload.get("idempotency_key") or event.id),
        )
        repair_payload = _autofill_payload(event, decision)
        repair_key = (
            "btc-autofill:"
            f"{repair_payload.get('watermark') or 'none'}:"
            f"{repair_payload.get('expected_latest_open') or 'none'}:"
            f"{repair_payload.get('reason_code') or 'unknown'}"
        )
        repair_event = event.bus.publish_once(
            BTC_AUTOFILL_TOPIC,
            repair_payload,
            idempotency_key=repair_key,
            parent_event_id=event.id,
        )
        if not repair_event.accepted:
            raise RuntimeError(f"BTC autofill event admission failed: {repair_event.outcome.value}")

    handler.__name__ = "btc_startup_gap_check"
    handler.__qualname__ = "runtime.btc_startup_gap_check"
    return handler


def _btc_autofill_handler(db: TradeDB, data_root: str) -> Callable[[Event], None]:
    from trade_py.jobs import JobQualityWarning, run_job

    def handler(event: Event) -> None:
        logger.info("BTC autofill started: event_id=%s payload=%s", event.id, event.payload)
        started = time.monotonic()
        run_id = db.job_run_start(
            BTC_AUTOFILL_JOB_NAME,
            stage="fetch",
            trigger_event_id=event.id,
            run_key="runtime:btc_autofill",
        )
        try:
            summary = run_job(
                BTC_AUTOFILL_JOB_NAME, data_root, config={"trigger": "startup_autofill"}
            )
        except JobQualityWarning as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            summary = str(exc)
            db.job_run_finish(
                run_id,
                "warn",
                result_summary=summary[:500],
                elapsed_ms=elapsed_ms,
            )
            logger.warning(
                "BTC autofill staged but not published: event_id=%s result=%s",
                event.id,
                summary,
            )
            return
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            db.job_run_finish(
                run_id,
                "error",
                result_summary=str(exc)[:500],
                elapsed_ms=elapsed_ms,
            )
            raise
        elapsed_ms = int((time.monotonic() - started) * 1000)
        db.job_run_finish(run_id, "ok", result_summary=summary, elapsed_ms=elapsed_ms)
        synced = event.bus.publish_child_once(
            Topic.CRYPTO_SYNCED,
            {"result": summary, "source": "btc_startup_autofill"},
            parent_event_id=event.id,
            handoff_key=f"btc-autofill:{event.id}:{Topic.CRYPTO_SYNCED}",
        )
        if not synced.accepted:
            logger.warning(
                "BTC downstream handoff deferred: event_id=%s child_event_id=%s outcome=%s",
                event.id,
                synced.event.id,
                synced.outcome.value,
            )
        logger.info("BTC autofill finished: event_id=%s result=%s", event.id, summary)

    handler.__name__ = BTC_AUTOFILL_JOB_NAME
    handler.__qualname__ = "runtime.btc_autofill.crypto_btc_fetch"
    return handler


def register_btc_startup_autofill_handlers(db: TradeDB, bus: EventBus, data_root: str) -> None:
    """Register visible startup BTC repair handlers on the supplied Web EventBus."""

    bus.subscribe(BTC_STARTUP_CHECK_TOPIC, _btc_startup_gap_handler())
    bus.subscribe(BTC_AUTOFILL_TOPIC, _btc_autofill_handler(db, data_root))


def publish_btc_startup_gap_check(
    _db: TradeDB,
    bus: EventBus,
    data_root: str,
    *,
    now: Any | None = None,
) -> BtcStartupGapDecision:
    """Publish one visible, idempotent startup BTC gap-check event."""

    decision = build_btc_startup_gap_decision(data_root, now=now)
    if not decision.payload.get("current_exists"):
        logger.info(
            "BTC startup gap-check skipped because current pointer is absent: path=%s",
            decision.payload.get("current_pointer"),
        )
        return decision
    event_payload = {
        **decision.payload,
        "idempotency_key": decision.idempotency_key,
    }
    result = bus.publish_once(
        BTC_STARTUP_CHECK_TOPIC,
        event_payload,
        idempotency_key=decision.idempotency_key,
    )
    if not result.accepted:
        logger.warning(
            "BTC startup gap-check event deferred: event_id=%s outcome=%s",
            result.event.id,
            result.outcome.value,
        )
    else:
        logger.info(
            "BTC startup gap-check event accepted: event_id=%s decision=%s reason=%s",
            result.event.id,
            decision.payload.get("decision"),
            decision.payload.get("reason_code"),
        )
    return decision
