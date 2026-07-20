from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

import pytest

from trade_py.devtools.quality import scope
from trade_py.devtools.quality.config import load_config
from trade_py.devtools.quality.executor import execute_steps
from trade_py.devtools.quality.models import CheckStep, ResultStatus, StepResult
from trade_py.devtools.quality.providers.base import batched_paths

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_noop_scope_stays_within_git_process_and_latency_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "quality@example.test")
    _git(repo, "config", "user.name", "Quality Test")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "baseline")
    _git(repo, "branch", "-M", "master")

    config = load_config(REPO_ROOT)
    real_run = subprocess.run
    calls = 0

    def counting_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_run(*args, **kwargs)

    monkeypatch.setattr(scope.subprocess, "run", counting_run)
    started = time.monotonic()
    selection = scope.select_scope(repo, base_ref="master")
    elapsed_ms = int((time.monotonic() - started) * 1_000)

    assert selection.files == ()
    assert calls <= config.max_git_processes
    assert elapsed_ms <= config.max_scope_discovery_ms


def test_large_path_sets_are_byte_bounded() -> None:
    max_bytes = 1_024
    prefix = ("tool", "check", "--")
    files = tuple(f"src/deep/{index:05d}-{'x' * 80}.py" for index in range(2_000))

    batches = batched_paths(files, argv_prefix=prefix, max_bytes=max_bytes)

    assert len(batches) > 100
    assert tuple(path for batch in batches for path in batch) == files
    for batch in batches:
        size = sum(len(item.encode()) + 1 for item in (*prefix, *batch))
        assert size <= max_bytes


class ConcurrencyProbe:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0
        self.lock = threading.Lock()

    def run_step(self, step: CheckStep) -> StepResult:
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        time.sleep(0.02)
        with self.lock:
            self.active -= 1
        return StepResult(
            check_id=step.check_id,
            group=step.group,
            name=step.name,
            status=ResultStatus.PASS,
            duration_ms=20,
        )


def test_lightweight_executor_respects_concurrency_bound() -> None:
    steps = tuple(
        CheckStep(f"step.{index:02d}", "test", "probe", ("probe",)) for index in range(12)
    )
    probe = ConcurrencyProbe()

    results = execute_steps(steps, probe, max_light_workers=3)

    assert len(results) == len(steps)
    assert 1 < probe.maximum <= 3
