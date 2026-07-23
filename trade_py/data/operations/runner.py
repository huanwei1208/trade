from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

from trade_py.data.operations.contracts import ExitCode, OperationResult, StepResult
from trade_py.data.operations.profiles import get_profile


def _dry_run_result(profile_name: str) -> OperationResult:
    profile = get_profile(profile_name)
    return OperationResult(
        operation="update",
        profile=profile.name,
        profile_version=profile.version,
        status="planned",
        exit_code=int(ExitCode.PASS),
        observed=False,
        dry_run=True,
        steps=[
            StepResult(
                step_id=step.step_id,
                job_name=step.job_name,
                status="planned",
                summary=json.dumps(step.config, ensure_ascii=False, sort_keys=True),
            )
            for step in profile.steps
        ],
        evidence={"description": profile.description},
    )


def run_update(
    data_root: str | Path,
    profile_name: str,
    *,
    dry_run: bool = False,
    keep_going: bool = False,
) -> OperationResult:
    """Execute one explicit profile with a non-blocking update-level lock."""
    if dry_run:
        return _dry_run_result(profile_name)

    started = time.monotonic()
    profile = get_profile(profile_name)
    root = Path(data_root)
    lock_dir = root / ".db" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "data-update.lock"
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return OperationResult(
                operation="update",
                profile=profile.name,
                profile_version=profile.version,
                status="error",
                exit_code=int(ExitCode.EXECUTION_ERROR),
                elapsed_ms=int((time.monotonic() - started) * 1000),
                evidence={"error": f"another data update holds {lock_path}"},
            )

        from trade_py.db.trade_db import TradeDB
        from trade_py.jobs import JobQualityWarning, run_job

        db = TradeDB(root)
        parent_run_id = db.job_run_start(f"data_update_{profile.name}", stage="fetch")
        results: list[StepResult] = []
        failed = False
        warned = False
        interrupted = False
        try:
            for step in profile.steps:
                step_started = time.monotonic()
                step_run_id = db.job_run_start(step.job_name, stage="fetch")
                try:
                    summary = run_job(
                        step.job_name,
                        str(root),
                        config=dict(step.config),
                    )
                    elapsed_ms = int((time.monotonic() - step_started) * 1000)
                    db.job_run_finish(
                        step_run_id,
                        "ok",
                        result_summary=str(summary)[:500],
                        elapsed_ms=elapsed_ms,
                    )
                    results.append(StepResult(
                        step.step_id,
                        step.job_name,
                        "ok",
                        str(summary),
                        elapsed_ms,
                        step_run_id,
                    ))
                except JobQualityWarning as exc:
                    elapsed_ms = int((time.monotonic() - step_started) * 1000)
                    summary = str(exc)
                    db.job_run_finish(
                        step_run_id,
                        "warn",
                        result_summary=summary[:500],
                        elapsed_ms=elapsed_ms,
                    )
                    results.append(StepResult(
                        step.step_id,
                        step.job_name,
                        "warn",
                        summary,
                        elapsed_ms,
                        step_run_id,
                    ))
                    warned = True
                except KeyboardInterrupt:
                    elapsed_ms = int((time.monotonic() - step_started) * 1000)
                    db.job_run_finish(
                        step_run_id,
                        "error",
                        result_summary="interrupted by user",
                        elapsed_ms=elapsed_ms,
                    )
                    results.append(StepResult(
                        step.step_id,
                        step.job_name,
                        "interrupted",
                        "interrupted by user",
                        elapsed_ms,
                        step_run_id,
                    ))
                    failed = True
                    interrupted = True
                    break
                except Exception as exc:
                    elapsed_ms = int((time.monotonic() - step_started) * 1000)
                    summary = f"{type(exc).__name__}: {exc}"
                    db.job_run_finish(
                        step_run_id,
                        "error",
                        result_summary=summary[:500],
                        elapsed_ms=elapsed_ms,
                    )
                    results.append(StepResult(
                        step.step_id,
                        step.job_name,
                        "error",
                        summary,
                        elapsed_ms,
                        step_run_id,
                    ))
                    failed = True
                    if not keep_going:
                        break

            elapsed_ms = int((time.monotonic() - started) * 1000)
            parent_status = "error" if failed else ("warn" if warned else "ok")
            db.job_run_finish(
                parent_run_id,
                parent_status,
                result_summary=(
                    f"profile={profile.name} completed={sum(r.status == 'ok' for r in results)} "
                    f"warned={sum(r.status == 'warn' for r in results)} "
                    f"failed={sum(r.status in {'error', 'interrupted'} for r in results)}"
                ),
                elapsed_ms=elapsed_ms,
            )
            return OperationResult(
                operation="update",
                profile=profile.name,
                profile_version=profile.version,
                status=(
                    "interrupted"
                    if interrupted
                    else ("fail" if failed else ("warn" if warned else "pass"))
                ),
                exit_code=int(
                    ExitCode.INTERRUPTED
                    if interrupted
                    else (
                        ExitCode.FAILURE
                        if failed
                        else (ExitCode.WARN if warned else ExitCode.PASS)
                    )
                ),
                observed=True,
                elapsed_ms=elapsed_ms,
                run_id=parent_run_id,
                steps=results,
                evidence={"lock_path": str(lock_path), "keep_going": keep_going},
            )
        finally:
            db.close()
    except Exception as exc:
        return OperationResult(
            operation="update",
            profile=profile.name,
            profile_version=profile.version,
            status="error",
            exit_code=int(ExitCode.EXECUTION_ERROR),
            elapsed_ms=int((time.monotonic() - started) * 1000),
            evidence={"error": f"{type(exc).__name__}: {exc}"},
        )
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
