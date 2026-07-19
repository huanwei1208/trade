"""Legacy timestamp adapter (WP0 §7.7 / WP1.2).

Existing manifests carry `created_at`, `acquisition_evidence.as_of`, and row-level
`fetched_at`, but NOT `staged_at`, `assurance_completed_at`, or
`capture_completed_at`. This adapter derives ordering times with explicit
provenance/precision and NEVER reads filesystem mtime. It emits `LEGACY_TIME_UNPROVEN`
whenever a precise stage time is unavailable so callers can honestly return
`PIT_NOT_PROVEN` for installation-observed queries.
"""
from __future__ import annotations

from typing import Any

from trade_py.observatory.domain.models import LegacyTimeProvenance

ADAPTER_VERSION = "obs-legacy-time-v1"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def derive_capture_completed_at(manifest: dict[str, Any]) -> LegacyTimeProvenance:
    """Capture completion time.

    New schema: attempt receipt time. Legacy: null, coalescing created_at only for
    ordering. Row-level fetched_at is NOT used to impersonate run completion.
    """

    exact = _text(manifest.get("capture_completed_at"))
    if exact:
        return LegacyTimeProvenance(exact, "receipt", "exact", False)
    created = _text(manifest.get("created_at"))
    return LegacyTimeProvenance(created, "manifest.created_at", "proxy", True)


def derive_assurance_completed_at(manifest: dict[str, Any]) -> LegacyTimeProvenance:
    exact = _text(manifest.get("assurance_completed_at"))
    if exact:
        return LegacyTimeProvenance(exact, "receipt", "exact", False)
    created = _text(manifest.get("created_at"))
    return LegacyTimeProvenance(created, "manifest.created_at", "proxy", True)


def derive_staged_at(manifest: dict[str, Any]) -> LegacyTimeProvenance:
    exact = _text(manifest.get("staged_at"))
    if exact:
        return LegacyTimeProvenance(exact, "receipt", "exact", False)
    created = _text(manifest.get("created_at"))
    return LegacyTimeProvenance(created, "manifest.created_at", "proxy", True)


def derive_effective_as_of(manifest: dict[str, Any]) -> str | None:
    """Effective as-of preserving original timezone/precision."""

    evidence = manifest.get("acquisition_evidence") or {}
    return _text(evidence.get("as_of")) or _text(manifest.get("created_at"))


def derive_first_proven_present_at(manifest: dict[str, Any]) -> str | None:
    """Time by which the run was provably registered (its immutable receipt time).

    This proves the fact is not later than this time; it does NOT prove earlier
    visibility.
    """

    return _text(manifest.get("created_at"))


def time_provenance_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Summary block for API/SDK responses."""

    staged = derive_staged_at(manifest)
    assurance = derive_assurance_completed_at(manifest)
    capture = derive_capture_completed_at(manifest)
    unproven = any(t.unproven for t in (staged, assurance, capture))
    return {
        "adapter_version": ADAPTER_VERSION,
        "staged_at": staged.__dict__,
        "assurance_completed_at": assurance.__dict__,
        "capture_completed_at": capture.__dict__,
        "effective_as_of": derive_effective_as_of(manifest),
        "first_proven_present_at": derive_first_proven_present_at(manifest),
        "legacy_time_unproven": unproven,
    }
