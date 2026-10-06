from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from itertools import product

import pytest

from trade.kernel.digest import ContentDigest
from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import Deadline, UtcInstant
from trade.platform.contracts.actor import (
    ActorAssurance,
    ActorContext,
    ActorOrigin,
    ActorProvenanceRef,
    PrincipalKind,
    ProvenanceType,
)
from trade.platform.contracts.errors import (
    ErrorCategory,
    ErrorEnvelope,
    ObservationState,
    QueryCondition,
    QueryStatus,
    make_admission_error,
)
from trade.platform.contracts.messages import (
    FingerprintDomain,
    FingerprintV1,
)
from trade.platform.contracts.operations import (
    ADMISSION_OUTCOME_COUNTER_NAME,
    AdmissionOutcome,
    AdmissionOutcomeLabels,
    AdmissionRefusalAuditV1,
    AdmissionRefusalEventV1,
    DeadlineTerminalEvidence,
    OperationReceipt,
    OperationState,
    validate_operation_receipt_transition,
    validate_operation_transition,
)
from trade.processes.contracts.process_view import (
    HistoryWindow,
    ProcessStartKeyV1,
    ProcessState,
    ProcessTransition,
    ProcessView,
    RecoveryAction,
    RecoveryActionDescriptor,
    validate_process_transition,
    validate_process_view_transition,
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
        principal_id=_id("principal", "alice"),
        authority_scopes=("operation.read", "process.recover"),
        delegation_chain=(),
        assurance=ActorAssurance.VERIFIED,
        provenance=provenance,
        established_at=_instant(),
    )


def _fingerprint(domain: FingerprintDomain, marker: str) -> FingerprintV1:
    return FingerprintV1(
        algorithm="hmac-sha256-v1",
        domain=domain,
        key_version=1,
        value=(marker * 64)[:64],
    )


def _operation_receipt(
    *,
    state: OperationState = OperationState.ACCEPTED,
    reason_code: str = "OPERATION_ACCEPTED",
    updated_second: int = 1,
    terminal_at: UtcInstant | None = None,
    process_id: OpaqueId | None = None,
) -> OperationReceipt:
    request = _id("message", "root-command")
    return OperationReceipt(
        schema_name="trade.operation_receipt",
        schema_version=1,
        operation_id=_id("operation", "one"),
        operation_kind="dataset.refresh",
        command_name="refresh_dataset",
        command_fingerprint=_fingerprint(FingerprintDomain.COMMAND, "a"),
        actor=_actor(),
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        idempotency_scope="dataset.refresh",
        idempotency_fingerprint=_fingerprint(FingerprintDomain.IDEMPOTENCY, "b"),
        state=state,
        reason_code=reason_code,
        accepted_at=_instant(),
        updated_at=_instant(updated_second),
        terminal_at=terminal_at,
        process_id=process_id,
    )


def _generic_error(
    *,
    category: ErrorCategory,
    observation: ObservationState,
    reason: str = "QUERY_FAILED",
) -> ErrorEnvelope:
    request = _id("message", "query")
    return ErrorEnvelope(
        schema_name="trade.error",
        schema_version=1,
        reason_code=reason,
        category=category,
        observation_state=observation,
        retryable=False,
        retry_after_ms=None,
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        operation_id=None,
        process_id=None,
        occurred_at=_instant(),
        safe_message="The query could not be completed.",
        recovery_hint="Inspect the owner status and retry under policy.",
    )


def _transition(
    sequence: int,
    state: ProcessState,
    *,
    reason_code: str | None = None,
) -> ProcessTransition:
    return ProcessTransition(
        sequence=sequence,
        transition_id=_id("transition", str(sequence)),
        state=state,
        step="capture.wait",
        reason_code=reason_code,
        observed_at=_instant(sequence),
    )


def _history(
    items: tuple[ProcessTransition, ...] = (),
    *,
    total_count: int | None = None,
) -> HistoryWindow:
    total = len(items) if total_count is None else total_count
    return HistoryWindow(
        items=items,
        total_count=total,
        returned_count=len(items),
        first_sequence=None if not items else items[0].sequence,
        last_sequence=None if not items else items[-1].sequence,
        omitted_before_count=total - len(items),
    )


def _process_view(
    *,
    state: ProcessState = ProcessState.RUNNING,
    reason_code: str | None = None,
    updated_second: int = 1,
    terminal_at: UtcInstant | None = None,
    retry_count: int = 0,
    retry_limit: int = 3,
    next_attempt_at: UtcInstant | None = None,
    history: HistoryWindow | None = None,
) -> ProcessView:
    return ProcessView(
        schema_name="trade.process_view",
        schema_version=1,
        process_id=_id("process", "one"),
        process_type="refresh_dataset",
        triggering_operation_id=_id("operation", "one"),
        correlation_id=_id("message", "root-command"),
        causation_id=None,
        state=state,
        observation_state=ObservationState.OBSERVED,
        current_step="capture.wait",
        reason_code=reason_code,
        retry_count=retry_count,
        retry_limit=retry_limit,
        next_attempt_at=next_attempt_at,
        deadline=_deadline(),
        last_error=None,
        compensation_state=None,
        dead_letter_state=None,
        bounded_history=_history() if history is None else history,
        permitted_recovery_actions=(),
        created_at=_instant(),
        updated_at=_instant(updated_second),
        terminal_at=terminal_at,
    )


_OPERATION_ALLOWED = {
    OperationState.REQUESTED: {
        OperationState.ACCEPTED,
        OperationState.FAILED,
        OperationState.CANCELLED,
        OperationState.DEADLINE_EXCEEDED,
    },
    OperationState.ACCEPTED: {
        OperationState.RUNNING,
        OperationState.WAITING,
        OperationState.RETRY_SCHEDULED,
        OperationState.BLOCKED,
        OperationState.COMPLETED,
        OperationState.FAILED,
        OperationState.CANCELLED,
        OperationState.DEADLINE_EXCEEDED,
    },
    OperationState.RUNNING: {
        OperationState.WAITING,
        OperationState.RETRY_SCHEDULED,
        OperationState.COMPENSATION_PENDING,
        OperationState.BLOCKED,
        OperationState.COMPLETED,
        OperationState.FAILED,
        OperationState.CANCELLED,
        OperationState.DEADLINE_EXCEEDED,
    },
    OperationState.WAITING: {
        OperationState.RUNNING,
        OperationState.RETRY_SCHEDULED,
        OperationState.BLOCKED,
        OperationState.FAILED,
        OperationState.CANCELLED,
        OperationState.DEADLINE_EXCEEDED,
    },
    OperationState.RETRY_SCHEDULED: {
        OperationState.RUNNING,
        OperationState.WAITING,
        OperationState.BLOCKED,
        OperationState.FAILED,
        OperationState.CANCELLED,
        OperationState.DEADLINE_EXCEEDED,
    },
    OperationState.COMPENSATION_PENDING: {
        OperationState.COMPENSATED,
        OperationState.BLOCKED,
        OperationState.FAILED,
        OperationState.DEADLINE_EXCEEDED,
    },
    OperationState.BLOCKED: {
        OperationState.RUNNING,
        OperationState.RETRY_SCHEDULED,
        OperationState.COMPENSATION_PENDING,
        OperationState.FAILED,
        OperationState.CANCELLED,
        OperationState.DEADLINE_EXCEEDED,
    },
    OperationState.COMPLETED: set(),
    OperationState.COMPENSATED: set(),
    OperationState.FAILED: set(),
    OperationState.CANCELLED: set(),
    OperationState.DEADLINE_EXCEEDED: set(),
}


@pytest.mark.parametrize(
    ("previous", "current"),
    tuple(product(OperationState, repeat=2)),
)
def test_operation_transition_relation_is_exact(
    previous: OperationState,
    current: OperationState,
) -> None:
    allowed = current is previous or current in _OPERATION_ALLOWED[previous]

    if allowed:
        evidence = (
            DeadlineTerminalEvidence.ALL_OWNED_WORKERS_EXITED
            if current is OperationState.DEADLINE_EXCEEDED and current is not previous
            else None
        )
        validate_operation_transition(
            previous,
            current,
            deadline_evidence=evidence,
        )
    else:
        with pytest.raises(ValueError, match="not allowed"):
            validate_operation_transition(previous, current)


_PROCESS_ALLOWED = {
    ProcessState.REQUESTED: {
        ProcessState.RUNNING,
        ProcessState.WAITING,
        ProcessState.FAILED,
        ProcessState.CANCELLED,
        ProcessState.DEADLINE_EXCEEDED,
    },
    ProcessState.RUNNING: {
        ProcessState.WAITING,
        ProcessState.RETRY_SCHEDULED,
        ProcessState.COMPENSATION_PENDING,
        ProcessState.BLOCKED,
        ProcessState.COMPLETED,
        ProcessState.FAILED,
        ProcessState.CANCELLED,
        ProcessState.DEADLINE_EXCEEDED,
    },
    ProcessState.WAITING: {
        ProcessState.RUNNING,
        ProcessState.RETRY_SCHEDULED,
        ProcessState.BLOCKED,
        ProcessState.FAILED,
        ProcessState.CANCELLED,
        ProcessState.DEADLINE_EXCEEDED,
    },
    ProcessState.RETRY_SCHEDULED: {
        ProcessState.RUNNING,
        ProcessState.WAITING,
        ProcessState.BLOCKED,
        ProcessState.FAILED,
        ProcessState.CANCELLED,
        ProcessState.DEADLINE_EXCEEDED,
    },
    ProcessState.COMPENSATION_PENDING: {
        ProcessState.COMPENSATED,
        ProcessState.BLOCKED,
        ProcessState.FAILED,
        ProcessState.DEADLINE_EXCEEDED,
    },
    ProcessState.BLOCKED: {
        ProcessState.RUNNING,
        ProcessState.RETRY_SCHEDULED,
        ProcessState.COMPENSATION_PENDING,
        ProcessState.FAILED,
        ProcessState.CANCELLED,
        ProcessState.DEADLINE_EXCEEDED,
    },
    ProcessState.COMPLETED: set(),
    ProcessState.COMPENSATED: set(),
    ProcessState.FAILED: set(),
    ProcessState.CANCELLED: set(),
    ProcessState.DEADLINE_EXCEEDED: set(),
}


@pytest.mark.parametrize(
    ("previous", "current"),
    tuple(product(ProcessState, repeat=2)),
)
def test_process_transition_relation_is_exact(
    previous: ProcessState,
    current: ProcessState,
) -> None:
    allowed = current is previous or current in _PROCESS_ALLOWED[previous]

    if allowed:
        evidence = (
            DeadlineTerminalEvidence.RESIDUAL_WRITES_DURABLY_FENCED
            if current is ProcessState.DEADLINE_EXCEEDED and current is not previous
            else None
        )
        validate_process_transition(
            previous,
            current,
            deadline_evidence=evidence,
        )
    else:
        with pytest.raises(ValueError, match="not allowed"):
            validate_process_transition(previous, current)


@pytest.mark.parametrize(
    "evidence",
    tuple(DeadlineTerminalEvidence),
)
def test_owner_deadline_terminal_requires_exit_or_fence_evidence(
    evidence: DeadlineTerminalEvidence,
) -> None:
    validate_operation_transition(
        OperationState.RUNNING,
        OperationState.DEADLINE_EXCEEDED,
        deadline_evidence=evidence,
    )
    validate_process_transition(
        ProcessState.RUNNING,
        ProcessState.DEADLINE_EXCEEDED,
        deadline_evidence=evidence,
    )

    with pytest.raises(ValueError, match="worker-exit or durable-fence"):
        validate_operation_transition(
            OperationState.RUNNING,
            OperationState.DEADLINE_EXCEEDED,
        )
    with pytest.raises(ValueError, match="worker-exit or durable-fence"):
        validate_process_transition(
            ProcessState.RUNNING,
            ProcessState.DEADLINE_EXCEEDED,
        )


def test_caller_observation_timeout_cannot_create_owner_deadline_terminal() -> None:
    timeout = _generic_error(
        category=ErrorCategory.TIMEOUT,
        observation=ObservationState.NOT_OBSERVED,
    )

    status = QueryStatus(
        observation_state=ObservationState.NOT_OBSERVED,
        condition=None,
        error=timeout,
    )

    assert status.observation_state is ObservationState.NOT_OBSERVED
    with pytest.raises(ValueError, match="worker-exit or durable-fence"):
        validate_process_transition(
            ProcessState.RUNNING,
            ProcessState.DEADLINE_EXCEEDED,
        )


@pytest.mark.parametrize("state", tuple(OperationState))
def test_operation_receipt_terminal_time_product(state: OperationState) -> None:
    terminal_at = _instant(1) if state.is_terminal else None

    receipt = _operation_receipt(state=state, terminal_at=terminal_at)

    assert receipt.terminal_at is terminal_at
    with pytest.raises(ValueError, match="terminal"):
        replace(receipt, terminal_at=None if terminal_at is not None else _instant(1))


def test_operation_receipt_requires_typed_domains_and_causal_identity() -> None:
    receipt = _operation_receipt()

    with pytest.raises(ValueError, match="command fingerprint domain"):
        replace(
            receipt,
            command_fingerprint=_fingerprint(FingerprintDomain.IDEMPOTENCY, "c"),
        )
    with pytest.raises(ValueError, match="idempotency fingerprint domain"):
        replace(
            receipt,
            idempotency_fingerprint=_fingerprint(FingerprintDomain.COMMAND, "d"),
        )
    with pytest.raises(ValueError, match="root operation correlation"):
        replace(receipt, correlation_id=_id("message", "other"))


def test_operation_receipt_transition_preserves_admission_identity() -> None:
    accepted = _operation_receipt(process_id=None)
    running = replace(
        accepted,
        state=OperationState.RUNNING,
        reason_code="OPERATION_RUNNING",
        updated_at=_instant(2),
        process_id=_id("process", "one"),
    )

    validate_operation_receipt_transition(accepted, running)
    with pytest.raises(ValueError, match="request_message_id"):
        validate_operation_receipt_transition(
            accepted,
            replace(
                running,
                request_message_id=_id("message", "duplicate"),
                correlation_id=_id("message", "duplicate"),
            ),
        )
    with pytest.raises(ValueError, match="process link"):
        validate_operation_receipt_transition(
            running,
            replace(running, updated_at=_instant(3), process_id=_id("process", "two")),
        )


def test_terminal_operation_receipt_is_immutable() -> None:
    completed = _operation_receipt(
        state=OperationState.COMPLETED,
        reason_code="OPERATION_COMPLETED",
        terminal_at=_instant(2),
        updated_second=2,
    )

    validate_operation_receipt_transition(completed, completed)
    with pytest.raises(ValueError, match="terminal operation receipt"):
        validate_operation_receipt_transition(
            completed,
            replace(completed, updated_at=_instant(3)),
        )


_ADMISSION_PRODUCTS = {
    "REPLAY_OPERATION_NOT_FOUND": (
        ErrorCategory.INVALID,
        ObservationState.OBSERVED,
        False,
        None,
        True,
    ),
    "REPLAY_ADMISSION_CONFLICT": (
        ErrorCategory.CONFLICT,
        ObservationState.OBSERVED,
        False,
        None,
        True,
    ),
    "REPLAY_AUDIT_CLOCK_UNAVAILABLE": (
        ErrorCategory.UNAVAILABLE,
        ObservationState.UNAVAILABLE,
        True,
        250,
        False,
    ),
    "REPLAY_AUDIT_UNAVAILABLE": (
        ErrorCategory.UNAVAILABLE,
        ObservationState.UNAVAILABLE,
        True,
        250,
        True,
    ),
    "IDEMPOTENCY_COMMAND_CONFLICT": (
        ErrorCategory.CONFLICT,
        ObservationState.OBSERVED,
        False,
        None,
        True,
    ),
    "IDEMPOTENCY_CLAIM_CORRUPT": (
        ErrorCategory.INTERNAL,
        ObservationState.OBSERVED,
        False,
        None,
        True,
    ),
    "IDEMPOTENCY_KEYSET_CONTENTION": (
        ErrorCategory.UNAVAILABLE,
        ObservationState.UNAVAILABLE,
        True,
        250,
        True,
    ),
    "IDEMPOTENCY_AUDIT_UNAVAILABLE": (
        ErrorCategory.UNAVAILABLE,
        ObservationState.UNAVAILABLE,
        True,
        250,
        True,
    ),
}


@pytest.mark.parametrize(
    ("reason", "expected"),
    tuple(_ADMISSION_PRODUCTS.items()),
)
def test_admission_error_products_are_exact(
    reason: str,
    expected: tuple[
        ErrorCategory,
        ObservationState,
        bool,
        int | None,
        bool,
    ],
) -> None:
    category, observation, retryable, retry_after, has_occurred_at = expected
    request = _id("message", "request")

    error = make_admission_error(
        reason_code=reason,
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        occurred_at=_instant() if has_occurred_at else None,
        safe_message="The operation was refused safely.",
        retry_after_ms=retry_after,
    )

    assert (
        error.category,
        error.observation_state,
        error.retryable,
        error.retry_after_ms,
        error.occurred_at is not None,
    ) == expected
    assert error.operation_id is None
    assert error.process_id is None


def test_admission_error_rejects_wrong_product_and_public_links() -> None:
    request = _id("message", "request")
    error = make_admission_error(
        reason_code="IDEMPOTENCY_COMMAND_CONFLICT",
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        occurred_at=_instant(),
        safe_message="The idempotency identity belongs to another command.",
    )

    with pytest.raises(ValueError, match="invalid error category"):
        replace(error, category=ErrorCategory.INTERNAL)
    with pytest.raises(ValueError, match="forbids retry_after"):
        replace(error, retry_after_ms=1)
    with pytest.raises(ValueError, match="forbids operation"):
        replace(error, operation_id=_id("operation", "hidden"))


def test_clock_unavailable_is_the_only_clockless_error() -> None:
    request = _id("message", "request")
    clockless = make_admission_error(
        reason_code="REPLAY_AUDIT_CLOCK_UNAVAILABLE",
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        occurred_at=None,
        safe_message="The trusted replay audit clock is unavailable.",
        retry_after_ms=100,
    )

    assert clockless.occurred_at is None
    with pytest.raises(ValueError, match="must not contain occurred_at"):
        replace(clockless, occurred_at=_instant())
    with pytest.raises(ValueError, match="occurred_at is required"):
        _generic_error(
            category=ErrorCategory.INTERNAL,
            observation=ObservationState.UNKNOWN,
        ).__class__(
            **{
                **{
                    field.name: getattr(
                        _generic_error(
                            category=ErrorCategory.INTERNAL,
                            observation=ObservationState.UNKNOWN,
                        ),
                        field.name,
                    )
                    for field in fields(ErrorEnvelope)
                },
                "occurred_at": None,
            }
        )


_QUERY_PRODUCTS = (
    (ObservationState.OBSERVED, QueryCondition.PRESENT, None),
    (ObservationState.OBSERVED, QueryCondition.EMPTY, None),
    (
        ObservationState.OBSERVED,
        QueryCondition.PARTIAL,
        ErrorCategory.UNAVAILABLE,
    ),
    (ObservationState.OBSERVED, QueryCondition.STALE, ErrorCategory.STALE),
    (
        ObservationState.OBSERVED,
        QueryCondition.QUARANTINED,
        ErrorCategory.QUARANTINED,
    ),
    (ObservationState.OBSERVED, QueryCondition.BLOCKED, ErrorCategory.BLOCKED),
    (ObservationState.NOT_OBSERVED, None, ErrorCategory.TIMEOUT),
    (ObservationState.UNAVAILABLE, None, ErrorCategory.UNAVAILABLE),
    (ObservationState.UNKNOWN, None, ErrorCategory.INTERNAL),
)


@pytest.mark.parametrize(
    ("observation", "condition", "category"),
    _QUERY_PRODUCTS,
)
def test_query_status_accepts_only_the_closed_products(
    observation: ObservationState,
    condition: QueryCondition | None,
    category: ErrorCategory | None,
) -> None:
    error = None if category is None else _generic_error(category=category, observation=observation)

    status = QueryStatus(
        observation_state=observation,
        condition=condition,
        error=error,
    )

    assert status.condition is condition


def test_query_status_rejects_mismatched_condition_error_and_observation() -> None:
    timeout = _generic_error(
        category=ErrorCategory.TIMEOUT,
        observation=ObservationState.NOT_OBSERVED,
    )

    with pytest.raises(ValueError, match="forbids a condition"):
        QueryStatus(
            observation_state=ObservationState.NOT_OBSERVED,
            condition=QueryCondition.EMPTY,
            error=timeout,
        )
    with pytest.raises(ValueError, match="requires an error"):
        QueryStatus(
            observation_state=ObservationState.OBSERVED,
            condition=QueryCondition.PARTIAL,
            error=None,
        )
    with pytest.raises(ValueError, match="category"):
        QueryStatus(
            observation_state=ObservationState.OBSERVED,
            condition=QueryCondition.BLOCKED,
            error=_generic_error(
                category=ErrorCategory.UNAVAILABLE,
                observation=ObservationState.OBSERVED,
            ),
        )
    with pytest.raises(ValueError, match="observation"):
        QueryStatus(
            observation_state=ObservationState.UNKNOWN,
            condition=None,
            error=_generic_error(
                category=ErrorCategory.INTERNAL,
                observation=ObservationState.OBSERVED,
            ),
        )


@pytest.mark.parametrize(
    ("observation", "condition", "category"),
    tuple(
        product(
            ObservationState,
            (None, *tuple(QueryCondition)),
            (None, *tuple(ErrorCategory)),
        )
    ),
)
def test_query_status_rejects_every_unlisted_product(
    observation: ObservationState,
    condition: QueryCondition | None,
    category: ErrorCategory | None,
) -> None:
    valid_products = {
        (listed_observation, listed_condition, listed_category)
        for listed_observation, listed_condition, listed_category in _QUERY_PRODUCTS
    }
    error = None if category is None else _generic_error(category=category, observation=observation)

    if (observation, condition, category) in valid_products:
        QueryStatus(
            observation_state=observation,
            condition=condition,
            error=error,
        )
    else:
        with pytest.raises(ValueError):
            QueryStatus(
                observation_state=observation,
                condition=condition,
                error=error,
            )


def test_process_start_key_is_owner_local_exact_identity() -> None:
    key = ProcessStartKeyV1(
        schema_version=1,
        process_type="refresh_dataset",
        triggering_operation_id=_id("operation", "one"),
        workflow_key=ContentDigest.from_bytes(b"immutable-workflow"),
    )

    assert key.canonical_bytes() == (
        b'{"process_type":"refresh_dataset","schema_version":1,'
        b'"triggering_operation_id":{"namespace":"operation","value":"one"},'
        b'"workflow_key":{"algorithm":"sha256","value":'
        b'"8f70ca39102c2e9ce05ac89bc87a0f3ee3dc74c4683c1bc07e23df62dbc492d7"}}'
    )
    assert tuple(field.name for field in fields(key)) == (
        "schema_version",
        "process_type",
        "triggering_operation_id",
        "workflow_key",
    )


def test_history_window_empty_and_truncated_products_are_exact() -> None:
    assert _history() == HistoryWindow((), 0, 0, None, None, 0)
    items = tuple(_transition(sequence, ProcessState.RUNNING) for sequence in range(51, 101))

    window = _history(items, total_count=100)

    assert window.returned_count == 50
    assert window.first_sequence == 51
    assert window.last_sequence == 100
    assert window.omitted_before_count == 50


def test_history_window_rejects_inconsistent_or_decreasing_sequence() -> None:
    first = _transition(1, ProcessState.RUNNING)
    second = _transition(2, ProcessState.WAITING)

    with pytest.raises(ValueError, match="returned_count"):
        HistoryWindow((first,), 1, 0, 1, 1, 0)
    with pytest.raises(ValueError, match="omitted_before_count"):
        HistoryWindow((first,), 2, 1, 1, 1, 0)
    with pytest.raises(ValueError, match="strictly increasing"):
        HistoryWindow((second, first), 2, 2, 2, 1, 0)
    with pytest.raises(ValueError, match="strictly increasing"):
        HistoryWindow((first, replace(second, sequence=1)), 2, 2, 1, 1, 0)


@pytest.mark.parametrize(
    ("state", "reason_required", "reason_forbidden"),
    (
        (ProcessState.REQUESTED, False, True),
        (ProcessState.RUNNING, False, True),
        (ProcessState.WAITING, False, True),
        (ProcessState.RETRY_SCHEDULED, True, False),
        (ProcessState.COMPENSATION_PENDING, False, False),
        (ProcessState.COMPLETED, False, True),
        (ProcessState.COMPENSATED, False, True),
        (ProcessState.FAILED, True, False),
        (ProcessState.BLOCKED, True, False),
        (ProcessState.CANCELLED, True, False),
        (ProcessState.DEADLINE_EXCEEDED, True, False),
    ),
)
def test_process_reason_product_is_exact(
    state: ProcessState,
    reason_required: bool,
    reason_forbidden: bool,
) -> None:
    terminal_at = _instant(1) if state.is_terminal else None
    next_attempt = _instant(2) if state is ProcessState.RETRY_SCHEDULED else None
    reason = "PROCESS_STATE_REASON" if reason_required else None

    view = _process_view(
        state=state,
        reason_code=reason,
        terminal_at=terminal_at,
        next_attempt_at=next_attempt,
    )

    assert view.reason_code == reason
    if reason_required:
        with pytest.raises(ValueError, match="requires reason_code"):
            replace(view, reason_code=None)
    if reason_forbidden:
        with pytest.raises(ValueError, match="forbids reason_code"):
            replace(view, reason_code="UNEXPECTED_REASON")


def test_process_retry_product_and_terminal_time_are_truthful() -> None:
    scheduled = _process_view(
        state=ProcessState.RETRY_SCHEDULED,
        reason_code="RETRY_SCHEDULED",
        next_attempt_at=_instant(2),
        retry_count=1,
    )

    with pytest.raises(ValueError, match="requires next_attempt_at"):
        replace(scheduled, next_attempt_at=None)
    with pytest.raises(ValueError, match="only valid"):
        replace(
            scheduled,
            state=ProcessState.RUNNING,
            reason_code=None,
        )
    with pytest.raises(ValueError, match="cannot exceed retry_limit"):
        replace(scheduled, retry_count=4)
    with pytest.raises(ValueError, match="terminal process state requires"):
        _process_view(
            state=ProcessState.FAILED,
            reason_code="PROCESS_FAILED",
            terminal_at=None,
        )


def test_recovery_actions_are_closed_bounded_and_informational() -> None:
    actions = tuple(
        RecoveryActionDescriptor(
            owner_namespace=IdNamespace("processes"),
            action=action,
            target_id=_id("process", f"target-{index}"),
            policy_namespace=IdNamespace("processes.recovery"),
            policy_version="1.0.0",
            reason_code="RECOVERY_ALLOWED",
            expires_at=_instant(30),
            required_actor_scope="process.recover",
        )
        for index, action in enumerate(RecoveryAction)
    )

    view = replace(_process_view(), permitted_recovery_actions=actions)

    assert {item.action for item in view.permitted_recovery_actions} == set(RecoveryAction)
    assert "redrive" not in {item.action.value for item in actions}
    with pytest.raises(ValueError, match="at most 16"):
        replace(view, permitted_recovery_actions=actions * 3)


def test_process_view_exposes_no_owner_idempotency_material() -> None:
    public_fields = {field.name for field in fields(ProcessView)}

    assert public_fields.isdisjoint(
        {
            "process_start_key",
            "workflow_key",
            "idempotency_key",
            "idempotency_fingerprint",
            "raw_key",
            "secret",
        }
    )


def test_process_view_transition_preserves_identity_and_terminal_facts() -> None:
    running = _process_view()
    completed = replace(
        running,
        state=ProcessState.COMPLETED,
        current_step="workspace.done",
        updated_at=_instant(2),
        terminal_at=_instant(2),
    )

    validate_process_view_transition(running, completed)
    validate_process_view_transition(completed, completed)
    with pytest.raises(ValueError, match="triggering_operation_id"):
        validate_process_view_transition(
            running,
            replace(completed, triggering_operation_id=_id("operation", "other")),
        )
    with pytest.raises(ValueError, match="terminal process view"):
        validate_process_view_transition(
            completed,
            replace(completed, updated_at=_instant(3)),
        )


@pytest.mark.parametrize(
    ("reason", "versions"),
    (
        ("IDEMPOTENCY_COMMAND_CONFLICT", (2,)),
        ("IDEMPOTENCY_CLAIM_CORRUPT", (1, 2)),
        ("IDEMPOTENCY_KEYSET_CONTENTION", ()),
    ),
)
def test_refusal_audit_contains_only_allowlisted_bounded_evidence(
    reason: str,
    versions: tuple[int, ...],
) -> None:
    request = _id("message", "request")
    audit = AdmissionRefusalAuditV1(
        schema_name="trade.idempotency_refusal_audit",
        schema_version=1,
        reason_code=reason,
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        owner_namespace=IdNamespace("platform"),
        matched_key_versions=versions,
        key_set_generation=8,
        attempt_count=3,
        occurred_at=_instant(),
    )

    assert {field.name for field in fields(audit)} == {
        "schema_name",
        "schema_version",
        "reason_code",
        "request_message_id",
        "correlation_id",
        "causation_id",
        "owner_namespace",
        "matched_key_versions",
        "key_set_generation",
        "attempt_count",
        "occurred_at",
    }


def test_refusal_audit_rejects_corrupt_key_evidence_and_attempt_overflow() -> None:
    request = _id("message", "request")
    common = {
        "schema_name": "trade.idempotency_refusal_audit",
        "schema_version": 1,
        "request_message_id": request,
        "correlation_id": request,
        "causation_id": None,
        "owner_namespace": IdNamespace("platform"),
        "key_set_generation": 8,
        "occurred_at": _instant(),
    }

    with pytest.raises(ValueError, match="one matched key"):
        AdmissionRefusalAuditV1(
            **common,
            reason_code="IDEMPOTENCY_COMMAND_CONFLICT",
            matched_key_versions=(),
            attempt_count=1,
        )
    with pytest.raises(ValueError, match="sorted and unique"):
        AdmissionRefusalAuditV1(
            **common,
            reason_code="IDEMPOTENCY_CLAIM_CORRUPT",
            matched_key_versions=(2, 1),
            attempt_count=1,
        )
    with pytest.raises(ValueError, match="1..3"):
        AdmissionRefusalAuditV1(
            **common,
            reason_code="IDEMPOTENCY_KEYSET_CONTENTION",
            matched_key_versions=(),
            attempt_count=4,
        )


@pytest.mark.parametrize(
    ("reason", "outcome", "versions"),
    (
        (
            "IDEMPOTENCY_COMMAND_CONFLICT",
            AdmissionOutcome.COMMAND_CONFLICT,
            (1,),
        ),
        (
            "IDEMPOTENCY_CLAIM_CORRUPT",
            AdmissionOutcome.CLAIM_CORRUPT,
            (1, 2),
        ),
        (
            "IDEMPOTENCY_KEYSET_CONTENTION",
            AdmissionOutcome.KEYSET_CONTENTION,
            (),
        ),
        (
            "IDEMPOTENCY_AUDIT_UNAVAILABLE",
            AdmissionOutcome.AUDIT_UNAVAILABLE,
            (1,),
        ),
    ),
)
def test_refusal_event_is_one_bounded_allowlisted_terminal_product(
    reason: str,
    outcome: AdmissionOutcome,
    versions: tuple[int, ...],
) -> None:
    request = _id("message", "request")
    event = AdmissionRefusalEventV1(
        schema_name="trade.idempotency_admission_refusal",
        schema_version=1,
        reason_code=reason,
        outcome=outcome,
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        owner_namespace=IdNamespace("platform"),
        matched_key_versions=versions,
        key_set_generation=7,
        attempt_count=3,
    )

    assert {field.name for field in fields(event)} == {
        "schema_name",
        "schema_version",
        "reason_code",
        "outcome",
        "request_message_id",
        "correlation_id",
        "causation_id",
        "owner_namespace",
        "matched_key_versions",
        "key_set_generation",
        "attempt_count",
    }


def test_admission_metric_has_one_closed_counter_and_two_labels() -> None:
    labels = AdmissionOutcomeLabels(
        owner_namespace=IdNamespace("platform"),
        outcome=AdmissionOutcome.CREATED,
    )

    assert ADMISSION_OUTCOME_COUNTER_NAME == ("platform_idempotency_admission_outcomes_total")
    assert tuple(field.name for field in fields(labels)) == (
        "owner_namespace",
        "outcome",
    )
    assert {outcome.value for outcome in AdmissionOutcome} == {
        "created",
        "replayed",
        "command_conflict",
        "claim_corrupt",
        "keyset_contention",
        "audit_unavailable",
    }


def test_refusal_event_rejects_reason_outcome_and_evidence_mismatch() -> None:
    request = _id("message", "request")
    event = AdmissionRefusalEventV1(
        schema_name="trade.idempotency_admission_refusal",
        schema_version=1,
        reason_code="IDEMPOTENCY_COMMAND_CONFLICT",
        outcome=AdmissionOutcome.COMMAND_CONFLICT,
        request_message_id=request,
        correlation_id=request,
        causation_id=None,
        owner_namespace=IdNamespace("platform"),
        matched_key_versions=(1,),
        key_set_generation=7,
        attempt_count=1,
    )

    with pytest.raises(ValueError, match="outcome does not match"):
        replace(event, outcome=AdmissionOutcome.CLAIM_CORRUPT)
    with pytest.raises(ValueError, match="one matched key"):
        replace(event, matched_key_versions=())
    with pytest.raises(ValueError, match="at most four"):
        replace(event, matched_key_versions=(1, 2, 3, 4, 5))
