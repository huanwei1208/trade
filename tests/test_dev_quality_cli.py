from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from trade_py.cli import dev

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_quality_parser_contract() -> None:
    parser = dev.make_parser()
    args = parser.parse_args(
        [
            "check",
            "--all",
            "--base",
            "master",
            "--path",
            "trade_py",
            "--format",
            "json",
            "--show-plan",
        ]
    )

    assert args.cmd == "check"
    assert args.all_mode is True
    assert args.base == "master"
    assert args.path == ["trade_py"]
    assert args.format == "json"
    assert args.show_plan is True


def test_shell_quality_route_is_frozen_and_no_sync(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(REPO_ROOT / "trade"), "dev", "check", "--show-plan"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.splitlines()[:4] == ["run", "--frozen", "--no-sync", "python"]
    assert "dev" in result.stdout.splitlines()
    assert "check" in result.stdout.splitlines()


def test_existing_unregistered_review_path_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "trade"
    repo.mkdir()
    slug = "stale"
    expected = repo.parent / f"trade-wt-review-{slug}"
    expected.mkdir()
    monkeypatch.setattr(
        "trade_py.devtools.quality.scope.discover_repo_root",
        lambda _start: repo,
    )
    monkeypatch.setattr("trade_py.devtools.review.worktree_entries", lambda _root: {})
    args = argparse.Namespace(slug=slug, roles="1,2,3,4,5,6", scope=".")

    code = dev._run_review(args)

    captured = capsys.readouterr()
    assert code == 2
    assert f"wt/review-{slug}-{datetime.now():%Y%m%d}" in captured.out
    assert "unregistered" in captured.out
