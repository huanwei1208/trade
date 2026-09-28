"""Typed immutable snapshots parsed from layout evidence records."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Final, NoReturn

from trade_py.devtools.layout_status.constraints import LayoutStatusAxes
from trade_py.devtools.layout_status.errors import invalid
from trade_py.devtools.layout_status.models import (
    ConsumerInventorySnapshot,
    LayoutSelectorSnapshotV1,
    MigrationEvidenceRef,
    ModuleAuthoritySnapshot,
    OperationStatusSnapshotV1,
    PackageGenerationSnapshot,
    PreparedEvidenceRef,
    ProcessReceipt,
    ProcessSnapshot,
    RollbackSnapshot,
    SelectorObservation,
    ShutdownSnapshot,
    ValidationReportSnapshot,
)
from trade_py.devtools.layout_status.records import (
    EvidenceRecord,
    canonical_json,
    contains_unsafe_text,
)

_DIGEST_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")
_IDENTITY_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SCOPE_RE: Final = re.compile(r"(?:python_deployment|web_build)")
_PHASES: Final = (
    "prepared",
    "selector_committed",
    "start_intent_recorded",
    "process_started",
    "verified",
    "failed",
    "rollback_prepared",
    "rollback_selector_committed",
    "rollback_verified",
)
_SHUTDOWN_STAGES: Final = frozenset({"not_started", "term", "kill", "complete"})
_ESCALATIONS: Final = frozenset({"none", "term", "term_kill"})
_RECEIPT_TYPES: Final = frozenset({"process_started", "terminal_absence", "teardown"})
_MIGRATION_STATES: Final = frozenset(
    {
        "inventoried",
        "prepared",
        "shadow_verified",
        "legacy_forwarding",
        "target_authoritative",
        "retireable",
    }
)


def parse_inventory(record: EvidenceRecord) -> ConsumerInventorySnapshot:
    _expect_type(record, "consumer_inventory")
    payload = _object(
        record.payload,
        {
            "schema_version",
            "source_commit",
            "tree_digest",
            "scanner_name",
            "scanner_version",
            "scanner_source_digest",
            "included_roots",
            "explicit_exclusions",
            "rules_digest",
            "generated_at",
            "max_age_seconds",
            "completeness_state",
            "production_module_count",
            "consumer_count",
            "unclassified_consumer_count",
            "entry_digest",
            "report_digest",
        },
        record,
    )
    report_digest = _digest(payload, "report_digest", record)
    if report_digest != _content_digest(payload, "report_digest"):
        _fail(record, "layout.status.inventory_digest", "Inventory report digest mismatches.")
    generated_at = _utc_timestamp(payload, "generated_at", record)
    completeness = _string(payload, "completeness_state", record)
    if completeness not in {"complete", "incomplete", "tool_failed", "over_budget"}:
        _fail(record, "layout.status.inventory_state", "Inventory completeness is unknown.")
    return ConsumerInventorySnapshot(
        record_digest=record.record_digest,
        schema_version=_integer(payload, "schema_version", record, minimum=1, maximum=1),
        source_commit=_commit(payload, "source_commit", record),
        tree_digest=_digest(payload, "tree_digest", record),
        scanner_name=_identity(payload, "scanner_name", record),
        scanner_version=_identity(payload, "scanner_version", record),
        scanner_source_digest=_digest(payload, "scanner_source_digest", record),
        included_roots=_bounded_string_list(
            payload, "included_roots", record, maximum=32, item_maximum=256
        ),
        explicit_exclusions=_bounded_string_list(
            payload, "explicit_exclusions", record, maximum=128, item_maximum=256
        ),
        rules_digest=_digest(payload, "rules_digest", record),
        generated_at=generated_at,
        max_age_seconds=_integer(payload, "max_age_seconds", record, minimum=1, maximum=86_400),
        completeness_state=completeness,
        production_module_count=_integer(payload, "production_module_count", record, maximum=50),
        consumer_count=_integer(payload, "consumer_count", record, maximum=500),
        unclassified_consumer_count=_integer(
            payload, "unclassified_consumer_count", record, maximum=500
        ),
        entry_digest=_digest(payload, "entry_digest", record),
        report_digest=report_digest,
    )


def parse_authority(record: EvidenceRecord) -> ModuleAuthoritySnapshot:
    _expect_type(record, "module_authority")
    payload = _object(
        record.payload,
        {
            "legacy_module",
            "target_module",
            "owner",
            "contract_generation",
            "implementation_digest",
            "compatibility_direction",
            "state",
            "consumer_inventory_ref",
            "activation_plan_digest",
        },
        record,
    )
    direction = _string(payload, "compatibility_direction", record)
    if direction != "legacy_to_target":
        _fail(
            record,
            "layout.status.authority_direction",
            "Authority compatibility direction is unsupported.",
        )
    state = _string(payload, "state", record)
    if state not in _MIGRATION_STATES:
        _fail(record, "layout.status.authority_state", "Authority state is unknown.")
    return ModuleAuthoritySnapshot(
        record_digest=record.record_digest,
        legacy_module=_identity(payload, "legacy_module", record),
        target_module=_identity(payload, "target_module", record),
        owner=_identity(payload, "owner", record),
        contract_generation=_identity(payload, "contract_generation", record),
        implementation_digest=_digest(payload, "implementation_digest", record),
        compatibility_direction=direction,
        state=state,
        consumer_inventory_ref=_digest(payload, "consumer_inventory_ref", record),
        activation_plan_digest=_digest(payload, "activation_plan_digest", record),
    )


def parse_package(record: EvidenceRecord) -> PackageGenerationSnapshot:
    _expect_type(record, "package_generation")
    payload = _object(
        record.payload,
        {
            "distribution_name",
            "distribution_version",
            "python_tag",
            "platform_tag",
            "wheel_digest",
            "wheel_member_digest",
            "wheel_member_count",
            "compatibility_manifest_digest",
        },
        record,
    )
    return PackageGenerationSnapshot(
        record_digest=record.record_digest,
        distribution_name=_identity(payload, "distribution_name", record),
        distribution_version=_identity(payload, "distribution_version", record),
        python_tag=_identity(payload, "python_tag", record),
        platform_tag=_identity(payload, "platform_tag", record),
        wheel_digest=_digest(payload, "wheel_digest", record),
        wheel_member_digest=_digest(payload, "wheel_member_digest", record),
        wheel_member_count=_integer(payload, "wheel_member_count", record),
        compatibility_manifest_digest=_digest(payload, "compatibility_manifest_digest", record),
    )


def parse_validation_report(record: EvidenceRecord) -> ValidationReportSnapshot:
    _expect_type(record, "validation_report")
    payload = _object(
        record.payload,
        {
            "source_commit",
            "source_tree_digest",
            "package_generation_ref",
            "root_console_parity",
            "asgi_import_state",
            "reload_child_import_state",
            "route_parity_state",
            "openapi_parity_state",
            "sse_parity_state",
            "capability_parity_state",
            "web_build_digest",
            "web_missing_asset_count",
            "native_capability_state",
            "native_build_state",
            "native_differential_state",
            "notebook_state",
            "report_entries_digest",
            "report_digest",
        },
        record,
    )
    report_digest = _digest(payload, "report_digest", record)
    if report_digest != _content_digest(payload, "report_digest"):
        _fail(
            record,
            "layout.status.validation_report_digest",
            "Validation report digest mismatches.",
        )
    return ValidationReportSnapshot(
        record_digest=record.record_digest,
        source_commit=_commit(payload, "source_commit", record),
        source_tree_digest=_digest(payload, "source_tree_digest", record),
        package_generation_ref=_digest(payload, "package_generation_ref", record),
        root_console_parity=_check_state(payload, "root_console_parity", record),
        asgi_import_state=_check_state(payload, "asgi_import_state", record),
        reload_child_import_state=_check_state(payload, "reload_child_import_state", record),
        route_parity_state=_check_state(payload, "route_parity_state", record),
        openapi_parity_state=_check_state(payload, "openapi_parity_state", record),
        sse_parity_state=_check_state(payload, "sse_parity_state", record),
        capability_parity_state=_check_state(payload, "capability_parity_state", record),
        web_build_digest=_optional_digest(payload, "web_build_digest", record),
        web_missing_asset_count=_integer(payload, "web_missing_asset_count", record),
        native_capability_state=_check_state(payload, "native_capability_state", record),
        native_build_state=_check_state(payload, "native_build_state", record),
        native_differential_state=_check_state(payload, "native_differential_state", record),
        notebook_state=_check_state(payload, "notebook_state", record),
        report_entries_digest=_digest(payload, "report_entries_digest", record),
        report_digest=report_digest,
    )


def parse_prepared(record: EvidenceRecord) -> PreparedEvidenceRef:
    _expect_type(record, "prepared_evidence")
    payload = _object(
        record.payload,
        {
            "operation_id",
            "attempt_id",
            "scope",
            "source_commit",
            "source_tree_digest",
            "policy_digest",
            "approved_design_digest",
            "activation_plan_digest",
            "current_composition_digest",
            "immutable_input_refs",
            "intended_target_generation",
            "expected_generation",
            "expected_revision",
            "expected_fence",
            "deployment_unit",
            "invocation_token",
            "command_digests",
            "prepared_at",
        },
        record,
    )
    return PreparedEvidenceRef(
        record_digest=record.record_digest,
        operation_id=_identity(payload, "operation_id", record),
        attempt_id=_identity(payload, "attempt_id", record),
        scope=_scope(payload, "scope", record),
        source_commit=_commit(payload, "source_commit", record),
        source_tree_digest=_digest(payload, "source_tree_digest", record),
        policy_digest=_digest(payload, "policy_digest", record),
        approved_design_digest=_digest(payload, "approved_design_digest", record),
        activation_plan_digest=_digest(payload, "activation_plan_digest", record),
        current_composition_digest=_digest(payload, "current_composition_digest", record),
        immutable_input_refs=_digest_list(payload, "immutable_input_refs", record),
        intended_target_generation=_identity(payload, "intended_target_generation", record),
        expected_generation=_identity(payload, "expected_generation", record),
        expected_revision=_integer(payload, "expected_revision", record),
        expected_fence=_integer(payload, "expected_fence", record),
        deployment_unit=_identity(payload, "deployment_unit", record),
        invocation_token=_identity(payload, "invocation_token", record),
        command_digests=_ordered_digest_list(payload, "command_digests", record),
        prepared_at=_utc_timestamp(payload, "prepared_at", record),
    )


def parse_selector(record: EvidenceRecord) -> LayoutSelectorSnapshotV1:
    _expect_type(record, "layout_selector_snapshot")
    payload = _object(
        record.payload,
        {
            "scope",
            "generation",
            "revision",
            "fence",
            "operation_id",
            "plan_digest",
            "prepared_evidence_ref",
            "predecessor_generation",
            "predecessor_revision",
            "selector_payload_digest",
        },
        record,
    )
    selector = LayoutSelectorSnapshotV1(
        record_digest=record.record_digest,
        scope=_scope(payload, "scope", record),
        generation=_identity(payload, "generation", record),
        revision=_integer(payload, "revision", record, minimum=1),
        fence=_integer(payload, "fence", record, minimum=1),
        operation_id=_identity(payload, "operation_id", record),
        plan_digest=_digest(payload, "plan_digest", record),
        prepared_evidence_ref=_digest(payload, "prepared_evidence_ref", record),
        predecessor_generation=_identity(payload, "predecessor_generation", record),
        predecessor_revision=_integer(payload, "predecessor_revision", record),
        selector_payload_digest=_digest(payload, "selector_payload_digest", record),
    )
    expected_digest = _content_digest(payload, "selector_payload_digest")
    if selector.selector_payload_digest != expected_digest:
        _fail(record, "layout.status.selector_digest", "Selector payload digest mismatches.")
    if selector.predecessor_revision + 1 != selector.revision:
        _fail(
            record,
            "layout.status.selector_revision",
            "Selector revision must be exactly one after its predecessor.",
        )
    if selector.generation == selector.predecessor_generation:
        _fail(
            record,
            "layout.status.selector_generation",
            "Selector generation must differ from its predecessor.",
        )
    return selector


def parse_operation(record: EvidenceRecord) -> OperationStatusSnapshotV1:
    _expect_type(record, "operation_status_snapshot")
    payload = _object(
        record.payload,
        {
            "operation_id",
            "attempt_id",
            "scope",
            "activation_phase",
            "states",
            "operator_action",
            "tool_exit_code",
            "partial_evidence_ref",
            "stopped_early",
            "stop_reason",
            "failure_detail",
            "degraded_components",
            "process",
            "shutdown",
            "rollback",
        },
        record,
    )
    phase = _string(payload, "activation_phase", record)
    if phase not in _PHASES:
        _fail(record, "layout.status.phase", "Operation uses an unknown activation phase.")
    action = _string(payload, "operator_action", record)
    process = _parse_process(_mapping(payload, "process", record), record)
    shutdown = _parse_shutdown(_mapping(payload, "shutdown", record), record)
    rollback = _parse_rollback(_mapping(payload, "rollback", record), record)
    degraded = _identity_list(payload, "degraded_components", record, maximum=32)
    return OperationStatusSnapshotV1(
        record_digest=record.record_digest,
        operation_id=_identity(payload, "operation_id", record),
        attempt_id=_identity(payload, "attempt_id", record),
        scope=_scope(payload, "scope", record),
        activation_phase=phase,
        axes=_axes(_mapping(payload, "states", record), record),
        operator_action=action,
        tool_exit_code=_optional_integer(payload, "tool_exit_code", record, minimum=0),
        partial_evidence_ref=_optional_digest(payload, "partial_evidence_ref", record),
        stopped_early=_boolean(payload, "stopped_early", record),
        stop_reason=_optional_identity(payload, "stop_reason", record),
        failure_detail=_optional_identity(payload, "failure_detail", record),
        degraded_components=degraded,
        process=process,
        shutdown=shutdown,
        rollback=rollback,
    )


def parse_migration(record: EvidenceRecord) -> MigrationEvidenceRef:
    _expect_type(record, "migration_evidence")
    payload = _object(
        record.payload,
        {
            "operation_id",
            "attempt_id",
            "scope",
            "source_commit",
            "source_tree_digest",
            "policy_digest",
            "approved_design_digest",
            "consumer_inventory_ref",
            "module_authority_ref",
            "artifact_refs",
            "activation_plan_digest",
            "prepared_evidence_ref",
            "operation_status_ref",
            "selector_before",
            "selector_after",
            "phases",
            "terminal_outcome",
            "command_digests",
            "toolchain",
            "deadline_milliseconds",
            "typed_outcomes",
            "partial_evidence_refs",
            "report_entries_digest",
        },
        record,
    )
    phases = _phase_list(payload, record)
    terminal = _string(payload, "terminal_outcome", record)
    if terminal not in {"verified", "failed", "rolled_back"}:
        _fail(record, "layout.status.terminal_outcome", "Migration outcome is not terminal.")
    if terminal == "verified" and phases[-1] != "verified":
        _fail(record, "layout.status.phase_order", "Verified evidence must end at verified.")
    if terminal == "failed" and phases[-1] != "failed":
        _fail(record, "layout.status.phase_order", "Failed evidence must end at failed.")
    if terminal == "rolled_back" and phases[-1] != "rollback_verified":
        _fail(
            record,
            "layout.status.phase_order",
            "Rolled-back evidence must end at rollback_verified.",
        )
    return MigrationEvidenceRef(
        record_digest=record.record_digest,
        operation_id=_identity(payload, "operation_id", record),
        attempt_id=_identity(payload, "attempt_id", record),
        scope=_scope(payload, "scope", record),
        source_commit=_commit(payload, "source_commit", record),
        source_tree_digest=_digest(payload, "source_tree_digest", record),
        policy_digest=_digest(payload, "policy_digest", record),
        approved_design_digest=_digest(payload, "approved_design_digest", record),
        consumer_inventory_ref=_digest(payload, "consumer_inventory_ref", record),
        module_authority_ref=_digest(payload, "module_authority_ref", record),
        artifact_refs=_digest_list(payload, "artifact_refs", record),
        activation_plan_digest=_digest(payload, "activation_plan_digest", record),
        prepared_evidence_ref=_digest(payload, "prepared_evidence_ref", record),
        operation_status_ref=_digest(payload, "operation_status_ref", record),
        selector_before=_selector_observation(_mapping(payload, "selector_before", record), record),
        selector_after=_selector_observation(_mapping(payload, "selector_after", record), record),
        phases=phases,
        terminal_outcome=terminal,
        command_digests=_ordered_digest_list(payload, "command_digests", record),
        toolchain=_identity_list(payload, "toolchain", record, maximum=32),
        deadline_milliseconds=_integer(payload, "deadline_milliseconds", record, minimum=1),
        typed_outcomes=_axes(_mapping(payload, "typed_outcomes", record), record),
        partial_evidence_refs=_digest_list(payload, "partial_evidence_refs", record),
        report_entries_digest=_digest(payload, "report_entries_digest", record),
    )


def _parse_process(payload: dict[str, Any], record: EvidenceRecord) -> ProcessSnapshot:
    _exact(
        payload,
        {
            "deployment_unit",
            "invocation_token",
            "generation",
            "revision",
            "fence",
            "matching_live_instances",
            "zero_live_descendants",
            "receipts",
        },
        record,
    )
    return ProcessSnapshot(
        deployment_unit=_identity(payload, "deployment_unit", record),
        invocation_token=_identity(payload, "invocation_token", record),
        generation=_identity(payload, "generation", record),
        revision=_integer(payload, "revision", record),
        fence=_integer(payload, "fence", record),
        matching_live_instances=_integer(payload, "matching_live_instances", record, maximum=2),
        zero_live_descendants=_boolean(payload, "zero_live_descendants", record),
        receipts=_parse_receipts(payload, record),
    )


def _parse_receipts(payload: dict[str, Any], record: EvidenceRecord) -> tuple[ProcessReceipt, ...]:
    value = payload.get("receipts")
    if not isinstance(value, list) or len(value) > 8:
        _fail(record, "layout.status.receipt_shape", "Process receipts must be a bounded list.")
    receipts: list[ProcessReceipt] = []
    for raw in value:
        if not isinstance(raw, dict):
            _fail(record, "layout.status.receipt_shape", "Each process receipt must be an object.")
        _exact(
            raw,
            {
                "receipt_id",
                "receipt_type",
                "observed_at",
                "operation_id",
                "attempt_id",
                "deployment_unit",
                "invocation_token",
                "generation",
                "revision",
                "fence",
                "supersedes_receipt_id",
                "live_descendant_count",
            },
            record,
        )
        receipt_id = _digest(raw, "receipt_id", record)
        if receipt_id != _content_digest(raw, "receipt_id"):
            _fail(record, "layout.status.receipt_digest", "Process receipt digest mismatches.")
        receipt_type = _string(raw, "receipt_type", record)
        if receipt_type not in _RECEIPT_TYPES:
            _fail(record, "layout.status.receipt_shape", "Process receipt type is unknown.")
        receipts.append(
            ProcessReceipt(
                receipt_id=receipt_id,
                receipt_type=receipt_type,
                observed_at=_utc_timestamp(raw, "observed_at", record),
                operation_id=_identity(raw, "operation_id", record),
                attempt_id=_identity(raw, "attempt_id", record),
                deployment_unit=_identity(raw, "deployment_unit", record),
                invocation_token=_identity(raw, "invocation_token", record),
                generation=_identity(raw, "generation", record),
                revision=_integer(raw, "revision", record),
                fence=_integer(raw, "fence", record),
                supersedes_receipt_id=_optional_digest(raw, "supersedes_receipt_id", record),
                live_descendant_count=_integer(
                    raw, "live_descendant_count", record, maximum=2**31 - 1
                ),
            )
        )
    if len({item.receipt_id for item in receipts}) != len(receipts):
        _fail(record, "layout.status.receipt_duplicate", "Process receipt IDs must be unique.")
    timestamps = tuple(_parse_utc(item.observed_at) for item in receipts)
    if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
        _fail(record, "layout.status.receipt_order", "Process receipts must be time ordered.")
    return tuple(receipts)


def _parse_shutdown(payload: dict[str, Any], record: EvidenceRecord) -> ShutdownSnapshot:
    _exact(
        payload,
        {
            "stage",
            "signal_escalation",
            "residual_process_count",
            "residual_thread_count",
            "forced_exit_receipt",
            "complete",
        },
        record,
    )
    stage = _string(payload, "stage", record)
    escalation = _string(payload, "signal_escalation", record)
    if stage not in _SHUTDOWN_STAGES or escalation not in _ESCALATIONS:
        _fail(record, "layout.status.shutdown", "Shutdown state uses an unknown value.")
    return ShutdownSnapshot(
        stage=stage,
        signal_escalation=escalation,
        residual_process_count=_integer(payload, "residual_process_count", record),
        residual_thread_count=_integer(payload, "residual_thread_count", record),
        forced_exit_receipt=_boolean(payload, "forced_exit_receipt", record),
        complete=_boolean(payload, "complete", record),
    )


def _parse_rollback(payload: dict[str, Any], record: EvidenceRecord) -> RollbackSnapshot:
    _exact(
        payload,
        {
            "plan_scope",
            "target_generation",
            "later_accepted_slices",
            "target_is_historical_predecessor",
            "compensation_preserves_later_slices",
        },
        record,
    )
    return RollbackSnapshot(
        plan_scope=_scope(payload, "plan_scope", record),
        target_generation=_optional_identity(payload, "target_generation", record),
        later_accepted_slices=_boolean(payload, "later_accepted_slices", record),
        target_is_historical_predecessor=_boolean(
            payload, "target_is_historical_predecessor", record
        ),
        compensation_preserves_later_slices=_boolean(
            payload, "compensation_preserves_later_slices", record
        ),
    )


def _selector_observation(payload: dict[str, Any], record: EvidenceRecord) -> SelectorObservation:
    _exact(payload, {"generation", "revision", "fence"}, record)
    return SelectorObservation(
        generation=_identity(payload, "generation", record),
        revision=_integer(payload, "revision", record),
        fence=_integer(payload, "fence", record),
    )


def _axes(payload: dict[str, Any], record: EvidenceRecord) -> LayoutStatusAxes:
    keys = {
        "migration_state",
        "execution_state",
        "failure_class",
        "rollback_state",
        "startup_state",
        "reconciliation_state",
    }
    _exact(payload, keys, record)
    return LayoutStatusAxes(**{key: _string(payload, key, record) for key in keys})


def _phase_list(payload: dict[str, Any], record: EvidenceRecord) -> tuple[str, ...]:
    value = payload.get("phases")
    if not isinstance(value, list) or not value or len(value) > len(_PHASES):
        _fail(record, "layout.status.phase_order", "Migration phases are missing or unbounded.")
    assert isinstance(value, list)
    if not all(isinstance(item, str) and item in _PHASES for item in value):
        _fail(record, "layout.status.phase_order", "Migration phases contain unknown values.")
    phases = tuple(value)
    verified = _PHASES[:5]
    failed_prefixes = tuple((*_PHASES[:index], "failed") for index in range(1, 5))
    rollback_prefixes = tuple(
        (*prefix, "rollback_prepared", "rollback_selector_committed", "rollback_verified")
        for prefix in failed_prefixes
    )
    if phases != verified and phases not in failed_prefixes and phases not in rollback_prefixes:
        _fail(record, "layout.status.phase_order", "Migration phases omit or reorder receipts.")
    return phases


def _object(payload: dict[str, Any], keys: set[str], record: EvidenceRecord) -> dict[str, Any]:
    _exact(payload, keys, record)
    return payload


def _mapping(payload: dict[str, Any], key: str, record: EvidenceRecord) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        _fail(record, "layout.status.evidence_shape", f"{key} must be an object.")
    return value


def _exact(payload: dict[str, Any], keys: set[str], record: EvidenceRecord) -> None:
    if set(payload) != keys:
        _fail(
            record,
            "layout.status.evidence_shape",
            "Evidence payload has missing or unknown fields.",
        )


def _expect_type(record: EvidenceRecord, expected: str) -> None:
    if record.record_type != expected:
        _fail(record, "layout.status.record_type", f"Expected {expected} evidence.")


def _string(
    payload: dict[str, Any], key: str, record: EvidenceRecord, *, maximum: int = 256
) -> str:
    value = payload.get(key)
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or contains_unsafe_text(value)
    ):
        _fail(record, "layout.status.evidence_shape", f"{key} must be a bounded string.")
    return value


def _optional_string(
    payload: dict[str, Any], key: str, record: EvidenceRecord, *, maximum: int
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return _string(payload, key, record, maximum=maximum)


def _identity(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = _string(payload, key, record)
    if not _IDENTITY_RE.fullmatch(value) or value in {"latest", "current"}:
        _fail(record, "layout.status.identity", f"{key} is not an immutable identity.")
    return value


def _optional_identity(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str | None:
    if payload.get(key) is None:
        return None
    return _identity(payload, key, record)


def _identity_list(
    payload: dict[str, Any], key: str, record: EvidenceRecord, *, maximum: int
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or len(value) > maximum:
        _fail(record, "layout.status.evidence_shape", f"{key} must be a bounded list.")
    assert isinstance(value, list)
    result = tuple(_identity({key: item}, key, record) for item in value)
    if result != tuple(sorted(set(result))):
        _fail(record, "layout.status.evidence_shape", f"{key} must be sorted and unique.")
    return result


def _bounded_string_list(
    payload: dict[str, Any],
    key: str,
    record: EvidenceRecord,
    *,
    maximum: int,
    item_maximum: int,
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or len(value) > maximum:
        _fail(record, "layout.status.evidence_shape", f"{key} must be a bounded list.")
    result = tuple(_string({key: item}, key, record, maximum=item_maximum) for item in value)
    if result != tuple(sorted(set(result))):
        _fail(record, "layout.status.evidence_shape", f"{key} must be sorted and unique.")
    return result


def _scope(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = _string(payload, key, record)
    if not _SCOPE_RE.fullmatch(value):
        _fail(record, "layout.status.scope", f"{key} is not a closed selector scope.")
    return value


def _check_state(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = _string(payload, key, record)
    if value not in {"passed", "failed", "unavailable"}:
        _fail(record, "layout.status.check_state", f"{key} uses an unknown check state.")
    return value


def _digest(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = _string(payload, key, record)
    if not _DIGEST_RE.fullmatch(value):
        _fail(record, "layout.status.digest", f"{key} is not a complete SHA-256 digest.")
    return value


def _optional_digest(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str | None:
    if payload.get(key) is None:
        return None
    return _digest(payload, key, record)


def _digest_list(payload: dict[str, Any], key: str, record: EvidenceRecord) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or len(value) > 64:
        _fail(record, "layout.status.evidence_shape", f"{key} must be a bounded list.")
    assert isinstance(value, list)
    result = tuple(_digest({key: item}, key, record) for item in value)
    if result != tuple(sorted(set(result))):
        _fail(record, "layout.status.evidence_shape", f"{key} must be sorted and unique.")
    return result


def _ordered_digest_list(
    payload: dict[str, Any], key: str, record: EvidenceRecord
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or len(value) > 64:
        _fail(record, "layout.status.evidence_shape", f"{key} must be a bounded list.")
    result = tuple(_digest({key: item}, key, record) for item in value)
    if len(set(result)) != len(result):
        _fail(record, "layout.status.evidence_shape", f"{key} must not contain duplicates.")
    return result


def _commit(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = _string(payload, key, record)
    if not _COMMIT_RE.fullmatch(value):
        _fail(record, "layout.status.commit", f"{key} is not a full commit identity.")
    return value


def _integer(
    payload: dict[str, Any],
    key: str,
    record: EvidenceRecord,
    *,
    minimum: int = 0,
    maximum: int = 2**63 - 1,
) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail(record, "layout.status.evidence_shape", f"{key} is outside its integer bound.")
    return value


def _optional_integer(
    payload: dict[str, Any],
    key: str,
    record: EvidenceRecord,
    *,
    minimum: int,
) -> int | None:
    if payload.get(key) is None:
        return None
    return _integer(payload, key, record, minimum=minimum)


def _boolean(payload: dict[str, Any], key: str, record: EvidenceRecord) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        _fail(record, "layout.status.evidence_shape", f"{key} must be boolean.")
    return value


def _utc_timestamp(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = _string(payload, key, record)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise invalid(
            "layout.status.timestamp",
            f"{key} must be an ISO-8601 UTC timestamp.",
            record=record.path,
        ) from exc
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        _fail(record, "layout.status.timestamp", f"{key} must be an explicit UTC timestamp.")
    return value


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _content_digest(payload: dict[str, Any], digest_key: str) -> str:
    content = dict(payload)
    content.pop(digest_key)
    return "sha256:" + hashlib.sha256(canonical_json(content)).hexdigest()


def _fail(record: EvidenceRecord, code: str, message: str) -> NoReturn:
    raise invalid(code, message, record=record.path)


__all__ = [
    "ConsumerInventorySnapshot",
    "LayoutSelectorSnapshotV1",
    "MigrationEvidenceRef",
    "ModuleAuthoritySnapshot",
    "OperationStatusSnapshotV1",
    "PackageGenerationSnapshot",
    "PreparedEvidenceRef",
    "ProcessReceipt",
    "ProcessSnapshot",
    "RollbackSnapshot",
    "SelectorObservation",
    "ShutdownSnapshot",
    "ValidationReportSnapshot",
    "parse_authority",
    "parse_inventory",
    "parse_migration",
    "parse_operation",
    "parse_package",
    "parse_prepared",
    "parse_selector",
    "parse_validation_report",
]
