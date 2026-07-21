"""FastAPI observatory router (WP3).

Thin HTTP adapter over the read-only ObservatoryQuery facade. It maps frozen reason
codes to the frozen HTTP status contract, applies ETag/304, and never embeds
business logic. `app.py` only calls `register_observatory_routes(app, data_root)`.

Import decoupling (RA.1): the heavy `ObservatoryQuery` facade is imported lazily
inside `register_observatory_routes` (not at module top) so that importing this
module — and registering the always-on read-only `/capability` probe — never pulls
in the facade or its dependencies. A defect in the facade therefore cannot silently
remove the capability route from the app.
"""

import os
from typing import Any

from trade_py.observatory.domain.vocab import ObservatoryError, ReasonCode

# Frozen reason-code -> HTTP status mapping (frozen_contracts.md §HTTP).
_REASON_STATUS: dict[str, int] = {
    ReasonCode.SNAPSHOT_NOT_FOUND.value: 404,
    ReasonCode.CURRENT_POINTER_INVALID.value: 409,
    ReasonCode.ARTIFACT_HASH_MISMATCH.value: 409,
    ReasonCode.MANIFEST_INVALID.value: 409,
    ReasonCode.CHANNEL_UNAVAILABLE.value: 404,
    ReasonCode.PIT_NOT_PROVEN.value: 422,
    ReasonCode.DATASET_STALE.value: 409,
    ReasonCode.QUALITY_BLOCKED.value: 422,
    ReasonCode.RESEARCH_NOT_ELIGIBLE.value: 422,
    ReasonCode.INVALID_SNAPSHOT_SELECTOR.value: 400,
    ReasonCode.COMPOSITE_NOT_DATASET.value: 422,
    ReasonCode.CATALOG_STALE.value: 503,
    ReasonCode.RESTATED_NOT_PIT.value: 422,
    ReasonCode.LEGACY_TIME_UNPROVEN.value: 422,
}

ASSET_PATH = "crypto.BTC"


def status_for(reason_code: str) -> int:
    return _REASON_STATUS.get(reason_code, 400)


def register_observatory_capability(
    app, data_root: str | None = None, *, enabled: bool | None = None
) -> None:
    """Register only the always-on read-only capability probe.

    This route is reachable regardless of the rollout flag so the frontend and the
    routes stay consistent: a disabled deploy still answers `/capability` with
    `state=disabled` (plan §G) without exposing any data route.
    """

    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    from trade_web.backend.observatory.capability import capability_payload

    root = data_root or os.environ.get("TRADE_DATA_ROOT", "data")
    router = APIRouter(prefix="/api/v1/observatory", tags=["observatory"])

    @router.get("/capability")
    def capability():
        # Read-only probe; never builds the Catalog. `enabled` is fixed at
        # registration time to reflect how the app was constructed.
        return JSONResponse(capability_payload(root, enabled=enabled))

    app.include_router(router)


def register_observatory_capability_error(app) -> None:
    """Register a capability probe that reports the enabled-but-broken state.

    Used only when data-route/facade registration failed while the feature is
    enabled: the frontend must still get an answer from `/capability` (never a
    silently missing route), and that answer must keep navigation hidden
    (`state=error`, `show_nav=False`, `reason_code=route_registration_failed`) so a
    broken deploy does not advertise a non-functional Observatory. The response is
    fixed and safe — it never carries `str(exc)` or paths; the full exception is
    logged server-side by the caller.
    """

    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    from trade_web.backend.observatory.capability import capability_error_payload

    payload = capability_error_payload()
    router = APIRouter(prefix="/api/v1/observatory", tags=["observatory"])

    @router.get("/capability")
    def capability_error():
        return JSONResponse(payload)

    app.include_router(router)


def register_observatory_routes(app, data_root: str | None = None) -> None:
    """Register the observatory router on an existing FastAPI app (minimal glue).

    Registers the always-on read-only capability probe plus the read-only data
    routes. When only the capability probe is wanted (feature disabled), call
    ``register_observatory_capability`` instead.
    """

    from fastapi import APIRouter, Query, Request
    from fastapi.responses import JSONResponse, Response

    # Lazy facade import: kept out of module scope so importing this module (for the
    # always-on capability probe) never depends on the facade or its heavy deps.
    from trade_py.observatory.query.facade import ObservatoryQuery

    root = data_root or os.environ.get("TRADE_DATA_ROOT", "data")
    router = APIRouter(prefix="/api/v1/observatory", tags=["observatory"])

    def _query() -> ObservatoryQuery:
        return ObservatoryQuery(root)

    def _error_response(exc: ObservatoryError) -> JSONResponse:
        status = status_for(exc.reason_code.value)
        payload = exc.to_payload()
        headers = {}
        if exc.reason_code == ReasonCode.CATALOG_STALE:
            headers["Retry-After"] = str(exc.extra.get("retry_after", 1))
        return JSONResponse(status_code=status, content=payload, headers=headers)

    def _maybe_304(request: Request, payload: dict[str, Any]) -> Response | None:
        etag = payload.get("etag")
        if etag and request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return None

    def _ok(payload: dict[str, Any]) -> JSONResponse:
        headers = {}
        if payload.get("etag"):
            headers["ETag"] = payload["etag"]
        return JSONResponse(status_code=200, content=payload, headers=headers)

    @router.get(f"/assets/{ASSET_PATH}/context")
    def context(
        request: Request,
        channel: str = Query("observed"),
        knowledge_as_of: str = Query("latest"),
        knowledge_mode: str = Query("installation_observed"),
        revision_policy: str = Query("as_known"),
        snapshot_id: str | None = Query(None),
        run_id: str | None = Query(None),
    ):
        try:
            payload = _query().context(
                channel=channel,
                knowledge_as_of=knowledge_as_of,
                knowledge_mode=knowledge_mode,
                revision_policy=revision_policy,
                snapshot_id=snapshot_id,
                run_id=run_id,
            )
        except ObservatoryError as exc:
            return _error_response(exc)
        not_modified = _maybe_304(request, payload)
        return not_modified or _ok(payload)

    @router.get(f"/assets/{ASSET_PATH}/series")
    def series(
        request: Request,
        view: str = Query("composite"),
        knowledge_as_of: str = Query("latest"),
        knowledge_mode: str = Query("installation_observed"),
        revision_policy: str = Query("as_known"),
        include_quarantined: bool = Query(False),
        snapshot_id: str | None = Query(None),
        run_id: str | None = Query(None),
        from_: str | None = Query(None, alias="from"),
        to: str | None = Query(None),
    ):
        try:
            payload = _query().series(
                view=view,
                knowledge_as_of=knowledge_as_of,
                knowledge_mode=knowledge_mode,
                revision_policy=revision_policy,
                include_quarantined=include_quarantined,
                snapshot_id=snapshot_id,
                run_id=run_id,
                date_from=from_,
                date_to=to,
            )
        except ObservatoryError as exc:
            return _error_response(exc)
        not_modified = _maybe_304(request, payload)
        return not_modified or _ok(payload)

    @router.get(f"/assets/{ASSET_PATH}/dates/{{market_date}}")
    def date_evidence(
        market_date: str, snapshot_id: str | None = Query(None), channel: str = Query("formal")
    ):
        try:
            return JSONResponse(
                _query().date_evidence(market_date, snapshot_id=snapshot_id, channel=channel)
            )
        except ObservatoryError as exc:
            return _error_response(exc)

    @router.get(f"/assets/{ASSET_PATH}/trust")
    def trust(snapshot_id: str | None = Query(None), channel: str = Query("formal")):
        try:
            return JSONResponse(_query().trust(snapshot_id=snapshot_id, channel=channel))
        except ObservatoryError as exc:
            return _error_response(exc)

    @router.get(f"/assets/{ASSET_PATH}/runs")
    def runs(cursor: str | None = Query(None), limit: int = Query(50, le=500)):
        try:
            return JSONResponse(_query().runs(cursor=cursor, limit=limit))
        except ObservatoryError as exc:
            return _error_response(exc)

    @router.get("/runs/diff")
    def run_diff(base: str = Query(...), compare: str = Query(...)):
        try:
            return JSONResponse(_query().run_diff(base, compare))
        except ObservatoryError as exc:
            return _error_response(exc)

    @router.get("/runs/{run_id}")
    def run_detail(run_id: str):
        try:
            return JSONResponse(_query().run_detail(run_id))
        except ObservatoryError as exc:
            return _error_response(exc)

    @router.get(f"/assets/{ASSET_PATH}/hypotheses")
    def hypotheses():
        try:
            return JSONResponse(_query().hypotheses())
        except ObservatoryError as exc:
            return _error_response(exc)

    @router.get("/research-runs/{research_run_id}")
    def research_run(research_run_id: str):
        try:
            return JSONResponse(_query().research_run(research_run_id))
        except ObservatoryError as exc:
            return _error_response(exc)

    app.include_router(router)
    # Register the always-on capability probe LAST so it only reports enabled=True
    # once every data route above has been successfully constructed. If any data
    # route above raised, this line is never reached and the caller (app factory)
    # registers the `error` capability instead — the probe never lies about a
    # half-registered app.
    register_observatory_capability(app, root, enabled=True)
