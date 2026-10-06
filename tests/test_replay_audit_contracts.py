from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal

import pytest

from trade.kernel.digest import ContentDigest
from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import Deadline, UtcInstant
from trade.platform.contracts.actor import (
    ActorAssurance,
    ActorContext,
    ActorOrigin,
    ActorProvenanceRef,
    PolicyRefV1,
    PrincipalKind,
    ProvenanceType,
    derive_idempotency_subject,
)
from trade.platform.contracts.errors import make_admission_error
from trade.platform.contracts.messages import (
    FingerprintDomain,
    FingerprintV1,
    ReplayAdmissionV1,
    ReplayContextV1,
)
from trade.platform.contracts.operations import (
    OperationReceipt,
    OperationState,
    ReplayAdmissionBindingDigestV1,
    ReplayAuditFactV1,
    ReplayAuditFailureKind,
    ReplayAuditHealthSignalV1,
    ReplayAuditKey,
    ReplayAuditOutcome,
    ReplayAuditOwnerPort,
    ReplayAuditOwnerResult,
    ReplayAuditResourceUsage,
    canonical_replay_audit_fact_bytes,
    derive_replay_admission_binding_digest,
)

_OWNER = IdNamespace("platform")
_FailureMode = Literal[
    "none",
    "transaction_start",
    "transaction_commit",
    "clock",
    "persistence",
    "crash_before_commit",
    "crash_after_commit",
]


def _id(namespace: str, value: str) -> OpaqueId:
    return OpaqueId(IdNamespace(namespace), value)


def _instant(second: int = 0) -> UtcInstant:
    return UtcInstant(
        datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=second)
    )


_ERROR_TIME = _instant(20)


def _actor(
    *,
    principal: str,
    scopes: tuple[str, ...],
    assurance: ActorAssurance = ActorAssurance.VERIFIED,
) -> ActorContext:
    provenance = ActorProvenanceRef(
        provenance_type=ProvenanceType.CLI_PROCESS,
        verifier_namespace=IdNamespace("platform.cli"),
        evidence_id=_id("session", f"{principal}-session"),
        established_at=_instant(),
        expires_at=None,
        reason_code="trusted.cli",
    )
    return ActorContext(
        schema_version=1,
        origin=ActorOrigin.CLI,
        principal_kind=PrincipalKind.AUTHENTICATED,
        principal_id=_id("principal", principal),
        authority_scopes=scopes,
        delegation_chain=(),
        assurance=assurance,
        provenance=provenance,
        established_at=_instant(),
    )


def _policy(*, marker: bytes = b"replay-policy") -> PolicyRefV1:
    return PolicyRefV1(
        policy_namespace=IdNamespace("platform.replay"),
        policy_name="direct.redispatch",
        semantic_version="1.0.0",
        content_digest=ContentDigest.from_bytes(marker),
    )


def _deadline(*, marker: int = 0) -> Deadline:
    return Deadline(
        wall_clock_expires_at=_instant(30 + marker),
        monotonic_expires_at=130.0 + marker,
    )


def _fingerprint(domain: FingerprintDomain, marker: str) -> FingerprintV1:
    return FingerprintV1(
        algorithm="hmac-sha256-v1",
        domain=domain,
        key_version=1,
        value=(marker * 64)[:64],
    )


def _receipt(
    *,
    historical_message_id: OpaqueId | None = None,
    operation_id: OpaqueId | None = None,
) -> OperationReceipt:
    historical_message_id = historical_message_id or _id("message", "historical")
    return OperationReceipt(
        schema_name="trade.operation_receipt",
        schema_version=1,
        operation_id=operation_id or _id("operation", "existing"),
        operation_kind="dataset.refresh",
        command_name="refresh_dataset",
        command_fingerprint=_fingerprint(FingerprintDomain.COMMAND, "a"),
        actor=_actor(principal="historical-operator", scopes=("dataset.refresh",)),
        request_message_id=historical_message_id,
        correlation_id=historical_message_id,
        causation_id=None,
        idempotency_scope="dataset.refresh",
        idempotency_fingerprint=_fingerprint(FingerprintDomain.IDEMPOTENCY, "b"),
        state=OperationState.COMPLETED,
        reason_code="OPERATION_COMPLETED",
        accepted_at=_instant(),
        updated_at=_instant(2),
        terminal_at=_instant(2),
        process_id=_id("process", "historical-process"),
    )


def _admission(
    *,
    request: str = "replay-request",
    child: bool = False,
    deadline_marker: int = 0,
) -> ReplayAdmissionV1:
    historical_message_id = _id("message", "historical")
    replay_request_message_id = _id("message", request)
    initiator = _actor(
        principal="current-operator",
        scopes=("operation.replay",),
    )
    context = ReplayContextV1(
        schema_version=1,
        replay_request_message_id=replay_request_message_id,
        replay_request_correlation_id=(
            _id("message", "replay-root") if child else replay_request_message_id
        ),
        replay_request_causation_id=(_id("message", "replay-parent") if child else None),
        historical_message_id=historical_message_id,
        historical_actor=_actor(
            principal="historical-operator",
            scopes=("legacy.admin",),
            assurance=ActorAssurance.UNVERIFIED,
        ),
        replay_initiator=initiator,
        replay_policy=_policy(),
    )
    return ReplayAdmissionV1(
        schema_version=1,
        context=context,
        historical_message_id=historical_message_id,
        historical_correlation_id=historical_message_id,
        historical_causation_id=None,
        historical_envelope_digest=ContentDigest.from_bytes(b"historical-envelope"),
        historical_operation_id=_id("operation", "existing"),
        current_subject=derive_idempotency_subject(
            actor=initiator,
            owner_namespace=_OWNER,
            tenant_id=_id("tenant", "one"),
        ),
        deadline=_deadline(marker=deadline_marker),
    )


def _usage(
    *,
    transaction: int,
    audit_key: int,
    operation: int,
    clock: int = 0,
    commit: int = 0,
    health: int = 0,
) -> ReplayAuditResourceUsage:
    return ReplayAuditResourceUsage(
        transaction_count=transaction,
        audit_key_lookup_count=audit_key,
        operation_lookup_count=operation,
        audit_clock_attempt_count=clock,
        audit_commit_count=commit,
        persistence_retry_count=0,
        background_continuation_count=0,
        health_signal_count=health,
    )


@dataclass(frozen=True, slots=True)
class _StoredReplay:
    binding_digest: ReplayAdmissionBindingDigestV1
    fact: ReplayAuditFactV1
    receipt: OperationReceipt


class _InjectedCrash(RuntimeError):
    pass


class _FakeTrustedClock:
    def __init__(self, values: list[UtcInstant | None]) -> None:
        self._values = values
        self.call_count = 0

    def sample(self) -> UtcInstant:
        self.call_count += 1
        value = self._values.pop(0)
        if value is None:
            raise RuntimeError("trusted clock unavailable")
        return value


class _FakeReplayOwner(ReplayAuditOwnerPort):
    def __init__(
        self,
        *,
        receipt: OperationReceipt | None,
        clock: _FakeTrustedClock,
    ) -> None:
        self.receipt = receipt
        self.clock = clock
        self.audits: dict[tuple[IdNamespace, OpaqueId], _StoredReplay] = {}
        self.events: list[str] = []
        self.failure_mode: _FailureMode = "none"
        self.error_time = _instant(20)

    def resolve_authorized_replay(
        self,
        *,
        owner_namespace: IdNamespace,
        admission: ReplayAdmissionV1,
        binding_digest: ReplayAdmissionBindingDigestV1,
    ) -> ReplayAuditOwnerResult:
        context = admission.context
        if self.failure_mode == "transaction_start":
            return self._unavailable(
                admission=admission,
                owner_namespace=owner_namespace,
                outcome=ReplayAuditOutcome.TRANSACTION_UNAVAILABLE,
                failure_kind=ReplayAuditFailureKind.TRANSACTION_UNAVAILABLE,
                usage=_usage(
                    transaction=0,
                    audit_key=0,
                    operation=0,
                    health=1,
                ),
            )

        self.events.append("transaction_started")
        self.events.append("audit_key_lookup")
        key = ReplayAuditKey(
            owner_namespace=owner_namespace,
            replay_request_message_id=context.replay_request_message_id,
        )
        existing = self.audits.get(key.storage_key)
        if existing is not None:
            if existing.binding_digest != binding_digest:
                return ReplayAuditOwnerResult(
                    outcome=ReplayAuditOutcome.ADMISSION_CONFLICT,
                    receipt=None,
                    audit_fact=None,
                    error=self._error(
                        admission=admission,
                        reason="REPLAY_ADMISSION_CONFLICT",
                        occurred_at=self.error_time,
                    ),
                    health_signal=None,
                    resource_usage=_usage(
                        transaction=1,
                        audit_key=1,
                        operation=0,
                    ),
                )
            self.events.append("operation_lookup")
            return ReplayAuditOwnerResult(
                outcome=ReplayAuditOutcome.RESOLVED_EXISTING_AUDIT,
                receipt=existing.receipt,
                audit_fact=existing.fact,
                error=None,
                health_signal=None,
                resource_usage=_usage(
                    transaction=1,
                    audit_key=1,
                    operation=1,
                ),
            )

        self.events.append("operation_lookup")
        if self.receipt is None or self.receipt.operation_id != admission.historical_operation_id:
            return ReplayAuditOwnerResult(
                outcome=ReplayAuditOutcome.OPERATION_NOT_FOUND,
                receipt=None,
                audit_fact=None,
                error=self._error(
                    admission=admission,
                    reason="REPLAY_OPERATION_NOT_FOUND",
                    occurred_at=self.error_time,
                ),
                health_signal=None,
                resource_usage=_usage(
                    transaction=1,
                    audit_key=1,
                    operation=1,
                ),
            )

        self.events.append("audit_clock_sample")
        try:
            occurred_at = self.clock.sample()
        except RuntimeError:
            return self._unavailable(
                admission=admission,
                owner_namespace=owner_namespace,
                outcome=ReplayAuditOutcome.CLOCK_UNAVAILABLE,
                failure_kind=ReplayAuditFailureKind.CLOCK_UNAVAILABLE,
                usage=_usage(
                    transaction=1,
                    audit_key=1,
                    operation=1,
                    clock=1,
                    health=1,
                ),
                occurred_at=None,
            )

        fact = ReplayAuditFactV1(
            schema_name="trade.replay_audit",
            schema_version=1,
            owner_namespace=owner_namespace,
            replay_request_message_id=context.replay_request_message_id,
            replay_request_correlation_id=context.replay_request_correlation_id,
            replay_request_causation_id=context.replay_request_causation_id,
            historical_message_id=admission.historical_message_id,
            historical_operation_id=admission.historical_operation_id,
            historical_envelope_digest=admission.historical_envelope_digest,
            admission_binding_digest=binding_digest,
            current_safe_principal_id=context.replay_initiator.principal_id,
            replay_policy=context.replay_policy,
            outcome="resolved",
            occurred_at=occurred_at,
        )
        self.events.append("audit_fact_constructed")
        if self.failure_mode == "crash_before_commit":
            raise _InjectedCrash("before replay audit commit")
        if self.failure_mode == "transaction_commit":
            return self._unavailable(
                admission=admission,
                owner_namespace=owner_namespace,
                outcome=ReplayAuditOutcome.TRANSACTION_UNAVAILABLE,
                failure_kind=ReplayAuditFailureKind.TRANSACTION_UNAVAILABLE,
                usage=_usage(
                    transaction=1,
                    audit_key=1,
                    operation=1,
                    clock=1,
                    health=1,
                ),
            )
        if self.failure_mode == "persistence":
            return self._unavailable(
                admission=admission,
                owner_namespace=owner_namespace,
                outcome=ReplayAuditOutcome.PERSISTENCE_UNAVAILABLE,
                failure_kind=ReplayAuditFailureKind.PERSISTENCE_UNAVAILABLE,
                usage=_usage(
                    transaction=1,
                    audit_key=1,
                    operation=1,
                    clock=1,
                    health=1,
                ),
            )

        self.events.append("audit_committed")
        self.audits[key.storage_key] = _StoredReplay(binding_digest, fact, self.receipt)
        if self.failure_mode == "crash_after_commit":
            raise _InjectedCrash("after replay audit commit")
        return ReplayAuditOwnerResult(
            outcome=ReplayAuditOutcome.RESOLVED_NEW_AUDIT,
            receipt=self.receipt,
            audit_fact=fact,
            error=None,
            health_signal=None,
            resource_usage=_usage(
                transaction=1,
                audit_key=1,
                operation=1,
                clock=1,
                commit=1,
            ),
        )

    def _unavailable(
        self,
        *,
        admission: ReplayAdmissionV1,
        owner_namespace: IdNamespace,
        outcome: ReplayAuditOutcome,
        failure_kind: ReplayAuditFailureKind,
        usage: ReplayAuditResourceUsage,
        occurred_at: UtcInstant | None = _ERROR_TIME,
    ) -> ReplayAuditOwnerResult:
        reason = (
            "REPLAY_AUDIT_CLOCK_UNAVAILABLE"
            if failure_kind is ReplayAuditFailureKind.CLOCK_UNAVAILABLE
            else "REPLAY_AUDIT_UNAVAILABLE"
        )
        return ReplayAuditOwnerResult(
            outcome=outcome,
            receipt=None,
            audit_fact=None,
            error=self._error(
                admission=admission,
                reason=reason,
                occurred_at=occurred_at,
            ),
            health_signal=ReplayAuditHealthSignalV1(
                schema_name="trade.replay_audit_health",
                schema_version=1,
                owner_namespace=owner_namespace,
                replay_request_message_id=(admission.context.replay_request_message_id),
                replay_request_correlation_id=(admission.context.replay_request_correlation_id),
                replay_request_causation_id=(admission.context.replay_request_causation_id),
                failure_kind=failure_kind,
            ),
            resource_usage=usage,
        )

    @staticmethod
    def _error(
        *,
        admission: ReplayAdmissionV1,
        reason: str,
        occurred_at: UtcInstant | None,
    ):
        context = admission.context
        return make_admission_error(
            reason_code=reason,
            request_message_id=context.replay_request_message_id,
            correlation_id=context.replay_request_correlation_id,
            causation_id=context.replay_request_causation_id,
            occurred_at=occurred_at,
            safe_message="The replay request could not be resolved safely.",
            retry_after_ms=250 if "UNAVAILABLE" in reason else None,
        )


class _FakeReplayAdapter:
    def __init__(self, owner: _FakeReplayOwner) -> None:
        self.owner = owner
        self.authorization_count = 0

    def replay(
        self,
        admission: ReplayAdmissionV1,
        *,
        authorized: bool = True,
    ) -> ReplayAuditOwnerResult:
        self.authorization_count += 1
        self.owner.events.append("authorized" if authorized else "denied")
        if not authorized:
            raise PermissionError("replay admission denied")
        return self.owner.resolve_authorized_replay(
            owner_namespace=_OWNER,
            admission=admission,
            binding_digest=derive_replay_admission_binding_digest(admission),
        )


def test_replay_binding_digest_is_domain_separated_and_excludes_only_deadline() -> None:
    admission = _admission()
    digest = derive_replay_admission_binding_digest(admission)

    assert digest.algorithm == "sha256"
    assert digest.domain == "trade.replay-admission-binding.v1"
    assert (
        digest.value
        == derive_replay_admission_binding_digest(
            replace(admission, deadline=_deadline(marker=10))
        ).value
    )
    assert digest.value == "db989f7e785bac64c75c5880b5c380191d55afe0a33ed8137294fc82251c5a8a"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: replace(
            item,
            historical_envelope_digest=ContentDigest.from_bytes(b"revised-envelope"),
        ),
        lambda item: replace(
            item,
            historical_operation_id=_id("operation", "other"),
        ),
        lambda item: replace(
            item,
            historical_correlation_id=_id("message", "historical-root"),
            historical_causation_id=_id("message", "historical-parent"),
        ),
        lambda item: replace(
            item,
            context=replace(
                item.context,
                replay_initiator=replace(
                    item.context.replay_initiator,
                    authority_scopes=("operation.replay", "operation.review"),
                ),
            ),
        ),
        lambda item: replace(
            item,
            context=replace(
                item.context,
                replay_policy=_policy(marker=b"revised-policy"),
            ),
        ),
        lambda item: replace(
            item,
            current_subject=replace(
                item.current_subject,
                tenant_id=_id("tenant", "two"),
            ),
        ),
    ],
    ids=(
        "historical-digest",
        "operation",
        "historical-identity",
        "current-actor",
        "policy",
        "current-subject",
    ),
)
def test_replay_binding_digest_changes_with_every_durable_binding(mutate) -> None:
    admission = _admission()

    assert derive_replay_admission_binding_digest(
        mutate(admission)
    ) != derive_replay_admission_binding_digest(admission)


def test_replay_audit_key_is_exact_owner_and_request_identity_tuple() -> None:
    admission = _admission()
    key = ReplayAuditKey(_OWNER, admission.context.replay_request_message_id)

    assert key.storage_key == (
        _OWNER,
        admission.context.replay_request_message_id,
    )
    assert len(key.storage_key) == 2


def test_new_replay_commits_audit_before_returning_unchanged_receipt() -> None:
    receipt = _receipt()
    clock = _FakeTrustedClock([_instant(10)])
    owner = _FakeReplayOwner(receipt=receipt, clock=clock)
    adapter = _FakeReplayAdapter(owner)
    admission = _admission()

    result = adapter.replay(admission)

    assert result.outcome is ReplayAuditOutcome.RESOLVED_NEW_AUDIT
    assert result.receipt is receipt
    assert result.audit_fact is not None
    assert result.audit_fact.occurred_at == _instant(10)
    assert result.audit_fact.current_safe_principal_id == (
        admission.context.replay_initiator.principal_id
    )
    assert owner.events == [
        "authorized",
        "transaction_started",
        "audit_key_lookup",
        "operation_lookup",
        "audit_clock_sample",
        "audit_fact_constructed",
        "audit_committed",
    ]
    assert result.resource_usage == _usage(
        transaction=1,
        audit_key=1,
        operation=1,
        clock=1,
        commit=1,
    )
    assert len(owner.audits) == 1


def test_same_binding_retry_uses_fresh_deadline_without_resampling_clock() -> None:
    receipt = _receipt()
    clock = _FakeTrustedClock([_instant(10), _instant(99)])
    owner = _FakeReplayOwner(receipt=receipt, clock=clock)
    adapter = _FakeReplayAdapter(owner)
    first = adapter.replay(_admission(deadline_marker=0))
    owner.events.clear()

    retried = adapter.replay(_admission(deadline_marker=15))

    assert retried.outcome is ReplayAuditOutcome.RESOLVED_EXISTING_AUDIT
    assert retried.receipt is receipt
    assert retried.audit_fact is first.audit_fact
    assert retried.audit_fact is not None
    assert retried.audit_fact.occurred_at == _instant(10)
    assert clock.call_count == 1
    assert len(owner.audits) == 1
    assert owner.events == [
        "authorized",
        "transaction_started",
        "audit_key_lookup",
        "operation_lookup",
    ]
    assert retried.resource_usage == _usage(
        transaction=1,
        audit_key=1,
        operation=1,
    )
    assert adapter.authorization_count == 2


def test_same_key_different_binding_conflicts_before_operation_lookup() -> None:
    receipt = _receipt()
    owner = _FakeReplayOwner(
        receipt=receipt,
        clock=_FakeTrustedClock([_instant(10)]),
    )
    adapter = _FakeReplayAdapter(owner)
    adapter.replay(_admission())
    owner.events.clear()
    changed = replace(
        _admission(),
        historical_envelope_digest=ContentDigest.from_bytes(b"changed"),
    )

    result = adapter.replay(changed)

    assert result.outcome is ReplayAuditOutcome.ADMISSION_CONFLICT
    assert result.error is not None
    assert result.error.reason_code == "REPLAY_ADMISSION_CONFLICT"
    assert result.receipt is None
    assert result.audit_fact is None
    assert "operation_lookup" not in owner.events
    assert owner.events == [
        "authorized",
        "transaction_started",
        "audit_key_lookup",
    ]
    assert not hasattr(result.error, "binding_digest")
    assert derive_replay_admission_binding_digest(changed).value not in repr(result)


def test_same_key_different_historical_identity_conflicts_before_operation_lookup() -> None:
    owner = _FakeReplayOwner(
        receipt=_receipt(),
        clock=_FakeTrustedClock([_instant(10)]),
    )
    adapter = _FakeReplayAdapter(owner)
    adapter.replay(_admission())
    owner.events.clear()
    changed = replace(
        _admission(),
        historical_correlation_id=_id("message", "historical-root"),
        historical_causation_id=_id("message", "historical-parent"),
    )

    result = adapter.replay(changed)

    assert result.outcome is ReplayAuditOutcome.ADMISSION_CONFLICT
    assert result.error is not None
    assert result.error.reason_code == "REPLAY_ADMISSION_CONFLICT"
    assert result.resource_usage == _usage(
        transaction=1,
        audit_key=1,
        operation=0,
    )
    assert owner.events == [
        "authorized",
        "transaction_started",
        "audit_key_lookup",
    ]


def test_missing_operation_creates_no_audit_receipt_or_claim() -> None:
    owner = _FakeReplayOwner(
        receipt=None,
        clock=_FakeTrustedClock([_instant(10)]),
    )

    result = _FakeReplayAdapter(owner).replay(_admission())

    assert result.outcome is ReplayAuditOutcome.OPERATION_NOT_FOUND
    assert result.error is not None
    assert result.error.reason_code == "REPLAY_OPERATION_NOT_FOUND"
    assert result.receipt is None
    assert result.audit_fact is None
    assert owner.audits == {}
    assert owner.clock.call_count == 0
    assert result.resource_usage == _usage(
        transaction=1,
        audit_key=1,
        operation=1,
    )


def test_authorization_denial_precedes_transaction_and_existence_disclosure() -> None:
    owner = _FakeReplayOwner(
        receipt=_receipt(),
        clock=_FakeTrustedClock([_instant(10)]),
    )
    adapter = _FakeReplayAdapter(owner)

    with pytest.raises(PermissionError, match="denied"):
        adapter.replay(_admission(), authorized=False)

    assert adapter.authorization_count == 1
    assert owner.events == ["denied"]
    assert owner.audits == {}
    assert owner.clock.call_count == 0


def test_child_replay_audit_preserves_current_direct_causation() -> None:
    admission = _admission(request="replay-child", child=True)
    owner = _FakeReplayOwner(
        receipt=_receipt(),
        clock=_FakeTrustedClock([_instant(10)]),
    )

    result = _FakeReplayAdapter(owner).replay(admission)

    assert result.audit_fact is not None
    assert result.audit_fact.replay_request_message_id == (
        admission.context.replay_request_message_id
    )
    assert result.audit_fact.replay_request_correlation_id == (
        admission.context.replay_request_correlation_id
    )
    assert result.audit_fact.replay_request_causation_id == (
        admission.context.replay_request_causation_id
    )


def test_child_replay_error_and_health_signal_preserve_current_direct_causation() -> None:
    admission = _admission(request="replay-child", child=True)
    owner = _FakeReplayOwner(
        receipt=_receipt(),
        clock=_FakeTrustedClock([None]),
    )

    result = _FakeReplayAdapter(owner).replay(admission)

    assert result.error is not None
    assert result.health_signal is not None
    assert (
        result.error.request_message_id,
        result.error.correlation_id,
        result.error.causation_id,
    ) == (
        admission.context.replay_request_message_id,
        admission.context.replay_request_correlation_id,
        admission.context.replay_request_causation_id,
    )
    assert (
        result.health_signal.replay_request_message_id,
        result.health_signal.replay_request_correlation_id,
        result.health_signal.replay_request_causation_id,
    ) == (
        admission.context.replay_request_message_id,
        admission.context.replay_request_correlation_id,
        admission.context.replay_request_causation_id,
    )


def test_single_and_persistent_clock_failure_never_fabricate_time() -> None:
    owner = _FakeReplayOwner(
        receipt=_receipt(),
        clock=_FakeTrustedClock([None, None]),
    )
    adapter = _FakeReplayAdapter(owner)

    for _ in range(2):
        result = adapter.replay(_admission())
        assert result.outcome is ReplayAuditOutcome.CLOCK_UNAVAILABLE
        assert result.error is not None
        assert result.error.reason_code == "REPLAY_AUDIT_CLOCK_UNAVAILABLE"
        assert result.error.occurred_at is None
        assert result.receipt is None
        assert result.audit_fact is None
        assert result.health_signal is not None
        assert result.health_signal.failure_kind is ReplayAuditFailureKind.CLOCK_UNAVAILABLE
        assert not hasattr(result.health_signal, "occurred_at")
        assert result.resource_usage == _usage(
            transaction=1,
            audit_key=1,
            operation=1,
            clock=1,
            health=1,
        )

    assert owner.audits == {}
    assert owner.clock.call_count == 2


@pytest.mark.parametrize(
    ("failure_mode", "outcome", "failure_kind", "expected_usage"),
    [
        (
            "transaction_start",
            ReplayAuditOutcome.TRANSACTION_UNAVAILABLE,
            ReplayAuditFailureKind.TRANSACTION_UNAVAILABLE,
            _usage(transaction=0, audit_key=0, operation=0, health=1),
        ),
        (
            "transaction_commit",
            ReplayAuditOutcome.TRANSACTION_UNAVAILABLE,
            ReplayAuditFailureKind.TRANSACTION_UNAVAILABLE,
            _usage(
                transaction=1,
                audit_key=1,
                operation=1,
                clock=1,
                health=1,
            ),
        ),
        (
            "persistence",
            ReplayAuditOutcome.PERSISTENCE_UNAVAILABLE,
            ReplayAuditFailureKind.PERSISTENCE_UNAVAILABLE,
            _usage(
                transaction=1,
                audit_key=1,
                operation=1,
                clock=1,
                health=1,
            ),
        ),
    ],
)
def test_transaction_and_persistence_failures_are_distinct_and_bounded(
    failure_mode: _FailureMode,
    outcome: ReplayAuditOutcome,
    failure_kind: ReplayAuditFailureKind,
    expected_usage: ReplayAuditResourceUsage,
) -> None:
    owner = _FakeReplayOwner(
        receipt=_receipt(),
        clock=_FakeTrustedClock([_instant(10)]),
    )
    owner.failure_mode = failure_mode

    result = _FakeReplayAdapter(owner).replay(_admission())

    assert result.outcome is outcome
    assert result.error is not None
    assert result.error.reason_code == "REPLAY_AUDIT_UNAVAILABLE"
    assert result.error.occurred_at == _instant(20)
    assert result.receipt is None
    assert result.audit_fact is None
    assert result.health_signal is not None
    assert result.health_signal.failure_kind is failure_kind
    assert result.resource_usage == expected_usage
    assert result.resource_usage.persistence_retry_count == 0
    assert result.resource_usage.background_continuation_count == 0
    assert owner.audits == {}


def test_crash_before_commit_leaves_no_audit_and_retry_can_commit() -> None:
    owner = _FakeReplayOwner(
        receipt=_receipt(),
        clock=_FakeTrustedClock([_instant(10), _instant(11)]),
    )
    adapter = _FakeReplayAdapter(owner)
    owner.failure_mode = "crash_before_commit"

    with pytest.raises(_InjectedCrash, match="before"):
        adapter.replay(_admission())

    assert owner.audits == {}
    owner.failure_mode = "none"
    recovered = adapter.replay(_admission(deadline_marker=1))
    assert recovered.outcome is ReplayAuditOutcome.RESOLVED_NEW_AUDIT
    assert recovered.audit_fact is not None
    assert recovered.audit_fact.occurred_at == _instant(11)
    assert owner.clock.call_count == 2


def test_crash_after_commit_recovers_same_audit_receipt_and_time() -> None:
    receipt = _receipt()
    owner = _FakeReplayOwner(
        receipt=receipt,
        clock=_FakeTrustedClock([_instant(10), _instant(99)]),
    )
    adapter = _FakeReplayAdapter(owner)
    owner.failure_mode = "crash_after_commit"

    with pytest.raises(_InjectedCrash, match="after"):
        adapter.replay(_admission())

    assert len(owner.audits) == 1
    stored = next(iter(owner.audits.values()))
    owner.failure_mode = "none"
    recovered = adapter.replay(_admission(deadline_marker=1))
    assert recovered.outcome is ReplayAuditOutcome.RESOLVED_EXISTING_AUDIT
    assert recovered.receipt is receipt
    assert recovered.audit_fact is stored.fact
    assert recovered.audit_fact is not None
    assert recovered.audit_fact.occurred_at == _instant(10)
    assert owner.clock.call_count == 1
    assert len(owner.audits) == 1


def test_replay_audit_fact_is_bounded_and_contains_only_allowlisted_fields() -> None:
    owner = _FakeReplayOwner(
        receipt=_receipt(),
        clock=_FakeTrustedClock([_instant(10)]),
    )
    result = _FakeReplayAdapter(owner).replay(_admission())
    assert result.audit_fact is not None

    canonical = canonical_replay_audit_fact_bytes(result.audit_fact)

    assert len(canonical) <= 2_048
    assert b'"outcome":"resolved"' in canonical
    assert b'"occurred_at":"2026-07-27T12:00:10.000000Z"' in canonical
    assert b"raw_key" not in canonical
    assert b"credential" not in canonical
    assert b"deadline" not in canonical
    assert b"process_id" not in canonical
    assert b"historical-operator" not in canonical


def test_resource_usage_and_result_products_fail_closed() -> None:
    with pytest.raises(ValueError, match="operation lookup requires"):
        _usage(transaction=1, audit_key=0, operation=1)
    with pytest.raises(ValueError, match="0..0"):
        ReplayAuditResourceUsage(
            transaction_count=1,
            audit_key_lookup_count=1,
            operation_lookup_count=1,
            audit_clock_attempt_count=1,
            audit_commit_count=0,
            persistence_retry_count=1,
            background_continuation_count=0,
            health_signal_count=0,
        )

    owner = _FakeReplayOwner(
        receipt=_receipt(),
        clock=_FakeTrustedClock([_instant(10)]),
    )
    resolved = _FakeReplayAdapter(owner).replay(_admission())
    assert resolved.audit_fact is not None
    assert resolved.receipt is not None
    with pytest.raises(ValueError, match="forbids error"):
        replace(
            resolved,
            error=make_admission_error(
                reason_code="REPLAY_ADMISSION_CONFLICT",
                request_message_id=_id("message", "request"),
                correlation_id=_id("message", "request"),
                causation_id=None,
                occurred_at=_instant(),
                safe_message="The replay binding conflicts.",
            ),
        )


def test_replay_audit_failure_allows_bounded_health_signal_delivery_failure() -> None:
    owner = _FakeReplayOwner(
        receipt=_receipt(),
        clock=_FakeTrustedClock([None]),
    )
    failed = _FakeReplayAdapter(owner).replay(_admission())
    assert failed.health_signal is not None

    without_signal = replace(
        failed,
        health_signal=None,
        resource_usage=replace(failed.resource_usage, health_signal_count=0),
    )

    assert without_signal.outcome is ReplayAuditOutcome.CLOCK_UNAVAILABLE
    assert without_signal.error is failed.error
    assert without_signal.health_signal is None
    assert without_signal.resource_usage.health_signal_count == 0


def test_replay_audit_health_signal_has_no_producer_timestamp() -> None:
    signal = ReplayAuditHealthSignalV1(
        schema_name="trade.replay_audit_health",
        schema_version=1,
        owner_namespace=_OWNER,
        replay_request_message_id=_id("message", "request"),
        replay_request_correlation_id=_id("message", "request"),
        replay_request_causation_id=None,
        failure_kind=ReplayAuditFailureKind.PERSISTENCE_UNAVAILABLE,
    )

    assert not hasattr(signal, "occurred_at")
    assert not hasattr(signal, "timestamp")
    assert tuple(kind.value for kind in ReplayAuditFailureKind) == (
        "clock_unavailable",
        "transaction_unavailable",
        "persistence_unavailable",
    )
