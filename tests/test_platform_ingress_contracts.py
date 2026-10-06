from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace

import pytest

from trade.kernel.digest import ContentDigest
from trade.kernel.envelope import EnvelopeMeta
from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import Deadline, DurationMs, UtcInstant
from trade.platform.contracts.actor import (
    ActorAssurance,
    ActorContext,
    ActorOrigin,
    ActorProvenanceRef,
    IdempotencySubjectV1,
    PolicyRefV1,
    PrincipalKind,
    ProvenanceType,
    derive_idempotency_subject,
)
from trade.platform.contracts.messages import (
    CodecContentPolicy,
    CommandEnvelope,
    FingerprintDomain,
    FingerprintKeySetV1,
    FingerprintV1,
    FrozenCodecRegistry,
    OwnerCodecDescriptor,
    PayloadPurpose,
    QueryEnvelope,
    ReplayAdmissionV1,
    ReplayContextV1,
    canonical_idempotency_subject_bytes,
    derive_command_fingerprint,
    derive_idempotency_fingerprint,
    frame_hmac_components,
)


def _instant(second: int = 0) -> UtcInstant:
    return UtcInstant.from_wire(f"2026-07-27T00:00:{second:02d}.000000Z")


def _id(namespace: str, value: str) -> OpaqueId:
    return OpaqueId(IdNamespace(namespace), value)


def _provenance(
    provenance_type: ProvenanceType,
    *,
    reason: str = "trusted_adapter",
    established_at: UtcInstant | None = None,
) -> ActorProvenanceRef:
    return ActorProvenanceRef(
        provenance_type=provenance_type,
        verifier_namespace=IdNamespace("platform.ingress"),
        evidence_id=_id("actor.evidence", provenance_type.value),
        established_at=established_at or _instant(),
        expires_at=None,
        reason_code=reason,
    )


def _actor(
    *,
    origin: ActorOrigin = ActorOrigin.CLI,
    principal_kind: PrincipalKind = PrincipalKind.AUTHENTICATED,
    principal_value: str = "alice",
    scopes: tuple[str, ...] = ("capture.request",),
    assurance: ActorAssurance = ActorAssurance.VERIFIED,
    provenance_type: ProvenanceType = ProvenanceType.CLI_PROCESS,
    delegation_chain: tuple[ActorProvenanceRef, ...] = (),
) -> ActorContext:
    return ActorContext(
        schema_version=1,
        origin=origin,
        principal_kind=principal_kind,
        principal_id=_id("principal", principal_value),
        authority_scopes=scopes,
        delegation_chain=delegation_chain,
        assurance=assurance,
        provenance=_provenance(provenance_type),
        established_at=_instant(),
    )


def _deadline() -> Deadline:
    return Deadline.from_duration(
        wall_clock_started_at=_instant(),
        monotonic_started_at=10.0,
        duration=DurationMs(5_000),
    )


def _codec(purpose: PayloadPurpose) -> OwnerCodecDescriptor:
    return OwnerCodecDescriptor(
        owner_namespace=IdNamespace("capture"),
        schema_name=f"capture.{purpose.value}",
        schema_version=1,
        payload_purpose=purpose,
        max_canonical_bytes=1_024,
        content_policy=CodecContentPolicy.IMMUTABLE_REF_ONLY,
        codec_identity=ContentDigest.from_bytes(f"capture:{purpose.value}:v1".encode()),
    )


@dataclass(frozen=True, slots=True)
class _OwnerPayload:
    artifact_id: str


@pytest.mark.parametrize(
    ("origin", "provenance_type"),
    [
        (ActorOrigin.CLI, ProvenanceType.CLI_PROCESS),
        (ActorOrigin.HTTP, ProvenanceType.HTTP_SESSION),
        (ActorOrigin.SDK, ProvenanceType.SDK_CREDENTIAL),
        (ActorOrigin.NOTEBOOK, ProvenanceType.NOTEBOOK_SESSION),
        (ActorOrigin.SCHEDULER, ProvenanceType.SCHEDULE_LEASE),
        (ActorOrigin.EVENT, ProvenanceType.PARENT_ENVELOPE),
        (ActorOrigin.IMPORT, ProvenanceType.IMPORT_SESSION),
        (ActorOrigin.SYSTEM, ProvenanceType.BOOTSTRAP_IDENTITY),
    ],
)
def test_verified_actor_origin_is_the_trusted_channel(
    origin: ActorOrigin,
    provenance_type: ProvenanceType,
) -> None:
    actor = _actor(origin=origin, provenance_type=provenance_type)

    assert actor.can_submit_mutation


def test_product_protocols_do_not_create_actor_origins() -> None:
    values = {origin.value for origin in ActorOrigin}

    assert "graphql" not in values
    assert "mcp" not in values
    assert "tui" not in values
    assert "remote_worker" not in values


def test_actor_rejects_mismatched_origin_and_provenance() -> None:
    with pytest.raises(ValueError, match="origin"):
        _actor(origin=ActorOrigin.HTTP, provenance_type=ProvenanceType.CLI_PROCESS)


def test_wire_actor_is_unverified_attribution_without_mutation_authority() -> None:
    verified = _actor(scopes=("capture.request", "dataset.publish"))

    attribution = verified.as_wire_attribution()

    assert attribution.assurance is ActorAssurance.UNVERIFIED
    assert attribution.principal_id == verified.principal_id
    assert attribution.authority_scopes == verified.authority_scopes
    assert not attribution.can_submit_mutation
    assert verified.can_submit_mutation


def test_anonymous_read_actor_is_explicit_and_cannot_form_mutation_subject() -> None:
    actor = _actor(
        principal_kind=PrincipalKind.ANONYMOUS,
        principal_value="public",
        assurance=ActorAssurance.ANONYMOUS_ALLOWED,
        scopes=("dataset.read",),
    )

    assert not actor.can_submit_mutation
    with pytest.raises(ValueError, match="verified authenticated"):
        derive_idempotency_subject(
            actor=actor,
            owner_namespace=IdNamespace("capture"),
            tenant_id=_id("tenant", "public"),
        )


def test_unknown_actor_must_remain_unverified() -> None:
    with pytest.raises(ValueError, match="unknown principal"):
        _actor(
            principal_kind=PrincipalKind.UNKNOWN,
            principal_value="unknown",
            assurance=ActorAssurance.VERIFIED,
        )


def test_actor_scope_and_delegation_bounds_are_exact() -> None:
    scopes = tuple(f"scope.{index:02d}" for index in range(32))
    hops = tuple(
        _provenance(ProvenanceType.PARENT_ENVELOPE, reason=f"hop.{index}") for index in range(8)
    )

    actor = _actor(scopes=scopes, delegation_chain=hops)

    assert len(actor.authority_scopes) == 32
    assert len(actor.delegation_chain) == 8
    with pytest.raises(ValueError, match="32"):
        _actor(scopes=(*scopes, "scope.32"))
    with pytest.raises(ValueError, match="at most eight"):
        _actor(delegation_chain=(*hops, _provenance(ProvenanceType.PARENT_ENVELOPE)))
    with pytest.raises(ValueError, match="sorted and unique"):
        _actor(scopes=("dataset.read", "capture.request"))
    with pytest.raises(ValueError, match="sorted and unique"):
        _actor(scopes=("capture.request", "capture.request"))


def test_provenance_is_bounded_and_expiry_cannot_precede_establishment() -> None:
    reference = _provenance(ProvenanceType.HTTP_SESSION)

    assert len(reference.canonical_bytes()) <= 1_024
    with pytest.raises(ValueError, match="expiry"):
        ActorProvenanceRef(
            provenance_type=ProvenanceType.HTTP_SESSION,
            verifier_namespace=IdNamespace("platform.ingress"),
            evidence_id=_id("actor.evidence", "session"),
            established_at=_instant(1),
            expires_at=_instant(0),
            reason_code="trusted_adapter",
        )
    with pytest.raises(ValueError, match="reason_code"):
        _provenance(ProvenanceType.HTTP_SESSION, reason="unsafe reason")


def test_idempotency_subject_excludes_reauthentication_scopes_and_provenance() -> None:
    tenant = _id("tenant", "primary")
    first = _actor(scopes=("capture.request",))
    second = replace(
        first,
        authority_scopes=("capture.request", "dataset.publish"),
        provenance=_provenance(
            ProvenanceType.CLI_PROCESS,
            reason="reauthenticated",
            established_at=_instant(1),
        ),
        established_at=_instant(1),
    )

    first_subject = derive_idempotency_subject(
        actor=first,
        owner_namespace=IdNamespace("capture"),
        tenant_id=tenant,
    )
    second_subject = derive_idempotency_subject(
        actor=second,
        owner_namespace=IdNamespace("capture"),
        tenant_id=tenant,
    )

    assert first_subject == second_subject
    assert canonical_idempotency_subject_bytes(first_subject) == (
        b'{"delegated_subject_ids":[],"owner_namespace":"capture",'
        b'"principal_id":{"namespace":"principal","value":"alice"},'
        b'"principal_kind":"authenticated","schema_version":1,'
        b'"tenant_id":{"namespace":"tenant","value":"primary"}}'
    )
    assert b"scope" not in canonical_idempotency_subject_bytes(first_subject)
    assert b"reauthenticated" not in canonical_idempotency_subject_bytes(first_subject)


def test_idempotency_subject_distinguishes_tenant_principal_and_delegation_order() -> None:
    actor = _actor()
    owner = IdNamespace("capture")
    first_delegate = _id("principal", "delegate-a")
    second_delegate = _id("principal", "delegate-b")

    baseline = derive_idempotency_subject(
        actor=actor,
        owner_namespace=owner,
        tenant_id=_id("tenant", "one"),
        delegated_subject_ids=(first_delegate, second_delegate),
    )
    other_tenant = derive_idempotency_subject(
        actor=actor,
        owner_namespace=owner,
        tenant_id=_id("tenant", "two"),
        delegated_subject_ids=(first_delegate, second_delegate),
    )
    other_principal = derive_idempotency_subject(
        actor=_actor(principal_value="bob"),
        owner_namespace=owner,
        tenant_id=_id("tenant", "one"),
        delegated_subject_ids=(first_delegate, second_delegate),
    )
    reverse_delegation = derive_idempotency_subject(
        actor=actor,
        owner_namespace=owner,
        tenant_id=_id("tenant", "one"),
        delegated_subject_ids=(second_delegate, first_delegate),
    )

    canonical = {
        canonical_idempotency_subject_bytes(item)
        for item in (baseline, other_tenant, other_principal, reverse_delegation)
    }
    assert len(canonical) == 4


def test_idempotency_subject_requires_tuple_and_at_most_eight_delegates() -> None:
    common = {
        "schema_version": 1,
        "owner_namespace": IdNamespace("capture"),
        "tenant_id": _id("tenant", "one"),
        "principal_kind": PrincipalKind.AUTHENTICATED,
        "principal_id": _id("principal", "alice"),
    }
    delegates = tuple(_id("principal", f"delegate-{index}") for index in range(8))

    assert (
        len(IdempotencySubjectV1(**common, delegated_subject_ids=delegates).delegated_subject_ids)
        == 8
    )
    with pytest.raises(ValueError, match="at most 8"):
        IdempotencySubjectV1(
            **common,
            delegated_subject_ids=(*delegates, _id("principal", "delegate-8")),
        )
    with pytest.raises(TypeError, match="tuple"):
        IdempotencySubjectV1(**common, delegated_subject_ids=[])  # type: ignore[arg-type]


def test_policy_ref_is_owner_local_immutable_identity() -> None:
    policy = PolicyRefV1(
        policy_namespace=IdNamespace("platform.replay"),
        policy_name="direct.redispatch",
        semantic_version="1.2.3",
        content_digest=ContentDigest.from_bytes(b"policy-v1"),
    )

    assert policy.semantic_version == "1.2.3"
    with pytest.raises(ValueError, match="SemVer"):
        replace(policy, semantic_version="latest")


def test_owner_codec_registry_freezes_sorted_unique_descriptors() -> None:
    command = _codec(PayloadPurpose.COMMAND)
    query = _codec(PayloadPurpose.QUERY)

    registry = FrozenCodecRegistry.freeze((query, command))

    assert registry.descriptors == tuple(
        sorted((command, query), key=lambda item: item.registry_key)
    )
    assert (
        registry.resolve(
            owner_namespace=command.owner_namespace,
            schema_name=command.schema_name,
            schema_version=command.schema_version,
            payload_purpose=command.payload_purpose,
        )
        == command
    )
    with pytest.raises(ValueError, match="duplicate"):
        FrozenCodecRegistry.freeze((command, command))


@pytest.mark.parametrize("maximum", [1, 65_536])
def test_owner_codec_accepts_exact_canonical_byte_boundaries(maximum: int) -> None:
    descriptor = replace(_codec(PayloadPurpose.COMMAND), max_canonical_bytes=maximum)

    assert descriptor.max_canonical_bytes == maximum


@pytest.mark.parametrize("maximum", [0, 65_537])
def test_owner_codec_rejects_canonical_byte_overflow(maximum: int) -> None:
    with pytest.raises(ValueError, match="1..65,536"):
        replace(_codec(PayloadPurpose.COMMAND), max_canonical_bytes=maximum)


def test_fingerprint_key_set_has_one_active_and_at_most_three_retained() -> None:
    key_set = FingerprintKeySetV1(
        key_set_generation=9_223_372_036_854_775_807,
        active_write_version=4,
        retained_read_versions=(1, 2, 3),
    )

    assert key_set.candidate_versions == (4, 1, 2, 3)
    with pytest.raises(ValueError, match="three"):
        replace(key_set, retained_read_versions=(1, 2, 3, 5))
    with pytest.raises(ValueError, match="active"):
        replace(key_set, retained_read_versions=(1, 2, 4))
    with pytest.raises(ValueError, match="sorted and unique"):
        replace(key_set, retained_read_versions=(2, 1))


def test_hmac_framing_uses_unsigned_four_byte_lengths() -> None:
    assert frame_hmac_components((b"a", b"", b"bc")) == (
        b"\x00\x00\x00\x01a\x00\x00\x00\x00\x00\x00\x00\x02bc"
    )


def test_public_fingerprints_are_keyed_domain_separated_and_non_reversible() -> None:
    secret = bytes(range(32))
    subject = derive_idempotency_subject(
        actor=_actor(),
        owner_namespace=IdNamespace("capture"),
        tenant_id=_id("tenant", "one"),
    )
    raw_key = b"predictable-key"
    command = derive_command_fingerprint(
        secret=secret,
        key_version=7,
        canonical_payload=b'{"symbol":"BTCUSDT"}',
    )
    idempotency = derive_idempotency_fingerprint(
        secret=secret,
        key_version=7,
        subject=subject,
        command_scope="capture.request",
        raw_key=raw_key,
    )

    assert command.domain is FingerprintDomain.COMMAND
    assert idempotency.domain is FingerprintDomain.IDEMPOTENCY
    assert command.value != idempotency.value
    assert len(command.value) == len(idempotency.value) == 64
    assert raw_key not in command.value.encode()
    assert raw_key not in idempotency.value.encode()
    assert secret.hex() not in {command.value, idempotency.value}
    with pytest.raises(ValueError, match="256 bits"):
        derive_command_fingerprint(
            secret=b"x" * 31,
            key_version=1,
            canonical_payload=b"{}",
        )


def test_fingerprint_value_and_domain_are_closed() -> None:
    with pytest.raises(ValueError, match="algorithm"):
        FingerprintV1("sha256", FingerprintDomain.COMMAND, 1, "0" * 64)
    with pytest.raises(ValueError, match="lower-case"):
        FingerprintV1("hmac-sha256-v1", FingerprintDomain.COMMAND, 1, "A" * 64)


def test_typed_command_and_query_envelopes_require_frozen_owner_dto() -> None:
    actor = _actor()
    payload = _OwnerPayload("artifact-1")
    command_codec = _codec(PayloadPurpose.COMMAND)
    query_codec = _codec(PayloadPurpose.QUERY)
    command_meta = EnvelopeMeta.root(
        schema_name=command_codec.schema_name,
        schema_version=1,
        envelope_created_at=_instant(),
        message_id=_id("message", "command"),
    )
    query_meta = EnvelopeMeta.root(
        schema_name=query_codec.schema_name,
        schema_version=1,
        envelope_created_at=_instant(),
        message_id=_id("message", "query"),
    )

    command = CommandEnvelope(
        meta=command_meta,
        actor=actor,
        deadline=_deadline(),
        codec=command_codec,
        payload=payload,
        canonical_payload=b'{"artifact_id":"artifact-1"}',
    )
    query = QueryEnvelope(
        meta=query_meta,
        actor=actor.as_wire_attribution(),
        deadline=_deadline(),
        codec=query_codec,
        payload=payload,
        canonical_payload=b'{"artifact_id":"artifact-1"}',
    )

    assert command.payload is payload
    assert query.actor.assurance is ActorAssurance.UNVERIFIED
    assert not hasattr(command, "command_fingerprint")
    with pytest.raises(FrozenInstanceError):
        command.canonical_payload = b"other"  # type: ignore[misc]
    with pytest.raises(TypeError, match="frozen typed owner dataclass"):
        CommandEnvelope(
            meta=command_meta,
            actor=actor,
            deadline=_deadline(),
            codec=command_codec,
            payload={"artifact_id": "artifact-1"},
            canonical_payload=b"{}",
        )


def test_command_rejects_unverified_actor_and_codec_schema_mismatch() -> None:
    actor = _actor()
    codec = _codec(PayloadPurpose.COMMAND)
    meta = EnvelopeMeta.root(
        schema_name=codec.schema_name,
        schema_version=1,
        envelope_created_at=_instant(),
        message_id=_id("message", "command"),
    )
    common = {
        "meta": meta,
        "deadline": _deadline(),
        "codec": codec,
        "payload": _OwnerPayload("artifact-1"),
        "canonical_payload": b'{"artifact_id":"artifact-1"}',
    }

    with pytest.raises(ValueError, match="verified"):
        CommandEnvelope(actor=actor.as_wire_attribution(), **common)
    with pytest.raises(ValueError, match="schema identity"):
        CommandEnvelope(
            actor=actor,
            **{**common, "codec": replace(codec, schema_name="capture.other")},
        )


def test_replay_context_separates_historical_attribution_from_current_authority() -> None:
    historical_actor = _actor(scopes=("legacy.admin",)).as_wire_attribution()
    initiator = _actor(principal_value="operator", scopes=("operation.replay",))
    request = _id("message", "replay-request")
    context = ReplayContextV1(
        schema_version=1,
        replay_request_message_id=request,
        replay_request_correlation_id=request,
        replay_request_causation_id=None,
        historical_message_id=_id("message", "historical"),
        historical_actor=historical_actor,
        replay_initiator=initiator,
        replay_policy=PolicyRefV1(
            policy_namespace=IdNamespace("platform.replay"),
            policy_name="direct.redispatch",
            semantic_version="1.0.0",
            content_digest=ContentDigest.from_bytes(b"replay-policy"),
        ),
    )

    assert context.historical_actor.assurance is ActorAssurance.UNVERIFIED
    assert not context.historical_actor.can_submit_mutation
    assert context.replay_initiator.can_submit_mutation
    with pytest.raises(ValueError, match="unverified attribution"):
        replace(context, historical_actor=_actor(scopes=("legacy.admin",)))


def test_replay_admission_binds_historical_identity_and_current_subject() -> None:
    initiator = _actor(principal_value="operator", scopes=("operation.replay",))
    historical = _id("message", "historical")
    request = _id("message", "replay-request")
    context = ReplayContextV1(
        schema_version=1,
        replay_request_message_id=request,
        replay_request_correlation_id=request,
        replay_request_causation_id=None,
        historical_message_id=historical,
        historical_actor=_actor().as_wire_attribution(),
        replay_initiator=initiator,
        replay_policy=PolicyRefV1(
            policy_namespace=IdNamespace("platform.replay"),
            policy_name="direct.redispatch",
            semantic_version="1.0.0",
            content_digest=ContentDigest.from_bytes(b"replay-policy"),
        ),
    )
    subject = derive_idempotency_subject(
        actor=initiator,
        owner_namespace=IdNamespace("platform"),
        tenant_id=_id("tenant", "one"),
    )
    admission = ReplayAdmissionV1(
        schema_version=1,
        context=context,
        historical_message_id=historical,
        historical_correlation_id=historical,
        historical_causation_id=None,
        historical_envelope_digest=ContentDigest.from_bytes(b"historical-envelope"),
        historical_operation_id=_id("operation", "existing"),
        current_subject=subject,
        deadline=_deadline(),
    )

    assert admission.context.replay_initiator == initiator
    assert not hasattr(admission, "replay_initiator")
    assert not hasattr(admission, "replay_policy")
    with pytest.raises(ValueError, match="correlation identity"):
        replace(admission, historical_message_id=_id("message", "different"))
    with pytest.raises(ValueError, match="current subject"):
        replace(
            admission,
            current_subject=derive_idempotency_subject(
                actor=_actor(principal_value="other"),
                owner_namespace=IdNamespace("platform"),
                tenant_id=_id("tenant", "one"),
            ),
        )


def test_root_and_child_replay_request_causality_is_closed() -> None:
    initiator = _actor(principal_value="operator")
    policy = PolicyRefV1(
        policy_namespace=IdNamespace("platform.replay"),
        policy_name="direct.redispatch",
        semantic_version="1.0.0",
        content_digest=ContentDigest.from_bytes(b"replay-policy"),
    )
    root = _id("message", "root")
    parent = _id("message", "parent")
    child = _id("message", "child")

    ReplayContextV1(
        1,
        root,
        root,
        None,
        _id("message", "historical"),
        _actor().as_wire_attribution(),
        initiator,
        policy,
    )
    ReplayContextV1(
        1,
        child,
        root,
        parent,
        _id("message", "historical"),
        _actor().as_wire_attribution(),
        initiator,
        policy,
    )
    with pytest.raises(ValueError, match="root replay request"):
        ReplayContextV1(
            1,
            child,
            root,
            None,
            _id("message", "historical"),
            _actor().as_wire_attribution(),
            initiator,
            policy,
        )
