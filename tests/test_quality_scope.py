from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from trade_py.devtools.quality.scope import ScopeError, select_scope


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "quality@example.test")
    _git(repo, "config", "user.name", "Quality Test")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    (repo / "tracked.sh").write_text("#!/usr/bin/env bash\ntrue\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md", "tracked.sh")
    _git(repo, "commit", "-m", "baseline")
    _git(repo, "branch", "-M", "master")
    return repo


def test_changed_scope_combines_committed_staged_unstaged_and_untracked(git_repo: Path) -> None:
    _git(git_repo, "checkout", "-b", "feature")
    (git_repo / "committed.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(git_repo, "add", "--", "committed.py")
    _git(git_repo, "commit", "-m", "python")
    (git_repo / "tracked.sh").write_text("#!/usr/bin/env bash\necho changed\n", encoding="utf-8")
    (git_repo / "staged.cpp").write_text("int value = 1;\n", encoding="utf-8")
    _git(git_repo, "add", "--", "staged.cpp")
    (git_repo / "untracked.ts").write_text("export const value = 1;\n", encoding="utf-8")

    selection = select_scope(git_repo, base_ref="master")

    assert selection.files == (
        "committed.py",
        "staged.cpp",
        "tracked.sh",
        "untracked.ts",
    )
    assert selection.base_ref == "master"
    assert selection.base_sha == _git(git_repo, "rev-parse", "master")


def test_scope_is_nul_safe_for_option_and_newline_filenames(git_repo: Path) -> None:
    option_name = "--odd.py"
    newline_name = "line\nbreak.sh"
    (git_repo / option_name).write_text("VALUE = 1\n", encoding="utf-8")
    (git_repo / newline_name).write_text("#!/usr/bin/env bash\ntrue\n", encoding="utf-8")

    selection = select_scope(git_repo, base_ref="master")

    assert option_name in selection.files
    assert newline_name in selection.files


def test_external_symlink_is_rejected(git_repo: Path, tmp_path: Path) -> None:
    external = tmp_path / "outside.py"
    external.write_text("VALUE = 1\n", encoding="utf-8")
    os.symlink(external, git_repo / "escape.py")

    with pytest.raises(ScopeError, match="outside repository"):
        select_scope(git_repo, base_ref="master")


def test_path_filter_only_narrows_existing_scope(git_repo: Path) -> None:
    (git_repo / "one.py").write_text("ONE = 1\n", encoding="utf-8")
    (git_repo / "two.py").write_text("TWO = 2\n", encoding="utf-8")

    selection = select_scope(git_repo, base_ref="master", paths=("one.py",))

    assert selection.files == ("one.py",)
    with pytest.raises(ScopeError, match="escapes repository"):
        select_scope(git_repo, base_ref="master", paths=("../outside.py",))
