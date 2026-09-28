from __future__ import annotations

from itertools import product

from trade_py.devtools.layout_status.constraints import (
    EXECUTION_STATES,
    FAILURE_CLASSES,
    MIGRATION_STATES,
    OPERATOR_ACTIONS,
    RECONCILIATION_STATES,
    ROLLBACK_STATES,
    STARTUP_STATES,
    ConstraintFacts,
    LayoutStatusAxes,
    LayoutStatusConstraintsV1,
    aggregate_classifications,
)


def _axes(
    migration: str = "retireable",
    execution: str = "passed",
    failure: str = "none",
    rollback: str = "not_required",
    startup: str = "started_healthy",
    reconciliation: str = "not_required",
) -> LayoutStatusAxes:
    return LayoutStatusAxes(
        migration_state=migration,
        execution_state=execution,
        failure_class=failure,
        rollback_state=rollback,
        startup_state=startup,
        reconciliation_state=reconciliation,
    )


def test_finite_state_and_supplied_action_product_is_total() -> None:
    classifications: set[str] = set()
    valid_products = 0
    for values in product(
        MIGRATION_STATES,
        EXECUTION_STATES,
        FAILURE_CLASSES,
        ROLLBACK_STATES,
        STARTUP_STATES,
        RECONCILIATION_STATES,
    ):
        axes = LayoutStatusAxes(*values)
        result = LayoutStatusConstraintsV1.evaluate(axes)
        assert result.classification in {"healthy", "valid_attention", "invalid"}
        assert result.exit_code in {0, 1, 2}
        assert result.derived_action in OPERATOR_ACTIONS
        assert len(result.axis_classifications) == 6
        classifications.add(result.classification)

        matching = 0
        for action in OPERATOR_ACTIONS:
            supplied = LayoutStatusConstraintsV1.evaluate(axes, supplied_action=action)
            if action == result.derived_action and result.classification != "invalid":
                matching += 1
                assert supplied == result
            else:
                assert supplied.classification == "invalid"
                assert supplied.exit_code == 2
        if result.classification != "invalid":
            valid_products += 1
            assert matching == 1

    assert classifications == {"healthy", "valid_attention", "invalid"}
    assert valid_products > 0


def test_exit_aggregation_is_order_independent() -> None:
    samples = (
        ("healthy", "healthy", "healthy"),
        ("healthy", "valid_attention", "healthy"),
        ("valid_attention", "invalid", "healthy"),
    )
    for values in samples:
        expected = aggregate_classifications(values)
        assert aggregate_classifications(reversed(values)) == expected
        assert aggregate_classifications(values[1:] + values[:1]) == expected


def test_action_priority_distinguishes_reconciliation_outcomes() -> None:
    pending = LayoutStatusConstraintsV1.evaluate(
        _axes("prepared", "running", startup="starting", reconciliation="pending")
    )
    absence = LayoutStatusConstraintsV1.evaluate(
        _axes(
            "prepared",
            "stopped",
            startup="stopped",
            reconciliation="absence_proved",
        )
    )
    teardown = LayoutStatusConstraintsV1.evaluate(
        _axes(
            "prepared",
            "stopped",
            rollback="ready",
            startup="stopped",
            reconciliation="fenced_teardown",
        )
    )

    assert (pending.derived_action, pending.exit_code) == ("resume_reconciliation", 1)
    assert (absence.derived_action, absence.exit_code) == (
        "retry_identical_invocation",
        1,
    )
    assert (teardown.derived_action, teardown.exit_code) == (
        "execute_reviewed_rollback",
        1,
    )


def test_failure_and_capacity_rules_precede_generic_attention() -> None:
    unavailable = LayoutStatusConstraintsV1.evaluate(
        _axes(
            "prepared",
            "failed",
            "unavailable_prerequisite",
            startup="failed",
        )
    )
    capacity = LayoutStatusConstraintsV1.evaluate(
        _axes("prepared", "failed", "capacity_refusal", startup="failed")
    )

    assert unavailable.derived_action == "repair_prerequisite"
    assert unavailable.exit_code == 1
    assert capacity.derived_action == "narrow_slice"
    assert capacity.exit_code == 1


def test_unknowns_and_failed_evidence_facts_are_invalid() -> None:
    unknown = LayoutStatusConstraintsV1.evaluate(_axes(migration="future_state"))
    mismatched = LayoutStatusConstraintsV1.evaluate(
        _axes(),
        facts=ConstraintFacts(
            receipts_valid=False,
            identities_match=False,
            phases_ordered=False,
            rollback_target_valid=False,
        ),
    )

    assert unknown.classification == "invalid"
    assert unknown.exit_code == 2
    assert unknown.violations == ("layout.status.unknown_state",)
    assert mismatched.exit_code == 2
    assert set(mismatched.violations) == {
        "layout.status.identity_mismatch",
        "layout.status.phase_order_invalid",
        "layout.status.receipt_invalid",
        "layout.status.rollback_target_invalid",
    }


def test_authority_and_reconciliation_cross_axis_predicates_fail_closed() -> None:
    authoritative_failed = LayoutStatusConstraintsV1.evaluate(
        _axes("target_authoritative", "failed", "timeout", startup="failed")
    )
    adopted_without_allowed_product = LayoutStatusConstraintsV1.evaluate(
        _axes(reconciliation="adopted")
    )
    required_with_passed = LayoutStatusConstraintsV1.evaluate(
        _axes(
            "target_authoritative",
            "passed",
            "timeout",
            reconciliation="required",
        )
    )

    assert authoritative_failed.classification == "invalid"
    assert "layout.status.authority_not_verified" in authoritative_failed.violations
    assert adopted_without_allowed_product.classification == "invalid"
    assert required_with_passed.classification == "invalid"
