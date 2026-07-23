"""Trusted current-snapshot bindings for structured design report v1."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from trade_py.devtools.design_quality.errors import DesignQualityError
from trade_py.devtools.design_quality.models import ChangeSnapshot, Policy
from trade_py.devtools.design_quality.snapshot import load_snapshots, verify_snapshot
from trade_py.devtools.design_quality.v1_contract import is_substantive_reason
from trade_py.devtools.quality.toml_compat import tomllib


@dataclass(frozen=True)
class ReportBinding:
    governance_status: str
    artifact_digest: str
    profiles: tuple[str, ...] | None
    artifacts: tuple[dict[str, object], ...]
    total_bytes: int


def signaled_impacts(
    snapshot: ChangeSnapshot, policy: Policy, impacts: dict[str, bool]
) -> set[str]:
    text = "\n".join(
        artifact.content
        for artifact in snapshot.artifacts
        if artifact.path in {"proposal.md", "design.md", "tasks.md"}
        or artifact.path.startswith("specs/")
    )
    return {
        impact
        for impact, patterns in policy.impact_signals.items()
        if not impacts.get(impact, False) and any(re.search(pattern, text) for pattern in patterns)
    }


def selected_profile_names(
    snapshot: ChangeSnapshot, policy: Policy, impacts: dict[str, bool]
) -> tuple[str, ...]:
    signaled = signaled_impacts(snapshot, policy, impacts)
    return tuple(
        profile.name
        for profile in policy.profiles
        if profile.name == "core"
        or any(impacts.get(item, False) or item in signaled for item in profile.impacts)
    )


def _valid_impacts(snapshot: ChangeSnapshot, policy: Policy) -> dict[str, bool]:
    marker = snapshot.text("design-quality.toml")
    if marker is None:
        raise DesignQualityError(f"Governed PASS {snapshot.name} has no design-quality.toml")
    try:
        raw = tomllib.loads(marker)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise DesignQualityError(
            f"Governed PASS {snapshot.name} has an invalid design-quality.toml"
        ) from exc
    if raw.get("schema_version") != 1 or raw.get("policy_version") != policy.policy_version:
        raise DesignQualityError(f"Governed PASS {snapshot.name} has an unsupported marker version")
    rows = raw.get("impacts")
    if not isinstance(rows, list):
        raise DesignQualityError(f"Governed PASS {snapshot.name} has invalid impacts")
    impacts: dict[str, bool] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise DesignQualityError(f"Governed PASS {snapshot.name} has invalid impacts")
        impact_id = row.get("id")
        applies = row.get("applies")
        if (
            not isinstance(impact_id, str)
            or impact_id not in policy.required_impacts
            or impact_id in impacts
            or not isinstance(applies, bool)
            or not is_substantive_reason(row.get("reason"))
        ):
            raise DesignQualityError(f"Governed PASS {snapshot.name} has invalid impacts")
        impacts[impact_id] = applies
    if set(impacts) != set(policy.required_impacts):
        raise DesignQualityError(f"Governed PASS {snapshot.name} has incomplete impacts")
    return impacts


def load_report_bindings(
    repo_root: Path,
    names: tuple[str, ...],
    policy: Policy,
    *,
    require_governance: frozenset[str] = frozenset(),
) -> dict[str, ReportBinding]:
    if not names:
        return {}
    snapshots = load_snapshots(repo_root, names, policy)
    bindings: dict[str, ReportBinding] = {}
    for snapshot in snapshots:
        marker_present = snapshot.text("design-quality.toml") is not None
        profiles: tuple[str, ...] | None = ()
        if marker_present:
            try:
                impacts = _valid_impacts(snapshot, policy)
                profiles = selected_profile_names(snapshot, policy, impacts)
            except DesignQualityError:
                profiles = None
        verify_snapshot(snapshot, policy)
        bindings[snapshot.name] = ReportBinding(
            governance_status=(
                "GOVERNED"
                if marker_present
                else "REQUIRED_MISSING"
                if snapshot.name in require_governance
                else "NOT_GOVERNED"
            ),
            artifact_digest=snapshot.artifact_digest,
            profiles=profiles,
            artifacts=tuple(dict(item) for item in snapshot.inventory),
            total_bytes=snapshot.total_bytes,
        )
    return bindings
