"""FastAPI transport adapter for read-only runtime operations."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from trade_web.backend.runtime.service import RuntimeService


def build_runtime_router(service: RuntimeService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/status")
    async def get_status():
        return await service.status_snapshot()

    @router.get("/api/runtime/capacity")
    async def get_runtime_capacity():
        return service.capacity_snapshot()

    @router.get("/api/events/stream")
    async def stream_events(
        request: Request,
        after_id: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        poll_seconds: Annotated[float, Query(ge=0.25, le=60.0)] = 2.0,
    ):
        async def generate():
            try:
                async for item in service.event_stream(
                    is_disconnected=request.is_disconnected,
                    after_id=after_id,
                    limit=limit,
                    poll_seconds=poll_seconds,
                ):
                    yield item
            except (asyncio.CancelledError, RuntimeError):
                return

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/runtime/stream")
    async def stream_runtime(
        request: Request,
        scope: str = "report",
        poll_seconds: Annotated[float, Query(ge=0.25, le=60.0)] = 2.0,
    ):
        async def generate():
            try:
                async for item in service.runtime_stream(
                    is_disconnected=request.is_disconnected,
                    scope=scope,
                    poll_seconds=poll_seconds,
                ):
                    yield item
            except (asyncio.CancelledError, RuntimeError):
                return

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/calendar")
    async def get_calendar(
        date_str: str | None = None,
        days: Annotated[int, Query(ge=0, le=366)] = 5,
    ):
        return await service.calendar(date_str=date_str, days=days)

    @router.get("/api/agenda")
    async def get_agenda(
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        status: str | None = None,
    ):
        return await service.agenda(limit=limit, status=status)

    @router.get("/api/backups")
    async def get_backups(
        limit: Annotated[int, Query(ge=1, le=500)] = 20,
        status: str | None = None,
    ):
        return await service.backups(limit=limit, status=status)

    return router
