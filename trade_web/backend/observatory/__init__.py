"""Observatory FastAPI routes (read-only)."""

from trade_web.backend.observatory.capability import (
    capability_error_payload,
    capability_payload,
    observatory_enabled,
)
from trade_web.backend.observatory.router import (
    register_observatory_capability,
    register_observatory_capability_error,
    register_observatory_routes,
)

__all__ = [
    "register_observatory_routes",
    "register_observatory_capability",
    "register_observatory_capability_error",
    "capability_payload",
    "capability_error_payload",
    "observatory_enabled",
]
