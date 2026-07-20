"""Observatory rollout capability/readiness (RA.1, docs/27 Phase A).

The capability probe is a read-only rollout signal the frontend uses to decide
whether to advertise Observatory navigation. It distinguishes these states:

    disabled         -- the Web feature flag is off (TRADE_OBSERVATORY_ENABLED)
    catalog_missing  -- feature on but no Catalog projection has been built
    catalog_stale    -- projection is behind the immutable facts (needs rebuild)
    catalog_corrupt  -- the materialized SQLite projection failed an integrity probe
    ready            -- feature on and the Catalog is current and verifiable
    error            -- route/facade registration failed; feature is on but broken
                        (surfaced instead of silently dropping the capability route)

`disabled`/`error` are owned here (the Web layer); the catalog_* / ready states come
from the read-only `store.capability()` classifier, which never builds or writes the
projection. Startup and GET paths call this without side effects. Only `ready`
authorizes navigation (`show_nav`); every other state hides Observatory.
"""
from __future__ import annotations

import os
from typing import Any

from trade_py.observatory.catalog import store

# The single environment flag that gates the Observatory Web rollout. It is
# explicitly opt-in: an unconfigured/unprepared installation stays disabled so it
# never advertises a broken Observatory page (F14).
ENABLED_ENV = "TRADE_OBSERVATORY_ENABLED"


def observatory_enabled() -> bool:
    """Return True only when the rollout is explicitly enabled.

    Default is OFF. Only the exact values ``1``/``true``/``yes``/``on`` (any case)
    enable it; anything else — including an unset variable — keeps it disabled.
    """

    raw = os.environ.get(ENABLED_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def capability_payload(data_root: str, *, enabled: bool | None = None) -> dict[str, Any]:
    """Build the read-only capability payload for a data root.

    Never builds the Catalog. ``show_nav`` is True only for the fully ``ready``
    state so the frontend hides Observatory navigation for every unready/disabled
    installation.
    """

    if enabled is None:
        enabled = observatory_enabled()
    if not enabled:
        return {"enabled": False, "state": "disabled", "show_nav": False}
    cap = store.capability(data_root)
    state = cap["state"]
    payload: dict[str, Any] = {
        "enabled": True,
        "state": state,
        "show_nav": state == "ready",
    }
    if cap.get("generation_id"):
        payload["generation_id"] = cap["generation_id"]
    return payload


def capability_error_payload() -> dict[str, Any]:
    """Capability payload for an enabled-but-broken rollout.

    Returned when Observatory data-route/facade registration failed at app
    construction. It reports ``state=error`` with ``show_nav=False`` so the
    frontend keeps navigation hidden and the defect is observable via the probe
    rather than silently converting the app into one without a capability route.

    The public payload is stable and safe: it carries a fixed
    ``reason_code="route_registration_failed"`` and NEVER exposes ``str(exc)``,
    filesystem paths, or any internal exception text. The full exception (with
    traceback) is logged server-side by the app factory instead.
    """

    return {
        "enabled": True,
        "state": "error",
        "show_nav": False,
        "reason_code": "route_registration_failed",
    }
