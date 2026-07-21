"""Application service for read-only Web runtime operations."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any, Protocol, cast

from trade_web.backend.runtime.resources import ResourceLifecycle, WebResourceContainer

logger = logging.getLogger(__name__)

_PAYLOAD_SCHEMA_VERSION = "2026-03-21-recommendation-recovery-v2"
_STATUS_CACHE_TTL_SECONDS = 1.0


class _RuntimeReadStore(Protocol):
    def trading_calendar_range(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "SSE",
    ) -> list[dict[str, Any]]: ...


class RuntimeService:
    """Provide status, signatures, and stream payloads from owned resources."""

    def __init__(
        self,
        resources: WebResourceContainer,
        shutdown_event: asyncio.Event,
    ) -> None:
        self._resources = resources
        self._shutdown_event = shutdown_event
        self._status_lock = asyncio.Lock()
        self._status_cache: tuple[float, dict[str, Any]] | None = None

    @property
    def data_root(self) -> str:
        return self._resources.data_root

    def current_asof(self, db=None) -> str:
        local_db = db or self._resources.db
        try:
            return local_db.get_latest_market_asof() or date.today().isoformat()
        except Exception:
            return date.today().isoformat()

    def payload_signature(self, kind: str, db=None) -> str:
        local_db = db or self._resources.db
        base = "|".join(str(item or "") for item in local_db.runtime_payload_signature_inputs())
        return f"{kind}:{_PAYLOAD_SCHEMA_VERSION}:{self.current_asof(local_db)}:{base}"

    async def status_snapshot(self) -> dict[str, Any]:
        cached = self._status_cache
        now = time.monotonic()
        if cached is not None and now - cached[0] <= _STATUS_CACHE_TTL_SECONDS:
            return cached[1]
        async with self._status_lock:
            cached = self._status_cache
            now = time.monotonic()
            if cached is not None and now - cached[0] <= _STATUS_CACHE_TTL_SECONDS:
                return cached[1]
            snapshot = await asyncio.to_thread(self._build_status_snapshot)
            self._status_cache = (time.monotonic(), snapshot)
            return snapshot

    def _build_status_snapshot(self) -> dict[str, Any]:
        db = self._resources.db
        today = date.today().isoformat()
        reason_codes: list[str] = []

        def record_failure(reason_code: str, component: str, exc: Exception) -> None:
            reason_codes.append(reason_code)
            logger.warning(
                "runtime status component unavailable: component=%s error=%s",
                component,
                type(exc).__name__,
            )

        try:
            gate = db.quality_gate_get()
        except Exception as exc:
            record_failure("QUALITY_GATE_UNAVAILABLE", "quality_gate", exc)
            gate = None
        try:
            from trade_py.utils.data_inspector import get_data_status

            data_status = get_data_status(self.data_root, sample_limit=8)
        except Exception as exc:
            record_failure("DATA_STATUS_UNAVAILABLE", "data_status", exc)
            data_status = {
                "quality_gate": {
                    "status": "unknown",
                    "reason_codes": ["DATA_STATUS_UNAVAILABLE"],
                    "components": {},
                    "recovery_plan": [],
                }
            }
        try:
            from scripts.backup import backup_doctor

            backup_health = backup_doctor(self.data_root)
        except Exception as exc:
            record_failure("BACKUP_HEALTH_UNAVAILABLE", "backup_health", exc)
            backup_health = {
                "backend": "local",
                "enabled": False,
                "google_drive_available": False,
                "google_drive_folder_id": "",
                "google_drive_key_file": "",
            }
        try:
            inference_models = self._resources.inference.model_names
            models_loaded_at = self._resources.inference.loaded_at
        except Exception as exc:
            record_failure("INFERENCE_STATUS_UNAVAILABLE", "inference", exc)
            inference_models = []
            models_loaded_at = None
        try:
            due_agenda = db.agenda_queue_due(limit=10)
        except Exception as exc:
            record_failure("AGENDA_UNAVAILABLE", "agenda", exc)
            due_agenda = []
        try:
            planned_events = db.planned_events_list(
                start_date=today,
                end_date=(date.today() + timedelta(days=7)).isoformat(),
                limit=10,
            )
        except Exception as exc:
            record_failure("PLANNED_EVENTS_UNAVAILABLE", "planned_events", exc)
            planned_events = []
        try:
            backups = db.backup_snapshots_recent(limit=5)
        except Exception as exc:
            record_failure("BACKUP_SNAPSHOTS_UNAVAILABLE", "backups", exc)
            backups = []
        health_status = "degraded" if reason_codes else "ok"
        return {
            "status": "ok",
            "health": {
                "status": health_status,
                "reason_codes": reason_codes,
            },
            "degraded": bool(reason_codes),
            "data_root": self.data_root,
            "today": today,
            "inference_models": inference_models,
            "models_loaded_at": models_loaded_at,
            "quality_gate": gate,
            "data_quality_gate": data_status.get("quality_gate"),
            "data_status": data_status,
            "due_agenda": due_agenda,
            "planned_events": planned_events,
            "backups": backups,
            "backup_health": backup_health,
        }

    def capacity_snapshot(self) -> dict[str, Any]:
        lifecycle, snapshot = self._resources.bus_capacity_snapshot()
        if snapshot is None:
            return {
                "status": "unavailable",
                "lifecycle": lifecycle.value,
                "generation": None,
                "started_at": None,
                "channels": None,
            }
        return {
            "status": (
                "stopping" if lifecycle is ResourceLifecycle.STOPPING else snapshot.status.value
            ),
            "lifecycle": (
                "stopping" if lifecycle is ResourceLifecycle.STOPPING else snapshot.lifecycle.value
            ),
            "generation": snapshot.generation,
            "started_at": snapshot.started_at.isoformat(),
            "channels": {
                channel.name: {
                    "lifecycle": channel.lifecycle.value,
                    "workers": channel.workers,
                    "capacity": channel.capacity,
                    "admitted": channel.admitted,
                    "active": channel.active,
                    "available": channel.available,
                    "outcomes": {
                        "accepted": channel.accepted_count,
                        "saturated": channel.saturated_count,
                        "shutting_down": channel.shutting_down_count,
                        "submission_failed": channel.submission_failed_count,
                    },
                    "last_saturation_at": (
                        channel.last_saturation_at.isoformat()
                        if channel.last_saturation_at is not None
                        else None
                    ),
                }
                for channel in snapshot.channels
            },
        }

    async def calendar(self, date_str: str | None = None, days: int = 5) -> dict[str, Any]:
        return await asyncio.to_thread(self._read_calendar, date_str, days)

    def _read_calendar(self, date_str: str | None, days: int) -> dict[str, Any]:
        db = self._resources.db
        start = date.fromisoformat(date_str) if date_str else date.today()
        bounded_days = max(0, int(days))
        end = start + timedelta(days=bounded_days)
        calendar_rows = cast(_RuntimeReadStore, db).trading_calendar_range(
            start.isoformat(),
            end.isoformat(),
            exchange="SSE",
        )
        planned = db.planned_events_list(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            limit=100,
        )
        return {"calendar": calendar_rows, "planned_events": planned}

    async def agenda(self, limit: int = 50, status: str | None = None) -> list[dict]:
        return await asyncio.to_thread(
            self._resources.db.agenda_queue_recent,
            limit=limit,
            status=status,
        )

    async def backups(self, limit: int = 20, status: str | None = None) -> list[dict]:
        return await asyncio.to_thread(
            self._resources.db.backup_snapshots_recent,
            limit=limit,
            status=status,
        )

    async def event_stream(
        self,
        *,
        is_disconnected: Callable[[], Awaitable[bool]],
        after_id: int = 0,
        limit: int = 50,
        poll_seconds: float = 2.0,
    ) -> AsyncIterator[str]:
        last_id = max(0, int(after_id))
        db = self._resources.db
        while not self._shutdown_event.is_set():
            try:
                if await is_disconnected():
                    return
            except RuntimeError:
                return
            rows = db.event_log_since(after_id=last_id, limit=limit)
            if rows:
                for row in rows:
                    last_id = max(last_id, int(row.get("id") or 0))
                    yield f"data: {json.dumps(row, ensure_ascii=False)}\n\n"
            else:
                yield ": ping\n\n"
            if await self.wait_for_shutdown(poll_seconds):
                return

    async def runtime_stream(
        self,
        *,
        is_disconnected: Callable[[], Awaitable[bool]],
        scope: str = "report",
        poll_seconds: float = 2.0,
    ) -> AsyncIterator[str]:
        scope_name = "events-page" if str(scope).strip().lower() == "events" else "report-page"
        last_signature = ""
        db = self._resources.db
        while not self._shutdown_event.is_set():
            try:
                if await is_disconnected():
                    return
            except RuntimeError:
                return
            signature = self.payload_signature(scope_name, db=db)
            if signature != last_signature:
                last_signature = signature
                payload = {
                    "scope": scope_name,
                    "signature": signature,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            else:
                yield ": ping\n\n"
            if await self.wait_for_shutdown(poll_seconds):
                return

    async def wait_for_shutdown(self, poll_seconds: float) -> bool:
        try:
            await asyncio.wait_for(
                self._shutdown_event.wait(),
                timeout=max(0.25, float(poll_seconds)),
            )
            return True
        except asyncio.TimeoutError:
            return self._shutdown_event.is_set()
