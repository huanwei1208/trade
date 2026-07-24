"""Bounded, shell-free execution with dependency-aware aggregation."""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from trade_py.devtools.design_quality.v1_contract import (
    exception_state,
    is_rule_id,
    is_substantive_reason,
)
from trade_py.devtools.quality.config import QualityConfig, exclusion_reason
from trade_py.devtools.quality.models import (
    CheckStep,
    FailureKind,
    ResourceClass,
    ResultStatus,
    StepResult,
)

if TYPE_CHECKING:
    from trade_py.devtools.design_quality.models import Policy
    from trade_py.devtools.design_quality.report_binding import ReportBinding

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
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_CHANGE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
_SPEC_ARTIFACT_RE = re.compile(r"specs/[a-z0-9][a-z0-9-]{0,79}/spec\.md")
_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "checker_version",
        "policy_version",
        "policy_digest",
        "artifact_digest",
        "change",
        "strict",
        "effective_date",
        "approval_eligible",
        "governance_status",
        "status",
        "exit_code",
        "profiles",
        "findings",
        "exceptions",
        "artifacts",
        "counts",
        "metadata",
    }
)


class StepExecutor(Protocol):
    def run_step(self, step: CheckStep) -> StepResult: ...


@dataclass(frozen=True)
class _DesignInvocation:
    targets: tuple[str, ...]
    live_changes: tuple[str, ...]
    required_changes: tuple[str, ...]
    missing_changes: tuple[str, ...]
    policy_targets: tuple[str, ...]


@dataclass(frozen=True)
class DesignBatchValidation:
    envelope_error: str | None
    report_errors: dict[str, str]


def _design_invocation(argv: tuple[str, ...]) -> _DesignInvocation | None:
    try:
        module_index = argv.index("-m")
    except ValueError:
        return None
    if (
        module_index + 1 >= len(argv)
        or argv[module_index + 1] != "trade_py.devtools.design_quality.cli"
    ):
        return None
    changes: list[str] = []
    required: list[str] = []
    missing: list[str] = []
    policy_edits: list[str] = []
    index = module_index + 2
    while index < len(argv):
        argument = argv[index]
        if argument in {
            "--change",
            "--require-governance",
            "--missing-required",
            "--immutable-policy-edit",
        }:
            if index + 1 >= len(argv):
                break
            value = argv[index + 1]
            if argument == "--change":
                changes.append(value)
            elif argument == "--require-governance":
                required.append(value)
            elif argument == "--missing-required":
                missing.append(value)
            else:
                policy_edits.append(value)
            index += 2
            continue
        index += 1
    live_changes = tuple(sorted(set(changes)))
    missing_changes = tuple(sorted(set(missing) - set(live_changes)))
    policy_targets = tuple(
        f"immutable-policy-{Path(path).stem}" for path in sorted(set(policy_edits))
    )
    return _DesignInvocation(
        targets=(*live_changes, *missing_changes, *policy_targets),
        live_changes=live_changes,
        required_changes=tuple(sorted(set(required) & set(live_changes))),
        missing_changes=missing_changes,
        policy_targets=policy_targets,
    )


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _current_utc_date() -> date:
    return datetime.now(timezone.utc).date()


def _is_design_exception_record(item: object, policy: Policy) -> bool:
    if (
        not isinstance(item, dict)
        or set(item) != {"rule_id", "owner", "reason", "expires", "state"}
        or not all(isinstance(item.get(key), str) for key in ("rule_id", "owner", "reason"))
        or not _is_iso_date(item.get("expires"))
        or item.get("state") not in {"applied", "expiring", "expired", "invalid"}
    ):
        return False
    if item["state"] == "invalid":
        return True
    try:
        rule = policy.rule(item["rule_id"])
    except KeyError:
        return False
    return (
        is_rule_id(item["rule_id"])
        and rule.severity.value == "warning"
        and rule.suppressible
        and len(item["owner"].strip()) >= 2
        and is_substantive_reason(item["reason"])
    )


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


def _design_envelope_error(
    details: dict[str, object],
    returncode: int,
    *,
    policy: Policy,
    expected_changes: tuple[str, ...] | None = None,
    expected_governance: dict[str, str] | None = None,
    bindings: dict[str, ReportBinding] | None = None,
    current_date: date | None = None,
) -> str | None:
    nested_exit = details.get("exit_code")
    reports = details.get("reports")
    summary = details.get("summary")
    errors = details.get("errors", [])
    if (
        not isinstance(nested_exit, int)
        or isinstance(nested_exit, bool)
        or nested_exit != returncode
        or not isinstance(reports, list)
        or not all(isinstance(item, dict) for item in reports)
        or not isinstance(summary, dict)
        or not isinstance(errors, list)
    ):
        return "Structured design envelope is inconsistent with the child process exit"
    if (not reports and not errors) or len(reports) > policy.limits.max_changes_per_batch:
        return "Structured design envelope has an invalid report count"
    report_changes = tuple(item.get("change") for item in reports)
    if not all(isinstance(change, str) for change in report_changes):
        return "Structured design envelope contains malformed change names"
    if len(report_changes) != len(set(report_changes)):
        return "Structured design envelope contains duplicate change reports"
    if not errors and expected_changes is not None and report_changes != expected_changes:
        return "Structured design envelope does not match the planned changes"
    batch_date = current_date or _current_utc_date()
    for report in reports:
        change = report.get("change")
        report_error = _design_report_error(
            report,
            policy=policy,
            binding=bindings.get(change) if bindings and isinstance(change, str) else None,
            require_binding=expected_changes is not None,
            expected_governance=(
                expected_governance.get(change)
                if expected_governance and isinstance(change, str)
                else None
            ),
            current_date=batch_date,
        )
        if report_error:
            return report_error
    if not all(
        isinstance(item, dict)
        and isinstance(item.get("code"), str)
        and bool(item["code"])
        and isinstance(item.get("message"), str)
        and bool(item["message"])
        and isinstance(item.get("remediation"), str)
        and bool(item["remediation"])
        for item in errors
    ):
        return "Structured design envelope contains malformed error records"
    if set(summary) != {"changes", "passed", "failed", "not_governed", "errors"} or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in summary.values()
    ):
        return "Structured design envelope contains malformed summary counts"
    report_exits = [item.get("exit_code") for item in reports]
    if any(not isinstance(value, int) or isinstance(value, bool) for value in report_exits):
        return "Structured design envelope contains an invalid report exit code"
    expected_summary = {
        "changes": len(reports),
        "passed": sum(item.get("status") == "PASS" for item in reports),
        "failed": sum(value != 0 for value in report_exits),
        "not_governed": sum(item.get("governance_status") == "NOT_GOVERNED" for item in reports),
        "errors": len(errors),
    }
    if any(summary.get(key) != value for key, value in expected_summary.items()):
        return "Structured design envelope summary does not match its reports"
    artifact_total = sum(
        int(artifact["size_bytes"])
        for report in reports
        for artifact in report.get("artifacts", [])
        if isinstance(artifact, dict) and isinstance(artifact.get("size_bytes"), int)
    )
    if artifact_total > policy.limits.max_total_bytes_per_batch:
        return "Structured design envelope exceeds the aggregate artifact limit"
    expected_exit = 2 if errors else max(report_exits, default=0)
    if nested_exit != expected_exit:
        return "Structured design envelope exit code does not match its reports"
    return None


def validate_design_batch_payload(
    payload: dict[str, object],
    returncode: int,
    *,
    policy: Policy,
    expected_changes: tuple[str, ...],
    expected_governance: dict[str, str],
    bindings: dict[str, ReportBinding],
    evaluation_date: date,
) -> DesignBatchValidation:
    """Validate batch structure and return change-local report errors separately."""

    reports = payload.get("reports")
    summary = payload.get("summary")
    errors = payload.get("errors", [])
    nested_exit = payload.get("exit_code")
    if (
        payload.get("schema_version") != "trade.design.batch.v1"
        or not isinstance(nested_exit, int)
        or isinstance(nested_exit, bool)
        or nested_exit != returncode
        or not isinstance(reports, list)
        or not all(isinstance(item, dict) for item in reports)
        or not isinstance(summary, dict)
        or not isinstance(errors, list)
    ):
        return DesignBatchValidation(
            "Structured design envelope is inconsistent with the child process exit",
            {},
        )
    if errors:
        return DesignBatchValidation(
            "Structured design batch contains infrastructure error records",
            {},
        )
    report_changes = tuple(item.get("change") for item in reports)
    if not all(isinstance(change, str) for change in report_changes):
        return DesignBatchValidation(
            "Structured design envelope does not match the planned changes",
            {},
        )
    typed_changes = tuple(change for change in report_changes if isinstance(change, str))
    expected = set(expected_changes)
    if any(change not in expected for change in typed_changes):
        return DesignBatchValidation(
            "Structured design envelope does not match the planned changes",
            {},
        )
    counts = Counter(typed_changes)
    if (
        all(count == 1 for count in counts.values())
        and set(typed_changes) == expected
        and typed_changes != expected_changes
    ):
        return DesignBatchValidation(
            "Structured design envelope does not match the planned changes",
            {},
        )
    if set(summary) != {"changes", "passed", "failed", "not_governed", "errors"} or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in summary.values()
    ):
        return DesignBatchValidation(
            "Structured design envelope contains malformed summary counts",
            {},
        )
    if (
        summary.get("changes") != len(reports)
        or summary.get("errors") != 0
        or sum(int(summary.get(name, 0)) for name in ("passed", "failed", "not_governed"))
        != len(reports)
        or returncode not in {0, 1}
        or returncode != (1 if summary.get("failed", 0) else 0)
    ):
        return DesignBatchValidation(
            "Structured design envelope summary does not match its report scope",
            {},
        )

    report_exits = [report.get("exit_code") for report in reports]
    report_statuses = [report.get("status") for report in reports]
    report_governance = [report.get("governance_status") for report in reports]
    classifications_are_valid = (
        all(isinstance(value, int) and not isinstance(value, bool) for value in report_exits)
        and all(
            value in {"PASS", "FAIL", "NOT_GOVERNED", "DIAGNOSTIC"} for value in report_statuses
        )
        and all(
            value
            in {
                "GOVERNED",
                "NOT_GOVERNED",
                "REQUIRED_MISSING",
                "POLICY_IMMUTABILITY_VIOLATION",
            }
            for value in report_governance
        )
    )
    if classifications_are_valid:
        expected_summary = {
            "changes": len(reports),
            "passed": sum(value == "PASS" for value in report_statuses),
            "failed": sum(value != 0 for value in report_exits),
            "not_governed": sum(value == "NOT_GOVERNED" for value in report_governance),
            "errors": 0,
        }
        expected_exit = max(report_exits, default=0)
        if summary != expected_summary or returncode != expected_exit:
            return DesignBatchValidation(
                "Structured design envelope summary does not match its reports",
                {},
            )

    report_errors = {
        name: "Structured design batch contains duplicate reports for this change"
        for name, count in counts.items()
        if count > 1
    }
    report_errors.update(
        {
            name: "Structured design batch omitted this selected change"
            for name in expected_changes
            if name not in counts
        }
    )
    for report in reports:
        change = report["change"]
        assert isinstance(change, str)
        if change in report_errors:
            continue
        error = _design_report_error(
            report,
            policy=policy,
            binding=bindings.get(change),
            require_binding=True,
            expected_governance=expected_governance.get(change),
            current_date=evaluation_date,
        )
        if error:
            report_errors[change] = error
    return DesignBatchValidation(None, report_errors)


def _design_report_error(
    report: dict[object, object],
    *,
    policy: Policy,
    binding: ReportBinding | None = None,
    require_binding: bool = False,
    expected_governance: str | None = None,
    current_date: date | None = None,
) -> str | None:
    checker_version = report.get("checker_version")
    policy_version = report.get("policy_version")
    policy_digest = report.get("policy_digest")
    artifact_digest = report.get("artifact_digest")
    change = report.get("change")
    effective_date = report.get("effective_date")
    status = report.get("status")
    governance = report.get("governance_status")
    exit_code = report.get("exit_code")
    approval = report.get("approval_eligible")
    strict = report.get("strict")
    profiles = report.get("profiles")
    allowed_governance = {
        "GOVERNED",
        "NOT_GOVERNED",
        "REQUIRED_MISSING",
        "POLICY_IMMUTABILITY_VIOLATION",
    }
    if (
        set(report) != _REPORT_FIELDS
        or report.get("schema_version") != "trade.design.report.v1"
        or not isinstance(checker_version, str)
        or not checker_version
        or policy_version != policy.policy_version
        or not isinstance(policy_digest, str)
        or not _SHA256_RE.fullmatch(policy_digest)
        or policy_digest != policy.digest
        or not isinstance(artifact_digest, str)
        or not _SHA256_RE.fullmatch(artifact_digest)
        or not isinstance(change, str)
        or not _CHANGE_RE.fullmatch(change)
        or not _is_iso_date(effective_date)
        or status not in {"PASS", "FAIL", "NOT_GOVERNED", "DIAGNOSTIC"}
        or governance not in allowed_governance
        or not isinstance(exit_code, int)
        or isinstance(exit_code, bool)
        or not isinstance(approval, bool)
        or not isinstance(strict, bool)
        or not isinstance(report.get("findings"), list)
        or not isinstance(report.get("counts"), dict)
        or not isinstance(profiles, list)
        or not all(isinstance(item, str) and bool(item) for item in profiles)
        or len(profiles) != len(set(profiles))
        or not set(profiles) <= {item.name for item in policy.profiles}
        or (governance == "GOVERNED" and "core" not in profiles)
        or (governance != "GOVERNED" and bool(profiles))
        or not isinstance(report.get("exceptions"), list)
        or not isinstance(report.get("artifacts"), list)
        or not isinstance(report.get("metadata"), dict)
    ):
        return "Structured design envelope contains a malformed report"
    exceptions = report["exceptions"]
    artifacts = report["artifacts"]
    metadata = report["metadata"]
    if expected_governance is not None and governance != expected_governance:
        return "Structured design report governance contradicts the planned current snapshot"
    if not isinstance(exceptions, list) or not all(
        _is_design_exception_record(item, policy) for item in exceptions
    ):
        return "Structured design envelope contains malformed exceptions"
    if not isinstance(artifacts, list) or not all(
        isinstance(item, dict)
        and set(item) == {"path", "size_bytes", "digest"}
        and isinstance(item.get("path"), str)
        and bool(item["path"])
        and isinstance(item.get("size_bytes"), int)
        and not isinstance(item["size_bytes"], bool)
        and item["size_bytes"] >= 0
        and isinstance(item.get("digest"), str)
        and bool(_SHA256_RE.fullmatch(item["digest"]))
        for item in artifacts
    ):
        return "Structured design envelope contains malformed artifact inventory"
    artifact_paths = [item["path"] for item in artifacts]
    artifact_sizes = [item["size_bytes"] for item in artifacts]
    allowed_root_paths = set(policy.root_files)
    if (
        len(artifacts) > policy.limits.max_files_per_change
        or len(artifact_paths) != len(set(artifact_paths))
        or any(
            path not in allowed_root_paths and not _SPEC_ARTIFACT_RE.fullmatch(path)
            for path in artifact_paths
        )
        or any(size > policy.limits.max_file_bytes for size in artifact_sizes)
        or sum(artifact_sizes) > policy.limits.max_total_bytes_per_change
    ):
        return "Structured design envelope violates artifact inventory policy"
    if (
        not isinstance(metadata, dict)
        or not isinstance(metadata.get("total_bytes"), int)
        or isinstance(metadata.get("total_bytes"), bool)
        or metadata["total_bytes"] != sum(artifact_sizes)
    ):
        return "Structured design envelope contains inconsistent artifact totals"
    if not isinstance(metadata, dict) or (
        approval
        and (
            not isinstance(metadata.get("reviewed_at"), str)
            or not _is_iso_date(metadata["reviewed_at"])
            or metadata["reviewed_at"] != effective_date
            or effective_date != (current_date or _current_utc_date()).isoformat()
            or not isinstance(metadata.get("reviewed_commit"), str)
            or not _COMMIT_RE.fullmatch(metadata["reviewed_commit"])
            or metadata.get("reviewed_commit_status") not in {"verified", "missing", "not_git"}
        )
    ):
        return "Structured design envelope lacks approval provenance"
    counts = report["counts"]
    if not isinstance(counts, dict) or any(
        not isinstance(counts.get(name), int)
        or isinstance(counts.get(name), bool)
        or counts[name] < 0
        for name in ("blockers", "warnings", "suppressed")
    ):
        return "Structured design envelope contains malformed report counts"
    findings = report["findings"]
    counts = report["counts"]
    if (
        not isinstance(findings, list)
        or len(findings) > policy.limits.max_findings
        or not isinstance(counts, dict)
    ):
        return "Structured design envelope contains malformed report findings"
    active_blockers = 0
    active_warnings = 0
    suppressed = 0
    active_exceptions: set[str] = set()
    assert isinstance(effective_date, str)
    effective = date.fromisoformat(effective_date)
    for exception in exceptions:
        expires = date.fromisoformat(exception["expires"])
        state = exception["state"]
        if state != "invalid" and state != exception_state(expires, effective):
            return "Structured design exception state contradicts its expiry"
        if state in {"applied", "expiring"}:
            active_exceptions.add(exception["rule_id"])
        if approval and state in {"expired", "invalid"}:
            return "Structured design approval contains an inactive exception"
    for finding in findings:
        if (
            not isinstance(finding, dict)
            or finding.get("severity") not in {"blocker", "warning"}
            or not isinstance(finding.get("suppressed"), bool)
            or not isinstance(finding.get("rule_id"), str)
            or not is_rule_id(finding["rule_id"])
            or not isinstance(finding.get("path"), str)
            or not isinstance(finding.get("message"), str)
            or not isinstance(finding.get("remediation"), str)
            or not finding["rule_id"]
            or not finding["path"]
            or not finding["message"]
            or not finding["remediation"]
        ):
            return "Structured design envelope contains malformed report findings"
        try:
            rule = policy.rule(finding["rule_id"])
        except KeyError:
            return "Structured design report references an unknown policy rule"
        if finding["severity"] != rule.severity.value:
            return "Structured design finding severity contradicts immutable policy"
        if finding["severity"] == "blocker" and finding["suppressed"]:
            return "Structured design report illegally suppresses a blocker"
        if finding["suppressed"] and not rule.suppressible:
            return "Structured design report suppresses a non-suppressible policy rule"
        if finding["suppressed"] and finding["rule_id"] not in active_exceptions:
            return "Structured design report suppresses a warning without an active exception"
        if finding["suppressed"]:
            suppressed += 1
        elif finding["severity"] == "blocker":
            active_blockers += 1
        else:
            active_warnings += 1
    if counts != {
        "blockers": active_blockers,
        "warnings": active_warnings,
        "suppressed": suppressed,
    }:
        return "Structured design report counts contradict its findings"
    valid_state = (
        (status == "PASS" and governance == "GOVERNED" and exit_code == 0 and approval and strict)
        or (status == "FAIL" and governance != "NOT_GOVERNED" and exit_code == 1 and not approval)
        or (
            status == "NOT_GOVERNED"
            and governance == "NOT_GOVERNED"
            and exit_code == 0
            and not approval
        )
    )
    if not strict:
        return "Structured changed-scope design reports must be strict"
    if status == "PASS" and (active_blockers or active_warnings):
        return "Structured design PASS report contains active findings"
    if status == "FAIL" and not (active_blockers or active_warnings):
        return "Structured design FAIL report contains no active findings"
    if status == "NOT_GOVERNED" and findings:
        return "Structured NOT_GOVERNED report contains findings"
    if binding is not None:
        if (
            governance != binding.governance_status
            or artifact_digest != binding.artifact_digest
            or tuple(artifacts) != binding.artifacts
            or metadata.get("total_bytes") != binding.total_bytes
        ):
            return "Structured design report contradicts its trusted current snapshot"
        if binding.profiles is not None and tuple(profiles) != binding.profiles:
            return "Structured design report profiles contradict its trusted current snapshot"
        if status == "PASS" and binding.profiles is None:
            return "Structured design PASS lacks valid current applicability evidence"
    elif status == "PASS" and governance == "GOVERNED" and require_binding:
        return "Structured design PASS lacks a trusted current-snapshot binding"
    return None if valid_state else "Structured design report status contradicts its exit state"


def _bounded_communicate(
    process: subprocess.Popen[bytes],
    timeout_seconds: int,
    limit: int,
    *,
    terminate_on_stdout_limit: bool,
) -> tuple[bytes, bytes, bool, bool, bool]:
    if process.stdout is None or process.stderr is None:
        raise ValueError("Quality subprocess pipes are unavailable")
    streams = {
        process.stdout.fileno(): ("stdout", process.stdout),
        process.stderr.fileno(): ("stderr", process.stderr),
    }
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    selector = selectors.DefaultSelector()
    for descriptor, (_, stream) in streams.items():
        os.set_blocking(descriptor, False)
        selector.register(stream, selectors.EVENT_READ, descriptor)
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    terminated_for_output = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not timed_out:
                os.killpg(process.pid, signal.SIGKILL)
                timed_out = True
                deadline = time.monotonic() + 5
                remaining = 5
            if remaining <= 0:
                raise RuntimeError("Timed-out process did not close output pipes")
            for key, _ in selector.select(min(remaining, 0.1)):
                descriptor = key.data
                label, stream = streams[descriptor]
                try:
                    chunk = os.read(descriptor, 65_536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    continue
                room = limit + 1 - len(buffers[label])
                if room > 0:
                    buffers[label].extend(chunk[:room])
                if len(chunk) > room or len(buffers[label]) > limit:
                    truncated[label] = True
                    if (
                        label == "stdout"
                        and terminate_on_stdout_limit
                        and not terminated_for_output
                        and process.poll() is None
                    ):
                        os.killpg(process.pid, signal.SIGKILL)
                        terminated_for_output = True
                        deadline = time.monotonic() + 5
        if process.poll() is None:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                timed_out = True
                process.wait(timeout=5)
    finally:
        selector.close()
    return (
        bytes(buffers["stdout"]),
        bytes(buffers["stderr"]),
        timed_out,
        truncated["stdout"],
        truncated["stderr"],
    )


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

    def _structured_details(self, step: CheckStep, stdout: bytes) -> dict[str, object] | None:
        if step.structured_output_schema is None:
            return None
        try:
            payload = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid structured output from {step.check_id}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid structured output from {step.check_id}: expected object")
        if payload.get("schema_version") != step.structured_output_schema:
            raise ValueError(
                f"Invalid structured output from {step.check_id}: expected schema "
                f"{step.structured_output_schema!r}"
            )
        return payload

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
            stdout, stderr, timed_out, stdout_truncated, stderr_truncated = _bounded_communicate(
                process,
                step.timeout_seconds,
                step.output_limit_bytes,
                terminate_on_stdout_limit=step.structured_output_schema is not None,
            )
        except (ValueError, RuntimeError) as exc:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            return self._infrastructure(step, started, str(exc), tool_path=tool_path)
        except OSError as exc:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            return self._infrastructure(
                step,
                started,
                f"Cannot spawn or read {step.argv[0]}: {exc}",
                tool_path=tool_path,
            )
        if timed_out:
            diagnostic = _bounded_diagnostic(stdout, stderr, step.output_limit_bytes)
            suffix = f"\n{diagnostic}" if diagnostic else ""
            return self._infrastructure(
                step,
                started,
                f"Timed out after {step.timeout_seconds}s{suffix}",
                tool_path=tool_path,
            )
        if step.structured_output_schema is not None and stdout_truncated:
            return self._infrastructure(
                step,
                started,
                f"Structured output exceeded {step.output_limit_bytes} bytes",
                tool_path=tool_path,
            )
        if stderr_truncated:
            stderr = stderr[: step.output_limit_bytes] + b"\n... stderr truncated ..."
        returncode = process.returncode
        if returncode is None:
            return self._infrastructure(
                step, started, "Quality subprocess did not report an exit code", tool_path=tool_path
            )
        duration_ms = int((time.monotonic() - started) * 1_000)
        try:
            details = self._structured_details(step, stdout)
        except ValueError as exc:
            diagnostic = _bounded_diagnostic(stdout, stderr, step.output_limit_bytes)
            suffix = f"\n{diagnostic}" if diagnostic else ""
            return self._infrastructure(step, started, f"{exc}{suffix}", tool_path=tool_path)
        structured_design = (
            details is not None and details.get("schema_version") == "trade.design.batch.v1"
        )
        trusted_design_policy: Policy | None = None
        design_invocation = _design_invocation(step.argv) if structured_design else None
        trusted_bindings: dict[str, ReportBinding] = {}
        expected_governance: dict[str, str] = {}
        if structured_design:
            from trade_py.devtools.design_quality.errors import DesignQualityError
            from trade_py.devtools.design_quality.policy import load_policy
            from trade_py.devtools.design_quality.report_binding import load_report_bindings

            try:
                trusted_design_policy = load_policy(self._repo_root)
            except DesignQualityError as exc:
                return self._infrastructure(
                    step,
                    started,
                    f"Cannot validate structured design output: {exc}",
                    tool_path=tool_path,
                )
            if design_invocation is not None:
                try:
                    trusted_bindings = load_report_bindings(
                        self._repo_root,
                        design_invocation.live_changes,
                        trusted_design_policy,
                        require_governance=frozenset(design_invocation.required_changes),
                    )
                except DesignQualityError as exc:
                    return self._infrastructure(
                        step,
                        started,
                        f"Cannot bind structured design output: {exc}",
                        tool_path=tool_path,
                    )
                expected_governance = {
                    **{
                        name: binding.governance_status
                        for name, binding in trusted_bindings.items()
                    },
                    **{name: "REQUIRED_MISSING" for name in design_invocation.missing_changes},
                    **{
                        name: "POLICY_IMMUTABILITY_VIOLATION"
                        for name in design_invocation.policy_targets
                    },
                }
        if (
            structured_design
            and details is not None
            and trusted_design_policy is not None
            and (
                envelope_error := _design_envelope_error(
                    details,
                    returncode,
                    policy=trusted_design_policy,
                    expected_changes=(
                        design_invocation.targets if design_invocation is not None else None
                    ),
                    expected_governance=expected_governance,
                    bindings=trusted_bindings,
                )
            )
            is not None
        ):
            return self._infrastructure(
                step,
                started,
                envelope_error,
                tool_path=tool_path,
            )
        diagnostic = _bounded_diagnostic(
            b"" if details is not None else stdout, stderr, step.output_limit_bytes
        )
        version = self._version(step, cwd)
        if returncode == 0:
            status = ResultStatus.PASS
            summary = details.get("summary") if details is not None else None
            if (
                details is not None
                and details.get("schema_version") == "trade.design.batch.v1"
                and isinstance(summary, dict)
                and summary.get("not_governed", 0)
            ):
                status = ResultStatus.WARN
            return StepResult(
                check_id=step.check_id,
                group=step.group,
                name=step.name,
                status=status,
                duration_ms=duration_ms,
                exit_code=0,
                diagnostic=diagnostic,
                remediation_code=step.remediation_code,
                remediation=step.remediation,
                files=step.files,
                tool_path=tool_path,
                tool_version=version,
                details=details,
            )

        exit_mapping = dict(step.exit_code_kinds)
        failure_kind = exit_mapping.get(returncode, step.nonzero_kind)
        lowered = diagnostic.lower()
        if returncode < 0 or (
            not structured_design and any(marker in lowered for marker in _INFRA_DIAGNOSTIC_MARKERS)
        ):
            failure_kind = FailureKind.INFRASTRUCTURE
        status = ResultStatus.FAIL if step.required else ResultStatus.WARN
        return StepResult(
            check_id=step.check_id,
            group=step.group,
            name=step.name,
            status=status,
            duration_ms=duration_ms,
            exit_code=returncode,
            failure_kind=failure_kind,
            diagnostic=diagnostic,
            remediation_code=step.remediation_code,
            remediation=step.remediation,
            files=step.files,
            tool_path=tool_path,
            tool_version=version,
            details=details,
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
