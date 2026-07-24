from __future__ import annotations

from pathlib import Path

from trade_py.devtools.design_quality.governance import (
    GovernanceRequirementSource,
    resolve_governance_requirements,
)


def _change(repo: Path, name: str, *, governed: bool = False) -> Path:
    root = repo / "openspec" / "changes" / name
    root.mkdir(parents=True)
    if governed:
        (root / "design-quality.toml").write_text(
            'schema_version = 1\npolicy_version = "v1"\n',
            encoding="utf-8",
        )
    return root


def test_governance_requirements_preserve_all_provenance_sources(tmp_path: Path) -> None:
    _change(tmp_path, "new-change")
    _change(tmp_path, "marker-deleted")
    _change(tmp_path, "existing-governed", governed=True)
    _change(tmp_path, "historical-change")

    resolution = resolve_governance_requirements(
        tmp_path,
        (
            "historical-change",
            "existing-governed",
            "marker-deleted",
            "new-change",
        ),
        new_change_names=("new-change",),
        deleted_files=("openspec/changes/marker-deleted/design-quality.toml",),
    )

    assert tuple((item.change, item.source) for item in resolution.requirements) == (
        ("existing-governed", GovernanceRequirementSource.EXISTING_GOVERNED),
        ("historical-change", GovernanceRequirementSource.HISTORICAL_EXEMPT),
        ("marker-deleted", GovernanceRequirementSource.MARKER_DELETED),
        ("new-change", GovernanceRequirementSource.NEW_CHANGE),
    )
    assert resolution.live_changes == (
        "existing-governed",
        "historical-change",
        "marker-deleted",
        "new-change",
    )
    assert resolution.required_changes == (
        "existing-governed",
        "marker-deleted",
        "new-change",
    )
    assert resolution.missing_required_changes == ()


def test_deleted_governed_change_is_missing_required(tmp_path: Path) -> None:
    resolution = resolve_governance_requirements(
        tmp_path,
        ("deleted-change",),
        deleted_files=("openspec/changes/deleted-change/design-quality.toml",),
    )

    assert resolution.live_changes == ()
    assert resolution.required_changes == ("deleted-change",)
    assert resolution.missing_required_changes == ("deleted-change",)
