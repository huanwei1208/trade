from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from trade_py.devtools.quality.config import QualityConfig
from trade_py.devtools.quality.models import GateMode, ResourceClass, ScopeSelection
from trade_py.devtools.quality.planner import build_plan


def _selection(tmp_path: Path, *files: str, all_mode: bool = False) -> ScopeSelection:
    return ScopeSelection(
        repo_root=str(tmp_path),
        base_ref="master",
        base_sha="a" * 40,
        head_sha="b" * 40,
        files=tuple(files),
        fingerprint="f" * 64,
        all_mode=all_mode,
        delta_files=() if all_mode else tuple(files),
    )


def test_mixed_plan_routes_every_language_and_excludes_vendor(tmp_path: Path) -> None:
    plan = build_plan(
        _selection(
            tmp_path,
            "trade_py/service.py",
            "trade",
            "engine/src/main.cpp",
            "engine/tradedb-driver/src/main/java/io/tradedb/Test.java",
            "trade_web/frontend/src/App.tsx",
            "engine/vendor/sqlite/sqlite3.c",
            "new_language.rs",
        ),
        mode=GateMode.CHECK,
        config=QualityConfig(),
    )

    groups = {step.group for step in plan.steps}
    assert {"python", "shell", "cpp", "java", "web", "shared"} <= groups
    assert any(item.path == "engine/vendor/sqlite/sqlite3.c" for item in plan.exclusions)
    assert any(issue.code == "scope.uncovered_source" for issue in plan.issues)
    assert all(not step.mutates_source for step in plan.steps)
    assert all("--write" not in step.argv and "-i" not in step.argv for step in plan.steps)
    assert all(step.network_policy == "offline" for step in plan.steps)
    assert all(not {"install", "ci", "sync", "add"}.intersection(step.argv) for step in plan.steps)
    basedpyright = next(step for step in plan.steps if step.check_id == "python.basedpyright")
    assert basedpyright.argv[:3] == ("basedpyright", "--project", "pyproject.toml")


def test_fix_only_mutates_selected_owned_files(tmp_path: Path) -> None:
    plan = build_plan(
        _selection(
            tmp_path,
            "engine/src/owned.cpp",
            "engine/vendor/sqlite/sqlite3.c",
            "trade_web/frontend/src/App.tsx",
        ),
        mode=GateMode.FIX,
        config=QualityConfig(),
    )

    mutations = [step for step in plan.steps if step.mutates_source]
    assert mutations
    assert all("engine/vendor" not in path for step in mutations for path in step.files)
    assert {path for step in mutations for path in step.files} == {
        "engine/src/owned.cpp",
        "trade_web/frontend/src/App.tsx",
    }
    assert any(step.argv[:2] == ("clang-format", "-i") for step in mutations)
    assert any(step.argv[0].endswith("prettier") and "--write" in step.argv for step in mutations)
    assert any(step.argv[0].endswith("eslint") and "--fix" in step.argv for step in mutations)


def test_all_mode_adds_heavy_dependency_chains(tmp_path: Path) -> None:
    plan = build_plan(
        _selection(
            tmp_path,
            "engine/src/main.cpp",
            "engine/tradedb-driver/src/main/java/io/tradedb/Test.java",
            "trade_web/frontend/src/App.tsx",
            all_mode=True,
        ),
        mode=GateMode.CHECK,
        config=QualityConfig(),
    )
    by_id = {step.check_id: step for step in plan.steps}

    assert by_id["cpp.cmake_build"].prerequisites == ("cpp.cmake_configure",)
    assert by_id["cpp.ctest"].prerequisites == ("cpp.cmake_build",)
    assert by_id["java.tests"].prerequisites == ("java.spotless",)
    assert by_id["web.build"].prerequisites == ("web.typescript",)


@pytest.mark.parametrize("change_count", (2, 10, 100))
def test_design_contributor_is_supplemental_strict_and_batched(
    tmp_path: Path, change_count: int
) -> None:
    changes = []
    files = ["trade_py/service.py"]
    added = []
    for index in range(change_count):
        change = f"change-{index}"
        changes.append(change)
        root = tmp_path / "openspec" / "changes" / change
        root.mkdir(parents=True)
        (root / "design-quality.toml").write_text(
            'schema_version = 1\npolicy_version = "v1"\n', encoding="utf-8"
        )
        files.extend(
            (
                f"openspec/changes/{change}/design-quality.toml",
                f"openspec/changes/{change}/design.md",
            )
        )
        added.append(f"openspec/changes/{change}/.openspec.yaml")
    selection = _selection(tmp_path, *files)
    selection = replace(
        selection,
        added_files=tuple(added),
        new_change_names=tuple(changes),
    )

    plan = build_plan(selection, mode=GateMode.CHECK, config=QualityConfig())

    design_steps = [step for step in plan.steps if step.check_id == "design.strict"]
    assert len(design_steps) == 1
    step = design_steps[0]
    assert "--strict" in step.argv
    assert [item for item in step.argv if item == "--change"] == ["--change"] * change_count
    assert [item for item in step.argv if item == "--require-governance"] == [
        "--require-governance"
    ] * change_count
    assert step.structured_output_schema == "trade.design.batch.v1"
    assert step.resource_class is ResourceClass.HEAVY
    assert any(item.check_id == "python.ruff_lint" for item in plan.steps)
    assert any(item.check_id == "shared.config_parse" for item in plan.steps)


def test_deleted_governance_marker_plans_fail_closed_check(tmp_path: Path) -> None:
    marker = "openspec/changes/deleted-change/design-quality.toml"
    selection = ScopeSelection(
        repo_root=str(tmp_path),
        base_ref="master",
        base_sha="a" * 40,
        head_sha="b" * 40,
        files=(),
        fingerprint="f" * 64,
        deleted_files=(marker,),
    )

    plan = build_plan(selection, mode=GateMode.CHECK, config=QualityConfig())

    step = next(item for item in plan.steps if item.check_id == "design.strict")
    assert step.argv[-2:] == ("--missing-required", "deleted-change")


def test_historical_ungoverned_change_is_checked_without_forced_migration(tmp_path: Path) -> None:
    root = tmp_path / "openspec" / "changes" / "historical-change"
    root.mkdir(parents=True)
    (root / "proposal.md").write_text("historical\n", encoding="utf-8")

    plan = build_plan(
        _selection(tmp_path, "openspec/changes/historical-change/proposal.md"),
        mode=GateMode.CHECK,
        config=QualityConfig(),
    )

    step = next(item for item in plan.steps if item.check_id == "design.strict")
    assert step.argv[-2:] == ("--change", "historical-change")
    assert "--require-governance" not in step.argv


def test_new_change_without_openspec_sentinel_requires_governance(tmp_path: Path) -> None:
    root = tmp_path / "openspec" / "changes" / "new-change"
    root.mkdir(parents=True)
    (root / "proposal.md").write_text("new\n", encoding="utf-8")
    selection = replace(
        _selection(tmp_path, "openspec/changes/new-change/proposal.md"),
        added_files=("openspec/changes/new-change/proposal.md",),
        new_change_names=("new-change",),
    )

    plan = build_plan(selection, mode=GateMode.CHECK, config=QualityConfig())

    step = next(item for item in plan.steps if item.check_id == "design.strict")
    assert step.argv[-4:] == (
        "--change",
        "new-change",
        "--require-governance",
        "new-change",
    )


def test_existing_policy_version_edit_is_blocked(tmp_path: Path) -> None:
    selection = _selection(tmp_path, "design-policy/v1.toml")

    plan = build_plan(selection, mode=GateMode.CHECK, config=QualityConfig())

    step = next(item for item in plan.steps if item.check_id == "design.strict")
    assert step.argv[-2:] == ("--immutable-policy-edit", "design-policy/v1.toml")
    assert step.nonzero_kind.value == "infrastructure"


def test_all_mode_does_not_treat_unchanged_policy_as_an_edit(tmp_path: Path) -> None:
    change = tmp_path / "openspec" / "changes" / "historical-change"
    change.mkdir(parents=True)
    (change / "proposal.md").write_text("historical\n", encoding="utf-8")
    selection = _selection(
        tmp_path,
        "design-policy/v1.toml",
        "openspec/changes/historical-change/proposal.md",
        all_mode=True,
    )

    plan = build_plan(selection, mode=GateMode.CHECK, config=QualityConfig())

    step = next(item for item in plan.steps if item.check_id == "design.strict")
    assert "--immutable-policy-edit" not in step.argv


def test_fix_mode_does_not_run_design_contributor(tmp_path: Path) -> None:
    root = tmp_path / "openspec" / "changes" / "fix-change"
    root.mkdir(parents=True)
    (root / "design-quality.toml").write_text("schema_version = 1\n", encoding="utf-8")

    plan = build_plan(
        _selection(tmp_path, "openspec/changes/fix-change/design-quality.toml"),
        mode=GateMode.FIX,
        config=QualityConfig(),
    )

    assert all(item.check_id != "design.strict" for item in plan.steps)
