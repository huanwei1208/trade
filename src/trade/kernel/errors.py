from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["ContractErrorCode", "ContractViolation"]

_MAX_DETAIL_BYTES = 1_024


class ContractErrorCode(str, Enum):
    INVALID_TYPE = "invalid_type"
    INVALID_VALUE = "invalid_value"
    OUT_OF_BOUNDS = "out_of_bounds"
    UNSUPPORTED = "unsupported"
    INVARIANT_VIOLATION = "invariant_violation"


@dataclass(frozen=True, slots=True)
class ContractViolation(ValueError):
    code: ContractErrorCode
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, ContractErrorCode):
            raise TypeError("contract error code must be ContractErrorCode")
        if not isinstance(self.detail, str):
            raise TypeError("contract error detail must be str")
        try:
            encoded = self.detail.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("contract error detail must be valid UTF-8") from error
        if len(encoded) > _MAX_DETAIL_BYTES:
            raise ValueError("contract error detail must contain at most 1,024 UTF-8 bytes")
        ValueError.__init__(self, self.detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "detail": self.detail}
