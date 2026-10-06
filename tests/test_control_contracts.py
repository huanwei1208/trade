from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from itertools import product

import pytest

from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import Deadline, DurationMs, UtcInstant
from trade.platform.contracts.actor import (
    ActorAssurance,
    ActorContext,
    ActorOrigin,
    ActorProvenanceRef,
    PrincipalKind,
    ProvenanceType,
)
from trade.platform.contracts.control import (
    ControlClaimIdentityV1,
    ControlCommitEvidence,
    ControlDeadlineBudget,
    ControlDisposition,
    ControlKind,
    ControlReceipt,
    ResidualOwner,
    ResidualOwnerCategory,
    ShutdownAttemptEvidence,
    ShutdownReceipt,
    ShutdownRecoveryAction,
    ShutdownRecoveryKind,
    ShutdownStage,
    ShutdownState,
    ShutdownTakeoverEvidence,
    make_control_error,
    make_control_receipt_unavailable_error,
    validate_control_commit,
    validate_control_receipt_resolution,
    validate_fence_write,
    validate_shutdown_attempt,
    validate_shutdown_control_link,
    validate_shutdown_receipt_resolution,
    validate_shutdown_takeover,
)
from trade.platform.contracts.errors import (
    ErrorCategory,
    ErrorEnvelope,
    ObservationState,
    QueryStatus,
)
from trade.platform.contracts.operations import OperationState, validate_operation_transition
from trade.processes.contracts.process_view import (
    ProcessState,
    validate_process_transition,
)


def _id(namespace: str, value: str) -> OpaqueId:
    return OpaqueId(IdNamespace(namespace), value)


def _instant(second: int = 0) -> UtcInstant:
    return UtcInstant(
        datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=second)
    )


def _deadline() -> Deadline:
    return Deadline(wall_clock_expires_at=_instant(30), monotonic_expires_at=130.0)


def _actor() -> ActorContext:
    provenance = ActorProvenanceRef(
        provenance_type=ProvenanceType.CLI_PROCESS,
        verifier_namespace=IdNamespace("platform.cli"),
        evidence_id=_id("session", "trusted"),
        established_at=_instant(),
        expires_at=None,
        reason_code="trusted.cli",
    )
    return ActorContext(
        schema_version=1,
        origin=ActorOrigin.CLI,
        principal_kind=PrincipalKind.AUTHENTICATED,
        principal_id=_id("principal", "operator"),
        authority_scopes=("operation.cancel", "runtime.shutdown"),
        delegation_chain=(),
        assurance=ActorAssurance.VERIFIED,
        provenance=provenance,
        established_at=_instant(),
    )


def _generic_error(
    *,
    reason_code: str,
    category: ErrorCategory,
    observation_state: ObservationState,
    request_message_id: OpaqueId,
    correlation_id: OpaqueId,
    causation_id: OpaqueId | None,
    operation_id: OpaqueId | None,
    process_id: OpaqueId | None,
    retryable: bool = False,
    retry_after_ms: int | None = None,
) -> ErrorEnvelope:
    return ErrorEnvelope(
        schema_name="trade.error",
        schema_version=1,
        reason_code=reason_code,
        category=category,
        observation_state=observation_state,
        retryable=retryable,
        retry_after_ms=retry_after_ms,
        request_message_id=request_message_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        operation_id=operation_id,
        process_id=process_id,
        occurred_at=_instant(1),
        safe_message="The bounded owner could not complete the requested action.",
        recovery_hint="Inspect owner state and follow an authorized recovery action.",
    )


def _control_receipt(
    disposition: ControlDisposition,
    *,
    control_kind: ControlKind = ControlKind.CANCEL,
    process_target: bool = False,
) -> ControlReceipt:
    request = _id("message", "control-root")
    operation_id = None if process_target else _id("operation", "target")
    process_id = _id("process", "target") if process_target else None
    target_terminal_receipt_id: OpaqueId | None = None
    safe_error: ErrorEnvelope | None = None
    reason_code = {
        ControlDisposition.ACCEPTED: "CONTROL_ACCEPTED",
        ControlDisposition.ALREADY_TERMINAL: "CONTROL_ALREADY_TERMINAL",
        ControlDisposition.DENIED: "CONTROL_DENIED",
        ControlDisposition.NOT_FOUND: "CONTROL_TARGET_NOT_FOUND",
        ControlDisposition.UNAVAILABLE: "CONTROL_UNAVAILABLE",
        ControlDisposition.DEADLINE_EXCEEDED: "CONTROL_DEADLINE_EXCEEDED",
    }[disposition]
    if disposition is ControlDisposition.ALREADY_TERMINAL:
        target_terminal_receipt_id = _id("receipt", "target-terminal")
    elif disposition not in {
        ControlDisposition.ACCEPTED,
        ControlDisposition.ALREADY_TERMINAL,
    }:
        retry_after_ms = 5_000 if disposition is ControlDisposition.UNAVAILABLE else None
        safe_error = make_control_error(
            disposition=disposition,
            request_message_id=request,
            correlation_id=request,
            causation_id=None,
            operation_id=operation_id,
            process_id=process_id,
            occurred_at=_instant(1),
            safe_message="The control request was resolved without durable intent.",
            retry_after_ms=retry_after_ms,
        )
    return ControlReceipt(
        schema_name="trade.control_receipt",
        schema_version=1,
        control_id=_id("operation", "control"),
        control_kind=control_kind,
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        initiator=_actor(),
        operation_id=operation_id,
        process_id=process_id,
        requested_at=_instant(),
        deadline=_deadline(),
        finished_at=_instant(1),
        disposition=disposition,
        reason_code=reason_code,
        target_terminal_receipt_id=target_terminal_receipt_id,
        safe_error=safe_error,
    )


def _residual(
    category: ResidualOwnerCategory = ResidualOwnerCategory.EXECUTOR_TASK,
) -> ResidualOwner:
    return ResidualOwner(
        category=category,
        count=1,
        inspection_selector=_id("residual", category.value),
        owner_instance_id=_id("owner", "runtime-1"),
        fence_generation=7,
    )


def _recovery(
    residual: ResidualOwner,
    action: ShutdownRecoveryKind = ShutdownRecoveryKind.INSPECT_RESIDUAL,
) -> ShutdownRecoveryAction:
    return ShutdownRecoveryAction(
        action=action,
        target_id=residual.inspection_selector,
        owner_instance_id=residual.owner_instance_id,
        fence_generation=residual.fence_generation,
        reason_code="SHUTDOWN_RECOVERY_AVAILABLE",
        expires_at=_instant(30),
        required_actor_scope="runtime.shutdown",
    )


def _shutdown_receipt(
    state: ShutdownState,
    *,
    stage: ShutdownStage | None = None,
    reason_code: str | None = None,
    error_category: ErrorCategory | None = None,
    residual: ResidualOwner | None = None,
) -> ShutdownReceipt:
    request = _id("message", "control-root")
    if state is ShutdownState.COMPLETED:
        selected_stage = ShutdownStage.DONE if stage is None else stage
        selected_reason = "SHUTDOWN_COMPLETED" if reason_code is None else reason_code
        residuals: tuple[ResidualOwner, ...] = ()
        actions: tuple[ShutdownRecoveryAction, ...] = ()
        safe_error = None
    else:
        selected_stage = ShutdownStage.DRAIN_DELIVERY if stage is None else stage
        selected_reason = (
            {
                ShutdownState.DEADLINE_EXCEEDED: "SHUTDOWN_DEADLINE_EXCEEDED",
                ShutdownState.INCOMPLETE: "SHUTDOWN_DELIVERY_BLOCKED",
                ShutdownState.FAILED: "SHUTDOWN_OWNER_FAILED",
            }[state]
            if reason_code is None
            else reason_code
        )
        selected_category = (
            {
                ShutdownState.DEADLINE_EXCEEDED: ErrorCategory.TIMEOUT,
                ShutdownState.INCOMPLETE: ErrorCategory.BLOCKED,
                ShutdownState.FAILED: ErrorCategory.INTERNAL,
            }[state]
            if error_category is None
            else error_category
        )
        selected_residual = _residual() if residual is None else residual
        residuals = (selected_residual,)
        actions = (_recovery(selected_residual),)
        safe_error = _generic_error(
            reason_code=selected_reason,
            category=selected_category,
            observation_state=ObservationState.OBSERVED,
            request_message_id=request,
            correlation_id=request,
            causation_id=None,
            operation_id=_id("operation", "target"),
            process_id=None,
        )
    return ShutdownReceipt(
        schema_name="trade.shutdown_receipt",
        schema_version=1,
        owner_namespace=IdNamespace("platform.execution"),
        owner_instance_id=_id("owner", "runtime-1"),
        fence_generation=7,
        control_id=_id("operation", "control"),
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        operation_id=_id("operation", "target"),
        process_id=None,
        initiator=_actor(),
        requested_at=_instant(),
        deadline=_deadline(),
        finished_at=_instant(2),
        state=state,
        current_stage=selected_stage,
        reason_code=selected_reason,
        graceful_termination_count=2,
        forced_termination_count=1,
        residual_owners=residuals,
        shutdown_recovery_actions=actions,
        safe_error=safe_error,
    )


@pytest.mark.parametrize("disposition", tuple(ControlDisposition))
@pytest.mark.parametrize("process_target", (False, True))
def test_control_disposition_products_are_exact(
    disposition: ControlDisposition,
    process_target: bool,
) -> None:
    receipt = _control_receipt(disposition, process_target=process_target)

    assert receipt.disposition is disposition
    assert (receipt.operation_id is None) is process_target
    assert (receipt.process_id is not None) is process_target
    if disposition is ControlDisposition.ACCEPTED:
        assert receipt.safe_error is None
        assert receipt.target_terminal_receipt_id is None
    elif disposition is ControlDisposition.ALREADY_TERMINAL:
        assert receipt.safe_error is None
        assert receipt.target_terminal_receipt_id is not None
    else:
        assert receipt.safe_error is not None
        assert receipt.target_terminal_receipt_id is None


def test_control_requires_exactly_one_target_and_preserves_claim_identity() -> None:
    receipt = _control_receipt(ControlDisposition.ACCEPTED)

    assert receipt.claim_identity == ControlClaimIdentityV1(
        schema_version=1,
        control_operation_id=receipt.control_id,
        control_kind=ControlKind.CANCEL,
        operation_id=receipt.operation_id,
        process_id=None,
    )
    with pytest.raises(ValueError, match="exactly one"):
        replace(receipt, operation_id=None)
    with pytest.raises(ValueError, match="exactly one"):
        replace(receipt, process_id=_id("process", "also-target"))


def test_control_root_child_and_error_causal_identity_are_closed() -> None:
    denied = _control_receipt(ControlDisposition.DENIED)
    parent = _id("message", "parent")
    child = _id("message", "child")
    child_error = make_control_error(
        disposition=ControlDisposition.DENIED,
        request_message_id=child,
        correlation_id=parent,
        causation_id=parent,
        operation_id=denied.operation_id,
        process_id=None,
        occurred_at=_instant(1),
        safe_message="The child control request was denied.",
    )
    child_receipt = replace(
        denied,
        request_message_id=child,
        correlation_id=parent,
        causation_id=parent,
        safe_error=child_error,
    )

    assert child_receipt.causation_id == parent
    with pytest.raises(ValueError, match="root control correlation"):
        replace(denied, correlation_id=_id("message", "other"))
    with pytest.raises(ValueError, match="request causal identity"):
        replace(
            child_receipt,
            safe_error=replace(child_error, causation_id=_id("message", "other-parent")),
        )


@pytest.mark.parametrize("disposition", tuple(ControlDisposition))
@pytest.mark.parametrize(
    (
        "claim_persisted",
        "receipt_persisted",
        "intent_persisted",
        "outbox_persisted",
        "finalization_reserved",
        "committed_within_deadline",
    ),
    tuple(product((False, True), repeat=6)),
)
def test_control_commit_product_is_exact(
    disposition: ControlDisposition,
    claim_persisted: bool,
    receipt_persisted: bool,
    intent_persisted: bool,
    outbox_persisted: bool,
    finalization_reserved: bool,
    committed_within_deadline: bool,
) -> None:
    receipt = _control_receipt(disposition)
    evidence = ControlCommitEvidence(
        claim_persisted=claim_persisted,
        receipt_persisted=receipt_persisted,
        intent_persisted=intent_persisted,
        outbox_persisted=outbox_persisted,
        receipt_finalization_reserved=finalization_reserved,
        committed_within_deadline=committed_within_deadline,
    )
    expected_intent = disposition is ControlDisposition.ACCEPTED
    valid = (
        claim_persisted
        and receipt_persisted
        and intent_persisted is expected_intent
        and outbox_persisted is expected_intent
        and finalization_reserved
        and committed_within_deadline
    )

    if valid:
        validate_control_commit(receipt, evidence)
    else:
        with pytest.raises(ValueError):
            validate_control_commit(receipt, evidence)


def test_accepted_control_proves_intent_not_terminal_cancellation() -> None:
    accepted = _control_receipt(ControlDisposition.ACCEPTED)

    validate_control_commit(
        accepted,
        ControlCommitEvidence(
            claim_persisted=True,
            receipt_persisted=True,
            intent_persisted=True,
            outbox_persisted=True,
            receipt_finalization_reserved=True,
            committed_within_deadline=True,
        ),
    )
    assert accepted.target_terminal_receipt_id is None
    assert accepted.safe_error is None
    validate_operation_transition(OperationState.RUNNING, OperationState.RUNNING)
    validate_process_transition(ProcessState.WAITING, ProcessState.WAITING)


def test_control_retry_redelivery_and_post_commit_recovery_preserve_receipt() -> None:
    receipt = _control_receipt(ControlDisposition.ACCEPTED)

    validate_control_receipt_resolution(receipt, receipt)
    with pytest.raises(ValueError, match="original receipt"):
        validate_control_receipt_resolution(
            receipt,
            replace(receipt, finished_at=_instant(2)),
        )


def test_signal_or_observation_timeout_cannot_prove_cancelled() -> None:
    accepted = _control_receipt(ControlDisposition.ACCEPTED)
    request = _id("message", "observe")
    timeout = _generic_error(
        reason_code="OBSERVATION_TIMEOUT",
        category=ErrorCategory.TIMEOUT,
        observation_state=ObservationState.NOT_OBSERVED,
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        operation_id=accepted.operation_id,
        process_id=None,
        retryable=True,
    )

    status = QueryStatus(
        observation_state=ObservationState.NOT_OBSERVED,
        condition=None,
        error=timeout,
    )

    assert status.observation_state is ObservationState.NOT_OBSERVED
    assert accepted.disposition is ControlDisposition.ACCEPTED
    with pytest.raises(ValueError, match="not allowed"):
        validate_operation_transition(OperationState.RUNNING, OperationState.ACCEPTED)


def test_control_error_products_reject_wrong_retry_and_terminal_link() -> None:
    unavailable = _control_receipt(ControlDisposition.UNAVAILABLE)

    assert unavailable.safe_error is not None
    assert unavailable.safe_error.retry_after_ms == 5_000
    with pytest.raises(ValueError, match="retry_after_ms"):
        replace(unavailable, safe_error=replace(unavailable.safe_error, retry_after_ms=None))
    with pytest.raises(ValueError, match="terminal receipt link"):
        replace(
            unavailable,
            target_terminal_receipt_id=_id("receipt", "not-terminal"),
        )


def test_control_receipt_unavailable_is_error_only_without_public_links() -> None:
    request = _id("message", "control")
    error = make_control_receipt_unavailable_error(
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        occurred_at=_instant(1),
        safe_message="The durable control receipt could not be committed.",
        retry_after_ms=250,
    )

    assert error.reason_code == "CONTROL_RECEIPT_UNAVAILABLE"
    assert error.retryable
    assert error.operation_id is None
    assert error.process_id is None
    with pytest.raises(ValueError, match="1..1,000"):
        make_control_receipt_unavailable_error(
            request_message_id=request,
            correlation_id=request,
            causation_id=None,
            occurred_at=_instant(1),
            safe_message="The durable control receipt could not be committed.",
            retry_after_ms=1_001,
        )


def test_control_deadline_budget_never_consumes_finalization_reserve() -> None:
    budget = ControlDeadlineBudget(
        deadline=Deadline(
            wall_clock_expires_at=_instant(10),
            monotonic_expires_at=10.0,
        ),
        receipt_finalization_reserve=DurationMs(250),
    )

    assert budget.remaining_target_ms(9.0) == 750
    assert budget.can_start_target_step(required_ms=750, monotonic_now=9.0)
    assert not budget.can_start_target_step(required_ms=751, monotonic_now=9.0)
    assert budget.remaining_target_ms(10.0) == 0


@pytest.mark.parametrize(
    ("state", "category"),
    (
        (ShutdownState.COMPLETED, None),
        (ShutdownState.DEADLINE_EXCEEDED, ErrorCategory.TIMEOUT),
        (ShutdownState.INCOMPLETE, ErrorCategory.BLOCKED),
        (ShutdownState.INCOMPLETE, ErrorCategory.UNAVAILABLE),
        (ShutdownState.FAILED, ErrorCategory.INTERNAL),
        (ShutdownState.FAILED, ErrorCategory.UNAVAILABLE),
    ),
)
def test_shutdown_state_products_are_exact(
    state: ShutdownState,
    category: ErrorCategory | None,
) -> None:
    receipt = _shutdown_receipt(state, error_category=category)

    assert receipt.state is state
    if state is ShutdownState.COMPLETED:
        assert receipt.current_stage is ShutdownStage.DONE
        assert receipt.residual_owners == ()
        assert receipt.shutdown_recovery_actions == ()
        assert receipt.safe_error is None
    else:
        assert receipt.current_stage is not ShutdownStage.DONE
        assert receipt.residual_owners
        assert receipt.shutdown_recovery_actions
        assert receipt.safe_error is not None
        assert receipt.safe_error.observation_state is ObservationState.OBSERVED


@pytest.mark.parametrize("state", tuple(ShutdownState))
@pytest.mark.parametrize("stage", tuple(ShutdownStage))
def test_shutdown_done_stage_is_closed(
    state: ShutdownState,
    stage: ShutdownStage,
) -> None:
    valid = (state is ShutdownState.COMPLETED and stage is ShutdownStage.DONE) or (
        state is not ShutdownState.COMPLETED and stage is not ShutdownStage.DONE
    )

    if valid:
        _shutdown_receipt(state, stage=stage)
    else:
        with pytest.raises(ValueError, match="done stage|forbids done"):
            _shutdown_receipt(state, stage=stage)


@pytest.mark.parametrize("category", tuple(ResidualOwnerCategory))
@pytest.mark.parametrize("count", (1, 10))
def test_residual_owner_taxonomy_is_closed_and_owner_fenced(
    category: ResidualOwnerCategory,
    count: int,
) -> None:
    residual = replace(_residual(category), count=count)
    receipt = _shutdown_receipt(
        ShutdownState.INCOMPLETE,
        residual=residual,
    )

    assert receipt.residual_owners == (residual,)
    with pytest.raises(ValueError, match="owner instance and fence"):
        replace(
            receipt,
            residual_owners=(replace(residual, owner_instance_id=_id("owner", "other")),),
        )


@pytest.mark.parametrize("action", tuple(ShutdownRecoveryKind))
def test_shutdown_recovery_actions_are_closed_owner_scoped_and_informational(
    action: ShutdownRecoveryKind,
) -> None:
    residual = _residual()
    receipt = _shutdown_receipt(
        ShutdownState.INCOMPLETE,
        residual=residual,
    )
    recovery = _recovery(residual, action)

    updated = replace(receipt, shutdown_recovery_actions=(recovery,))

    assert updated.shutdown_recovery_actions[0].action is action
    with pytest.raises(ValueError, match="reported residual"):
        replace(
            updated,
            shutdown_recovery_actions=(replace(recovery, target_id=_id("residual", "unknown")),),
        )


def test_shutdown_residual_and_recovery_collections_are_bounded_at_sixteen() -> None:
    residuals = tuple(
        replace(
            _residual(ResidualOwnerCategory.EXECUTOR_TASK),
            inspection_selector=_id("residual", f"task-{index}"),
        )
        for index in range(16)
    )
    actions = tuple(_recovery(residual) for residual in residuals)
    receipt = _shutdown_receipt(ShutdownState.INCOMPLETE)

    bounded = replace(
        receipt,
        residual_owners=residuals,
        shutdown_recovery_actions=actions,
    )

    assert len(bounded.residual_owners) == 16
    assert len(bounded.shutdown_recovery_actions) == 16
    seventeenth = replace(
        residuals[-1],
        inspection_selector=_id("residual", "task-16"),
    )
    with pytest.raises(ValueError, match="at most 16"):
        replace(bounded, residual_owners=(*residuals, seventeenth))
    with pytest.raises(ValueError, match="at most 16"):
        replace(
            bounded,
            shutdown_recovery_actions=(*actions, _recovery(seventeenth)),
        )


def test_shutdown_completed_requires_audit_resources_and_matching_fence_release() -> None:
    receipt = _shutdown_receipt(ShutdownState.COMPLETED)
    valid = ShutdownAttemptEvidence(
        live_owned_work_count=0,
        terminal_audit_committed=True,
        resources_released=True,
        released_fence_generation=7,
        fence_retained=False,
        returned_within_deadline=True,
    )

    validate_shutdown_attempt(receipt, valid)
    with pytest.raises(ValueError, match="zero live"):
        validate_shutdown_attempt(receipt, replace(valid, live_owned_work_count=1))
    with pytest.raises(ValueError, match="terminal audit"):
        validate_shutdown_attempt(receipt, replace(valid, terminal_audit_committed=False))
    with pytest.raises(ValueError, match="released resources"):
        validate_shutdown_attempt(receipt, replace(valid, resources_released=False))
    with pytest.raises(ValueError, match="matching fence"):
        validate_shutdown_attempt(receipt, replace(valid, released_fence_generation=6))


def test_noncompleted_shutdown_retains_fence_and_reports_live_owners() -> None:
    receipt = _shutdown_receipt(ShutdownState.DEADLINE_EXCEEDED)
    valid = ShutdownAttemptEvidence(
        live_owned_work_count=1,
        terminal_audit_committed=False,
        resources_released=False,
        released_fence_generation=None,
        fence_retained=True,
        returned_within_deadline=True,
    )

    validate_shutdown_attempt(receipt, valid)
    with pytest.raises(ValueError, match="retain its fence"):
        validate_shutdown_attempt(receipt, replace(valid, fence_retained=False))
    with pytest.raises(ValueError, match="cannot release"):
        validate_shutdown_attempt(
            receipt,
            replace(valid, released_fence_generation=7),
        )
    with pytest.raises(ValueError, match="represented by residual"):
        validate_shutdown_attempt(receipt, replace(valid, live_owned_work_count=2))
    with pytest.raises(ValueError, match="shared deadline"):
        validate_shutdown_attempt(
            receipt,
            replace(valid, returned_within_deadline=False),
        )


def test_shutdown_receipt_links_to_exact_immutable_control_attribution() -> None:
    control = _control_receipt(
        ControlDisposition.ACCEPTED,
        control_kind=ControlKind.SHUTDOWN,
    )
    shutdown = _shutdown_receipt(ShutdownState.COMPLETED)

    validate_shutdown_control_link(shutdown, control)
    with pytest.raises(ValueError, match="initiator"):
        validate_shutdown_control_link(
            replace(shutdown, initiator=replace(_actor(), principal_id=_id("principal", "other"))),
            control,
        )
    with pytest.raises(ValueError, match="control_id"):
        validate_shutdown_control_link(
            replace(shutdown, control_id=_id("operation", "other-control")),
            control,
        )


def test_concurrent_shutdown_callers_resolve_one_immutable_receipt() -> None:
    receipt = _shutdown_receipt(ShutdownState.INCOMPLETE)

    validate_shutdown_receipt_resolution(receipt, receipt)
    with pytest.raises(ValueError, match="one immutable receipt"):
        validate_shutdown_receipt_resolution(
            receipt,
            replace(receipt, graceful_termination_count=3),
        )


def test_replay_derived_control_uses_only_current_verified_initiator() -> None:
    current_initiator = _actor()
    receipt = replace(
        _control_receipt(ControlDisposition.ACCEPTED),
        initiator=current_initiator,
    )

    assert receipt.initiator is current_initiator
    assert receipt.initiator.assurance is ActorAssurance.VERIFIED
    assert {field.name for field in fields(receipt)}.isdisjoint(
        {
            "historical_actor",
            "historical_authority_scopes",
            "historical_assurance",
            "replay_policy",
        }
    )


def test_persistent_audit_blockage_and_executor_tail_remain_explicit() -> None:
    for category in (
        ResidualOwnerCategory.PERSISTENCE_AUDIT,
        ResidualOwnerCategory.EXECUTOR_TASK,
    ):
        residual = _residual(category)
        receipt = _shutdown_receipt(
            ShutdownState.INCOMPLETE,
            residual=residual,
        )
        evidence = ShutdownAttemptEvidence(
            live_owned_work_count=1,
            terminal_audit_committed=False,
            resources_released=False,
            released_fence_generation=None,
            fence_retained=True,
            returned_within_deadline=True,
        )

        validate_shutdown_attempt(receipt, evidence)
        assert receipt.residual_owners[0].category is category


def test_fence_write_rejects_stale_or_future_generation() -> None:
    validate_fence_write(claimed_generation=8, writer_generation=8)
    with pytest.raises(ValueError, match="does not match"):
        validate_fence_write(claimed_generation=8, writer_generation=7)
    with pytest.raises(ValueError, match="does not match"):
        validate_fence_write(claimed_generation=8, writer_generation=9)


@pytest.mark.parametrize(
    ("expired", "revoked"),
    ((True, False), (False, True)),
)
def test_shutdown_takeover_requires_next_generation_and_one_lease_proof(
    expired: bool,
    revoked: bool,
) -> None:
    evidence = ShutdownTakeoverEvidence(
        previous_owner_instance_id=_id("owner", "old"),
        previous_generation=7,
        next_owner_instance_id=_id("owner", "new"),
        next_generation=8,
        prior_lease_expired=expired,
        prior_lease_revoked=revoked,
        takeover_causation_id=_id("takeover", "lease-proof"),
    )

    validate_shutdown_takeover(evidence)
    with pytest.raises(ValueError, match="next fence"):
        validate_shutdown_takeover(replace(evidence, next_generation=9))
    with pytest.raises(ValueError, match="new owner"):
        validate_shutdown_takeover(
            replace(
                evidence,
                next_owner_instance_id=evidence.previous_owner_instance_id,
            )
        )


def test_fake_monotonic_clock_uses_one_shared_deadline_without_sleep() -> None:
    class FakeClock:
        def __init__(self) -> None:
            self.now = 100.0

        def advance_ms(self, milliseconds: int) -> None:
            self.now += milliseconds / 1_000

    clock = FakeClock()
    deadline = Deadline(
        wall_clock_expires_at=_instant(2),
        monotonic_expires_at=102.0,
    )
    budget = ControlDeadlineBudget(
        deadline=deadline,
        receipt_finalization_reserve=DurationMs(250),
    )

    assert budget.remaining_target_ms(clock.now) == 1_750
    clock.advance_ms(1_500)
    assert budget.remaining_target_ms(clock.now) == 250
    assert not budget.can_start_target_step(required_ms=251, monotonic_now=clock.now)
    clock.advance_ms(250)
    assert budget.remaining_target_ms(clock.now) == 0
    assert deadline.remaining_ms(clock.now) == 250
    clock.advance_ms(250)
    assert deadline.is_expired(clock.now)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="process-group termination fixture requires POSIX signals",
)
def test_real_child_process_tree_is_reaped_within_shared_two_second_deadline() -> None:
    started = time.monotonic()
    deadline = started + 2.0
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=max(0.01, deadline - time.monotonic()))
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=max(0.01, deadline - time.monotonic()))

    elapsed = time.monotonic() - started
    assert child.poll() is not None
    assert elapsed <= 2.25


def test_control_and_shutdown_contracts_expose_no_process_implementation_type() -> None:
    forbidden = {
        "repository",
        "connection",
        "callback",
        "thread",
        "future",
        "executor",
        "subprocess",
        "payload",
    }
    public_fields = {
        field.name
        for contract in (
            ControlReceipt,
            ShutdownReceipt,
            ResidualOwner,
            ShutdownRecoveryAction,
        )
        for field in fields(contract)
    }

    assert public_fields.isdisjoint(forbidden)
