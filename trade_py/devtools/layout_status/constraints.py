"""Pure v1 legality, action, and exit rules for package-layout status."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

Classification = Literal["healthy", "valid_attention", "invalid"]

MIGRATION_STATES: Final = (
    "inventoried",
    "prepared",
    "shadow_verified",
    "legacy_forwarding",
    "target_authoritative",
    "retireable",
)
EXECUTION_STATES: Final = ("not_run", "running", "passed", "failed", "stopped")
FAILURE_CLASSES: Final = (
    "none",
    "unavailable_prerequisite",
    "timeout",
    "test_failure",
    "contract_mismatch",
    "tool_failure",
    "capacity_refusal",
    "process_cleanup_incomplete",
)
ROLLBACK_STATES: Final = (
    "not_required",
    "ready",
    "requested",
    "running",
    "succeeded",
    "failed",
    "unknown",
)
STARTUP_STATES: Final = (
    "not_started",
    "starting",
    "started_healthy",
    "started_degraded",
    "failed",
    "stopped",
)
RECONCILIATION_STATES: Final = (
    "not_required",
    "pending",
    "adopted",
    "absence_proved",
    "fenced_teardown",
    "required",
    "failed",
)
OPERATOR_ACTIONS: Final = (
    "none",
    "wait",
    "continue_validation",
    "resume_reconciliation",
    "retry_identical_invocation",
    "repair_prerequisite",
    "narrow_slice",
    "execute_reviewed_rollback",
    "investigate",
)

_HEALTHY: Final = {
    "migration_state": frozenset({"retireable"}),
    "execution_state": frozenset({"passed"}),
    "failure_class": frozenset({"none"}),
    "rollback_state": frozenset({"not_required", "succeeded"}),
    "startup_state": frozenset({"started_healthy"}),
    "reconciliation_state": frozenset({"not_required", "adopted"}),
}
_DECLARED: Final = {
    "migration_state": frozenset(MIGRATION_STATES),
    "execution_state": frozenset(EXECUTION_STATES),
    "failure_class": frozenset(FAILURE_CLASSES),
    "rollback_state": frozenset(ROLLBACK_STATES),
    "startup_state": frozenset(STARTUP_STATES),
    "reconciliation_state": frozenset(RECONCILIATION_STATES),
}
_RECONCILIATION_PRODUCTS: Final = {
    "pending": (
        frozenset({"inventoried", "prepared", "shadow_verified"}),
        frozenset({"not_run", "running", "stopped"}),
        frozenset({"not_required"}),
        frozenset(
            {
                "not_started",
                "starting",
                "started_healthy",
                "started_degraded",
                "stopped",
            }
        ),
    ),
    "adopted": (
        frozenset({"prepared", "shadow_verified", "legacy_forwarding", "target_authoritative"}),
        frozenset({"running", "passed"}),
        frozenset({"not_required"}),
        frozenset({"started_healthy", "started_degraded"}),
    ),
    "absence_proved": (
        frozenset({"inventoried", "prepared", "shadow_verified"}),
        frozenset({"not_run", "stopped"}),
        frozenset({"not_required"}),
        frozenset({"not_started", "stopped"}),
    ),
    "fenced_teardown": (
        frozenset({"prepared", "shadow_verified"}),
        frozenset({"stopped"}),
        frozenset({"ready"}),
        frozenset({"stopped"}),
    ),
    "required": (
        frozenset({"inventoried", "prepared", "shadow_verified"}),
        frozenset({"failed", "stopped"}),
        frozenset(ROLLBACK_STATES),
        frozenset(STARTUP_STATES),
    ),
    "failed": (
        frozenset({"inventoried", "prepared", "shadow_verified"}),
        frozenset({"failed", "stopped"}),
        frozenset(ROLLBACK_STATES),
        frozenset(STARTUP_STATES),
    ),
}
_RECONCILIATION_FAILURES: Final = frozenset(
    {
        "unavailable_prerequisite",
        "timeout",
        "contract_mismatch",
        "tool_failure",
        "process_cleanup_incomplete",
    }
)


@dataclass(frozen=True)
class LayoutStatusAxes:
    migration_state: str
    execution_state: str
    failure_class: str
    rollback_state: str
    startup_state: str
    reconciliation_state: str

    def items(self) -> tuple[tuple[str, str], ...]:
        return (
            ("migration_state", self.migration_state),
            ("execution_state", self.execution_state),
            ("failure_class", self.failure_class),
            ("rollback_state", self.rollback_state),
            ("startup_state", self.startup_state),
            ("reconciliation_state", self.reconciliation_state),
        )


@dataclass(frozen=True)
class ConstraintFacts:
    receipts_valid: bool = True
    identities_match: bool = True
    phases_ordered: bool = True
    rollback_target_valid: bool = True


_DEFAULT_FACTS: Final = ConstraintFacts()


@dataclass(frozen=True)
class ConstraintResult:
    classification: Classification
    derived_action: str
    exit_code: int
    axis_classifications: tuple[tuple[str, Classification], ...]
    violations: tuple[str, ...]


class LayoutStatusConstraintsV1:
    """Dependency-free implementation of the frozen v1 status truth table."""

    schema_version: Final = 1

    @classmethod
    def evaluate(
        cls,
        axes: LayoutStatusAxes,
        *,
        supplied_action: str | None = None,
        facts: ConstraintFacts = _DEFAULT_FACTS,
        additional_classifications: tuple[tuple[str, Classification], ...] = (),
    ) -> ConstraintResult:
        base_axis_classes: tuple[tuple[str, Classification], ...] = tuple(
            (name, cls.classify_axis(name, value)) for name, value in axes.items()
        )
        axis_classes = base_axis_classes + additional_classifications
        declared = all(item != "invalid" for _, item in base_axis_classes)
        has_additional_attention = any(
            item == "valid_attention" for _, item in additional_classifications
        )
        derived_action = (
            cls.derive_action(
                axes,
                has_additional_attention=has_additional_attention,
            )
            if declared
            else "investigate"
        )
        violations: list[str] = []
        if declared:
            violations.extend(cls._product_violations(axes))
        else:
            violations.append("layout.status.unknown_state")
        if not facts.receipts_valid:
            violations.append("layout.status.receipt_invalid")
        if not facts.identities_match:
            violations.append("layout.status.identity_mismatch")
        if not facts.phases_ordered:
            violations.append("layout.status.phase_order_invalid")
        if not facts.rollback_target_valid:
            violations.append("layout.status.rollback_target_invalid")
        if any(item == "invalid" for _, item in additional_classifications):
            violations.append("layout.status.additional_invalid")
        if supplied_action is not None and supplied_action not in OPERATOR_ACTIONS:
            violations.append("layout.status.unknown_action")
        elif supplied_action is not None and supplied_action != derived_action:
            violations.append("layout.status.action_mismatch")

        if violations:
            classification: Classification = "invalid"
        else:
            classification = aggregate_classifications(item for _, item in axis_classes)
        return ConstraintResult(
            classification=classification,
            derived_action=derived_action,
            exit_code={"healthy": 0, "valid_attention": 1, "invalid": 2}[classification],
            axis_classifications=axis_classes,
            violations=tuple(sorted(set(violations))),
        )

    @staticmethod
    def classify_axis(axis: str, value: str) -> Classification:
        declared = _DECLARED.get(axis)
        if declared is None or value not in declared:
            return "invalid"
        return "healthy" if value in _HEALTHY[axis] else "valid_attention"

    @staticmethod
    def derive_action(
        axes: LayoutStatusAxes,
        *,
        has_additional_attention: bool = False,
    ) -> str:
        if axes.reconciliation_state in {"required", "failed"}:
            return (
                "repair_prerequisite"
                if axes.failure_class == "unavailable_prerequisite"
                else "investigate"
            )
        if axes.reconciliation_state == "fenced_teardown":
            return "execute_reviewed_rollback"
        if axes.reconciliation_state == "absence_proved":
            return "retry_identical_invocation"
        if axes.reconciliation_state == "pending":
            return "resume_reconciliation"
        if axes.failure_class == "unavailable_prerequisite":
            return "repair_prerequisite"
        if axes.failure_class == "capacity_refusal":
            return "narrow_slice"
        if (
            axes.failure_class != "none"
            or axes.rollback_state in {"failed", "unknown"}
            or axes.startup_state in {"started_degraded", "failed", "stopped"}
        ):
            return "investigate"
        if axes.rollback_state == "ready":
            return "execute_reviewed_rollback"
        if (
            axes.rollback_state in {"requested", "running"}
            or axes.execution_state == "running"
            or axes.startup_state == "starting"
        ):
            return "wait"
        if (
            any(
                LayoutStatusConstraintsV1.classify_axis(name, value) == "valid_attention"
                for name, value in axes.items()
            )
            or has_additional_attention
        ):
            return "continue_validation"
        return "none"

    @staticmethod
    def _product_violations(axes: LayoutStatusAxes) -> tuple[str, ...]:
        violations: list[str] = []
        if axes.execution_state == "passed" and axes.failure_class != "none":
            violations.append("layout.status.passed_with_failure")
        if axes.failure_class != "none" and axes.execution_state == "passed":
            violations.append("layout.status.failure_with_passed")
        if axes.migration_state in {"target_authoritative", "retireable"} and (
            axes.execution_state != "passed"
            or axes.failure_class != "none"
            or axes.rollback_state != "not_required"
            or axes.reconciliation_state not in {"not_required", "adopted"}
        ):
            violations.append("layout.status.authority_not_verified")

        reconciliation = axes.reconciliation_state
        if reconciliation in {
            "pending",
            "adopted",
            "absence_proved",
            "fenced_teardown",
        }:
            if axes.failure_class != "none":
                violations.append("layout.status.reconciliation_failure_forbidden")
        elif reconciliation in {"required", "failed"}:
            if axes.failure_class not in _RECONCILIATION_FAILURES:
                violations.append("layout.status.reconciliation_failure_required")

        allowed = _RECONCILIATION_PRODUCTS.get(reconciliation)
        if allowed is not None:
            migration, execution, rollback, startup = allowed
            if axes.migration_state not in migration:
                violations.append("layout.status.reconciliation_migration_forbidden")
            if axes.execution_state not in execution:
                violations.append("layout.status.reconciliation_execution_forbidden")
            if axes.rollback_state not in rollback:
                violations.append("layout.status.reconciliation_rollback_forbidden")
            if axes.startup_state not in startup:
                violations.append("layout.status.reconciliation_startup_forbidden")
        return tuple(violations)


def aggregate_classifications(values: Iterable[object]) -> Classification:
    """Aggregate any finite iterable without depending on iteration order."""

    seen_attention = False
    for value in values:
        if value == "invalid":
            return "invalid"
        if value == "valid_attention":
            seen_attention = True
        elif value != "healthy":
            return "invalid"
    return "valid_attention" if seen_attention else "healthy"


__all__ = [
    "ConstraintFacts",
    "ConstraintResult",
    "EXECUTION_STATES",
    "FAILURE_CLASSES",
    "LayoutStatusAxes",
    "LayoutStatusConstraintsV1",
    "MIGRATION_STATES",
    "OPERATOR_ACTIONS",
    "RECONCILIATION_STATES",
    "ROLLBACK_STATES",
    "STARTUP_STATES",
    "aggregate_classifications",
]
