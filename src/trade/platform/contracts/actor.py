from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum

from trade.kernel.digest import ContentDigest
from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import UtcInstant

__all__ = [
    "ActorAssurance",
    "ActorContext",
    "ActorOrigin",
    "ActorProvenanceRef",
    "IdempotencySubjectV1",
    "PolicyRefV1",
    "PrincipalKind",
    "ProvenanceType",
    "derive_idempotency_subject",
]

_TOKEN_PATTERN = re.compile(r"[a-z0-9._:-]{1,96}", re.ASCII)
_SEMANTIC_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
    re.ASCII,
)
_MAX_SCOPES = 32
_MAX_DELEGATION_HOPS = 8
_MAX_PROVENANCE_CANONICAL_BYTES = 1_024
_MAX_SEMANTIC_VERSION_BYTES = 96


class ActorOrigin(str, Enum):
    CLI = "cli"
    HTTP = "http"
    SDK = "sdk"
    NOTEBOOK = "notebook"
    SCHEDULER = "scheduler"
    EVENT = "event"
    IMPORT = "import"
    SYSTEM = "system"


class PrincipalKind(str, Enum):
    AUTHENTICATED = "authenticated"
    SYSTEM = "system"
    ANONYMOUS = "anonymous"
    UNKNOWN = "unknown"


class ActorAssurance(str, Enum):
    VERIFIED = "verified"
    ANONYMOUS_ALLOWED = "anonymous_allowed"
    UNVERIFIED = "unverified"


class ProvenanceType(str, Enum):
    CLI_PROCESS = "cli_process"
    HTTP_SESSION = "http_session"
    SDK_CREDENTIAL = "sdk_credential"
    NOTEBOOK_SESSION = "notebook_session"
    SCHEDULE_LEASE = "schedule_lease"
    PARENT_ENVELOPE = "parent_envelope"
    IMPORT_SESSION = "import_session"
    BOOTSTRAP_IDENTITY = "bootstrap_identity"


_ORIGIN_PROVENANCE = {
    ActorOrigin.CLI: ProvenanceType.CLI_PROCESS,
    ActorOrigin.HTTP: ProvenanceType.HTTP_SESSION,
    ActorOrigin.SDK: ProvenanceType.SDK_CREDENTIAL,
    ActorOrigin.NOTEBOOK: ProvenanceType.NOTEBOOK_SESSION,
    ActorOrigin.SCHEDULER: ProvenanceType.SCHEDULE_LEASE,
    ActorOrigin.EVENT: ProvenanceType.PARENT_ENVELOPE,
    ActorOrigin.IMPORT: ProvenanceType.IMPORT_SESSION,
    ActorOrigin.SYSTEM: ProvenanceType.BOOTSTRAP_IDENTITY,
}


def _token(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be 1-96 ASCII lower-case letters, digits, '.', '_', ':' or '-'"
        )
    return value


def _tuple_of_ids(
    values: tuple[OpaqueId, ...],
    *,
    field_name: str,
    maximum: int,
) -> tuple[OpaqueId, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if len(values) > maximum:
        raise ValueError(f"{field_name} must contain at most {maximum} entries")
    if any(not isinstance(value, OpaqueId) for value in values):
        raise TypeError(f"{field_name} entries must be OpaqueId")
    return values


@dataclass(frozen=True, slots=True)
class ActorProvenanceRef:
    provenance_type: ProvenanceType
    verifier_namespace: IdNamespace
    evidence_id: OpaqueId
    established_at: UtcInstant
    expires_at: UtcInstant | None
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.provenance_type, ProvenanceType):
            raise TypeError("provenance_type must be ProvenanceType")
        if not isinstance(self.verifier_namespace, IdNamespace):
            raise TypeError("verifier_namespace must be IdNamespace")
        if not isinstance(self.evidence_id, OpaqueId):
            raise TypeError("evidence_id must be OpaqueId")
        if not isinstance(self.established_at, UtcInstant):
            raise TypeError("established_at must be UtcInstant")
        if self.expires_at is not None and not isinstance(self.expires_at, UtcInstant):
            raise TypeError("expires_at must be UtcInstant or None")
        if self.expires_at is not None and self.expires_at.value < self.established_at.value:
            raise ValueError("provenance expiry cannot precede establishment")
        _token(self.reason_code, field_name="reason_code")
        if len(self.canonical_bytes()) > _MAX_PROVENANCE_CANONICAL_BYTES:
            raise ValueError("actor provenance canonical form must contain at most 1,024 bytes")

    def canonical_bytes(self) -> bytes:
        expires_at = "" if self.expires_at is None else self.expires_at.to_wire()
        components = (
            self.provenance_type.value.encode("ascii"),
            self.verifier_namespace.value.encode("ascii"),
            self.evidence_id.namespace.value.encode("ascii"),
            self.evidence_id.value.encode("ascii"),
            self.established_at.to_wire().encode("ascii"),
            expires_at.encode("ascii"),
            self.reason_code.encode("ascii"),
        )
        return b"".join(len(component).to_bytes(4, "big") + component for component in components)


@dataclass(frozen=True, slots=True)
class ActorContext:
    schema_version: int
    origin: ActorOrigin
    principal_kind: PrincipalKind
    principal_id: OpaqueId
    authority_scopes: tuple[str, ...]
    delegation_chain: tuple[ActorProvenanceRef, ...]
    assurance: ActorAssurance
    provenance: ActorProvenanceRef
    established_at: UtcInstant

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("ActorContext schema_version must be 1")
        if not isinstance(self.origin, ActorOrigin):
            raise TypeError("origin must be ActorOrigin")
        if not isinstance(self.principal_kind, PrincipalKind):
            raise TypeError("principal_kind must be PrincipalKind")
        if not isinstance(self.principal_id, OpaqueId):
            raise TypeError("principal_id must be OpaqueId")
        if not isinstance(self.authority_scopes, tuple):
            raise TypeError("authority_scopes must be a tuple")
        if len(self.authority_scopes) > _MAX_SCOPES:
            raise ValueError("authority_scopes must contain at most 32 entries")
        validated_scopes = tuple(
            _token(scope, field_name="authority scope") for scope in self.authority_scopes
        )
        if validated_scopes != tuple(sorted(set(validated_scopes))):
            raise ValueError("authority_scopes must be sorted and unique")
        if not isinstance(self.delegation_chain, tuple):
            raise TypeError("delegation_chain must be a tuple")
        if len(self.delegation_chain) > _MAX_DELEGATION_HOPS:
            raise ValueError("delegation_chain must contain at most eight hops")
        if any(not isinstance(item, ActorProvenanceRef) for item in self.delegation_chain):
            raise TypeError("delegation_chain entries must be ActorProvenanceRef")
        if not isinstance(self.assurance, ActorAssurance):
            raise TypeError("assurance must be ActorAssurance")
        if not isinstance(self.provenance, ActorProvenanceRef):
            raise TypeError("provenance must be ActorProvenanceRef")
        if not isinstance(self.established_at, UtcInstant):
            raise TypeError("established_at must be UtcInstant")
        if self.provenance.provenance_type is not _ORIGIN_PROVENANCE[self.origin]:
            raise ValueError("actor origin must match its trusted provenance type")
        if self.principal_kind is PrincipalKind.ANONYMOUS:
            if self.assurance not in {
                ActorAssurance.ANONYMOUS_ALLOWED,
                ActorAssurance.UNVERIFIED,
            }:
                raise ValueError(
                    "anonymous actor assurance must be anonymous_allowed or unverified"
                )
        elif self.assurance is ActorAssurance.ANONYMOUS_ALLOWED:
            raise ValueError("anonymous_allowed assurance requires an anonymous principal")
        if (
            self.principal_kind is PrincipalKind.UNKNOWN
            and self.assurance is not ActorAssurance.UNVERIFIED
        ):
            raise ValueError("unknown principal must remain unverified")

    @property
    def can_submit_mutation(self) -> bool:
        return self.assurance is ActorAssurance.VERIFIED and self.principal_kind in {
            PrincipalKind.AUTHENTICATED,
            PrincipalKind.SYSTEM,
        }

    def as_wire_attribution(self) -> ActorContext:
        return replace(self, assurance=ActorAssurance.UNVERIFIED)


@dataclass(frozen=True, slots=True)
class IdempotencySubjectV1:
    schema_version: int
    owner_namespace: IdNamespace
    tenant_id: OpaqueId
    principal_kind: PrincipalKind
    principal_id: OpaqueId
    delegated_subject_ids: tuple[OpaqueId, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("IdempotencySubjectV1 schema_version must be 1")
        if not isinstance(self.owner_namespace, IdNamespace):
            raise TypeError("owner_namespace must be IdNamespace")
        if not isinstance(self.tenant_id, OpaqueId):
            raise TypeError("tenant_id must be OpaqueId")
        if self.principal_kind not in {PrincipalKind.AUTHENTICATED, PrincipalKind.SYSTEM}:
            raise ValueError("idempotency subject requires authenticated or system principal")
        if not isinstance(self.principal_id, OpaqueId):
            raise TypeError("principal_id must be OpaqueId")
        _tuple_of_ids(
            self.delegated_subject_ids,
            field_name="delegated_subject_ids",
            maximum=_MAX_DELEGATION_HOPS,
        )


def derive_idempotency_subject(
    *,
    actor: ActorContext,
    owner_namespace: IdNamespace,
    tenant_id: OpaqueId,
    delegated_subject_ids: tuple[OpaqueId, ...] = (),
) -> IdempotencySubjectV1:
    if not isinstance(actor, ActorContext):
        raise TypeError("actor must be ActorContext")
    if not actor.can_submit_mutation:
        raise ValueError("mutation idempotency subject requires a verified authenticated actor")
    return IdempotencySubjectV1(
        schema_version=1,
        owner_namespace=owner_namespace,
        tenant_id=tenant_id,
        principal_kind=actor.principal_kind,
        principal_id=actor.principal_id,
        delegated_subject_ids=delegated_subject_ids,
    )


@dataclass(frozen=True, slots=True)
class PolicyRefV1:
    policy_namespace: IdNamespace
    policy_name: str
    semantic_version: str
    content_digest: ContentDigest

    def __post_init__(self) -> None:
        if not isinstance(self.policy_namespace, IdNamespace):
            raise TypeError("policy_namespace must be IdNamespace")
        _token(self.policy_name, field_name="policy_name")
        if (
            not isinstance(self.semantic_version, str)
            or _SEMANTIC_VERSION_PATTERN.fullmatch(self.semantic_version) is None
            or len(self.semantic_version.encode("ascii")) > _MAX_SEMANTIC_VERSION_BYTES
        ):
            raise ValueError("semantic_version must be a SemVer 2.0 value of at most 96 bytes")
        if not isinstance(self.content_digest, ContentDigest):
            raise TypeError("content_digest must be ContentDigest")
