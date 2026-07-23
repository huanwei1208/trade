"""Resolve OpenSpec governance applicability from Git scope provenance."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class GovernanceRequirementSource(str, Enum):
    NEW_CHANGE = "new_change"
    MARKER_DELETED = "marker_deleted"
    EXISTING_GOVERNED = "existing_governed"
    HISTORICAL_EXEMPT = "historical_exempt"


@dataclass(frozen=True)
class GovernanceRequirement:
    change: str
    required: bool
    source: GovernanceRequirementSource
    live: bool


@dataclass(frozen=True)
class GovernanceResolution:
    requirements: tuple[GovernanceRequirement, ...]

    @property
    def live_changes(self) -> tuple[str, ...]:
        return tuple(item.change for item in self.requirements if item.live)

    @property
    def required_changes(self) -> tuple[str, ...]:
        return tuple(item.change for item in self.requirements if item.required)

    @property
    def missing_required_changes(self) -> tuple[str, ...]:
        return tuple(item.change for item in self.requirements if item.required and not item.live)


def resolve_governance_requirements(
    repo_root: Path,
    changes: Iterable[str],
    *,
    new_change_names: Iterable[str] = (),
    deleted_files: Iterable[str] = (),
) -> GovernanceResolution:
    """Classify governance requirements using already-established Git provenance."""

    new_changes = set(new_change_names)
    deleted = set(deleted_files)
    requirements: list[GovernanceRequirement] = []
    for change in sorted(set(changes)):
        change_dir = repo_root / "openspec" / "changes" / change
        marker_path = change_dir / "design-quality.toml"
        marker_deleted = f"openspec/changes/{change}/design-quality.toml" in deleted
        if marker_deleted:
            source = GovernanceRequirementSource.MARKER_DELETED
        elif change in new_changes:
            source = GovernanceRequirementSource.NEW_CHANGE
        elif marker_path.is_file():
            source = GovernanceRequirementSource.EXISTING_GOVERNED
        else:
            source = GovernanceRequirementSource.HISTORICAL_EXEMPT
        requirements.append(
            GovernanceRequirement(
                change=change,
                required=source is not GovernanceRequirementSource.HISTORICAL_EXEMPT,
                source=source,
                live=change_dir.is_dir(),
            )
        )
    return GovernanceResolution(tuple(requirements))
