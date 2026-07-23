"""High-level quality planning and execution orchestration."""

from __future__ import annotations

import hashlib
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from trade_py.devtools.quality.config import QualityConfig, load_config
from trade_py.devtools.quality.executor import StepExecutor, SubprocessExecutor, execute_steps
from trade_py.devtools.quality.models import (
    FailureKind,
    GateMode,
    GatePlan,
    GateReport,
    ResultStatus,
    StepResult,
)
from trade_py.devtools.quality.planner import build_plan
from trade_py.devtools.quality.scope import select_scope


def make_plan(
    repo_root: Path,
    *,
    mode: GateMode,
    base_ref: str | None = None,
    all_mode: bool = False,
    paths: tuple[str, ...] = (),
    config: QualityConfig | None = None,
) -> GatePlan:
    active_config = config or load_config(repo_root)
    selection = select_scope(repo_root, base_ref=base_ref, all_mode=all_mode, paths=paths)
    return build_plan(selection, mode=mode, config=active_config)


def _working_tree_fingerprint(repo_root: Path, eligible_files: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for args in (
        ("diff", "--binary", "--no-ext-diff", "HEAD", "--"),
        ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
    ):
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        digest.update(result.stdout)
        digest.update(b"\0")
    for raw in eligible_files:
        path = repo_root / raw
        digest.update(raw.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _planning_results(plan: GatePlan) -> tuple[StepResult, ...]:
    return tuple(
        StepResult(
            check_id=f"planner.{issue.code}.{index + 1:03d}",
            group="planner",
            name=issue.code,
            status=ResultStatus.FAIL,
            duration_ms=0,
            failure_kind=FailureKind.INFRASTRUCTURE,
            diagnostic=issue.message,
            remediation_code=issue.code,
            remediation="Update quality ownership/provider configuration before completion.",
            files=issue.files,
        )
        for index, issue in enumerate(plan.issues)
    )


def run_gate(
    repo_root: Path,
    *,
    mode: GateMode,
    base_ref: str | None = None,
    all_mode: bool = False,
    paths: tuple[str, ...] = (),
    config: QualityConfig | None = None,
    executor: StepExecutor | None = None,
) -> GateReport:
    started_wall = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    active_config = config or load_config(repo_root)
    plan = make_plan(
        repo_root,
        mode=mode,
        base_ref=base_ref,
        all_mode=all_mode,
        paths=paths,
        config=active_config,
    )
    before = (
        _working_tree_fingerprint(repo_root, plan.eligible_files)
        if mode is GateMode.CHECK and plan.steps
        else None
    )
    active_executor = executor or SubprocessExecutor(repo_root, active_config)
    executed = execute_steps(
        plan.steps,
        active_executor,
        max_light_workers=active_config.max_light_workers,
    )
    results = list(_planning_results(plan)) + list(executed)
    if before is not None:
        after = _working_tree_fingerprint(repo_root, plan.eligible_files)
        if after != before:
            results.append(
                StepResult(
                    check_id="shared.read_only_contract",
                    group="shared",
                    name="Check-mode source protection",
                    status=ResultStatus.FAIL,
                    duration_ms=0,
                    failure_kind=FailureKind.INFRASTRUCTURE,
                    diagnostic="A check step changed tracked or selected source state.",
                    remediation_code="runner.read_only",
                    remediation="Revert the tool write and use ./trade dev fix explicitly.",
                    files=plan.eligible_files,
                )
            )
    return GateReport(
        mode=mode,
        selection=plan.selection,
        started_at=started_wall,
        duration_ms=int((time.monotonic() - started) * 1_000),
        results=tuple(sorted(results, key=lambda item: item.check_id)),
        eligible_files=plan.eligible_files,
        exclusions=plan.exclusions,
        metadata={"all_mode": all_mode, "network_policy": "offline"},
    )
