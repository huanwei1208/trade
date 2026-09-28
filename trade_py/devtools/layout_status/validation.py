"""Cross-record validation for immutable layout status evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final, NoReturn

from trade_py.devtools.layout_status.constraints import (
    Classification,
    ConstraintFacts,
    ConstraintResult,
    LayoutStatusConstraintsV1,
)
from trade_py.devtools.layout_status.deadline import InvocationDeadline
from trade_py.devtools.layout_status.errors import invalid
from trade_py.devtools.layout_status.models import ProcessReceipt
from trade_py.devtools.layout_status.records import (
    EvidenceGraph,
    EvidenceRecord,
    contains_unsafe_text,
)
from trade_py.devtools.layout_status.schema import (
    ConsumerInventorySnapshot,
    LayoutSelectorSnapshotV1,
    MigrationEvidenceRef,
    ModuleAuthoritySnapshot,
    OperationStatusSnapshotV1,
    PackageGenerationSnapshot,
    PreparedEvidenceRef,
    ValidationReportSnapshot,
    parse_authority,
    parse_inventory,
    parse_migration,
    parse_operation,
    parse_package,
    parse_prepared,
    parse_selector,
    parse_validation_report,
)

_MANIFEST_KEYS: Final = {
    "scope",
    "selected_generation",
    "prior_generation",
    "selected_revision",
    "selected_fence",
    "wheel_digest",
    "wheel_member_count",
    "legacy_module_origin",
    "target_module_origin",
    "selected_authority",
    "source_commit",
    "source_tree_digest",
    "inventory_scanner_digest",
    "inventory_rules_digest",
    "inventory_completeness",
    "inventory_age_seconds",
    "missing_consumers",
    "duplicate_consumers",
    "reverse_dependencies",
    "unclassified_consumers",
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
    "bridge_owner",
    "bridge_population_digest",
    "bridge_coverage_state",
    "bridge_age_seconds",
    "bridge_last_observed_use",
    "bridge_deadline",
    "selector_ref",
    "operation_ref",
    "prepared_evidence_ref",
    "migration_evidence_ref",
}
_IDENTITY_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


@dataclass(frozen=True)
class LayoutStatusSummary:
    scope: str
    selected_generation: str
    prior_generation: str
    selected_revision: int
    selected_fence: int
    wheel_digest: str
    wheel_member_count: int
    legacy_module_origin: str
    target_module_origin: str
    selected_authority: str
    source_commit: str
    source_tree_digest: str
    inventory_scanner_digest: str
    inventory_rules_digest: str
    inventory_completeness: str
    inventory_age_seconds: int
    missing_consumers: int
    duplicate_consumers: int
    reverse_dependencies: int
    unclassified_consumers: int
    root_console_parity: str
    asgi_import_state: str
    reload_child_import_state: str
    route_parity_state: str
    openapi_parity_state: str
    sse_parity_state: str
    capability_parity_state: str
    web_build_digest: str | None
    web_missing_asset_count: int
    native_capability_state: str
    native_build_state: str
    native_differential_state: str
    notebook_state: str
    bridge_owner: str
    bridge_population_digest: str
    bridge_coverage_state: str
    bridge_age_seconds: int | None
    bridge_last_observed_use: str | None
    bridge_deadline: str


@dataclass(frozen=True)
class ValidatedLayoutStatus:
    summary: LayoutStatusSummary
    inventory: ConsumerInventorySnapshot
    authority: ModuleAuthoritySnapshot
    package: PackageGenerationSnapshot
    validation_report: ValidationReportSnapshot
    selector: LayoutSelectorSnapshotV1
    operation: OperationStatusSnapshotV1
    prepared: PreparedEvidenceRef
    migration: MigrationEvidenceRef | None
    constraints: ConstraintResult
    record_count: int
    aggregate_bytes: int


def validate_graph(
    graph: EvidenceGraph,
    *,
    deadline: InvocationDeadline | None = None,
) -> ValidatedLayoutStatus:
    _check_deadline(deadline)
    manifest = _manifest(graph.root)
    summary = _summary(manifest, graph.root)
    references = {item.name: item.digest for item in graph.root.references}
    required = {
        "inventory",
        "authority",
        "package",
        "validation_report",
        "selector",
        "operation",
        "prepared",
    }
    reference_names = set(references)
    if reference_names != required and reference_names != required | {"migration"}:
        _fail(
            graph.root,
            "layout.status.manifest_references",
            (
                "Manifest must reference inventory, authority, package, validation report, "
                "selector, operation, prepared, and optional migration records."
            ),
        )

    inventory = parse_inventory(graph.by_digest(references["inventory"]))
    authority = parse_authority(graph.by_digest(references["authority"]))
    package = parse_package(graph.by_digest(references["package"]))
    validation_report = parse_validation_report(graph.by_digest(references["validation_report"]))
    _match_manifest_reference(manifest, "selector_ref", references["selector"], graph.root)
    _match_manifest_reference(manifest, "operation_ref", references["operation"], graph.root)
    _match_manifest_reference(manifest, "prepared_evidence_ref", references["prepared"], graph.root)
    migration_digest = references.get("migration")
    manifest_migration = manifest["migration_evidence_ref"]
    if migration_digest is None:
        if manifest_migration is not None:
            _fail(
                graph.root,
                "layout.status.manifest_references",
                "Manifest names migration evidence without an explicit reference.",
            )
    else:
        _match_manifest_reference(manifest, "migration_evidence_ref", migration_digest, graph.root)

    selector = parse_selector(graph.by_digest(references["selector"]))
    operation = parse_operation(graph.by_digest(references["operation"]))
    prepared = parse_prepared(graph.by_digest(references["prepared"]))
    migration = (
        parse_migration(graph.by_digest(migration_digest)) if migration_digest is not None else None
    )
    _check_deadline(deadline)
    facts = _cross_record_facts(
        summary,
        inventory,
        authority,
        package,
        validation_report,
        selector,
        operation,
        prepared,
        migration,
    )
    constraints = LayoutStatusConstraintsV1.evaluate(
        operation.axes,
        supplied_action=operation.operator_action,
        facts=facts,
        additional_classifications=_summary_classifications(
            summary,
            inventory,
            authority,
            validation_report,
            prepared,
            operation,
        ),
    )
    if constraints.exit_code == 2 and not constraints.violations:
        _fail(
            graph.root,
            "layout.status.constraints",
            "Layout status constraints rejected evidence without a typed violation.",
        )
    _validate_manifest_identity(
        summary,
        inventory,
        authority,
        package,
        validation_report,
        selector,
        prepared,
        operation,
        graph.root,
    )
    _check_deadline(deadline)
    return ValidatedLayoutStatus(
        summary=summary,
        inventory=inventory,
        authority=authority,
        package=package,
        validation_report=validation_report,
        selector=selector,
        operation=operation,
        prepared=prepared,
        migration=migration,
        constraints=constraints,
        record_count=len(graph.records),
        aggregate_bytes=graph.aggregate_bytes,
    )


def _cross_record_facts(
    summary: LayoutStatusSummary,
    inventory: ConsumerInventorySnapshot,
    authority: ModuleAuthoritySnapshot,
    package: PackageGenerationSnapshot,
    validation_report: ValidationReportSnapshot,
    selector: LayoutSelectorSnapshotV1,
    operation: OperationStatusSnapshotV1,
    prepared: PreparedEvidenceRef,
    migration: MigrationEvidenceRef | None,
) -> ConstraintFacts:
    receipt_identities_match = _receipt_identities_match(operation, prepared)
    identities_match = (
        selector.operation_id == operation.operation_id == prepared.operation_id
        and operation.attempt_id == prepared.attempt_id
        and selector.scope == operation.scope == prepared.scope
        and selector.plan_digest == prepared.activation_plan_digest
        and selector.prepared_evidence_ref == prepared.record_digest
        and selector.predecessor_generation == prepared.expected_generation
        and selector.predecessor_revision == prepared.expected_revision
        and selector.fence == prepared.expected_fence + 1
        and selector.generation == prepared.intended_target_generation
        and operation.process.deployment_unit == prepared.deployment_unit
        and operation.process.invocation_token == prepared.invocation_token
        and operation.rollback.plan_scope == selector.scope
        and inventory.record_digest in prepared.immutable_input_refs
        and authority.record_digest in prepared.immutable_input_refs
        and package.record_digest in prepared.immutable_input_refs
        and validation_report.record_digest in prepared.immutable_input_refs
        and authority.consumer_inventory_ref == inventory.record_digest
        and authority.activation_plan_digest == prepared.activation_plan_digest
        and receipt_identities_match
    )
    if operation.axes.reconciliation_state == "fenced_teardown":
        identities_match = identities_match and (
            operation.process.fence < selector.fence
            and operation.process.generation == selector.predecessor_generation
            and operation.process.revision == selector.predecessor_revision
        )
    else:
        identities_match = identities_match and (
            operation.process.generation == selector.generation
            and operation.process.revision == selector.revision
            and operation.process.fence == selector.fence
        )
    phases_ordered = _phase_consistency(operation, migration)
    receipts_valid = _receipt_consistency(
        operation,
        migration,
        prepared,
    ) and _operation_consistency(operation)
    rollback_target_valid = _rollback_consistency(operation, selector)
    if migration is not None:
        identities_match = identities_match and (
            migration.operation_id == operation.operation_id
            and migration.attempt_id == operation.attempt_id
            and migration.scope == operation.scope
            and migration.prepared_evidence_ref == prepared.record_digest
            and migration.operation_status_ref == operation.record_digest
            and migration.consumer_inventory_ref == inventory.record_digest
            and migration.module_authority_ref == authority.record_digest
            and package.record_digest in migration.artifact_refs
            and migration.report_entries_digest == validation_report.report_entries_digest
            and migration.activation_plan_digest == selector.plan_digest
            and migration.source_commit == prepared.source_commit
            and migration.source_tree_digest == prepared.source_tree_digest
            and migration.policy_digest == prepared.policy_digest
            and migration.approved_design_digest == prepared.approved_design_digest
            and migration.selector_before.generation == selector.predecessor_generation
            and migration.selector_before.revision == selector.predecessor_revision
            and migration.selector_before.fence == prepared.expected_fence
            and migration.selector_after.generation == selector.generation
            and migration.selector_after.revision == selector.revision
            and migration.selector_after.fence == selector.fence
            and migration.typed_outcomes == operation.axes
            and migration.command_digests == prepared.command_digests
            and (
                operation.partial_evidence_ref is None
                or operation.partial_evidence_ref in migration.partial_evidence_refs
            )
        )
    return ConstraintFacts(
        receipts_valid=receipts_valid,
        identities_match=identities_match,
        phases_ordered=phases_ordered,
        rollback_target_valid=rollback_target_valid,
    )


def _phase_consistency(
    operation: OperationStatusSnapshotV1,
    migration: MigrationEvidenceRef | None,
) -> bool:
    if migration is None:
        return operation.activation_phase not in {
            "verified",
            "failed",
            "rollback_verified",
        } and operation.axes.migration_state not in {"target_authoritative", "retireable"}
    if operation.activation_phase != migration.phases[-1]:
        return False
    if migration.terminal_outcome == "verified":
        return (
            operation.axes.execution_state == "passed"
            and operation.axes.failure_class == "none"
            and operation.axes.rollback_state == "not_required"
            and operation.axes.startup_state in {"started_healthy", "started_degraded"}
        )
    if migration.terminal_outcome == "failed":
        return (
            operation.axes.execution_state in {"failed", "stopped"}
            and (
                operation.axes.failure_class != "none"
                or operation.axes.reconciliation_state == "fenced_teardown"
            )
            and operation.axes.migration_state not in {"target_authoritative", "retireable"}
        )
    return (
        migration.terminal_outcome == "rolled_back"
        and operation.axes.execution_state in {"failed", "stopped"}
        and operation.axes.failure_class != "none"
        and operation.axes.rollback_state == "succeeded"
        and operation.axes.migration_state not in {"target_authoritative", "retireable"}
    )


def _receipt_consistency(
    operation: OperationStatusSnapshotV1,
    migration: MigrationEvidenceRef | None,
    prepared: PreparedEvidenceRef,
) -> bool:
    process = operation.process
    shutdown = operation.shutdown
    reconciliation = operation.axes.reconciliation_state
    if not _shutdown_consistency(operation):
        return False
    if (
        operation.axes.startup_state in {"started_healthy", "started_degraded"}
        and process.matching_live_instances != 1
    ):
        return False
    if operation.axes.startup_state in {"started_healthy", "started_degraded"} and (
        shutdown.stage != "not_started"
        or shutdown.signal_escalation != "none"
        or shutdown.residual_process_count != 0
        or shutdown.residual_thread_count != 0
        or shutdown.forced_exit_receipt
        or shutdown.complete
        or process.zero_live_descendants
    ):
        return False
    if operation.axes.failure_class == "process_cleanup_incomplete" and (
        shutdown.complete
        or (shutdown.residual_process_count == 0 and shutdown.residual_thread_count == 0)
    ):
        return False
    receipts = process.receipts
    starts = tuple(item for item in receipts if item.receipt_type == "process_started")
    absences = tuple(item for item in receipts if item.receipt_type == "terminal_absence")
    teardowns = tuple(item for item in receipts if item.receipt_type == "teardown")
    if any(_parse_utc(item.observed_at) <= _parse_utc(prepared.prepared_at) for item in receipts):
        return False
    start_recorded = (
        "process_started" in migration.phases
        if migration is not None
        else operation.activation_phase == "process_started"
    )
    if (start_recorded and len(starts) != 1) or (not start_recorded and starts):
        return False
    if operation.activation_phase in {
        "prepared",
        "selector_committed",
        "start_intent_recorded",
    } and (starts or teardowns or process.matching_live_instances != 0):
        return False
    if operation.activation_phase == "verified" and (
        migration is None
        or migration.terminal_outcome != "verified"
        or len(starts) != 1
        or process.matching_live_instances != 1
    ):
        return False
    if reconciliation == "adopted":
        return (
            len(starts) == 1
            and not absences
            and not teardowns
            and process.matching_live_instances == 1
            and operation.activation_phase in {"process_started", "verified"}
        )
    if reconciliation == "absence_proved":
        if (
            process.matching_live_instances != 0
            or not process.zero_live_descendants
            or len(absences) != 1
            or teardowns
        ):
            return False
        if not starts:
            return (
                absences[0].supersedes_receipt_id is None and absences[0].live_descendant_count == 0
            )
        return _terminal_supersedes_start(
            starts[0],
            absences[0],
        )
    if reconciliation == "fenced_teardown":
        return (
            len(teardowns) == 1
            and not absences
            and (
                _terminal_without_start(teardowns[0])
                if not starts
                else _terminal_supersedes_start(starts[0], teardowns[0])
            )
            and process.matching_live_instances == 0
            and process.zero_live_descendants
            and shutdown.complete
            and shutdown.residual_process_count == 0
            and shutdown.residual_thread_count == 0
        )
    if operation.activation_phase == "verified":
        return len(starts) == 1 and not absences and not teardowns
    if migration is not None and migration.terminal_outcome == "rolled_back":
        return (
            not absences
            and len(teardowns) == 1
            and (
                _terminal_without_start(teardowns[0])
                if not starts
                else _terminal_supersedes_start(starts[0], teardowns[0])
            )
            and process.matching_live_instances == 0
            and process.zero_live_descendants
            and shutdown.complete
        )
    return not absences and not teardowns


def _shutdown_consistency(operation: OperationStatusSnapshotV1) -> bool:
    shutdown = operation.shutdown
    process = operation.process
    if shutdown.stage == "not_started":
        return (
            shutdown.signal_escalation == "none"
            and shutdown.residual_process_count == 0
            and shutdown.residual_thread_count == 0
            and not shutdown.forced_exit_receipt
            and not shutdown.complete
        )
    if shutdown.stage == "term":
        return (
            shutdown.signal_escalation == "term"
            and not shutdown.forced_exit_receipt
            and not shutdown.complete
        )
    if shutdown.stage == "kill":
        return (
            shutdown.signal_escalation == "term_kill"
            and shutdown.forced_exit_receipt
            and not shutdown.complete
        )
    return (
        shutdown.stage == "complete"
        and shutdown.signal_escalation in {"term", "term_kill"}
        and shutdown.forced_exit_receipt == (shutdown.signal_escalation == "term_kill")
        and shutdown.residual_process_count == 0
        and shutdown.residual_thread_count == 0
        and shutdown.complete
        and process.matching_live_instances == 0
    )


def _terminal_without_start(terminal: ProcessReceipt) -> bool:
    return terminal.supersedes_receipt_id is None and terminal.live_descendant_count == 0


def _terminal_supersedes_start(start: ProcessReceipt, terminal: ProcessReceipt) -> bool:
    return (
        terminal.supersedes_receipt_id == start.receipt_id
        and terminal.live_descendant_count == 0
        and _parse_utc(terminal.observed_at) > _parse_utc(start.observed_at)
    )


def _operation_consistency(operation: OperationStatusSnapshotV1) -> bool:
    axes = operation.axes
    if axes.execution_state == "passed" and (
        operation.tool_exit_code != 0
        or operation.stopped_early
        or operation.stop_reason is not None
        or operation.failure_detail is not None
    ):
        return False
    if axes.failure_class == "none":
        if operation.failure_detail is not None or operation.tool_exit_code not in {None, 0}:
            return False
    elif operation.failure_detail is None:
        return False
    if operation.stopped_early != (operation.stop_reason is not None):
        return False
    if axes.startup_state == "started_degraded":
        if not operation.degraded_components:
            return False
    elif operation.degraded_components:
        return False
    if axes.startup_state == "failed" and axes.failure_class == "none":
        return False
    return True


def _receipt_identities_match(
    operation: OperationStatusSnapshotV1,
    prepared: PreparedEvidenceRef,
) -> bool:
    process = operation.process
    for receipt in process.receipts:
        if (
            receipt.operation_id != operation.operation_id
            or receipt.attempt_id != operation.attempt_id
            or receipt.deployment_unit != process.deployment_unit
            or receipt.deployment_unit != prepared.deployment_unit
            or receipt.invocation_token != process.invocation_token
            or receipt.invocation_token != prepared.invocation_token
            or receipt.generation != process.generation
            or receipt.revision != process.revision
            or receipt.fence != process.fence
        ):
            return False
    return True


def _rollback_consistency(
    operation: OperationStatusSnapshotV1,
    selector: LayoutSelectorSnapshotV1,
) -> bool:
    rollback = operation.rollback
    if operation.axes.rollback_state == "not_required":
        return rollback.target_generation is None
    if rollback.target_generation is None:
        return False
    if (
        operation.axes.rollback_state == "succeeded"
        and rollback.target_generation != selector.generation
    ):
        return False
    if operation.scope == "python_deployment" and rollback.later_accepted_slices:
        return (
            not rollback.target_is_historical_predecessor
            and rollback.compensation_preserves_later_slices
        )
    return True


def _summary_classifications(
    summary: LayoutStatusSummary,
    inventory: ConsumerInventorySnapshot,
    authority: ModuleAuthoritySnapshot,
    validation_report: ValidationReportSnapshot,
    prepared: PreparedEvidenceRef,
    operation: OperationStatusSnapshotV1,
) -> tuple[tuple[str, Classification], ...]:
    generated = _parse_utc(inventory.generated_at)
    prepared_at = _parse_utc(prepared.prepared_at)
    age_seconds = int((prepared_at - generated).total_seconds())
    inventory_classification: Classification = (
        "healthy"
        if (
            inventory.completeness_state == "complete"
            and inventory.unclassified_consumer_count == 0
            and 0 <= age_seconds <= inventory.max_age_seconds <= 86_400
            and summary.inventory_completeness == inventory.completeness_state
            and summary.inventory_age_seconds == age_seconds
        )
        else "invalid"
    )
    authority_classification: Classification = (
        "healthy" if authority.state == operation.axes.migration_state else "invalid"
    )
    consumers = (
        "healthy"
        if (
            summary.missing_consumers
            + summary.duplicate_consumers
            + summary.reverse_dependencies
            + summary.unclassified_consumers
        )
        == 0
        else "valid_attention"
    )
    parity_values = (
        validation_report.root_console_parity,
        validation_report.asgi_import_state,
        validation_report.reload_child_import_state,
        validation_report.route_parity_state,
        validation_report.openapi_parity_state,
        validation_report.sse_parity_state,
        validation_report.capability_parity_state,
        validation_report.native_capability_state,
        validation_report.native_build_state,
        validation_report.native_differential_state,
        validation_report.notebook_state,
    )
    parity = "healthy" if all(item == "passed" for item in parity_values) else "valid_attention"
    web = (
        "healthy"
        if (
            validation_report.web_build_digest is not None
            and validation_report.web_missing_asset_count == 0
        )
        else "valid_attention"
    )
    bridge: Classification = (
        "valid_attention" if summary.bridge_coverage_state == "unavailable" else "invalid"
    )
    return (
        ("inventory", inventory_classification),
        ("authority", authority_classification),
        ("consumers", consumers),
        ("compatibility", parity),
        ("web_assets", web),
        ("bridge_coverage", bridge),
    )


def _validate_manifest_identity(
    summary: LayoutStatusSummary,
    inventory: ConsumerInventorySnapshot,
    authority: ModuleAuthoritySnapshot,
    package: PackageGenerationSnapshot,
    validation_report: ValidationReportSnapshot,
    selector: LayoutSelectorSnapshotV1,
    prepared: PreparedEvidenceRef,
    operation: OperationStatusSnapshotV1,
    record: EvidenceRecord,
) -> None:
    if (
        summary.scope != selector.scope
        or summary.selected_generation != selector.generation
        or summary.prior_generation != selector.predecessor_generation
        or summary.selected_revision != selector.revision
        or summary.selected_fence != selector.fence
        or summary.source_commit != prepared.source_commit
        or summary.source_tree_digest != prepared.source_tree_digest
        or inventory.source_commit != summary.source_commit
        or inventory.tree_digest != summary.source_tree_digest
        or inventory.scanner_source_digest != summary.inventory_scanner_digest
        or inventory.rules_digest != summary.inventory_rules_digest
        or authority.legacy_module != summary.legacy_module_origin
        or authority.target_module != summary.target_module_origin
        or authority.target_module != summary.selected_authority
        or package.wheel_digest != summary.wheel_digest
        or package.wheel_member_count != summary.wheel_member_count
        or validation_report.source_commit != summary.source_commit
        or validation_report.source_tree_digest != summary.source_tree_digest
        or validation_report.package_generation_ref != package.record_digest
        or validation_report.root_console_parity != summary.root_console_parity
        or validation_report.asgi_import_state != summary.asgi_import_state
        or validation_report.reload_child_import_state != summary.reload_child_import_state
        or validation_report.route_parity_state != summary.route_parity_state
        or validation_report.openapi_parity_state != summary.openapi_parity_state
        or validation_report.sse_parity_state != summary.sse_parity_state
        or validation_report.capability_parity_state != summary.capability_parity_state
        or validation_report.web_build_digest != summary.web_build_digest
        or validation_report.web_missing_asset_count != summary.web_missing_asset_count
        or validation_report.native_capability_state != summary.native_capability_state
        or validation_report.native_build_state != summary.native_build_state
        or validation_report.native_differential_state != summary.native_differential_state
        or validation_report.notebook_state != summary.notebook_state
        or operation.scope != summary.scope
    ):
        _fail(
            record,
            "layout.status.manifest_identity",
            "Manifest identity does not match selected immutable evidence.",
        )


def _manifest(record: EvidenceRecord) -> dict[str, Any]:
    if set(record.payload) != _MANIFEST_KEYS:
        _fail(
            record,
            "layout.status.manifest_shape",
            "Layout status manifest has missing or unknown fields.",
        )
    return record.payload


def _summary(payload: dict[str, Any], record: EvidenceRecord) -> LayoutStatusSummary:
    return LayoutStatusSummary(
        scope=_string(payload, "scope", record),
        selected_generation=_string(payload, "selected_generation", record),
        prior_generation=_string(payload, "prior_generation", record),
        selected_revision=_integer(payload, "selected_revision", record),
        selected_fence=_integer(payload, "selected_fence", record),
        wheel_digest=_digest(payload, "wheel_digest", record),
        wheel_member_count=_integer(payload, "wheel_member_count", record),
        legacy_module_origin=_identity(payload, "legacy_module_origin", record),
        target_module_origin=_identity(payload, "target_module_origin", record),
        selected_authority=_identity(payload, "selected_authority", record),
        source_commit=_commit(payload, "source_commit", record),
        source_tree_digest=_digest(payload, "source_tree_digest", record),
        inventory_scanner_digest=_digest(payload, "inventory_scanner_digest", record),
        inventory_rules_digest=_digest(payload, "inventory_rules_digest", record),
        inventory_completeness=_enum(
            payload,
            "inventory_completeness",
            {"complete", "incomplete", "tool_failed", "over_budget"},
            record,
        ),
        inventory_age_seconds=_integer(payload, "inventory_age_seconds", record),
        missing_consumers=_integer(payload, "missing_consumers", record),
        duplicate_consumers=_integer(payload, "duplicate_consumers", record),
        reverse_dependencies=_integer(payload, "reverse_dependencies", record),
        unclassified_consumers=_integer(payload, "unclassified_consumers", record),
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
        bridge_owner=_identity(payload, "bridge_owner", record),
        bridge_population_digest=_digest(payload, "bridge_population_digest", record),
        bridge_coverage_state=_enum(
            payload,
            "bridge_coverage_state",
            {"complete", "partial", "unavailable", "stale"},
            record,
        ),
        bridge_age_seconds=_optional_integer(payload, "bridge_age_seconds", record),
        bridge_last_observed_use=_optional_timestamp(payload, "bridge_last_observed_use", record),
        bridge_deadline=_timestamp(payload, "bridge_deadline", record),
    )


def _match_manifest_reference(
    payload: dict[str, Any], key: str, expected: str, record: EvidenceRecord
) -> None:
    if payload.get(key) != expected:
        _fail(
            record,
            "layout.status.manifest_references",
            f"Manifest {key} does not match its explicit record reference.",
        )


def _string(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > 256 or contains_unsafe_text(value):
        _fail(record, "layout.status.manifest_shape", f"{key} must be a bounded string.")
    return value


def _identity(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = _string(payload, key, record)
    if not _IDENTITY_RE.fullmatch(value) or value in {"latest", "current"}:
        _fail(
            record,
            "layout.status.manifest_shape",
            f"{key} must be an immutable identity.",
        )
    return value


def _integer(payload: dict[str, Any], key: str, record: EvidenceRecord) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(
            record,
            "layout.status.manifest_shape",
            f"{key} must be a non-negative integer.",
        )
    return value


def _optional_integer(payload: dict[str, Any], key: str, record: EvidenceRecord) -> int | None:
    if payload.get(key) is None:
        return None
    return _integer(payload, key, record)


def _digest(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = _string(payload, key, record)
    if len(value) != 71 or not value.startswith("sha256:"):
        _fail(record, "layout.status.manifest_shape", f"{key} must be a SHA-256 digest.")
    try:
        int(value[7:], 16)
    except ValueError:
        _fail(record, "layout.status.manifest_shape", f"{key} must be a SHA-256 digest.")
    return value


def _optional_digest(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str | None:
    if payload.get(key) is None:
        return None
    return _digest(payload, key, record)


def _commit(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = _string(payload, key, record)
    if len(value) != 40:
        _fail(record, "layout.status.manifest_shape", f"{key} must be a full commit.")
    try:
        int(value, 16)
    except ValueError:
        _fail(record, "layout.status.manifest_shape", f"{key} must be a full commit.")
    return value


def _enum(
    payload: dict[str, Any],
    key: str,
    allowed: set[str],
    record: EvidenceRecord,
) -> str:
    value = _string(payload, key, record)
    if value not in allowed:
        _fail(record, "layout.status.manifest_shape", f"{key} uses an unknown value.")
    return value


def _check_state(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    return _enum(payload, key, {"passed", "failed", "unavailable"}, record)


def _timestamp(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str:
    value = _string(payload, key, record)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise invalid(
            "layout.status.manifest_shape",
            f"{key} must be an ISO-8601 UTC timestamp.",
            record=record.path,
        ) from exc
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        _fail(
            record,
            "layout.status.manifest_shape",
            f"{key} must be an explicit UTC timestamp.",
        )
    return value


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _check_deadline(deadline: InvocationDeadline | None) -> None:
    if deadline is not None:
        deadline.check()


def _optional_timestamp(payload: dict[str, Any], key: str, record: EvidenceRecord) -> str | None:
    if payload.get(key) is None:
        return None
    return _timestamp(payload, key, record)


def _fail(record: EvidenceRecord, code: str, message: str) -> NoReturn:
    raise invalid(code, message, record=record.path)


__all__ = [
    "LayoutStatusSummary",
    "ValidatedLayoutStatus",
    "validate_graph",
]
