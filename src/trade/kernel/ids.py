from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

__all__ = ["IdNamespace", "OpaqueId"]

_NAMESPACE_PATTERN = re.compile(r"[a-z0-9._-]{1,64}", re.ASCII)


@dataclass(frozen=True, slots=True)
class IdNamespace:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _NAMESPACE_PATTERN.fullmatch(self.value) is None:
            raise ValueError(
                "identifier namespace must be 1-64 ASCII lower-case letters, digits, '.', '_' or '-'"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OpaqueId:
    namespace: IdNamespace
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, IdNamespace):
            raise TypeError("identifier namespace must be IdNamespace")
        if not isinstance(self.value, str):
            raise TypeError("identifier value must be str")
        if not 1 <= len(self.value) <= 128:
            raise ValueError("identifier value must contain 1-128 ASCII characters")
        if any(not 0x21 <= ord(character) <= 0x7E for character in self.value):
            raise ValueError(
                "identifier value must contain printable ASCII without whitespace or controls"
            )

    @classmethod
    def generate(cls, namespace: IdNamespace) -> OpaqueId:
        return cls(namespace=namespace, value=str(uuid4()))

    def to_dict(self) -> dict[str, str]:
        return {"namespace": self.namespace.value, "value": self.value}
