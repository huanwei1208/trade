"""Bounded, shell-free execution with dependency-aware aggregation."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol

from trade_py.devtools.quality.config import QualityConfig, exclusion_reason
from trade_py.devtools.quality.models import (
    CheckStep,
    FailureKind,
    ResourceClass,
    ResultStatus,
    StepResult,
)

_INFRA_DIAGNOSTIC_MARKERS = (
    "pluginresolutionexception",
    "dependencyresolutionexception",
    "could not resolve dependencies",
    "cannot access central in offline mode",
    "has not been downloaded from it before",
    "could not find or load main class",
    "glibc_",
    "version `glibc",
    "not found (required by",
)


class StepExecutor(Protocol):
    def run_step(self, step: CheckStep) -> StepResult: ...


def resolve_executable(executable: str, cwd: Path) -> str | None:
    if "/" in executable:
        candidate = Path(executable)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        return (
            str(candidate.resolve())
            if candidate.is_file() and os.access(candidate, os.X_OK)
            else None
        )
    return shutil.which(executable)


def _bounded_diagnostic(stdout: bytes, stderr: bytes, limit: int) -> str:
    combined = stderr
    if stdout:
        combined = combined + (b"\n" if combined else b"") + stdout
    if len(combined) > limit:
        combined = combined[:limit] + b"\n... output truncated by quality gate ..."
    return combined.decode("utf-8", "replace").strip()


class SubprocessExecutor:
    def __init__(self, repo_root: Path, config: QualityConfig) -> None:
        self._repo_root = repo_root.resolve()
        self._config = config

    def _cwd(self, step: CheckStep) -> Path:
        cwd = (self._repo_root / step.cwd).resolve()
        try:
            cwd.relative_to(self._repo_root)
        except ValueError as exc:
            raise ValueError(f"Step cwd escapes repository: {step.cwd}") from exc
        if not cwd.is_dir():
            raise ValueError(f"Step cwd does not exist: {step.cwd}")
        return cwd

    def _version(self, step: CheckStep, cwd: Path) -> str | None:
        if not step.version_argv:
            return None
        try:
            result = subprocess.run(
                list(step.version_argv),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        output = (result.stdout or result.stderr).strip().splitlines()
        return output[0][:512] if output else None

    def _validate_mutation_targets(self, step: CheckStep) -> str | None:
        if not step.mutates_source:
            return None
        for raw in step.files:
            path = self._repo_root / raw
            if path.is_symlink():
                return f"Refusing to mutate symlinked source: {raw}"
            try:
                path.resolve(strict=True).relative_to(self._repo_root)
            except (OSError, ValueError):
                return f"Mutation target is missing or outside repository: {raw}"
            if reason := exclusion_reason(raw, self._config):
                return f"Refusing to mutate {reason} path: {raw}"
        return None

    def run_step(self, step: CheckStep) -> StepResult:
        started = time.monotonic()
        try:
            cwd = self._cwd(step)
        except ValueError as exc:
            return self._infrastructure(step, started, str(exc))
        if not step.argv:
            return self._infrastructure(step, started, "Step has empty argv")
        if mutation_error := self._validate_mutation_targets(step):
            return self._infrastructure(step, started, mutation_error)
        tool_path = resolve_executable(step.argv[0], cwd)
        if not tool_path:
            hint = self._config.setup_hint(step.argv[0])
            return self._infrastructure(
                step,
                started,
                f"Missing required tool: {step.argv[0]}\nSetup: {hint}",
                remediation=hint,
            )

        env = os.environ.copy()
        env.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PIP_NO_INDEX": "1",
                "UV_OFFLINE": "1",
                "npm_config_offline": "true",
            }
        )
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                list(step.argv),
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            stdout, stderr = process.communicate(timeout=step.timeout_seconds)
        except subprocess.TimeoutExpired:
            if process is not None:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
            else:
                stdout, stderr = b"", b""
            diagnostic = _bounded_diagnostic(stdout, stderr, step.output_limit_bytes)
            suffix = f"\n{diagnostic}" if diagnostic else ""
            return self._infrastructure(
                step,
                started,
                f"Timed out after {step.timeout_seconds}s{suffix}",
                tool_path=tool_path,
            )
        except OSError as exc:
            return self._infrastructure(
                step, started, f"Cannot spawn {step.argv[0]}: {exc}", tool_path=tool_path
            )

        duration_ms = int((time.monotonic() - started) * 1_000)
        diagnostic = _bounded_diagnostic(stdout, stderr, step.output_limit_bytes)
        version = self._version(step, cwd)
        if process.returncode == 0:
            return StepResult(
                check_id=step.check_id,
                group=step.group,
                name=step.name,
                status=ResultStatus.PASS,
                duration_ms=duration_ms,
                exit_code=0,
                diagnostic=diagnostic,
                remediation_code=step.remediation_code,
                remediation=step.remediation,
                files=step.files,
                tool_path=tool_path,
                tool_version=version,
            )

        failure_kind = step.nonzero_kind
        lowered = diagnostic.lower()
        if process.returncode < 0 or any(marker in lowered for marker in _INFRA_DIAGNOSTIC_MARKERS):
            failure_kind = FailureKind.INFRASTRUCTURE
        status = ResultStatus.FAIL if step.required else ResultStatus.WARN
        return StepResult(
            check_id=step.check_id,
            group=step.group,
            name=step.name,
            status=status,
            duration_ms=duration_ms,
            exit_code=process.returncode,
            failure_kind=failure_kind,
            diagnostic=diagnostic,
            remediation_code=step.remediation_code,
            remediation=step.remediation,
            files=step.files,
            tool_path=tool_path,
            tool_version=version,
        )

    def _infrastructure(
        self,
        step: CheckStep,
        started: float,
        diagnostic: str,
        *,
        remediation: str | None = None,
        tool_path: str | None = None,
    ) -> StepResult:
        return StepResult(
            check_id=step.check_id,
            group=step.group,
            name=step.name,
            status=ResultStatus.FAIL,
            duration_ms=int((time.monotonic() - started) * 1_000),
            failure_kind=FailureKind.INFRASTRUCTURE,
            diagnostic=diagnostic,
            remediation_code="infrastructure.tool",
            remediation=remediation or step.remediation,
            files=step.files,
            tool_path=tool_path,
        )


def _blocked_result(step: CheckStep, cause: StepResult) -> StepResult:
    return StepResult(
        check_id=step.check_id,
        group=step.group,
        name=step.name,
        status=ResultStatus.SKIP,
        duration_ms=0,
        failure_kind=cause.failure_kind or FailureKind.QUALITY,
        diagnostic=f"Blocked by {cause.check_id}",
        remediation_code=step.remediation_code,
        remediation=step.remediation,
        files=step.files,
        caused_by=cause.check_id,
    )


def execute_steps(
    steps: tuple[CheckStep, ...],
    executor: StepExecutor,
    *,
    max_light_workers: int,
) -> tuple[StepResult, ...]:
    pending = {step.check_id: step for step in steps}
    results: dict[str, StepResult] = {}
    while pending:
        progressed = False
        for check_id, step in tuple(pending.items()):
            failed_causes = [
                results[item]
                for item in step.prerequisites
                if item in results
                and results[item].status not in {ResultStatus.PASS, ResultStatus.WARN}
            ]
            if failed_causes:
                results[check_id] = _blocked_result(step, failed_causes[0])
                del pending[check_id]
                progressed = True

        ready = [
            step for step in pending.values() if all(item in results for item in step.prerequisites)
        ]
        light = sorted(
            (step for step in ready if step.resource_class is ResourceClass.LIGHT),
            key=lambda item: item.check_id,
        )
        if light:
            with ThreadPoolExecutor(max_workers=max(1, max_light_workers)) as pool:
                completed = list(pool.map(executor.run_step, light))
            for step, result in zip(light, completed, strict=True):
                results[step.check_id] = result
                del pending[step.check_id]
                progressed = True

        heavy = sorted(
            (
                step
                for step in ready
                if step.resource_class is ResourceClass.HEAVY and step.check_id in pending
            ),
            key=lambda item: item.check_id,
        )
        for step in heavy:
            results[step.check_id] = executor.run_step(step)
            del pending[step.check_id]
            progressed = True

        if not progressed:
            for step in pending.values():
                results[step.check_id] = StepResult(
                    check_id=step.check_id,
                    group=step.group,
                    name=step.name,
                    status=ResultStatus.FAIL,
                    duration_ms=0,
                    failure_kind=FailureKind.INFRASTRUCTURE,
                    diagnostic="Cyclic or unresolved quality prerequisites",
                    remediation_code="plan.dependencies",
                    remediation="Fix the provider prerequisite graph.",
                    files=step.files,
                )
            break
    return tuple(results[key] for key in sorted(results))
