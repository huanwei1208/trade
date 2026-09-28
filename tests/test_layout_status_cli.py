from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from trade_py.cli import dev
from trade_py.cli import main as main_cli
from trade_py.devtools.layout_status.deadline import InvocationDeadline
from trade_py.devtools.layout_status.errors import LayoutStatusInvalid
from trade_py.devtools.layout_status.records import (
    ExplicitRecordReader,
    ReaderLimits,
    canonical_json,
    canonical_record_digest,
)
from trade_py.devtools.layout_status.validation import validate_graph

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
COMMIT = "d" * 40
REPO_ROOT = Path(__file__).resolve().parents[1]


def _record(record_type: str, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = {
        "schema_version": "trade.layout.record.v1",
        "record_type": record_type,
        "record_id": record_id,
        "references": [],
        "payload": payload,
    }
    record["record_digest"] = canonical_record_digest(record)
    return record


def _write(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(record) + b"\n")


def _content_digest(payload: dict[str, Any], digest_key: str) -> str:
    content = dict(payload)
    content.pop(digest_key, None)
    return "sha256:" + hashlib.sha256(canonical_json(content)).hexdigest()


def _inventory_payload() -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "source_commit": COMMIT,
        "tree_digest": DIGEST_B,
        "scanner_name": "layout-scanner",
        "scanner_version": "v1",
        "scanner_source_digest": DIGEST_A,
        "included_roots": ["src/trade", "trade_py"],
        "explicit_exclusions": ["segment:tests"],
        "rules_digest": DIGEST_B,
        "generated_at": "2026-07-27T11:59:00Z",
        "max_age_seconds": 86_400,
        "completeness_state": "complete",
        "production_module_count": 2,
        "consumer_count": 4,
        "unclassified_consumer_count": 0,
        "entry_digest": DIGEST_C,
    }
    payload["report_digest"] = _content_digest(payload, "report_digest")
    return payload


def _authority_payload(inventory_ref: str, *, state: str) -> dict[str, Any]:
    return {
        "legacy_module": "trade_py",
        "target_module": "trade",
        "owner": "bootstrap",
        "contract_generation": "layout-v1",
        "implementation_digest": DIGEST_C,
        "compatibility_direction": "legacy_to_target",
        "state": state,
        "consumer_inventory_ref": inventory_ref,
        "activation_plan_digest": DIGEST_A,
    }


def _package_payload() -> dict[str, Any]:
    return {
        "distribution_name": "trade-py",
        "distribution_version": "0.1.0",
        "python_tag": "py3",
        "platform_tag": "any",
        "wheel_digest": DIGEST_A,
        "wheel_member_digest": DIGEST_B,
        "wheel_member_count": 42,
        "compatibility_manifest_digest": DIGEST_C,
    }


def _validation_report_payload(package_ref: str) -> dict[str, Any]:
    payload = {
        "source_commit": COMMIT,
        "source_tree_digest": DIGEST_B,
        "package_generation_ref": package_ref,
        "root_console_parity": "passed",
        "asgi_import_state": "passed",
        "reload_child_import_state": "passed",
        "route_parity_state": "passed",
        "openapi_parity_state": "passed",
        "sse_parity_state": "passed",
        "capability_parity_state": "passed",
        "web_build_digest": DIGEST_C,
        "web_missing_asset_count": 0,
        "native_capability_state": "passed",
        "native_build_state": "passed",
        "native_differential_state": "passed",
        "notebook_state": "passed",
        "report_entries_digest": DIGEST_C,
    }
    payload["report_digest"] = _content_digest(payload, "report_digest")
    return payload


def _selector_payload() -> dict[str, Any]:
    payload = {
        "scope": "python_deployment",
        "generation": "generation-2",
        "revision": 2,
        "fence": 2,
        "operation_id": "operation-1",
        "plan_digest": DIGEST_A,
        "prepared_evidence_ref": "",
        "predecessor_generation": "generation-1",
        "predecessor_revision": 1,
    }
    payload["selector_payload_digest"] = (
        "sha256:" + __import__("hashlib").sha256(canonical_json(payload)).hexdigest()
    )
    return payload


def _prepared_payload(*, immutable_input_refs: list[str]) -> dict[str, Any]:
    return {
        "operation_id": "operation-1",
        "attempt_id": "attempt-1",
        "scope": "python_deployment",
        "source_commit": COMMIT,
        "source_tree_digest": DIGEST_B,
        "policy_digest": DIGEST_C,
        "approved_design_digest": DIGEST_A,
        "activation_plan_digest": DIGEST_A,
        "current_composition_digest": DIGEST_B,
        "immutable_input_refs": sorted(immutable_input_refs),
        "intended_target_generation": "generation-2",
        "expected_generation": "generation-1",
        "expected_revision": 1,
        "expected_fence": 1,
        "deployment_unit": "trade-api",
        "invocation_token": "invocation-1",
        "command_digests": [DIGEST_A],
        "prepared_at": "2026-07-27T12:00:00Z",
    }


def _states(
    *,
    migration: str = "target_authoritative",
    execution: str = "passed",
    failure: str = "none",
    rollback: str = "not_required",
    startup: str = "started_healthy",
    reconciliation: str = "not_required",
) -> dict[str, str]:
    return {
        "migration_state": migration,
        "execution_state": execution,
        "failure_class": failure,
        "rollback_state": rollback,
        "startup_state": startup,
        "reconciliation_state": reconciliation,
    }


def _operation_payload(
    *,
    states: dict[str, str] | None = None,
    action: str = "continue_validation",
    phase: str = "verified",
) -> dict[str, Any]:
    process = {
        "deployment_unit": "trade-api",
        "invocation_token": "invocation-1",
        "generation": "generation-2",
        "revision": 2,
        "fence": 2,
        "matching_live_instances": 1,
        "zero_live_descendants": False,
        "receipts": [],
    }
    operation = {
        "operation_id": "operation-1",
        "attempt_id": "attempt-1",
        "scope": "python_deployment",
        "activation_phase": phase,
        "states": states or _states(),
        "operator_action": action,
        "tool_exit_code": 0,
        "partial_evidence_ref": None,
        "stopped_early": False,
        "stop_reason": None,
        "failure_detail": None,
        "degraded_components": [],
        "process": process,
        "shutdown": {
            "stage": "not_started",
            "signal_escalation": "none",
            "residual_process_count": 0,
            "residual_thread_count": 0,
            "forced_exit_receipt": False,
            "complete": False,
        },
        "rollback": {
            "plan_scope": "python_deployment",
            "target_generation": None,
            "later_accepted_slices": False,
            "target_is_historical_predecessor": False,
            "compensation_preserves_later_slices": False,
        },
    }
    process["receipts"] = [_process_receipt(operation, "process_started")]
    return operation


def _process_receipt(
    operation: dict[str, Any],
    receipt_type: str,
    *,
    supersedes_receipt_id: str | None = None,
    observed_at: str = "2026-07-27T12:00:01Z",
    live_descendant_count: int = 1,
) -> dict[str, Any]:
    process = operation["process"]
    payload = {
        "receipt_type": receipt_type,
        "observed_at": observed_at,
        "operation_id": operation["operation_id"],
        "attempt_id": operation["attempt_id"],
        "deployment_unit": process["deployment_unit"],
        "invocation_token": process["invocation_token"],
        "generation": process["generation"],
        "revision": process["revision"],
        "fence": process["fence"],
        "supersedes_receipt_id": supersedes_receipt_id,
        "live_descendant_count": live_descendant_count,
    }
    payload["receipt_id"] = _content_digest(payload, "receipt_id")
    return payload


def _migration_payload(
    operation: dict[str, Any],
    prepared_digest: str,
    inventory_ref: str,
    authority_ref: str,
    package_ref: str,
    report_entries_digest: str,
) -> dict[str, Any]:
    phase = operation["activation_phase"]
    if phase == "verified":
        phases = [
            "prepared",
            "selector_committed",
            "start_intent_recorded",
            "process_started",
            "verified",
        ]
        terminal_outcome = "verified"
    elif phase == "failed":
        phases = [
            "prepared",
            "selector_committed",
            "start_intent_recorded",
            "process_started",
            "failed",
        ]
        terminal_outcome = "failed"
    elif phase == "rollback_verified":
        phases = [
            "prepared",
            "selector_committed",
            "start_intent_recorded",
            "process_started",
            "failed",
            "rollback_prepared",
            "rollback_selector_committed",
            "rollback_verified",
        ]
        terminal_outcome = "rolled_back"
    else:
        raise ValueError(f"Cannot build terminal evidence for phase: {phase}")
    return {
        "operation_id": "operation-1",
        "attempt_id": "attempt-1",
        "scope": "python_deployment",
        "source_commit": COMMIT,
        "source_tree_digest": DIGEST_B,
        "policy_digest": DIGEST_C,
        "approved_design_digest": DIGEST_A,
        "consumer_inventory_ref": inventory_ref,
        "module_authority_ref": authority_ref,
        "artifact_refs": [package_ref],
        "activation_plan_digest": DIGEST_A,
        "prepared_evidence_ref": prepared_digest,
        "operation_status_ref": "",
        "selector_before": {
            "generation": "generation-1",
            "revision": 1,
            "fence": 1,
        },
        "selector_after": {
            "generation": "generation-2",
            "revision": 2,
            "fence": 2,
        },
        "phases": phases,
        "terminal_outcome": terminal_outcome,
        "command_digests": [DIGEST_A],
        "toolchain": ["python-3.10"],
        "deadline_milliseconds": 5000,
        "typed_outcomes": operation["states"],
        "partial_evidence_refs": (
            [operation["partial_evidence_ref"]]
            if operation["partial_evidence_ref"] is not None
            else []
        ),
        "report_entries_digest": report_entries_digest,
    }


def _manifest_payload(
    selector_digest: str,
    operation_digest: str,
    prepared_digest: str,
    migration_digest: str | None,
) -> dict[str, Any]:
    return {
        "scope": "python_deployment",
        "selected_generation": "generation-2",
        "prior_generation": "generation-1",
        "selected_revision": 2,
        "selected_fence": 2,
        "wheel_digest": DIGEST_A,
        "wheel_member_count": 42,
        "legacy_module_origin": "trade_py",
        "target_module_origin": "trade",
        "selected_authority": "trade",
        "source_commit": COMMIT,
        "source_tree_digest": DIGEST_B,
        "inventory_scanner_digest": DIGEST_A,
        "inventory_rules_digest": DIGEST_B,
        "inventory_completeness": "complete",
        "inventory_age_seconds": 60,
        "missing_consumers": 0,
        "duplicate_consumers": 0,
        "reverse_dependencies": 0,
        "unclassified_consumers": 0,
        "root_console_parity": "passed",
        "asgi_import_state": "passed",
        "reload_child_import_state": "passed",
        "route_parity_state": "passed",
        "openapi_parity_state": "passed",
        "sse_parity_state": "passed",
        "capability_parity_state": "passed",
        "web_build_digest": DIGEST_C,
        "web_missing_asset_count": 0,
        "native_capability_state": "passed",
        "native_build_state": "passed",
        "native_differential_state": "passed",
        "notebook_state": "passed",
        "bridge_owner": "interfaces",
        "bridge_population_digest": DIGEST_C,
        "bridge_coverage_state": "unavailable",
        "bridge_age_seconds": None,
        "bridge_last_observed_use": None,
        "bridge_deadline": "2026-10-27T12:00:00Z",
        "selector_ref": selector_digest,
        "operation_ref": operation_digest,
        "prepared_evidence_ref": prepared_digest,
        "migration_evidence_ref": migration_digest,
    }


def _fixture(
    tmp_path: Path,
    *,
    operation_payload: dict[str, Any] | None = None,
    manifest_changes: dict[str, Any] | None = None,
    validation_report_changes: dict[str, Any] | None = None,
    include_migration: bool = True,
) -> Path:
    root = tmp_path / "layout-control"
    operation_payload = deepcopy(operation_payload or _operation_payload())
    rollback_succeeded = operation_payload["states"]["rollback_state"] == "succeeded"
    inventory = _record("consumer_inventory", "inventory-1", _inventory_payload())
    package = _record("package_generation", "package-1", _package_payload())
    validation_report_payload = _validation_report_payload(package["record_digest"])
    if validation_report_changes:
        validation_report_payload.update(validation_report_changes)
        validation_report_payload["report_digest"] = _content_digest(
            validation_report_payload,
            "report_digest",
        )
    validation_report = _record(
        "validation_report", "validation-report-1", validation_report_payload
    )
    authority = _record(
        "module_authority",
        "authority-1",
        _authority_payload(
            inventory["record_digest"],
            state=operation_payload["states"]["migration_state"],
        ),
    )
    prepared_payload = _prepared_payload(
        immutable_input_refs=[
            inventory["record_digest"],
            authority["record_digest"],
            package["record_digest"],
            validation_report["record_digest"],
        ]
    )
    selector_payload = _selector_payload()
    if rollback_succeeded:
        target = operation_payload["rollback"]["target_generation"]
        assert isinstance(target, str)
        prepared_payload.update(
            {
                "intended_target_generation": target,
                "expected_generation": "generation-2",
                "expected_revision": 2,
                "expected_fence": 2,
            }
        )
        selector_payload.update(
            {
                "generation": target,
                "revision": 3,
                "fence": 3,
                "predecessor_generation": "generation-2",
                "predecessor_revision": 2,
            }
        )
        operation_payload["process"].update(
            {
                "generation": target,
                "revision": 3,
                "fence": 3,
            }
        )
        start = _process_receipt(operation_payload, "process_started")
        operation_payload["process"]["receipts"] = [
            start,
            _process_receipt(
                operation_payload,
                "teardown",
                supersedes_receipt_id=start["receipt_id"],
                observed_at="2026-07-27T12:00:02Z",
                live_descendant_count=0,
            ),
        ]
    prepared = _record("prepared_evidence", "prepared-1", prepared_payload)
    selector_payload["prepared_evidence_ref"] = prepared["record_digest"]
    selector_payload["selector_payload_digest"] = (
        "sha256:"
        + __import__("hashlib")
        .sha256(
            canonical_json(
                {
                    key: value
                    for key, value in selector_payload.items()
                    if key != "selector_payload_digest"
                }
            )
        )
        .hexdigest()
    )
    selector = _record("layout_selector_snapshot", "selector-1", selector_payload)
    operation = _record("operation_status_snapshot", "operation-1", operation_payload)
    migration_payload = (
        _migration_payload(
            operation_payload,
            prepared["record_digest"],
            inventory["record_digest"],
            authority["record_digest"],
            package["record_digest"],
            validation_report_payload["report_entries_digest"],
        )
        if include_migration
        else None
    )
    if migration_payload is not None:
        migration_payload["operation_status_ref"] = operation["record_digest"]
    migration = (
        _record(
            "migration_evidence",
            "migration-1",
            migration_payload,
        )
        if migration_payload is not None
        else None
    )
    if migration is not None and rollback_succeeded:
        migration["payload"]["selector_before"] = {
            "generation": "generation-2",
            "revision": 2,
            "fence": 2,
        }
        migration["payload"]["selector_after"] = {
            "generation": selector_payload["generation"],
            "revision": selector_payload["revision"],
            "fence": selector_payload["fence"],
        }
        migration["record_digest"] = canonical_record_digest(migration)
    for name, record in (
        ("records/inventory.json", inventory),
        ("records/authority.json", authority),
        ("records/package.json", package),
        ("records/validation-report.json", validation_report),
        ("records/prepared.json", prepared),
        ("records/selector.json", selector),
        ("records/operation.json", operation),
    ):
        _write(root / name, record)
    if migration is not None:
        _write(root / "records/migration.json", migration)

    manifest_payload = _manifest_payload(
        selector["record_digest"],
        operation["record_digest"],
        prepared["record_digest"],
        migration["record_digest"] if migration is not None else None,
    )
    if rollback_succeeded:
        manifest_payload.update(
            {
                "selected_generation": selector_payload["generation"],
                "prior_generation": selector_payload["predecessor_generation"],
                "selected_revision": selector_payload["revision"],
                "selected_fence": selector_payload["fence"],
            }
        )
    if manifest_changes:
        manifest_payload.update(manifest_changes)
    manifest = _record("layout_status_manifest", "status-1", manifest_payload)
    manifest["references"] = [
        {
            "name": "authority",
            "path": "records/authority.json",
            "digest": authority["record_digest"],
        },
        {
            "name": "inventory",
            "path": "records/inventory.json",
            "digest": inventory["record_digest"],
        },
        {
            "name": "operation",
            "path": "records/operation.json",
            "digest": operation["record_digest"],
        },
        {
            "name": "package",
            "path": "records/package.json",
            "digest": package["record_digest"],
        },
        {
            "name": "prepared",
            "path": "records/prepared.json",
            "digest": prepared["record_digest"],
        },
        {
            "name": "selector",
            "path": "records/selector.json",
            "digest": selector["record_digest"],
        },
        {
            "name": "validation_report",
            "path": "records/validation-report.json",
            "digest": validation_report["record_digest"],
        },
    ]
    if migration is not None:
        manifest["references"].append(
            {
                "name": "migration",
                "path": "records/migration.json",
                "digest": migration["record_digest"],
            }
        )
    manifest["record_digest"] = canonical_record_digest(manifest)
    path = root / "status.json"
    _write(path, manifest)
    return path


def _rewrite_record_and_manifest_reference(
    manifest: Path,
    *,
    reference_name: str,
    mutate: Any,
) -> None:
    manifest_record = json.loads(manifest.read_text(encoding="utf-8"))
    reference = next(
        item for item in manifest_record["references"] if item["name"] == reference_name
    )
    record_path = manifest.parent / reference["path"]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    mutate(record)
    record["record_digest"] = canonical_record_digest(record)
    _write(record_path, record)
    reference["digest"] = record["record_digest"]
    manifest_key = {
        "migration": "migration_evidence_ref",
        "operation": "operation_ref",
        "prepared": "prepared_evidence_ref",
        "selector": "selector_ref",
    }.get(reference_name)
    if manifest_key is not None:
        manifest_record["payload"][manifest_key] = record["record_digest"]
    manifest_record["record_digest"] = canonical_record_digest(manifest_record)
    _write(manifest, manifest_record)


def test_parser_contract_and_unset_root_fail_before_business_data(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = dev.make_parser().parse_args(["layout-status", "--json"])
    assert args.cmd == "layout-status"
    assert args.as_json is True

    monkeypatch.delenv("TRADE_LAYOUT_STATUS_MANIFEST", raising=False)
    code = dev.main(["layout-status", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["error"]["code"] == "layout.status.manifest_unset"
    assert payload["summary"] is None


def test_json_and_human_views_share_attention_action_and_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _fixture(tmp_path)
    monkeypatch.setenv("TRADE_LAYOUT_STATUS_MANIFEST", str(manifest))

    json_code = dev.main(["layout-status", "--json"])
    payload = json.loads(capsys.readouterr().out)
    human_code = dev.main(["layout-status"])
    human = capsys.readouterr().out

    assert json_code == human_code == 1
    assert payload["status"] == "ATTENTION"
    assert payload["operation"]["states"]["reconciliation_state"] == "not_required"
    assert payload["operation"]["operator_action"] == "continue_validation"
    assert payload["validation"]["record_count"] == 9
    assert "Layout status: ATTENTION (exit 1)" in human
    assert "reconciliation_state=not_required" in human
    assert "action=continue_validation" in human
    assert "revision=2 fence=2" in human
    assert "residual_processes=0 residual_threads=0" in human
    assert "Compatibility: console=passed asgi=passed reload_child=passed" in human
    assert "route=passed openapi=passed sse=passed capability=passed" in human
    assert f"Web: build={DIGEST_C} missing_assets=0" in human
    assert "Native: capability=passed build=passed differential=passed notebook=passed" in human
    assert "Operation: id=operation-1 attempt=attempt-1" in human
    assert "Outcome: failure=none detail=None degraded=none" in human
    assert "Receipts: process_started@2026-07-27T12:00:01Z->None" in human
    assert f"population={DIGEST_C} age=None last_use=None" in human


@pytest.mark.parametrize(
    ("states", "action", "phase", "process_changes", "shutdown_changes"),
    [
        (
            _states(
                migration="prepared",
                execution="running",
                startup="starting",
                reconciliation="pending",
            ),
            "resume_reconciliation",
            "start_intent_recorded",
            {"receipts": [], "matching_live_instances": 0},
            {},
        ),
        (
            _states(
                migration="prepared",
                execution="stopped",
                startup="stopped",
                reconciliation="absence_proved",
            ),
            "retry_identical_invocation",
            "process_started",
            {"matching_live_instances": 0, "zero_live_descendants": True},
            {},
        ),
        (
            _states(
                migration="prepared",
                execution="stopped",
                rollback="ready",
                startup="stopped",
                reconciliation="fenced_teardown",
            ),
            "execute_reviewed_rollback",
            "failed",
            {
                "matching_live_instances": 0,
                "zero_live_descendants": True,
            },
            {"stage": "complete", "signal_escalation": "term", "complete": True},
        ),
    ],
)
def test_reconciliation_attention_goldens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    states: dict[str, str],
    action: str,
    phase: str,
    process_changes: dict[str, Any],
    shutdown_changes: dict[str, Any],
) -> None:
    operation = _operation_payload(states=states, action=action, phase=phase)
    operation["process"].update(process_changes)
    start = operation["process"]["receipts"][0] if operation["process"]["receipts"] else None
    if states["reconciliation_state"] == "absence_proved":
        assert start is not None
        operation["process"]["receipts"].append(
            _process_receipt(
                operation,
                "terminal_absence",
                supersedes_receipt_id=start["receipt_id"],
                observed_at="2026-07-27T12:00:02Z",
                live_descendant_count=0,
            )
        )
    elif states["reconciliation_state"] == "fenced_teardown":
        assert start is not None
        operation["process"]["generation"] = "generation-1"
        operation["process"]["revision"] = 1
        operation["process"]["fence"] = 1
        operation["process"]["receipts"] = [
            _process_receipt(operation, "process_started"),
        ]
        start = operation["process"]["receipts"][0]
        operation["process"]["receipts"].append(
            _process_receipt(
                operation,
                "teardown",
                supersedes_receipt_id=start["receipt_id"],
                observed_at="2026-07-27T12:00:02Z",
                live_descendant_count=0,
            )
        )
        operation["tool_exit_code"] = 0
    operation["shutdown"].update(shutdown_changes)
    if states["rollback_state"] != "not_required":
        operation["rollback"]["target_generation"] = "generation-compensation-3"
    manifest = _fixture(
        tmp_path,
        operation_payload=operation,
        include_migration=phase in {"verified", "failed", "rollback_verified"},
    )
    monkeypatch.setenv("TRADE_LAYOUT_STATUS_MANIFEST", str(manifest))

    code = dev.main(["layout-status", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["status"] == "ATTENTION"
    assert payload["operation"]["operator_action"] == action
    assert payload["operation"]["states"]["reconciliation_state"] == states["reconciliation_state"]


@pytest.mark.parametrize(
    ("mutate", "violation"),
    [
        (
            lambda operation: (
                operation.update(
                    {
                        "states": _states(
                            migration="target_authoritative",
                            reconciliation="adopted",
                        ),
                        "operator_action": "continue_validation",
                    }
                ),
                operation["process"].update({"matching_live_instances": 0, "receipts": []}),
            ),
            "layout.status.receipt_invalid",
        ),
        (
            lambda operation: operation["process"].update({"revision": 1}),
            "layout.status.identity_mismatch",
        ),
        (
            lambda operation: operation.update({"operator_action": "wait"}),
            "layout.status.action_mismatch",
        ),
    ],
)
def test_invalid_receipt_identity_and_action_return_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutate: Any,
    violation: str,
) -> None:
    operation = _operation_payload()
    mutate(operation)
    manifest = _fixture(tmp_path, operation_payload=operation)
    monkeypatch.setenv("TRADE_LAYOUT_STATUS_MANIFEST", str(manifest))

    code = dev.main(["layout-status", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert violation in payload["validation"]["violations"]


def test_historical_start_requires_exact_terminal_absence_receipt(tmp_path: Path) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="stopped",
            startup="stopped",
            reconciliation="absence_proved",
        ),
        action="retry_identical_invocation",
        phase="process_started",
    )
    operation["process"].update({"matching_live_instances": 0, "zero_live_descendants": True})
    operation["process"]["receipts"].append(
        _process_receipt(
            operation,
            "terminal_absence",
            supersedes_receipt_id=DIGEST_A,
            observed_at="2026-07-27T12:00:02Z",
            live_descendant_count=0,
        )
    )
    status = validate_graph(
        ExplicitRecordReader(
            _fixture(tmp_path, operation_payload=operation, include_migration=False)
        ).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.receipt_invalid" in status.constraints.violations


def test_absence_without_historical_start_requires_terminal_receipt(tmp_path: Path) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="stopped",
            startup="stopped",
            reconciliation="absence_proved",
        ),
        action="retry_identical_invocation",
        phase="start_intent_recorded",
    )
    operation["process"].update(
        {
            "matching_live_instances": 0,
            "zero_live_descendants": True,
            "receipts": [
                _process_receipt(
                    operation,
                    "terminal_absence",
                    observed_at="2026-07-27T12:00:01Z",
                    live_descendant_count=0,
                )
            ],
        }
    )
    status = validate_graph(
        ExplicitRecordReader(
            _fixture(tmp_path, operation_payload=operation, include_migration=False)
        ).read()
    )

    assert status.constraints.exit_code == 1
    assert status.constraints.derived_action == "retry_identical_invocation"


def test_terminal_receipt_must_causally_follow_superseded_start(tmp_path: Path) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="stopped",
            startup="stopped",
            reconciliation="absence_proved",
        ),
        action="retry_identical_invocation",
        phase="process_started",
    )
    start = _process_receipt(
        operation,
        "process_started",
        observed_at="2026-07-27T12:00:02Z",
    )
    absence = _process_receipt(
        operation,
        "terminal_absence",
        supersedes_receipt_id=start["receipt_id"],
        observed_at="2026-07-27T12:00:01Z",
        live_descendant_count=0,
    )
    operation["process"].update(
        {
            "matching_live_instances": 0,
            "zero_live_descendants": True,
            "receipts": [absence, start],
        }
    )
    status = validate_graph(
        ExplicitRecordReader(
            _fixture(tmp_path, operation_payload=operation, include_migration=False)
        ).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.receipt_invalid" in status.constraints.violations


def test_process_receipt_must_follow_prepared_evidence(tmp_path: Path) -> None:
    operation = _operation_payload()
    operation["process"]["receipts"] = [
        _process_receipt(
            operation,
            "process_started",
            observed_at="2026-07-27T11:59:59Z",
        )
    ]
    status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path, operation_payload=operation)).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.receipt_invalid" in status.constraints.violations


def test_adopted_rejects_terminal_process_receipts(tmp_path: Path) -> None:
    operation = _operation_payload(
        states=_states(reconciliation="adopted"),
        action="none",
    )
    start = operation["process"]["receipts"][0]
    operation["process"]["receipts"].append(
        _process_receipt(
            operation,
            "terminal_absence",
            supersedes_receipt_id=start["receipt_id"],
            observed_at="2026-07-27T12:00:02Z",
            live_descendant_count=0,
        )
    )
    status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path, operation_payload=operation)).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.receipt_invalid" in status.constraints.violations


@pytest.mark.parametrize("phase", ["prepared", "selector_committed", "start_intent_recorded"])
def test_pre_start_phases_reject_start_and_live_process(
    tmp_path: Path,
    phase: str,
) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="running",
            startup="starting",
            reconciliation="pending",
        ),
        action="resume_reconciliation",
        phase=phase,
    )
    status = validate_graph(
        ExplicitRecordReader(
            _fixture(tmp_path, operation_payload=operation, include_migration=False)
        ).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.receipt_invalid" in status.constraints.violations


def test_failed_phase_with_process_started_history_requires_start_receipt(
    tmp_path: Path,
) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="failed",
            failure="tool_failure",
            startup="failed",
        ),
        action="investigate",
        phase="failed",
    )
    operation["process"]["receipts"] = []
    operation["tool_exit_code"] = 70
    operation["failure_detail"] = "validator_exit_70"
    status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path, operation_payload=operation)).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.receipt_invalid" in status.constraints.violations


@pytest.mark.parametrize(
    "shutdown_changes",
    [
        {
            "stage": "not_started",
            "signal_escalation": "term_kill",
            "forced_exit_receipt": True,
        },
        {
            "stage": "kill",
            "signal_escalation": "none",
            "forced_exit_receipt": False,
        },
    ],
)
def test_shutdown_stage_and_escalation_products_are_closed(
    tmp_path: Path,
    shutdown_changes: dict[str, Any],
) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="failed",
            failure="tool_failure",
            startup="failed",
        ),
        action="investigate",
        phase="failed",
    )
    operation["tool_exit_code"] = 70
    operation["failure_detail"] = "validator_exit_70"
    operation["shutdown"].update(shutdown_changes)
    status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path, operation_payload=operation)).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.receipt_invalid" in status.constraints.violations


def test_non_lifo_historical_rollback_target_is_invalid(tmp_path: Path) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="failed",
            failure="contract_mismatch",
            rollback="ready",
            startup="failed",
        ),
        action="execute_reviewed_rollback",
        phase="failed",
    )
    operation["rollback"].update(
        {
            "target_generation": "generation-1",
            "later_accepted_slices": True,
            "target_is_historical_predecessor": True,
            "compensation_preserves_later_slices": False,
        }
    )
    operation["tool_exit_code"] = 1
    operation["failure_detail"] = "contract_mismatch"
    status = validate_graph(
        ExplicitRecordReader(
            _fixture(tmp_path, operation_payload=operation, include_migration=False)
        ).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.rollback_target_invalid" in status.constraints.violations


def test_timeout_retains_failure_after_successful_forward_rollback(tmp_path: Path) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="stopped",
            failure="timeout",
            rollback="succeeded",
            startup="stopped",
        ),
        action="investigate",
        phase="rollback_verified",
    )
    operation["tool_exit_code"] = 124
    operation["stopped_early"] = True
    operation["stop_reason"] = "deadline_exceeded"
    operation["failure_detail"] = "subprocess_timeout"
    operation["rollback"].update(
        {
            "target_generation": "generation-compensation-3",
            "later_accepted_slices": True,
            "target_is_historical_predecessor": False,
            "compensation_preserves_later_slices": True,
        }
    )
    operation["shutdown"].update(
        {
            "stage": "complete",
            "signal_escalation": "term_kill",
            "forced_exit_receipt": True,
            "complete": True,
        }
    )
    operation["process"].update({"matching_live_instances": 0, "zero_live_descendants": True})
    status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path, operation_payload=operation)).read()
    )

    assert status.constraints.exit_code == 1
    assert status.constraints.derived_action == "investigate"
    assert status.operation.axes.failure_class == "timeout"
    assert status.operation.axes.rollback_state == "succeeded"
    assert status.selector.generation == "generation-compensation-3"
    assert status.selector.revision == 3
    assert status.selector.fence == 3
    assert status.operation.rollback.target_generation == status.selector.generation
    assert status.operation.shutdown.signal_escalation == "term_kill"
    assert status.operation.shutdown.forced_exit_receipt is True


def test_cleanup_residue_is_attention_not_success(tmp_path: Path) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="stopped",
            failure="process_cleanup_incomplete",
            rollback="ready",
            startup="stopped",
            reconciliation="required",
        ),
        action="investigate",
        phase="failed",
    )
    operation["rollback"]["target_generation"] = "generation-compensation-3"
    operation["failure_detail"] = "process_cleanup_incomplete"
    operation["tool_exit_code"] = 1
    operation["shutdown"].update(
        {
            "stage": "kill",
            "signal_escalation": "term_kill",
            "residual_process_count": 1,
            "residual_thread_count": 2,
            "forced_exit_receipt": True,
            "complete": False,
        }
    )
    status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path, operation_payload=operation)).read()
    )

    assert status.constraints.exit_code == 1
    assert status.constraints.derived_action == "investigate"
    assert status.operation.shutdown.residual_process_count == 1
    assert status.operation.shutdown.residual_thread_count == 2


def test_tool_failure_retains_partial_evidence_and_early_stop(tmp_path: Path) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="failed",
            failure="tool_failure",
            startup="failed",
        ),
        action="investigate",
        phase="failed",
    )
    operation["tool_exit_code"] = 70
    operation["partial_evidence_ref"] = DIGEST_C
    operation["stopped_early"] = True
    operation["stop_reason"] = "tool_failed"
    operation["failure_detail"] = "validator_exit_70"
    status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path, operation_payload=operation)).read()
    )

    assert status.constraints.exit_code == 1
    assert status.operation.partial_evidence_ref == DIGEST_C
    assert status.operation.stopped_early is True
    assert status.operation.stop_reason == "tool_failed"


def test_unknown_enum_phase_order_and_operation_conflict_return_two(tmp_path: Path) -> None:
    unknown = _operation_payload()
    unknown["states"]["startup_state"] = "future_state"
    unknown_status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path / "unknown", operation_payload=unknown)).read()
    )
    assert unknown_status.constraints.exit_code == 2
    assert "layout.status.unknown_state" in unknown_status.constraints.violations

    operation = _operation_payload()
    manifest = _fixture(tmp_path / "phase", operation_payload=operation)
    migration_path = manifest.parent / "records" / "migration.json"
    migration = json.loads(migration_path.read_text(encoding="utf-8"))
    migration["payload"]["phases"] = [
        "prepared",
        "process_started",
        "selector_committed",
        "verified",
    ]
    migration["record_digest"] = canonical_record_digest(migration)
    _write(migration_path, migration)
    manifest_record = json.loads(manifest.read_text(encoding="utf-8"))
    migration_ref = next(
        item for item in manifest_record["references"] if item["name"] == "migration"
    )
    migration_ref["digest"] = migration["record_digest"]
    manifest_record["payload"]["migration_evidence_ref"] = migration["record_digest"]
    manifest_record["record_digest"] = canonical_record_digest(manifest_record)
    _write(manifest, manifest_record)
    with pytest.raises(LayoutStatusInvalid) as phase:
        validate_graph(ExplicitRecordReader(manifest).read())
    assert phase.value.error.code == "layout.status.phase_order"

    conflict = _operation_payload()
    conflict["operation_id"] = "operation-conflict"
    conflict_status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path / "conflict", operation_payload=conflict)).read()
    )
    assert conflict_status.constraints.exit_code == 2
    assert "layout.status.identity_mismatch" in conflict_status.constraints.violations


def test_terminal_failure_cannot_reuse_success_axes(tmp_path: Path) -> None:
    operation = _operation_payload(phase="failed")
    operation["operator_action"] = "continue_validation"
    status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path, operation_payload=operation)).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.phase_order_invalid" in status.constraints.violations


@pytest.mark.parametrize(
    ("operation", "mutate"),
    [
        (
            _operation_payload(),
            lambda operation: operation["process"].update({"matching_live_instances": 0}),
        ),
        (
            _operation_payload(),
            lambda operation: operation["shutdown"].update({"stage": "complete", "complete": True}),
        ),
        (
            _operation_payload(),
            lambda operation: operation["shutdown"].update(
                {"stage": "term", "signal_escalation": "term"}
            ),
        ),
        (
            _operation_payload(
                states=_states(startup="started_degraded"),
                action="investigate",
            ),
            lambda operation: (
                operation.update({"degraded_components": ["startup-automation"]}),
                operation["shutdown"].update({"stage": "term", "signal_escalation": "term"}),
            ),
        ),
    ],
)
def test_verified_running_process_requires_live_instance_and_no_shutdown(
    tmp_path: Path,
    operation: dict[str, Any],
    mutate: Any,
) -> None:
    operation = deepcopy(operation)
    mutate(operation)
    status = validate_graph(
        ExplicitRecordReader(_fixture(tmp_path, operation_payload=operation)).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.receipt_invalid" in status.constraints.violations


def test_authoritative_state_requires_terminal_migration_evidence(tmp_path: Path) -> None:
    operation = _operation_payload(phase="process_started")
    status = validate_graph(
        ExplicitRecordReader(
            _fixture(tmp_path, operation_payload=operation, include_migration=False)
        ).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.phase_order_invalid" in status.constraints.violations


def test_selector_fence_must_advance_exactly_once(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)

    def jump_fence(record: dict[str, Any]) -> None:
        record["payload"]["fence"] = 9
        content = dict(record["payload"])
        content.pop("selector_payload_digest")
        record["payload"]["selector_payload_digest"] = (
            "sha256:" + hashlib.sha256(canonical_json(content)).hexdigest()
        )

    _rewrite_record_and_manifest_reference(
        manifest,
        reference_name="selector",
        mutate=jump_fence,
    )
    manifest_record = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_record["payload"]["selected_fence"] = 9
    manifest_record["record_digest"] = canonical_record_digest(manifest_record)
    _write(manifest, manifest_record)
    status = validate_graph(ExplicitRecordReader(manifest).read())

    assert status.constraints.exit_code == 2
    assert "layout.status.identity_mismatch" in status.constraints.violations


def test_missing_web_build_digest_cannot_be_classified_healthy(tmp_path: Path) -> None:
    status = validate_graph(
        ExplicitRecordReader(
            _fixture(
                tmp_path,
                manifest_changes={"web_build_digest": None},
                validation_report_changes={"web_build_digest": None},
            )
        ).read()
    )

    assert status.constraints.exit_code == 1
    assert dict(status.constraints.axis_classifications)["web_assets"] == "valid_attention"


def test_terminal_commands_and_report_must_match_prepared_evidence(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    _rewrite_record_and_manifest_reference(
        manifest,
        reference_name="migration",
        mutate=lambda record: record["payload"].update(
            {"command_digests": [DIGEST_B], "report_entries_digest": DIGEST_A}
        ),
    )
    status = validate_graph(ExplicitRecordReader(manifest).read())

    assert status.constraints.exit_code == 2
    assert "layout.status.identity_mismatch" in status.constraints.violations


def test_inventory_freshness_is_derived_from_bound_timestamps(tmp_path: Path) -> None:
    manifest = _fixture(
        tmp_path,
        manifest_changes={"inventory_age_seconds": 1},
    )
    status = validate_graph(ExplicitRecordReader(manifest).read())

    assert status.constraints.exit_code == 2
    assert "layout.status.additional_invalid" in status.constraints.violations


def test_unsuperseded_process_start_cannot_prove_absence(tmp_path: Path) -> None:
    operation = _operation_payload(
        states=_states(
            migration="prepared",
            execution="stopped",
            startup="stopped",
            reconciliation="absence_proved",
        ),
        action="retry_identical_invocation",
        phase="process_started",
    )
    operation["process"].update({"matching_live_instances": 0, "zero_live_descendants": True})
    status = validate_graph(
        ExplicitRecordReader(
            _fixture(tmp_path, operation_payload=operation, include_migration=False)
        ).read()
    )

    assert status.constraints.exit_code == 2
    assert "layout.status.receipt_invalid" in status.constraints.violations


def test_bridge_coverage_cannot_claim_child_outcomes_before_child_exists(
    tmp_path: Path,
) -> None:
    operation = _operation_payload(action="continue_validation")
    status = validate_graph(
        ExplicitRecordReader(
            _fixture(
                tmp_path,
                operation_payload=operation,
                manifest_changes={"bridge_coverage_state": "partial"},
            )
        ).read()
    )

    assert status.constraints.exit_code == 2
    assert status.constraints.derived_action == "continue_validation"
    assert dict(status.constraints.axis_classifications)["bridge_coverage"] == "invalid"


def test_inventory_over_age_or_incomplete_is_invalid(tmp_path: Path) -> None:
    for index, changes in enumerate(
        ({"inventory_age_seconds": 86_401}, {"inventory_completeness": "tool_failed"})
    ):
        status = validate_graph(
            ExplicitRecordReader(_fixture(tmp_path / str(index), manifest_changes=changes)).read()
        )
        assert status.constraints.exit_code == 2
        assert "layout.status.additional_invalid" in status.constraints.violations


def test_reader_rejects_symlink_corrupt_digest_and_noncanonical_json(
    tmp_path: Path,
) -> None:
    manifest = _fixture(tmp_path / "symlink")
    operation = manifest.parent / "records" / "operation.json"
    real = operation.with_name("real-operation.json")
    operation.rename(real)
    operation.symlink_to(real.name)
    with pytest.raises(LayoutStatusInvalid) as symlink:
        ExplicitRecordReader(manifest).read()
    assert symlink.value.error.code == "layout.status.record_open"

    manifest = _fixture(tmp_path / "digest")
    operation = manifest.parent / "records" / "operation.json"
    payload = bytearray(operation.read_bytes())
    payload[-3] = ord("0") if payload[-3] != ord("0") else ord("1")
    operation.write_bytes(bytes(payload))
    with pytest.raises(LayoutStatusInvalid) as digest:
        ExplicitRecordReader(manifest).read()
    assert digest.value.error.code in {
        "layout.status.record_digest",
        "layout.status.record_json",
        "layout.status.reference_digest",
    }

    manifest = _fixture(tmp_path / "pretty")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps(record, indent=2), encoding="utf-8")
    with pytest.raises(LayoutStatusInvalid) as noncanonical:
        ExplicitRecordReader(manifest).read()
    assert noncanonical.value.error.code == "layout.status.record_canonical"


def test_reader_rejects_references_owned_by_non_root_records(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    manifest_record = json.loads(manifest.read_text(encoding="utf-8"))
    authority_reference = next(
        item for item in manifest_record["references"] if item["name"] == "authority"
    )
    authority_path = manifest.parent / authority_reference["path"]
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    nested = _record(
        "consumer_inventory",
        "unconsumed-inventory",
        _inventory_payload(),
    )
    nested_path = manifest.parent / "records" / "unconsumed-inventory.json"
    _write(nested_path, nested)
    authority["references"] = [
        {
            "name": "unconsumed",
            "path": "records/unconsumed-inventory.json",
            "digest": nested["record_digest"],
        }
    ]
    authority["record_digest"] = canonical_record_digest(authority)
    _write(authority_path, authority)
    authority_reference["digest"] = authority["record_digest"]
    manifest_record["record_digest"] = canonical_record_digest(manifest_record)
    _write(manifest, manifest_record)

    with pytest.raises(LayoutStatusInvalid) as non_root:
        ExplicitRecordReader(manifest).read()

    assert non_root.value.error.code == "layout.status.non_root_references"


def test_reader_enforces_count_size_depth_and_deadline(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path / "count")
    with pytest.raises(LayoutStatusInvalid) as count:
        ExplicitRecordReader(manifest, limits=ReaderLimits(max_records=4)).read()
    assert count.value.error.code == "layout.status.record_count"

    manifest = _fixture(tmp_path / "size")
    with pytest.raises(LayoutStatusInvalid) as size:
        ExplicitRecordReader(manifest, limits=ReaderLimits(max_record_bytes=128)).read()
    assert size.value.error.code == "layout.status.record_size"

    manifest = _fixture(tmp_path / "aggregate")
    with pytest.raises(LayoutStatusInvalid) as aggregate:
        ExplicitRecordReader(
            manifest,
            limits=ReaderLimits(max_aggregate_bytes=1024),
        ).read()
    assert aggregate.value.error.code == "layout.status.aggregate_size"

    manifest = _fixture(tmp_path / "depth")
    with pytest.raises(LayoutStatusInvalid) as depth:
        ExplicitRecordReader(manifest, limits=ReaderLimits(max_depth=0)).read()
    assert depth.value.error.code == "layout.status.reference_depth"

    ticks = iter((0.0, 0.0, 6.0))
    with pytest.raises(LayoutStatusInvalid) as deadline:
        ExplicitRecordReader(manifest, monotonic=lambda: next(ticks)).read()
    assert deadline.value.error.code == "layout.status.deadline"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO fixture requires POSIX")
def test_reader_rejects_fifo_without_waiting_for_a_writer(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    operation_path = manifest.parent / "records" / "operation.json"
    operation_path.unlink()
    os.mkfifo(operation_path)
    assert stat.S_ISFIFO(operation_path.stat().st_mode)

    started = time.monotonic()
    with pytest.raises(LayoutStatusInvalid) as blocked:
        ExplicitRecordReader(manifest).read()
    elapsed = time.monotonic() - started

    assert blocked.value.error.code == "layout.status.not_regular"
    assert elapsed < 1.0


def test_deep_json_returns_typed_invalid_instead_of_stack_error(tmp_path: Path) -> None:
    manifest = tmp_path / "status.json"
    manifest.write_bytes(
        (
            '{"payload":{"nested":'
            + "[" * 100
            + "0"
            + "]" * 100
            + '},"record_digest":"sha256:'
            + "0" * 64
            + '","record_id":"status","record_type":"layout_status_manifest",'
            + '"references":[],"schema_version":"trade.layout.record.v1"}'
        ).encode("utf-8")
    )

    with pytest.raises(LayoutStatusInvalid) as nested:
        ExplicitRecordReader(manifest).read()

    assert nested.value.error.code == "layout.status.record_json"


def test_invocation_deadline_interrupts_cross_record_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _fixture(tmp_path)
    monkeypatch.setenv("TRADE_LAYOUT_STATUS_MANIFEST", str(manifest))
    real_validate = validate_graph

    def slow_validate(*args: Any, **kwargs: Any) -> Any:
        time.sleep(0.1)
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(
        "trade_py.devtools.layout_status.cli.InvocationDeadline",
        lambda: InvocationDeadline(seconds=0.02),
    )
    monkeypatch.setattr(
        "trade_py.devtools.layout_status.cli.validate_graph",
        slow_validate,
    )

    code = dev.main(["layout-status", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["error"]["code"] == "layout.status.deadline"


def test_absolute_manifest_and_relative_references_cannot_escape(tmp_path: Path) -> None:
    with pytest.raises(LayoutStatusInvalid) as relative:
        ExplicitRecordReader(Path("status.json"))
    assert relative.value.error.code == "layout.status.manifest_not_absolute"

    manifest = _fixture(tmp_path)
    record = json.loads(manifest.read_text(encoding="utf-8"))
    record["references"][0]["path"] = "../operation.json"
    record["record_digest"] = canonical_record_digest(record)
    _write(manifest, record)
    with pytest.raises(LayoutStatusInvalid) as escape:
        ExplicitRecordReader(manifest).read()
    assert escape.value.error.code == "layout.status.reference_path"


@pytest.mark.parametrize(
    "control",
    ["\x00", "\x01", "\x1b", "\x7f", "\x80", "\x9b", "\x9f"],
)
def test_manifest_and_reference_paths_reject_terminal_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    with pytest.raises(LayoutStatusInvalid) as manifest_path:
        ExplicitRecordReader(Path(f"/tmp/status{control}.json"))
    assert manifest_path.value.error.code == "layout.status.manifest_not_absolute"

    manifest = _fixture(tmp_path)
    record = json.loads(manifest.read_text(encoding="utf-8"))
    record["references"][0]["path"] = f"records/{control}authority.json"
    record["record_digest"] = canonical_record_digest(record)
    _write(manifest, record)
    monkeypatch.setenv("TRADE_LAYOUT_STATUS_MANIFEST", str(manifest))

    code = dev.main(["layout-status"])
    output = capsys.readouterr().out

    assert code == 2
    assert "layout.status.reference_path" in output
    assert control not in output
    assert f"\\x{ord(control):02x}" in output


def test_manifest_and_reference_paths_reject_lone_surrogates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    surrogate = "\ud800"
    with pytest.raises(LayoutStatusInvalid) as manifest_path:
        ExplicitRecordReader(Path(f"/tmp/status{surrogate}.json"))
    assert manifest_path.value.error.code == "layout.status.manifest_not_absolute"

    manifest = _fixture(tmp_path)
    record = json.loads(manifest.read_text(encoding="utf-8"))
    record["references"][0]["path"] = f"records/{surrogate}authority.json"
    record["record_digest"] = canonical_record_digest(record)
    _write(manifest, record)
    monkeypatch.setenv("TRADE_LAYOUT_STATUS_MANIFEST", str(manifest))

    code = dev.main(["layout-status"])
    output = capsys.readouterr().out

    assert code == 2
    assert "layout.status.reference_path" in output
    assert surrogate not in output
    assert "\\ud800" in output


def test_top_level_layout_status_ignores_dotenv_manifest_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _fixture(tmp_path)
    env_file = tmp_path / "trade.env"
    env_file.write_text(
        f"TRADE_LAYOUT_STATUS_MANIFEST={manifest}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADE_ENV_FILE", str(env_file))
    monkeypatch.delenv("TRADE_LAYOUT_STATUS_MANIFEST", raising=False)

    code = main_cli.main(["dev", "layout-status", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["error"]["code"] == "layout.status.manifest_unset"
    assert "TRADE_LAYOUT_STATUS_MANIFEST" not in os.environ


def test_cli_does_not_invoke_git_process_or_business_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _fixture(tmp_path)
    monkeypatch.setenv("TRADE_LAYOUT_STATUS_MANIFEST", str(manifest))
    calls: list[tuple[Any, ...]] = []

    def forbidden(*args: Any, **kwargs: Any) -> None:
        calls.append((*args, kwargs))
        raise AssertionError("layout-status must not launch a process")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    assert dev.main(["layout-status", "--json"]) == 1
    assert calls == []


def test_shell_route_is_frozen_no_sync_and_help_lists_status(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    routed = subprocess.run(
        [str(REPO_ROOT / "trade"), "dev", "layout-status", "--json"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    help_result = subprocess.run(
        [str(REPO_ROOT / "trade"), "help"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    lines = routed.stdout.splitlines()
    assert lines[:4] == ["run", "--frozen", "--no-sync", "python"]
    assert lines[-3:] == ["dev", "layout-status", "--json"]
    assert "./trade dev layout-status" in help_result.stdout


def test_layout_status_source_has_no_runtime_or_mutation_dependencies() -> None:
    forbidden_imports = (
        "trade_py.data",
        "trade_py.db",
        "trade_py.event",
        "trade_py.infra",
        "trade_py.jobs",
        "trade_web",
    )
    forbidden_calls = {
        "glob",
        "rglob",
        "walk",
        "Popen",
        "run",
        "system",
        "fork",
        "kill",
    }
    for path in (REPO_ROOT / "trade_py" / "devtools" / "layout_status").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imported: list[str] = []
        calls: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.append(node.module)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)
        assert not any(
            module == prefix or module.startswith(f"{prefix}.")
            for module in imported
            for prefix in forbidden_imports
        ), path
        assert not forbidden_calls.intersection(calls), path
        assert "/proc" not in source
        assert "systemctl" not in source
        assert "service-manager" not in source
        assert "git " not in source.lower()
