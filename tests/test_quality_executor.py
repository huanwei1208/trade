from __future__ import annotations

import os
import sys
from pathlib import Path

from trade_py.devtools.quality.config import QualityConfig
from trade_py.devtools.quality.executor import SubprocessExecutor, execute_steps
from trade_py.devtools.quality.models import (
    CheckStep,
    FailureKind,
    ResultStatus,
    StepResult,
)


class ScriptedExecutor:
    def __init__(self, results: dict[str, StepResult]) -> None:
        self.results = results
        self.called: list[str] = []

    def run_step(self, step: CheckStep) -> StepResult:
        self.called.append(step.check_id)
        return self.results[step.check_id]


def _result(check_id: str, *, kind: FailureKind | None = None) -> StepResult:
    return StepResult(
        check_id=check_id,
        group="test",
        name=check_id,
        status=ResultStatus.FAIL if kind else ResultStatus.PASS,
        duration_ms=1,
        failure_kind=kind,
    )


def test_executor_aggregates_independent_failures_and_skips_dependents() -> None:
    steps = (
        CheckStep("lint", "python", "lint", ("lint",)),
        CheckStep("build", "cpp", "build", ("build",)),
        CheckStep("test", "cpp", "test", ("test",), prerequisites=("build",)),
    )
    executor = ScriptedExecutor(
        {
            "lint": _result("lint", kind=FailureKind.QUALITY),
            "build": _result("build", kind=FailureKind.INFRASTRUCTURE),
        }
    )

    results = execute_steps(steps, executor, max_light_workers=2)
    by_id = {result.check_id: result for result in results}

    assert set(executor.called) == {"lint", "build"}
    assert by_id["test"].status is ResultStatus.SKIP
    assert by_id["test"].caused_by == "build"
    assert max(result.aggregate_exit_code for result in results) == 2


def test_missing_relevant_tool_is_infrastructure_failure(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    step = CheckStep(
        "cpp.format",
        "cpp",
        "clang-format",
        ("definitely-missing-quality-tool", "--version"),
        remediation="Install it.",
    )

    result = executor.run_step(step)

    assert result.status is ResultStatus.FAIL
    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2
    assert "Missing required tool" in result.diagnostic


def test_mutation_target_is_revalidated_before_spawn(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.cpp"
    outside.write_text("int value;\n", encoding="utf-8")
    os.symlink(outside, tmp_path / "owned.cpp")
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    step = CheckStep(
        "cpp.fix",
        "cpp",
        "fix",
        (sys.executable, "--version"),
        files=("owned.cpp",),
        mutates_source=True,
    )

    result = executor.run_step(step)

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert "symlinked source" in result.diagnostic


def test_timeout_and_signal_are_infrastructure_failures(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    timeout = executor.run_step(
        CheckStep(
            "slow",
            "test",
            "slow",
            (sys.executable, "-c", "import time; time.sleep(10)"),
            timeout_seconds=1,
        )
    )
    signalled = executor.run_step(
        CheckStep(
            "signal",
            "test",
            "signal",
            (sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"),
        )
    )

    assert timeout.failure_kind is FailureKind.INFRASTRUCTURE
    assert "Timed out" in timeout.diagnostic
    assert signalled.failure_kind is FailureKind.INFRASTRUCTURE


def test_dynamic_loader_version_failure_is_infrastructure(tmp_path: Path) -> None:
    executor = SubprocessExecutor(tmp_path, QualityConfig())
    result = executor.run_step(
        CheckStep(
            "native",
            "web",
            "native tool",
            (
                sys.executable,
                "-c",
                "import sys; print('GLIBC_2.29 not found (required by tool)', file=sys.stderr); sys.exit(1)",
            ),
        )
    )

    assert result.failure_kind is FailureKind.INFRASTRUCTURE
    assert result.aggregate_exit_code == 2
