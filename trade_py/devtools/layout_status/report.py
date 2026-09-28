"""One typed report and paired renderers for layout status."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

from trade_py.devtools.layout_status.deadline import InvocationDeadline
from trade_py.devtools.layout_status.errors import LayoutStatusError
from trade_py.devtools.layout_status.validation import ValidatedLayoutStatus

REPORT_SCHEMA = "trade.layout.status.v1"


@dataclass(frozen=True)
class RenderedLayoutStatus:
    output: str
    exit_code: int


def render_status(
    status: ValidatedLayoutStatus | None,
    *,
    error: LayoutStatusError | None = None,
    as_json: bool,
    deadline: InvocationDeadline | None = None,
) -> RenderedLayoutStatus:
    if (status is None) == (error is None):
        raise ValueError("Exactly one layout status or error is required")
    payload = _status_payload(status) if status is not None else _error_payload(error)
    if deadline is not None:
        deadline.check()
    exit_code = int(payload["exit_code"])
    if as_json:
        output = json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        if deadline is not None:
            deadline.check()
        return RenderedLayoutStatus(output + "\n", exit_code)
    output = _render_text(payload)
    if deadline is not None:
        deadline.check()
    return RenderedLayoutStatus(output, exit_code)


def _status_payload(status: ValidatedLayoutStatus) -> dict[str, Any]:
    result = status.constraints
    operation = status.operation
    evidence = {
        "consumer_inventory_ref": status.inventory.record_digest,
        "module_authority_ref": status.authority.record_digest,
        "package_generation_ref": status.package.record_digest,
        "validation_report_ref": status.validation_report.record_digest,
        "prepared_evidence_ref": status.prepared.record_digest,
        "migration_evidence_ref": (
            status.migration.record_digest if status.migration is not None else None
        ),
        "activation_plan_digest": status.prepared.activation_plan_digest,
        "partial_evidence_ref": operation.partial_evidence_ref,
    }
    return {
        "schema_version": REPORT_SCHEMA,
        "status": {
            "healthy": "HEALTHY",
            "valid_attention": "ATTENTION",
            "invalid": "INVALID",
        }[result.classification],
        "exit_code": result.exit_code,
        "summary": asdict(status.summary),
        "selector": asdict(status.selector),
        "operation": {
            "operation_id": operation.operation_id,
            "attempt_id": operation.attempt_id,
            "scope": operation.scope,
            "activation_phase": operation.activation_phase,
            "states": asdict(operation.axes),
            "operator_action": result.derived_action,
            "tool_exit_code": operation.tool_exit_code,
            "partial_evidence_ref": operation.partial_evidence_ref,
            "stopped_early": operation.stopped_early,
            "stop_reason": operation.stop_reason,
            "failure_detail": operation.failure_detail,
            "degraded_components": list(operation.degraded_components),
            "process": asdict(operation.process),
            "shutdown": asdict(operation.shutdown),
            "rollback": asdict(operation.rollback),
        },
        "evidence": evidence,
        "validation": {
            "classification": result.classification,
            "axis_classifications": dict(result.axis_classifications),
            "violations": list(result.violations),
            "record_count": status.record_count,
            "aggregate_bytes": status.aggregate_bytes,
            "stopped_early": operation.stopped_early,
            "stop_reason": operation.stop_reason,
        },
        "error": None,
    }


def _error_payload(error: LayoutStatusError | None) -> dict[str, Any]:
    assert error is not None
    return {
        "schema_version": REPORT_SCHEMA,
        "status": "INVALID",
        "exit_code": 2,
        "summary": None,
        "selector": None,
        "operation": None,
        "evidence": None,
        "validation": {
            "classification": "invalid",
            "axis_classifications": {},
            "violations": [error.code],
            "record_count": 0,
            "aggregate_bytes": 0,
            "stopped_early": True,
            "stop_reason": error.code,
        },
        "error": error.to_dict(),
    }


def _render_text(payload: dict[str, Any]) -> str:
    status = str(payload["status"])
    exit_code = int(payload["exit_code"])
    lines = [f"Layout status: {status} (exit {exit_code})"]
    error = payload["error"]
    if isinstance(error, dict):
        lines.append(f"Error: {error['code']}: {error['message']}")
        if error["record"] is not None:
            lines.append(f"Record: {error['record']}")
        return _terminal_safe_output("\n".join(lines) + "\n")

    summary = payload["summary"]
    selector = payload["selector"]
    operation = payload["operation"]
    evidence = payload["evidence"]
    validation = payload["validation"]
    assert isinstance(summary, dict)
    assert isinstance(selector, dict)
    assert isinstance(operation, dict)
    assert isinstance(evidence, dict)
    assert isinstance(validation, dict)
    states = operation["states"]
    process = operation["process"]
    shutdown = operation["shutdown"]
    rollback = operation["rollback"]
    assert isinstance(states, dict)
    assert isinstance(process, dict)
    assert isinstance(shutdown, dict)
    assert isinstance(rollback, dict)

    lines.extend(
        (
            (
                f"Selector: {selector['scope']} {selector['generation']} "
                f"revision={selector['revision']} fence={selector['fence']} "
                f"prior={selector['predecessor_generation']}"
            ),
            (
                f"Package: wheel={summary['wheel_digest']} "
                f"members={summary['wheel_member_count']} "
                f"authority={summary['selected_authority']}"
            ),
            (
                f"Origins: legacy={summary['legacy_module_origin']} "
                f"target={summary['target_module_origin']}"
            ),
            (
                f"Compatibility: console={summary['root_console_parity']} "
                f"asgi={summary['asgi_import_state']} "
                f"reload_child={summary['reload_child_import_state']} "
                f"route={summary['route_parity_state']} "
                f"openapi={summary['openapi_parity_state']} "
                f"sse={summary['sse_parity_state']} "
                f"capability={summary['capability_parity_state']}"
            ),
            (
                f"Web: build={summary['web_build_digest']} "
                f"missing_assets={summary['web_missing_asset_count']}"
            ),
            (
                f"Native: capability={summary['native_capability_state']} "
                f"build={summary['native_build_state']} "
                f"differential={summary['native_differential_state']} "
                f"notebook={summary['notebook_state']}"
            ),
            (f"Source: commit={summary['source_commit']} tree={summary['source_tree_digest']}"),
            (
                f"Inventory: {summary['inventory_completeness']} "
                f"age={summary['inventory_age_seconds']}s "
                f"missing={summary['missing_consumers']} "
                f"duplicate={summary['duplicate_consumers']} "
                f"reverse={summary['reverse_dependencies']} "
                f"unclassified={summary['unclassified_consumers']}"
            ),
            ("States: " + " ".join(f"{name}={value}" for name, value in states.items())),
            (
                f"Operation: id={operation['operation_id']} "
                f"attempt={operation['attempt_id']} "
                f"phase={operation['activation_phase']} "
                f"action={operation['operator_action']} "
                f"tool_exit={operation['tool_exit_code']}"
            ),
            (
                f"Outcome: failure={states['failure_class']} "
                f"detail={operation['failure_detail']} "
                f"degraded={','.join(operation['degraded_components']) or 'none'} "
                f"stopped_early={operation['stopped_early']} "
                f"reason={operation['stop_reason']}"
            ),
            (
                f"Process: unit={process['deployment_unit']} "
                f"live={process['matching_live_instances']} "
                f"zero_descendants={process['zero_live_descendants']} "
                f"generation={process['generation']} "
                f"revision={process['revision']} fence={process['fence']}"
            ),
            (
                "Receipts: "
                + (
                    ", ".join(
                        (
                            f"{receipt['receipt_type']}@{receipt['observed_at']}"
                            f"->{receipt['supersedes_receipt_id']}"
                        )
                        for receipt in process["receipts"]
                    )
                    or "none"
                )
            ),
            (
                f"Shutdown: stage={shutdown['stage']} "
                f"signals={shutdown['signal_escalation']} "
                f"residual_processes={shutdown['residual_process_count']} "
                f"residual_threads={shutdown['residual_thread_count']} "
                f"forced_exit={shutdown['forced_exit_receipt']} "
                f"complete={shutdown['complete']}"
            ),
            (
                f"Rollback: target={rollback['target_generation']} "
                f"later_slices={rollback['later_accepted_slices']} "
                f"historical={rollback['target_is_historical_predecessor']} "
                f"preserves_later={rollback['compensation_preserves_later_slices']}"
            ),
            (
                f"Evidence: plan={evidence['activation_plan_digest']} "
                f"inventory={evidence['consumer_inventory_ref']} "
                f"authority={evidence['module_authority_ref']} "
                f"package={evidence['package_generation_ref']} "
                f"validation={evidence['validation_report_ref']} "
                f"prepared={evidence['prepared_evidence_ref']} "
                f"final={evidence['migration_evidence_ref']} "
                f"partial={evidence['partial_evidence_ref']}"
            ),
            (
                f"Coverage: bridge={summary['bridge_coverage_state']} "
                f"owner={summary['bridge_owner']} "
                f"population={summary['bridge_population_digest']} "
                f"age={summary['bridge_age_seconds']} "
                f"last_use={summary['bridge_last_observed_use']} "
                f"deadline={summary['bridge_deadline']}"
            ),
            (
                f"Input: records={validation['record_count']} "
                f"bytes={validation['aggregate_bytes']} "
                f"stopped_early={validation['stopped_early']} "
                f"reason={validation['stop_reason']}"
            ),
        )
    )
    violations = validation["violations"]
    if isinstance(violations, list) and violations:
        lines.append("Violations: " + ", ".join(str(item) for item in violations))
    return _terminal_safe_output("\n".join(lines) + "\n")


def _terminal_safe_output(value: str) -> str:
    escaped: list[str] = []
    for character in value:
        if character == "\n":
            escaped.append(character)
            continue
        if unicodedata.category(character) not in {"Cc", "Cs"}:
            escaped.append(character)
            continue
        codepoint = ord(character)
        escaped.append(f"\\x{codepoint:02x}" if codepoint <= 0xFF else f"\\u{codepoint:04x}")
    return "".join(escaped)


__all__ = ["REPORT_SCHEMA", "RenderedLayoutStatus", "render_status"]
