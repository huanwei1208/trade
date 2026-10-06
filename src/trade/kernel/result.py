from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, cast

__all__ = ["Result"]

T = TypeVar("T")
E = TypeVar("E")
_MISSING = object()


@dataclass(frozen=True, slots=True, init=False)
class Result(Generic[T, E]):
    _value: T | object
    _error: E | object

    def __init__(self, *, value: T | object = _MISSING, error: E | object = _MISSING) -> None:
        if (value is _MISSING) == (error is _MISSING):
            raise ValueError("result must contain exactly one of value or error")
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "_error", error)

    @classmethod
    def ok(cls, value: T) -> Result[T, E]:
        return cls(value=value)

    @classmethod
    def err(cls, error: E) -> Result[T, E]:
        return cls(error=error)

    @property
    def is_ok(self) -> bool:
        return self._value is not _MISSING

    @property
    def is_err(self) -> bool:
        return self._error is not _MISSING

    @property
    def value(self) -> T:
        if self._value is _MISSING:
            raise ValueError("error result has no value")
        return cast(T, self._value)

    @property
    def error(self) -> E:
        if self._error is _MISSING:
            raise ValueError("successful result has no error")
        return cast(E, self._error)

    def __bool__(self) -> bool:
        raise TypeError("Result has no implicit truthiness; inspect is_ok or is_err")
