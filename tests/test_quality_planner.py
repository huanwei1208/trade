from __future__ import annotations

from pathlib import Path

from trade_py.devtools.quality.config import QualityConfig
from trade_py.devtools.quality.models import GateMode, ScopeSelection
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
