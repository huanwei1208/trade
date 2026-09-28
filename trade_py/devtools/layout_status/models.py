"""Immutable read models for package-layout evidence."""

from __future__ import annotations

from dataclasses import dataclass

from trade_py.devtools.layout_status.constraints import LayoutStatusAxes


@dataclass(frozen=True)
class ConsumerInventorySnapshot:
    record_digest: str
    schema_version: int
    source_commit: str
    tree_digest: str
    scanner_name: str
    scanner_version: str
    scanner_source_digest: str
    included_roots: tuple[str, ...]
    explicit_exclusions: tuple[str, ...]
    rules_digest: str
    generated_at: str
    max_age_seconds: int
    completeness_state: str
    production_module_count: int
    consumer_count: int
    unclassified_consumer_count: int
    entry_digest: str
    report_digest: str


@dataclass(frozen=True)
class ModuleAuthoritySnapshot:
    record_digest: str
    legacy_module: str
    target_module: str
    owner: str
    contract_generation: str
    implementation_digest: str
    compatibility_direction: str
    state: str
    consumer_inventory_ref: str
    activation_plan_digest: str


@dataclass(frozen=True)
class PackageGenerationSnapshot:
    record_digest: str
    distribution_name: str
    distribution_version: str
    python_tag: str
    platform_tag: str
    wheel_digest: str
    wheel_member_digest: str
    wheel_member_count: int
    compatibility_manifest_digest: str


@dataclass(frozen=True)
class ValidationReportSnapshot:
    record_digest: str
    source_commit: str
    source_tree_digest: str
    package_generation_ref: str
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
    report_entries_digest: str
    report_digest: str


@dataclass(frozen=True)
class PreparedEvidenceRef:
    record_digest: str
    operation_id: str
    attempt_id: str
    scope: str
    source_commit: str
    source_tree_digest: str
    policy_digest: str
    approved_design_digest: str
    activation_plan_digest: str
    current_composition_digest: str
    immutable_input_refs: tuple[str, ...]
    intended_target_generation: str
    expected_generation: str
    expected_revision: int
    expected_fence: int
    deployment_unit: str
    invocation_token: str
    command_digests: tuple[str, ...]
    prepared_at: str


@dataclass(frozen=True)
class LayoutSelectorSnapshotV1:
    record_digest: str
    scope: str
    generation: str
    revision: int
    fence: int
    operation_id: str
    plan_digest: str
    prepared_evidence_ref: str
    predecessor_generation: str
    predecessor_revision: int
    selector_payload_digest: str


@dataclass(frozen=True)
class ProcessReceipt:
    receipt_id: str
    receipt_type: str
    observed_at: str
    operation_id: str
    attempt_id: str
    deployment_unit: str
    invocation_token: str
    generation: str
    revision: int
    fence: int
    supersedes_receipt_id: str | None
    live_descendant_count: int


@dataclass(frozen=True)
class ProcessSnapshot:
    deployment_unit: str
    invocation_token: str
    generation: str
    revision: int
    fence: int
    matching_live_instances: int
    zero_live_descendants: bool
    receipts: tuple[ProcessReceipt, ...]


@dataclass(frozen=True)
class ShutdownSnapshot:
    stage: str
    signal_escalation: str
    residual_process_count: int
    residual_thread_count: int
    forced_exit_receipt: bool
    complete: bool


@dataclass(frozen=True)
class RollbackSnapshot:
    plan_scope: str
    target_generation: str | None
    later_accepted_slices: bool
    target_is_historical_predecessor: bool
    compensation_preserves_later_slices: bool


@dataclass(frozen=True)
class OperationStatusSnapshotV1:
    record_digest: str
    operation_id: str
    attempt_id: str
    scope: str
    activation_phase: str
    axes: LayoutStatusAxes
    operator_action: str
    tool_exit_code: int | None
    partial_evidence_ref: str | None
    stopped_early: bool
    stop_reason: str | None
    failure_detail: str | None
    degraded_components: tuple[str, ...]
    process: ProcessSnapshot
    shutdown: ShutdownSnapshot
    rollback: RollbackSnapshot


@dataclass(frozen=True)
class SelectorObservation:
    generation: str
    revision: int
    fence: int


@dataclass(frozen=True)
class MigrationEvidenceRef:
    record_digest: str
    operation_id: str
    attempt_id: str
    scope: str
    source_commit: str
    source_tree_digest: str
    policy_digest: str
    approved_design_digest: str
    consumer_inventory_ref: str
    module_authority_ref: str
    artifact_refs: tuple[str, ...]
    activation_plan_digest: str
    prepared_evidence_ref: str
    operation_status_ref: str
    selector_before: SelectorObservation
    selector_after: SelectorObservation
    phases: tuple[str, ...]
    terminal_outcome: str
    command_digests: tuple[str, ...]
    toolchain: tuple[str, ...]
    deadline_milliseconds: int
    typed_outcomes: LayoutStatusAxes
    partial_evidence_refs: tuple[str, ...]
    report_entries_digest: str


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
]
