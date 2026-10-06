from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

__all__ = ["ContentDigest"]

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)


@dataclass(frozen=True, slots=True)
class ContentDigest:
    algorithm: str
    value: str

    def __post_init__(self) -> None:
        if self.algorithm != "sha256":
            raise ValueError("content digest algorithm must be 'sha256'")
        if not isinstance(self.value, str) or _SHA256_PATTERN.fullmatch(self.value) is None:
            raise ValueError("SHA-256 content digest must be 64 lower-case hexadecimal characters")

    @classmethod
    def from_bytes(cls, content: bytes) -> ContentDigest:
        if not isinstance(content, bytes):
            raise TypeError("content digest input must be bytes")
        return cls(algorithm="sha256", value=hashlib.sha256(content).hexdigest())

    def to_dict(self) -> dict[str, str]:
        return {"algorithm": self.algorithm, "value": self.value}
