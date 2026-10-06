from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Generic, TypeVar

from trade.kernel.ids import IdNamespace, OpaqueId
from trade.kernel.time import UtcInstant

__all__ = ["Envelope", "EnvelopeMeta"]

T = TypeVar("T")
_SCHEMA_NAME_PATTERN = re.compile(r"[a-z0-9._-]{1,96}", re.ASCII)
_MAX_SCHEMA_VERSION = 2_147_483_647
_MESSAGE_NAMESPACE = IdNamespace("message")


@dataclass(frozen=True, slots=True)
class EnvelopeMeta:
    schema_name: str
    schema_version: int
    message_id: OpaqueId
    correlation_id: OpaqueId
    causation_id: OpaqueId | None
    envelope_created_at: UtcInstant

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_name, str)
            or _SCHEMA_NAME_PATTERN.fullmatch(self.schema_name) is None
        ):
            raise ValueError(
                "schema name must be 1-96 ASCII lower-case letters, digits, '.', '_' or '-'"
            )
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool):
            raise TypeError("schema version must be an integer")
        if not 1 <= self.schema_version <= _MAX_SCHEMA_VERSION:
            raise ValueError("schema version must be in 1..2,147,483,647")
        for name, identity in (
            ("message_id", self.message_id),
            ("correlation_id", self.correlation_id),
        ):
            if not isinstance(identity, OpaqueId):
                raise TypeError(f"{name} must be OpaqueId")
        if self.causation_id is not None and not isinstance(self.causation_id, OpaqueId):
            raise TypeError("causation_id must be OpaqueId or None")
        if not isinstance(self.envelope_created_at, UtcInstant):
            raise TypeError("envelope_created_at must be UtcInstant")
        if self.causation_id is None and self.correlation_id != self.message_id:
            raise ValueError("root envelope correlation identity must equal its message identity")
        if self.causation_id is not None and self.message_id in {
            self.correlation_id,
            self.causation_id,
        }:
            raise ValueError("child envelope message identity must be new")

    @classmethod
    def root(
        cls,
        *,
        schema_name: str,
        schema_version: int,
        envelope_created_at: UtcInstant,
        message_id: OpaqueId | None = None,
    ) -> EnvelopeMeta:
        identity = message_id or OpaqueId.generate(_MESSAGE_NAMESPACE)
        return cls(
            schema_name=schema_name,
            schema_version=schema_version,
            message_id=identity,
            correlation_id=identity,
            causation_id=None,
            envelope_created_at=envelope_created_at,
        )

    @classmethod
    def child(
        cls,
        *,
        schema_name: str,
        schema_version: int,
        envelope_created_at: UtcInstant,
        parent: EnvelopeMeta,
        message_id: OpaqueId | None = None,
    ) -> EnvelopeMeta:
        if not isinstance(parent, EnvelopeMeta):
            raise TypeError("child envelope parent must be EnvelopeMeta")
        identity = message_id or OpaqueId.generate(_MESSAGE_NAMESPACE)
        return cls(
            schema_name=schema_name,
            schema_version=schema_version,
            message_id=identity,
            correlation_id=parent.correlation_id,
            causation_id=parent.message_id,
            envelope_created_at=envelope_created_at,
        )


@dataclass(frozen=True, slots=True)
class Envelope(Generic[T]):
    meta: EnvelopeMeta
    payload: T

    def __post_init__(self) -> None:
        if not isinstance(self.meta, EnvelopeMeta):
            raise TypeError("envelope metadata must be EnvelopeMeta")
