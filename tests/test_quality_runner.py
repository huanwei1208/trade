from __future__ import annotations

import json
import subprocess
from pathlib import Path

from trade_py.devtools.quality.config import QualityConfig
from trade_py.devtools.quality.models import CheckStep, GateMode, ResultStatus, StepResult
from trade_py.devtools.quality.render import render_report_json
from trade_py.devtools.quality.runner import run_gate


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "quality@example.test")
    _git(repo, "config", "user.name", "Quality Test")
    (repo / "base.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "--", "base.md")
    _git(repo, "commit", "-m", "baseline")
    _git(repo, "branch", "-M", "master")
    return repo


class PassingExecutor:
    def run_step(self, step: CheckStep) -> StepResult:
        return StepResult(
            check_id=step.check_id,
            group=step.group,
            name=step.name,
            status=ResultStatus.PASS,
            duration_ms=1,
            files=step.files,
        )


class MutatingExecutor(PassingExecutor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.mutated = False

    def run_step(self, step: CheckStep) -> StepResult:
        if not self.mutated:
            self.path.write_text("changed by check\n", encoding="utf-8")
            self.mutated = True
        return super().run_step(step)


def test_check_detects_source_mutation_from_a_tool(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    source = repo / "service.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    report = run_gate(
        repo,
        mode=GateMode.CHECK,
        base_ref="master",
        config=QualityConfig(max_light_workers=1),
        executor=MutatingExecutor(source),
    )

    by_id = {result.check_id: result for result in report.results}
    assert by_id["shared.read_only_contract"].aggregate_exit_code == 2
    assert report.exit_code == 2


def test_no_applicable_files_is_success_and_json_is_versioned(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    report = run_gate(
        repo,
        mode=GateMode.CHECK,
        base_ref="master",
        executor=PassingExecutor(),
    )
    payload = json.loads(render_report_json(report))

    assert report.exit_code == 0
    assert report.results == ()
    assert payload["schema_version"] == "trade.quality.report.v1"
    assert payload["scope"]["base_ref"] == "master"
    assert payload["results"] == []
