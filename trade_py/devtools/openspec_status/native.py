"""Strict adapter for native OpenSpec read commands."""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from trade_py.devtools.openspec_status.errors import (
    WorkflowCollectionError,
    WorkflowError,
)
from trade_py.devtools.openspec_status.executor import (
    BoundedProcessExecutor,
    ProcessResult,
)
from trade_py.devtools.openspec_status.models import (
    ArtifactEvidence,
    NativeEvidence,
    TaskProgress,
    ValidationEvidence,
    ValidationIssue,
    WorkflowLimits,
)


@dataclass(frozen=True)
class NativeChange:
    name: str
    tasks: TaskProgress
    evidence: NativeEvidence


@dataclass(frozen=True)
class NativeCollection:
    names: tuple[str, ...]
    changes: dict[str, NativeChange]
    errors: dict[str, WorkflowError]
    list_digest: str


def collect_native_evidence(
    snapshot_root: Path,
    *,
    expected_names: tuple[str, ...],
    requested_change: str | None,
    executor: BoundedProcessExecutor,
    deadline: float,
    limits: WorkflowLimits,
) -> NativeCollection:
    list_result = executor.run(
        ("openspec", "list", "--json"),
        cwd=snapshot_root,
        deadline=deadline,
        timeout_seconds=limits.subprocess_timeout_seconds,
        output_limit_bytes=limits.native_output_bytes,
        source="openspec",
    )
    list_payload = _json_object(list_result, command="openspec list --json")
    list_rows = _parse_list(list_payload)
    names = tuple(sorted(list_rows))
    if names != expected_names:
        _raise(
            "workflow.openspec.scope_drift",
            None,
            "Native OpenSpec active changes do not match the immutable snapshot.",
            "Stop concurrent edits and rerun the workflow status command.",
        )
    if requested_change is not None and requested_change not in list_rows:
        _raise(
            "workflow.request.unknown_change",
            requested_change,
            f"Requested change is not active: {requested_change}",
            "Run ./trade dev openspec to list active changes.",
            source="request",
        )
    selected = (requested_change,) if requested_change else names
    validation_result = executor.run(
        (
            ("openspec", "validate", requested_change, "--json")
            if requested_change
            else ("openspec", "validate", "--all", "--json")
        ),
        cwd=snapshot_root,
        deadline=deadline,
        timeout_seconds=limits.subprocess_timeout_seconds,
        output_limit_bytes=limits.native_output_bytes,
        source="openspec",
        change=requested_change,
        allowed_returncodes=frozenset({0, 1}),
    )
    validations = _parse_validations(
        _json_object(validation_result, command="openspec validate --json"),
        expected_names=selected,
    )
    validation_digest = _digest(validation_result.stdout)
    statuses, status_errors = _collect_statuses(
        snapshot_root,
        selected,
        executor=executor,
        deadline=deadline,
        limits=limits,
    )
    list_digest = _digest(list_result.stdout)
    changes: dict[str, NativeChange] = {}
    errors = dict(status_errors)
    for name in selected:
        if name in errors:
            continue
        try:
            status_result, status_payload = statuses[name]
            status = _parse_status(status_payload, expected_name=name)
            if (
                status["schema_name"] != "spec-driven"
                or "tasks" not in status["apply_requires"]
                or not any(item.id == "tasks" for item in status["artifacts"])
            ):
                _raise(
                    "workflow.openspec.unsupported_schema",
                    name,
                    "Active change does not use the supported task-bearing spec-driven schema.",
                    "Add a reviewed schema strategy before aggregating this change.",
                    details={
                        "schema_name": status["schema_name"],
                        "payload_digest": _digest(status_result.stdout),
                    },
                )
            changes[name] = NativeChange(
                name=name,
                tasks=list_rows[name],
                evidence=NativeEvidence(
                    schema_name=status["schema_name"],
                    is_complete=status["is_complete"],
                    apply_requires=status["apply_requires"],
                    artifacts=status["artifacts"],
                    validation=validations[name],
                    payload_digests={
                        "list": list_digest,
                        "status": _digest(status_result.stdout),
                        "validation": validation_digest,
                    },
                ),
            )
        except WorkflowCollectionError as exc:
            errors[name] = exc.error
    return NativeCollection(
        names=names,
        changes=changes,
        errors=errors,
        list_digest=list_digest,
    )


def _collect_statuses(
    snapshot_root: Path,
    names: tuple[str, ...],
    *,
    executor: BoundedProcessExecutor,
    deadline: float,
    limits: WorkflowLimits,
) -> tuple[
    dict[str, tuple[ProcessResult, dict[str, Any]]],
    dict[str, WorkflowError],
]:
    if not names:
        return {}, {}

    def collect(name: str) -> tuple[str, ProcessResult, dict[str, Any]]:
        if time.monotonic() >= deadline:
            _raise(
                "workflow.process.timeout",
                name,
                "Command-wide deadline expired before native status collection.",
                "Rerun after reducing active OpenSpec work or fixing slow tooling.",
            )
        result = executor.run(
            ("openspec", "status", "--change", name, "--json"),
            cwd=snapshot_root,
            deadline=deadline,
            timeout_seconds=limits.subprocess_timeout_seconds,
            output_limit_bytes=limits.native_output_bytes,
            source="openspec",
            change=name,
        )
        return name, result, _json_object(result, command="openspec status --json")

    collected: dict[str, tuple[ProcessResult, dict[str, Any]]] = {}
    errors: dict[str, WorkflowError] = {}
    with ThreadPoolExecutor(max_workers=min(limits.status_workers, len(names))) as pool:
        futures = {pool.submit(collect, name): name for name in names}
        try:
            for future in as_completed(futures):
                name = futures[future]
                try:
                    _, result, payload = future.result()
                    collected[name] = (result, payload)
                except WorkflowCollectionError as exc:
                    errors[name] = exc.error
        except BaseException:
            for future in futures:
                future.cancel()
            executor.cancel_all()
            raise
    return collected, errors


def _parse_list(payload: dict[str, Any]) -> dict[str, TaskProgress]:
    if set(payload) != {"changes"} or not isinstance(payload["changes"], list):
        _raise_shape("Native OpenSpec list response is malformed.")
    rows: dict[str, TaskProgress] = {}
    for item in payload["changes"]:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "name",
                "completedTasks",
                "totalTasks",
                "lastModified",
                "status",
            }
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("lastModified"), str)
            or item.get("status") not in {"no-tasks", "in-progress", "complete"}
        ):
            _raise_shape("Native OpenSpec list contains a malformed change record.")
        completed = _nonnegative_int(item.get("completedTasks"))
        total = _nonnegative_int(item.get("totalTasks"))
        name = item["name"]
        if completed is None or total is None:
            _raise_shape("Native OpenSpec list contains inconsistent task counts.")
        assert completed is not None
        assert total is not None
        if completed > total or name in rows:
            _raise_shape("Native OpenSpec list contains inconsistent task counts.")
        progress = TaskProgress.from_counts(completed, total)
        if progress.status != item["status"]:
            _raise_shape("Native OpenSpec list task status contradicts its counts.")
        rows[name] = progress
    return rows


def _parse_status(payload: dict[str, Any], *, expected_name: str) -> dict[str, Any]:
    if set(payload) != {
        "changeName",
        "schemaName",
        "isComplete",
        "applyRequires",
        "artifacts",
    }:
        _raise_shape("Native OpenSpec status response is malformed.", expected_name)
    if (
        payload.get("changeName") != expected_name
        or not isinstance(payload.get("schemaName"), str)
        or not payload["schemaName"]
        or not isinstance(payload.get("isComplete"), bool)
        or not _string_list(payload.get("applyRequires"))
        or not isinstance(payload.get("artifacts"), list)
    ):
        _raise_shape("Native OpenSpec status fields are malformed.", expected_name)
    artifacts: list[ArtifactEvidence] = []
    ids: set[str] = set()
    for item in payload["artifacts"]:
        if (
            not isinstance(item, dict)
            or not {"id", "outputPath", "status"} <= set(item)
            or set(item) - {"id", "outputPath", "status", "missingDeps"}
            or not isinstance(item.get("id"), str)
            or not item["id"]
            or item["id"] in ids
            or not isinstance(item.get("outputPath"), str)
            or not item["outputPath"]
            or item.get("status") not in {"ready", "blocked", "done"}
        ):
            _raise_shape("Native OpenSpec status contains a malformed artifact.", expected_name)
        missing = item.get("missingDeps", [])
        if not _string_list(missing):
            _raise_shape(
                "Native OpenSpec status contains malformed dependencies.",
                expected_name,
            )
        ids.add(item["id"])
        artifacts.append(
            ArtifactEvidence(
                id=item["id"],
                output_path=item["outputPath"],
                status=item["status"],
                missing_deps=tuple(missing),
            )
        )
    is_complete = payload["isComplete"]
    if is_complete != all(item.status == "done" for item in artifacts):
        _raise_shape("Native OpenSpec completion contradicts artifact status.", expected_name)
    return {
        "schema_name": payload["schemaName"],
        "is_complete": is_complete,
        "apply_requires": tuple(payload["applyRequires"]),
        "artifacts": tuple(artifacts),
    }


def _parse_validations(
    payload: dict[str, Any], *, expected_names: tuple[str, ...]
) -> dict[str, ValidationEvidence]:
    if (
        set(payload) != {"items", "summary", "version"}
        or payload.get("version") != "1.0"
        or not isinstance(payload.get("items"), list)
        or not isinstance(payload.get("summary"), dict)
    ):
        _raise_shape("Native OpenSpec validation response is malformed.")
    results: dict[str, ValidationEvidence] = {}
    for row in payload["items"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"id", "type", "valid", "issues", "durationMs"}
            or row.get("type") != "change"
            or not isinstance(row.get("id"), str)
            or not isinstance(row.get("valid"), bool)
            or not isinstance(row.get("issues"), list)
            or _nonnegative_int(row.get("durationMs")) is None
        ):
            _raise_shape("Native OpenSpec validation contains a malformed record.")
        name = row["id"]
        if name in results:
            _raise_shape("Native OpenSpec validation contains duplicate changes.")
        issues: list[ValidationIssue] = []
        for issue in row["issues"]:
            if (
                not isinstance(issue, dict)
                or not {"level", "path", "message"} <= set(issue)
                or set(issue) - {"level", "path", "message", "line", "column"}
                or issue.get("level") not in {"ERROR", "WARNING", "INFO"}
                or not isinstance(issue.get("path"), str)
                or not isinstance(issue.get("message"), str)
                or not issue["message"]
            ):
                _raise_shape("Native OpenSpec validation contains a malformed issue.", name)
            issues.append(
                ValidationIssue(
                    severity="error" if issue["level"] == "ERROR" else "warning",
                    path=issue["path"] or None,
                    message=issue["message"],
                )
            )
        ordered = tuple(
            sorted(issues, key=lambda item: (item.severity, item.path or "", item.message))
        )
        valid = row["valid"]
        if valid == any(item.severity == "error" for item in ordered):
            _raise_shape("Native OpenSpec validation validity contradicts its issues.", name)
        results[name] = ValidationEvidence(
            valid=valid,
            issues=ordered[:50],
            omitted_count=max(0, len(ordered) - 50),
        )
    if tuple(sorted(results)) != tuple(sorted(expected_names)):
        _raise_shape("Native OpenSpec validation scope does not match active changes.")
    return results


def _json_object(result: ProcessResult, *, command: str) -> dict[str, Any]:
    try:
        payload = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _raise_shape(f"{command} did not emit valid JSON.")
        raise AssertionError("unreachable") from exc
    if not isinstance(payload, dict):
        _raise_shape(f"{command} did not emit a JSON object.")
    return payload


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and bool(item) for item in value)


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _raise_shape(message: str, change: str | None = None) -> NoReturn:
    _raise(
        "workflow.openspec.shape",
        change,
        message,
        "Upgrade or repair the native OpenSpec CLI, then rerun.",
    )


def _raise(
    code: str,
    change: str | None,
    message: str,
    remediation: str,
    *,
    source: str = "openspec",
    details: dict[str, str] | None = None,
) -> NoReturn:
    raise WorkflowCollectionError(
        WorkflowError(
            code=code,
            source=source,
            change=change,
            message=message,
            remediation=remediation,
            details=details or {},
        )
    )
